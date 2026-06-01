from __future__ import annotations

import json
import time

from redis.asyncio import Redis

from worker.config.settings import QueueSettings
from worker.queue.models import Job, JobState


class QueueManager:
    def __init__(self, redis_url: str, settings: QueueSettings) -> None:
        self.redis_url = redis_url
        self.settings = settings
        self.redis: Redis | None = None
        self.ready_key = f"{settings.name}:ready"
        self.delayed_key = f"{settings.name}:delayed"
        self.active_key = f"{settings.name}:active"
        self.jobs_key = f"{settings.name}:jobs"
        self.job_ids_key = f"{settings.name}:job_ids"

    async def connect(self) -> None:
        if not self.redis_url or self.redis_url.startswith("${"):
            raise RuntimeError("REDIS_URL is required for the worker queue")
        self.redis = Redis.from_url(self.redis_url, decode_responses=True)
        await self.redis.ping()

    async def close(self) -> None:
        if self.redis is not None:
            await self.redis.aclose()

    async def enqueue(self, payload: dict) -> Job:
        job = Job.from_payload(payload, max_retries=self.settings.max_retries)
        await self.save_job(job)
        assert self.redis is not None
        await self.redis.lpush(self.ready_key, job.id)
        await self.redis.zadd(self.job_ids_key, {job.id: job.created_at.timestamp()})
        return job

    async def save_job(self, job: Job) -> None:
        assert self.redis is not None
        await self.redis.hset(self.jobs_key, job.id, job.model_dump_json())

    async def get_job(self, job_id: str) -> Job | None:
        assert self.redis is not None
        raw = await self.redis.hget(self.jobs_key, job_id)
        return Job.model_validate_json(raw) if raw else None

    async def list_jobs(self, limit: int = 100) -> list[Job]:
        assert self.redis is not None
        ids = await self.redis.zrevrange(self.job_ids_key, 0, limit - 1)
        if not ids:
            return []
        raw_jobs = await self.redis.hmget(self.jobs_key, ids)
        return [Job.model_validate_json(raw) for raw in raw_jobs if raw]

    async def pop_ready(self) -> Job | None:
        assert self.redis is not None
        await self.release_due_delayed()
        job_id = await self.redis.rpop(self.ready_key)
        if job_id is None:
            return None
        job = await self.get_job(job_id)
        return job

    async def mark_active(self, job: Job) -> None:
        assert self.redis is not None
        await self.redis.hset(self.active_key, job.id, job.model_dump_json())
        await self.save_job(job)

    async def remove_active(self, job: Job) -> None:
        assert self.redis is not None
        await self.redis.hdel(self.active_key, job.id)
        await self.save_job(job)

    async def requeue(self, job: Job, delay_seconds: int) -> None:
        assert self.redis is not None
        job.state = JobState.RETRYING
        await self.save_job(job)
        if delay_seconds > 0:
            await self.redis.zadd(self.delayed_key, {job.id: time.time() + delay_seconds})
        else:
            await self.redis.lpush(self.ready_key, job.id)

    async def release_due_delayed(self) -> int:
        assert self.redis is not None
        now = time.time()
        ids = await self.redis.zrangebyscore(self.delayed_key, 0, now, start=0, num=100)
        if not ids:
            return 0
        pipe = self.redis.pipeline()
        for job_id in ids:
            pipe.zrem(self.delayed_key, job_id)
            pipe.lpush(self.ready_key, job_id)
        await pipe.execute()
        return len(ids)

    async def stats(self) -> dict:
        assert self.redis is not None
        await self.cleanup_active()
        return {
            "ready": await self.redis.llen(self.ready_key),
            "delayed": await self.redis.zcard(self.delayed_key),
            "active": await self.redis.hlen(self.active_key),
            "total_jobs": await self.redis.zcard(self.job_ids_key),
        }

    async def cleanup_active(self) -> int:
        assert self.redis is not None
        active_ids = await self.redis.hkeys(self.active_key)
        if not active_ids:
            return 0
        raw_jobs = await self.redis.hmget(self.jobs_key, active_ids)
        stale_ids: list[str] = []
        terminal = {JobState.COMPLETED, JobState.FAILED, JobState.TIMEOUT}
        for job_id, raw in zip(active_ids, raw_jobs, strict=False):
            if not raw:
                stale_ids.append(job_id)
                continue
            try:
                job = Job.model_validate_json(raw)
            except Exception:
                stale_ids.append(job_id)
                continue
            if job.state in terminal:
                stale_ids.append(job_id)
        if stale_ids:
            await self.redis.hdel(self.active_key, *stale_ids)
        return len(stale_ids)
