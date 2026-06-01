from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


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


class Job(BaseModel):
    id: str = Field(default_factory=lambda: f"job-{uuid4().hex}")
    prompt: str
    generation_type: str | None = None
    flow_model: str | None = None
    duration: int | None = None
    estimated_credits: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    timeline: dict[str, datetime] = Field(default_factory=dict)
    state: JobState = JobState.QUEUED
    account_id: str | None = None
    retries: int = 0
    max_retries: int = 3
    created_at: datetime = Field(default_factory=utc_now)
    queued_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    last_error: str | None = None
    output_urls: list[str] = Field(default_factory=list)

    def stamp(self, stage: str) -> None:
        self.timeline[stage] = utc_now()

    @classmethod
    def from_payload(cls, payload: dict[str, Any], max_retries: int) -> "Job":
        prompt = str(payload.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("job payload requires non-empty prompt")
        flow_settings = payload.get("flow_settings") if isinstance(payload.get("flow_settings"), dict) else {}
        job = cls(
            prompt=prompt,
            generation_type=payload.get("generation_type"),
            flow_model=flow_settings.get("model") or payload.get("flow_model"),
            duration=flow_settings.get("duration") or payload.get("duration"),
            estimated_credits=flow_settings.get("estimated_credits") or payload.get("estimated_credits"),
            payload=payload,
            max_retries=max_retries,
        )
        job.stamp("local_queued")
        return job
