from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, HttpUrl


class WorkerSeed(BaseModel):
    id: str
    base_url: str
    enabled: bool = True
    max_jobs: int = Field(default=10, ge=1)
    weight: int = Field(default=100, ge=1)


class QueueSettings(BaseModel):
    name: str = "flow_global_jobs"
    max_retries: int = Field(default=3, ge=0)
    retry_delay_seconds: int = Field(default=60, ge=0)
    scheduler_interval_seconds: float = Field(default=1.0, gt=0)
    status_sync_interval_seconds: float = Field(default=5.0, gt=0)
    dispatch_timeout_seconds: int = Field(default=30, ge=5)
    stale_processing_seconds: int = Field(default=3600, ge=60)


class FlowGenerationSettings(BaseModel):
    model: str
    duration: int | None = Field(default=None, ge=1)
    estimated_credits: int = Field(default=0, ge=0)
    presets: dict[str, Any] = Field(default_factory=dict)


class FlowSettings(BaseModel):
    text_to_image: FlowGenerationSettings = Field(
        default_factory=lambda: FlowGenerationSettings(model="nano-banana-2", estimated_credits=20)
    )
    image_to_image: FlowGenerationSettings = Field(
        default_factory=lambda: FlowGenerationSettings(model="nano-banana-2-edit", estimated_credits=25)
    )
    text_to_video: FlowGenerationSettings = Field(
        default_factory=lambda: FlowGenerationSettings(model="veo-3.1-fast", duration=8, estimated_credits=160)
    )
    image_to_video: FlowGenerationSettings = Field(
        default_factory=lambda: FlowGenerationSettings(model="veo-3.1-quality", duration=8, estimated_credits=300)
    )


class StorageSettings(BaseModel):
    r2_endpoint_url: str | None = None
    r2_bucket: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    r2_public_base_url: str | None = None


class SecuritySettings(BaseModel):
    api_key: str | None = None
    allow_public_health: bool = True
    allow_public_docs: bool = False
    trusted_worker_api_key: str | None = None
    rate_limit_per_minute: int = Field(default=30, ge=1)


class Settings(BaseModel):
    orchestrator_id: str = "global-orchestrator-1"
    api_host: str = "0.0.0.0"
    api_port: int = 8090
    config_path: Path = Path("/orchestrator/config/orchestrator.yaml")
    logs_dir: Path = Path("/tmp/orchestrator/logs")
    redis_url: str = ""
    database_url: str | None = None
    mongodb_uri: str | None = None
    mongodb_database: str = "flowkit_orchestrator"
    public_base_url: HttpUrl | None = None
    queue: QueueSettings = Field(default_factory=QueueSettings)
    flow_settings: FlowSettings = Field(default_factory=FlowSettings)
    workers: list[WorkerSeed] = Field(default_factory=list)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)

    def ensure_directories(self) -> None:
        if not self.config_path.parent.exists():
            try:
                self.config_path.parent.mkdir(parents=True, exist_ok=True)
            except PermissionError:
                pass
        self.logs_dir.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    config_path = Path(os.getenv("ORCHESTRATOR_CONFIG", "/orchestrator/config/orchestrator.yaml"))
    if not config_path.exists() and config_path.is_absolute():
        repo_config_path = Path("config/orchestrator.yaml")
        if repo_config_path.exists():
            config_path = repo_config_path
    data: dict[str, Any] = {}
    if config_path.exists():
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    data["config_path"] = str(config_path)

    env: dict[str, Any] = {}
    for name, key in [
        ("ORCHESTRATOR_ID", "orchestrator_id"),
        ("ORCHESTRATOR_REDIS_URL", "redis_url"),
        ("DATABASE_URL", "database_url"),
        ("MONGODB_URI", "mongodb_uri"),
        ("MONGODB_DATABASE", "mongodb_database"),
        ("ORCHESTRATOR_PUBLIC_BASE_URL", "public_base_url"),
        ("ORCHESTRATOR_LOGS_DIR", "logs_dir"),
    ]:
        if os.getenv(name):
            env[key] = os.environ[name]
    storage_env: dict[str, Any] = {}
    for name, key in [
        ("R2_ENDPOINT_URL", "r2_endpoint_url"),
        ("R2_BUCKET", "r2_bucket"),
        ("R2_ACCESS_KEY_ID", "r2_access_key_id"),
        ("R2_SECRET_ACCESS_KEY", "r2_secret_access_key"),
        ("R2_PUBLIC_BASE_URL", "r2_public_base_url"),
    ]:
        if os.getenv(name):
            storage_env[key] = os.environ[name]
    if storage_env:
        env["storage"] = storage_env
    security_env: dict[str, Any] = {}
    for name, key in [
        ("ORCHESTRATOR_API_KEY", "api_key"),
        ("WORKER_API_KEY", "trusted_worker_api_key"),
    ]:
        if os.getenv(name):
            security_env[key] = os.environ[name]
    for name, key in [
        ("ORCHESTRATOR_ALLOW_PUBLIC_HEALTH", "allow_public_health"),
        ("ORCHESTRATOR_ALLOW_PUBLIC_DOCS", "allow_public_docs"),
    ]:
        if os.getenv(name):
            security_env[key] = os.environ[name].lower() in {"1", "true", "yes", "on"}
    if os.getenv("ORCHESTRATOR_RATE_LIMIT_PER_MINUTE"):
        security_env["rate_limit_per_minute"] = int(os.environ["ORCHESTRATOR_RATE_LIMIT_PER_MINUTE"])
    if security_env:
        env["security"] = security_env
    if os.getenv("ORCHESTRATOR_API_PORT"):
        env["api_port"] = int(os.environ["ORCHESTRATOR_API_PORT"])
    return Settings.model_validate(_deep_merge(data, env))


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged
