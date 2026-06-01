from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AccountStatus(StrEnum):
    READY = "READY"
    BUSY = "BUSY"
    COOLDOWN = "COOLDOWN"
    STOPPED = "STOPPED"
    CAPTCHA_REQUIRED = "CAPTCHA_REQUIRED"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    BROKEN_SESSION = "BROKEN_SESSION"
    BLOCKED = "BLOCKED"


class AccountSettings(BaseModel):
    flow_url: str | None = None
    max_concurrent_jobs: int = Field(default=1, ge=1)
    cooldown_until: datetime | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Account(BaseModel):
    id: str
    profile_path: str
    proxy_enabled: bool = False
    proxy_url: str | None = None
    proxy_health_score: int = Field(default=100, ge=0, le=100)
    status: AccountStatus = AccountStatus.READY
    jobs_running: int = 0
    last_used: datetime | None = None
    health_score: int = Field(default=100, ge=0, le=100)
    failure_count: int = 0
    success_count: int = 0
    browser_pid: int | None = None
    remote_debugging_port: int | None = None
    display: str | None = None
    vnc_port: int | None = None
    flowkit_ws_port: int | None = None
    flowkit_callback_url: str | None = None
    extension_runtime_path: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    settings: AccountSettings = Field(default_factory=AccountSettings)

    def mark_updated(self) -> None:
        self.updated_at = utc_now()
