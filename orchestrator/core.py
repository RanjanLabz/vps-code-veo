from __future__ import annotations

from dataclasses import dataclass

from orchestrator.capacity.manager import CapacityManager
from orchestrator.config.settings import Settings
from orchestrator.db.store import OrchestratorStore
from orchestrator.flow_config.manager import FlowConfigManager
from orchestrator.queue.manager import GlobalQueue
from orchestrator.scheduler.service import GlobalScheduler
from orchestrator.workers.client import WorkerClient
from orchestrator.workers.registry import WorkerRegistry


@dataclass(slots=True)
class OrchestratorState:
    settings: Settings
    flow_config: FlowConfigManager
    queue: GlobalQueue
    workers: WorkerRegistry
    capacity: CapacityManager
    worker_client: WorkerClient
    scheduler: GlobalScheduler
    store: OrchestratorStore
