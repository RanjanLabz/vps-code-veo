from __future__ import annotations

from orchestrator.queue.models import GlobalJob
from orchestrator.workers.models import WorkerRecord
from orchestrator.workers.registry import WorkerRegistry


class CapacityManager:
    def __init__(self, registry: WorkerRegistry) -> None:
        self.registry = registry
        self._last_worker_id: str | None = None

    async def select_worker(self, job: GlobalJob) -> WorkerRecord | None:
        await self.registry.refresh_all()
        if job.preferred_worker_id:
            preferred = self.registry.get(job.preferred_worker_id)
            if preferred and self._has_capacity(preferred):
                self._last_worker_id = preferred.id
                return preferred

        candidates = [worker for worker in self.registry.list_workers() if self._has_capacity(worker)]
        if not candidates:
            return None

        def score(worker: WorkerRecord) -> float:
            status = worker.status
            if status is None:
                return 0
            return (
                status.health_score * 2
                + status.capacity_remaining * 25
                + worker.weight
                - status.cpu * 1.5
                - status.ram * 0.5
                - status.queue_size * 8
                - status.active_jobs * 5
                - (35 if worker.id == self._last_worker_id else 0)
            )

        selected = sorted(candidates, key=score, reverse=True)[0]
        self._last_worker_id = selected.id
        return selected

    def _has_capacity(self, worker: WorkerRecord) -> bool:
        if not worker.enabled or worker.status is None or not worker.status.online:
            return False
        return worker.status.capacity_remaining > 0 and worker.status.ram < 92
