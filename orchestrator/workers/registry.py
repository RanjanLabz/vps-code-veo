from __future__ import annotations

import asyncio

from fastapi import HTTPException

from orchestrator.config.settings import WorkerSeed
from orchestrator.db.store import OrchestratorStore
from orchestrator.workers.client import WorkerClient
from orchestrator.workers.models import WorkerRecord, WorkerStatus


class WorkerRegistry:
    def __init__(self, seeds: list[WorkerSeed], client: WorkerClient, store: OrchestratorStore) -> None:
        self.client = client
        self.store = store
        self._seeds = seeds
        self._workers: dict[str, WorkerRecord] = {
            seed.id: WorkerRecord(
                id=seed.id,
                base_url=seed.base_url,
                enabled=seed.enabled,
                max_jobs=seed.max_jobs,
                weight=seed.weight,
            )
            for seed in seeds
        }
        self._lock = asyncio.Lock()

    async def load(self) -> None:
        """Load registered VPS workers from persistent storage.

        YAML/env workers are bootstrap seeds only. This lets a new install come
        online, but later IP changes and add/remove operations live in the DB.
        """
        persisted = await self.store.list_worker_records()
        async with self._lock:
            if persisted:
                previous_status = {worker.id: worker.status for worker in self._workers.values()}
                self._workers = {
                    worker.id: worker.model_copy(update={"status": previous_status.get(worker.id)})
                    for worker in persisted
                }
            for seed in self._seeds:
                if seed.id in self._workers:
                    continue
                worker = WorkerRecord(
                    id=seed.id,
                    base_url=seed.base_url,
                    enabled=seed.enabled,
                    max_jobs=seed.max_jobs,
                    weight=seed.weight,
                )
                self._workers[worker.id] = worker
                await self.store.save_worker_record(worker)

    def list_workers(self) -> list[WorkerRecord]:
        return sorted(self._workers.values(), key=lambda worker: worker.id)

    def get(self, worker_id: str) -> WorkerRecord | None:
        return self._workers.get(worker_id)

    async def upsert(self, payload: dict) -> WorkerRecord:
        seed = WorkerSeed.model_validate(payload)
        async with self._lock:
            worker = WorkerRecord(
                id=seed.id,
                base_url=seed.base_url,
                enabled=seed.enabled,
                max_jobs=seed.max_jobs,
                weight=seed.weight,
                status=self._workers.get(seed.id).status if seed.id in self._workers else None,
            )
            self._workers[seed.id] = worker
            await self.store.save_worker_record(worker)
            return worker

    async def delete(self, worker_id: str) -> None:
        async with self._lock:
            if worker_id not in self._workers:
                raise HTTPException(status_code=404, detail="worker not found")
            self._workers.pop(worker_id)
            await self.store.delete_worker_record(worker_id)

    async def refresh_one(self, worker: WorkerRecord) -> WorkerStatus:
        status = await self.client.health(worker)
        worker.status = status
        return status

    async def refresh_all(self) -> list[WorkerStatus]:
        statuses = await asyncio.gather(
            *(self.refresh_one(worker) for worker in self._workers.values() if worker.enabled),
            return_exceptions=True,
        )
        result: list[WorkerStatus] = []
        for status in statuses:
            if isinstance(status, WorkerStatus):
                result.append(status)
        return result
