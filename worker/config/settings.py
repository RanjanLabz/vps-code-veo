from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class PathSettings(BaseModel):
    base_dir: Path = Path("/opt/flow-worker")
    chrome_profiles_dir: Path = Path("/chrome-profiles")
    extension_dir: Path = Path("/extension")
    runtime_extension_dir: Path = Path("/tmp/flow-worker-extensions")
    fleet_extensions_dir: Path = Path("/chrome-profiles/_fleet-extensions")
    accounts_dir: Path = Path("/worker/accounts")
    logs_dir: Path = Path("/worker/logs")


class BrowserSettings(BaseModel):
    chrome_binary: str = "google-chrome"
    remote_debugging_host: str = "127.0.0.1"
    remote_debugging_start_port: int = 12000
    default_flow_url: str = "https://labs.google/fx/tools/flow"
    launch_timeout_seconds: int = 45
    navigation_timeout_ms: int = 60000
    extra_args: list[str] = Field(default_factory=list)


class VncSettings(BaseModel):
    display_start: int = 100
    vnc_start_port: int = 5901
    novnc_start_port: int = 6080
    novnc_web_dir: str = "/opt/noVNC"
    width: int = 1440
    height: int = 1000
    depth: int = 24
    password: str | None = None


class QueueSettings(BaseModel):
    name: str = "flow_jobs"
    max_retries: int = 3
    retry_delay_seconds: int = 60
    scheduler_interval_seconds: float = 1.0
    job_timeout_seconds: int = 900


class RecoverySettings(BaseModel):
    enabled: bool = True
    max_attempts: int = 3
    cooldown_seconds: int = 120


class FlowKitSettings(BaseModel):
    enabled: bool = True
    ws_host: str = "127.0.0.1"
    ws_start_port: int = 9222


class SecuritySettings(BaseModel):
    api_key: str | None = None
    allow_public_health: bool = True
    allow_public_docs: bool = False


class Settings(BaseModel):
    worker_id: str = "vps-worker-1"
    api_port: int = 8080
    redis_url: str = ""
    autostart_accounts: bool = True
    paths: PathSettings = Field(default_factory=PathSettings)
    browser: BrowserSettings = Field(default_factory=BrowserSettings)
    vnc: VncSettings = Field(default_factory=VncSettings)
    queue: QueueSettings = Field(default_factory=QueueSettings)
    recovery: RecoverySettings = Field(default_factory=RecoverySettings)
    flowkit: FlowKitSettings = Field(default_factory=FlowKitSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)

    def ensure_directories(self) -> None:
        for path in [
            self.paths.base_dir,
            self.paths.chrome_profiles_dir,
            self.paths.extension_dir,
            self.paths.runtime_extension_dir,
            self.paths.fleet_extensions_dir,
            self.paths.accounts_dir,
            self.paths.logs_dir,
        ]:
            path.mkdir(parents=True, exist_ok=True)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_settings() -> Settings:
    config_path = Path(os.getenv("WORKER_CONFIG", "/worker/config/worker.yaml"))
    data: dict[str, Any] = {}
    if config_path.exists():
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

    env_overrides: dict[str, Any] = {}
    if os.getenv("WORKER_ID"):
        env_overrides["worker_id"] = os.environ["WORKER_ID"]
    if os.getenv("REDIS_URL"):
        env_overrides["redis_url"] = os.environ["REDIS_URL"]
    if os.getenv("WORKER_API_PORT"):
        env_overrides["api_port"] = int(os.environ["WORKER_API_PORT"])
    if os.getenv("CHROME_BINARY"):
        env_overrides.setdefault("browser", {})["chrome_binary"] = os.environ["CHROME_BINARY"]
    if os.getenv("FLOW_URL"):
        env_overrides.setdefault("browser", {})["default_flow_url"] = os.environ["FLOW_URL"]
    if os.getenv("VNC_PASSWORD"):
        env_overrides.setdefault("vnc", {})["password"] = os.environ["VNC_PASSWORD"]
    security_env: dict[str, Any] = {}
    if os.getenv("WORKER_API_KEY"):
        security_env["api_key"] = os.environ["WORKER_API_KEY"]
    if os.getenv("WORKER_ALLOW_PUBLIC_HEALTH"):
        security_env["allow_public_health"] = os.environ["WORKER_ALLOW_PUBLIC_HEALTH"].lower() in {"1", "true", "yes", "on"}
    if os.getenv("WORKER_ALLOW_PUBLIC_DOCS"):
        security_env["allow_public_docs"] = os.environ["WORKER_ALLOW_PUBLIC_DOCS"].lower() in {"1", "true", "yes", "on"}
    if security_env:
        env_overrides["security"] = security_env

    return Settings.model_validate(_deep_merge(data, env_overrides))
