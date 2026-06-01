from __future__ import annotations

from dataclasses import dataclass

from worker.accounts.manager import AccountManager
from worker.config.flow_settings import FlowConfigManager
from worker.config.settings import Settings
from worker.health.reporter import HealthReporter
from worker.queue.manager import QueueManager
from worker.queue.scheduler import Scheduler


@dataclass(slots=True)
class AppState:
    settings: Settings
    accounts: AccountManager
    flow_config: FlowConfigManager
    queue: QueueManager
    scheduler: Scheduler
    health: HealthReporter
