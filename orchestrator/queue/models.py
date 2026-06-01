from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

GenerationType = Literal["text_to_image", "image_to_image", "text_to_video", "image_to_video"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class JobState(StrEnum):
    QUEUED = "QUEUED"
    ASSIGNED = "ASSIGNED"
    PROCESSING = "PROCESSING"
    RETRYING = "RETRYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"


class GlobalJob(BaseModel):
    id: str = Field(default_factory=lambda: f"gjob-{uuid4().hex}")
    prompt: str
    generation_type: GenerationType
    flow_settings: dict[str, Any]
    production_defaults_used: bool = True
    preferred_worker_id: str | None = None
    preferred_account_id: str | None = None
    assigned_worker_id: str | None = None
    worker_job_id: str | None = None
    state: JobState = JobState.QUEUED
    retries: int = 0
    max_retries: int = 3
    payload: dict[str, Any] = Field(default_factory=dict)
    timeline: dict[str, datetime] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    queued_at: datetime = Field(default_factory=utc_now)
    assigned_at: datetime | None = None
    completed_at: datetime | None = None
    last_error: str | None = None

    def stamp(self, stage: str) -> None:
        self.timeline[stage] = utc_now()

    @property
    def flow_model(self) -> str | None:
        model = self.flow_settings.get("model")
        return str(model) if model else None

    @property
    def estimated_credits(self) -> int | None:
        value = self.flow_settings.get("estimated_credits")
        return int(value) if value is not None else None
