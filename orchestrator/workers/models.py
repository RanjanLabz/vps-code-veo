from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WorkerStatus(BaseModel):
    vps_id: str
    base_url: str
    online: bool = False
    accounts_total: int = 0
    accounts_busy: int = 0
    accounts_ready: int = 0
    max_jobs: int = Field(default=10, ge=1)
    active_jobs: int = 0
    queue_size: int = 0
    cpu: float = 100
    ram: float = 100
    health_score: int = Field(default=0, ge=0, le=100)
    last_seen: datetime | None = None
    error: str | None = None
    raw_health: dict[str, Any] = Field(default_factory=dict)

    @property
    def capacity_remaining(self) -> int:
        account_slots = max(0, self.accounts_ready)
        job_slots = max(0, self.max_jobs - self.active_jobs)
        return min(account_slots, job_slots)


class WorkerRecord(BaseModel):
    id: str
    base_url: str
    enabled: bool = True
    max_jobs: int = Field(default=10, ge=1)
    weight: int = Field(default=100, ge=1)
    status: WorkerStatus | None = None
