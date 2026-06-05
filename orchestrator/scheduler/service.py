from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from orchestrator.capacity.manager import CapacityManager
from orchestrator.config.settings import Settings
from orchestrator.db.store import OrchestratorStore
from orchestrator.queue.manager import GlobalQueue
from orchestrator.queue.models import GlobalJob, JobState
from orchestrator.workers.client import WorkerClient

logger = logging.getLogger(__name__)
LARGE_PAYLOAD_KEYS = {"image_data_url", "imageBytes", "encodedImage", "encodedVideo"}


def redact_large_payload(value):
    if isinstance(value, dict):
        redacted = {}
        for key, child in value.items():
            if key in LARGE_PAYLOAD_KEYS:
                redacted[key] = f"<redacted:{len(child)} chars>" if isinstance(child, str) else "<redacted>"
            else:
                redacted[key] = redact_large_payload(child)
        return redacted
    if isinstance(value, list):
        return [redact_large_payload(item) for item in value]
    return value


class GlobalScheduler:
    def __init__(
        self,
        settings: Settings,
        queue: GlobalQueue,
        capacity: CapacityManager,
        worker_client: WorkerClient,
        store: OrchestratorStore,
    ) -> None:
        self.settings = settings
        self.queue = queue
        self.capacity = capacity
        self.worker_client = worker_client
        self.store = store
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._last_status_sync = 0.0

    async def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="global-orchestrator-scheduler")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self._sync_processing_jobs_if_due()
                job = await self.queue.pop_ready()
                if job is None:
                    await asyncio.sleep(self.settings.queue.scheduler_interval_seconds)
                    continue
                worker = await self.capacity.select_worker(job)
                if worker is None:
                    job.stamp("global_waiting_for_capacity")
                    await self.queue.requeue(job, delay_seconds=3)
                    await asyncio.sleep(self.settings.queue.scheduler_interval_seconds)
                    continue
                await self._dispatch(job, worker)
            except Exception:
                logger.exception("global scheduler loop error")
                await asyncio.sleep(2)

    async def _dispatch(self, job: GlobalJob, worker) -> None:
        job.assigned_worker_id = worker.id
        job.assigned_at = datetime.now(timezone.utc)
        job.stamp("vps_selected")
        await self.queue.mark_active(job)
        await self.store.save_job(job)
        try:
            worker_job = await asyncio.wait_for(
                self.worker_client.dispatch(worker, job),
                timeout=self.settings.queue.dispatch_timeout_seconds,
            )
            job.worker_job_id = str(worker_job.get("id") or "")
            job.state = JobState.PROCESSING
            job.stamp("worker_accepted")
            await self.queue.remove_active(job)
            await self.store.save_job(job)
            logger.info(
                "global job dispatched job_id=%s worker=%s worker_job=%s model=%s credits=%s",
                job.id,
                worker.id,
                job.worker_job_id,
                job.flow_model,
                job.estimated_credits,
            )
        except Exception as exc:
            logger.exception("global dispatch failed job_id=%s worker=%s", job.id, worker.id)
            job.last_error = str(exc)
            job.retries += 1
            job.stamp("dispatch_failed")
            await self.queue.remove_active(job)
            if job.retries <= job.max_retries:
                await self.queue.requeue(job, self.settings.queue.retry_delay_seconds)
            else:
                job.state = JobState.FAILED
                job.completed_at = datetime.now(timezone.utc)
                job.stamp("global_failed")
                await self.queue.save(job)
            await self.store.save_job(job)

    async def _sync_processing_jobs_if_due(self) -> None:
        now = time.monotonic()
        if now - self._last_status_sync < self.settings.queue.status_sync_interval_seconds:
            return
        self._last_status_sync = now
        jobs = await self.queue.list_jobs(limit=200)
        processing = [
            job
            for job in jobs
            if job.state == JobState.PROCESSING and job.assigned_worker_id and job.worker_job_id
        ]
        for job in processing:
            worker = self.capacity.registry.get(job.assigned_worker_id)
            if worker is None:
                await self._timeout_stale_processing_job(job, "assigned VPS is no longer registered")
                continue
            try:
                worker_job = await self.worker_client.job(worker, job.worker_job_id)
            except Exception:
                logger.exception("failed to sync worker job status job_id=%s worker_job=%s", job.id, job.worker_job_id)
                await self._timeout_stale_processing_job(job, "local worker job is no longer visible")
                continue
            worker_state = str(worker_job.get("state") or "")
            if not worker_state:
                await self._timeout_stale_processing_job(job, "local worker returned no job state")
                continue
            if worker_state not in {JobState.COMPLETED, JobState.FAILED, JobState.TIMEOUT}:
                await self._timeout_stale_processing_job(job, f"local worker still reports {worker_state}")
                continue
            job.state = JobState(worker_state)
            job.completed_at = datetime.now(timezone.utc)
            job.last_error = None if job.state == JobState.COMPLETED else worker_job.get("last_error")
            job.payload["worker_result"] = redact_large_payload(worker_job)
            if job.state == JobState.COMPLETED:
                job.stamp("global_completed")
            else:
                job.stamp("global_failed")
            await self.queue.save(job)
            await self.store.save_job(job)
            logger.info(
                "global job synced job_id=%s worker=%s worker_job=%s state=%s",
                job.id,
                worker.id,
                job.worker_job_id,
                job.state,
            )

    async def _timeout_stale_processing_job(self, job: GlobalJob, reason: str) -> bool:
        age_seconds = (datetime.now(timezone.utc) - job.created_at).total_seconds()
        if age_seconds < self.settings.queue.stale_processing_seconds:
            return False
        job.state = JobState.TIMEOUT
        job.completed_at = datetime.now(timezone.utc)
        job.last_error = f"Stale processing job timed out after {int(age_seconds)}s: {reason}"
        job.stamp("global_timeout")
        await self.queue.save(job)
        await self.store.save_job(job)
        logger.warning(
            "global stale processing job timed out job_id=%s worker=%s worker_job=%s age_seconds=%s reason=%s",
            job.id,
            job.assigned_worker_id,
            job.worker_job_id,
            int(age_seconds),
            reason,
        )
        return True
