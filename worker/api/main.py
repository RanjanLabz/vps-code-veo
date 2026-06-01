from __future__ import annotations

import asyncio
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import yaml
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from worker.accounts.manager import AccountManager
from worker.config.flow_settings import FlowConfigManager, GenerationType
from worker.config.settings import Settings, load_settings
from worker.core.app_state import AppState
from worker.core.logging_config import configure_logging
from worker.health.reporter import HealthReporter
from worker.queue.manager import QueueManager
from worker.queue.scheduler import Scheduler
from worker.storage.account_store import AccountStore


class GenerationRequest(BaseModel):
    prompt: str = Field(min_length=1)
    inputs: dict | None = None
    presets: dict | None = None
    metadata: dict | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = load_settings()
    settings.ensure_directories()
    configure_logging(settings)
    queue = QueueManager(settings.redis_url, settings.queue)
    await queue.connect()
    config_path = Path(os.getenv("WORKER_CONFIG", "/worker/config/worker.yaml"))
    flow_config = FlowConfigManager.from_worker_config(config_path)

    store = AccountStore(settings.paths.accounts_dir)
    account_manager = AccountManager(settings, store)
    await account_manager.load_existing_accounts()

    scheduler = Scheduler(settings, account_manager, queue)
    reporter = HealthReporter(settings, account_manager, queue)
    state = AppState(settings=settings, accounts=account_manager, flow_config=flow_config, queue=queue, scheduler=scheduler, health=reporter)
    app.state.worker = state

    await scheduler.start()
    yield
    await scheduler.stop()
    await account_manager.shutdown()
    await queue.close()


app = FastAPI(
    title="Flow Worker Appliance",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if load_settings().security.allow_public_docs else None,
    redoc_url="/redoc" if load_settings().security.allow_public_docs else None,
    openapi_url="/openapi.json" if load_settings().security.allow_public_docs else None,
)


def state() -> AppState:
    return app.state.worker


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    settings = state().settings if hasattr(app.state, "worker") else load_settings()
    path = request.url.path
    if is_public_path(path, settings.security.allow_public_health, settings.security.allow_public_docs):
        return await call_next(request)
    if not settings.security.api_key:
        return JSONResponse({"detail": "WORKER_API_KEY is required before exposing this service"}, status_code=503)
    provided = request.headers.get("x-api-key") or bearer_token(request.headers.get("authorization"))
    if not provided or not secrets.compare_digest(provided, settings.security.api_key):
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    return await call_next(request)


def is_public_path(path: str, allow_public_health: bool, allow_public_docs: bool) -> bool:
    if path == "/":
        return True
    if allow_public_health and path == "/health":
        return True
    if allow_public_docs and path in {"/docs", "/redoc", "/openapi.json"}:
        return True
    return False


def bearer_token(value: str | None) -> str | None:
    if not value:
        return None
    scheme, _, token = value.partition(" ")
    return token if scheme.lower() == "bearer" and token else None


def account_response(request: Request | None, account) -> dict:
    data = account.model_dump()
    data["vnc_web_url"] = None
    data["vnc_web_port"] = None
    if account.vnc_port is not None:
        offset = account.vnc_port - state().settings.vnc.vnc_start_port
        novnc_port = state().settings.vnc.novnc_start_port + offset
        data["vnc_web_port"] = novnc_port
        host = request.url.hostname if request is not None else None
        if host:
            data["vnc_web_url"] = f"{request.url.scheme}://{host}:{novnc_port}/vnc.html?autoconnect=1&resize=remote"
    return data


def persist_queue_settings(queue_data: dict) -> None:
    config_path = Path(os.getenv("WORKER_CONFIG", "/worker/config/worker.yaml"))
    config = {}
    if config_path.exists():
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    config["queue"] = {**config.get("queue", {}), **queue_data}
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


def generation_payload(generation_type: GenerationType, request: GenerationRequest) -> dict:
    flow_settings = state().flow_config.generation_payload(generation_type)
    payload = request.model_dump(exclude_none=True)
    payload.update(
        {
            "generation_type": generation_type,
            "flow_settings": flow_settings,
            "flow_model": flow_settings["model"],
            "duration": flow_settings.get("duration"),
            "estimated_credits": flow_settings["estimated_credits"],
        }
    )
    return payload


@app.get("/health")
async def health() -> dict:
    return await state().health.snapshot()


@app.get("/settings/queue")
async def get_queue_settings() -> dict:
    return state().settings.queue.model_dump()


@app.patch("/settings/queue")
async def patch_queue_settings(payload: dict) -> dict:
    allowed = {
        "max_retries",
        "retry_delay_seconds",
        "scheduler_interval_seconds",
        "job_timeout_seconds",
    }
    updates = {key: payload[key] for key in allowed if key in payload}
    if not updates:
        raise HTTPException(status_code=400, detail=f"provide one of: {', '.join(sorted(allowed))}")

    current = state().settings.queue.model_dump()
    current.update(updates)
    updated = type(state().settings.queue).model_validate(current)
    state().settings.queue = updated
    state().queue.settings = updated
    persist_queue_settings(updated.model_dump())
    return updated.model_dump()


@app.get("/flow-settings")
async def get_flow_settings() -> dict:
    return state().flow_config.snapshot().model_dump(exclude_none=True)


@app.patch("/flow-settings")
async def patch_flow_settings(payload: dict) -> dict:
    try:
        return state().flow_config.patch(payload).model_dump(exclude_none=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/accounts")
async def list_accounts(request: Request) -> list[dict]:
    return [account_response(request, account) for account in state().accounts.list_accounts()]


@app.get("/accounts/{account_id}")
async def get_account(request: Request, account_id: str) -> dict:
    account = state().accounts.get_account(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="account not found")
    return account_response(request, account)


@app.post("/accounts", status_code=201)
async def create_account(request: Request, payload: dict) -> dict:
    account = await state().accounts.create_account(payload)
    return account_response(request, account)


@app.delete("/accounts/{account_id}")
async def delete_account(account_id: str, remove_profile: bool = Query(False)) -> dict:
    await state().accounts.delete_account(account_id, remove_profile=remove_profile)
    return {"deleted": True, "id": account_id, "profile_removed": remove_profile}


@app.post("/accounts/{account_id}/start")
async def start_account(request: Request, account_id: str) -> dict:
    account = await state().accounts.start_account(account_id)
    return account_response(request, account)


@app.post("/accounts/{account_id}/stop")
async def stop_account(request: Request, account_id: str) -> dict:
    account = await state().accounts.stop_account(account_id)
    return account_response(request, account)


@app.post("/accounts/{account_id}/restart")
async def restart_account(request: Request, account_id: str) -> dict:
    account = await state().accounts.restart_account(account_id)
    return account_response(request, account)


@app.post("/accounts/{account_id}/recover")
async def recover_account(request: Request, account_id: str) -> dict:
    account = await state().accounts.recover_account(account_id, reason="manual-api")
    return account_response(request, account)


@app.patch("/accounts/{account_id}/proxy")
async def patch_proxy(request: Request, account_id: str, payload: dict) -> dict:
    account = await state().accounts.update_proxy(account_id, payload)
    return account_response(request, account)


@app.patch("/accounts/{account_id}/settings")
async def patch_settings(request: Request, account_id: str, payload: dict) -> dict:
    account = await state().accounts.update_settings(account_id, payload)
    return account_response(request, account)


@app.post("/jobs", status_code=201)
async def create_job(payload: dict) -> dict:
    job = await state().queue.enqueue(payload)
    return job.model_dump()


@app.post("/generate/text-to-image", status_code=202)
async def generate_text_to_image(payload: GenerationRequest) -> dict:
    job = await state().queue.enqueue(generation_payload("text_to_image", payload))
    return job.model_dump()


@app.post("/generate/image-to-image", status_code=202)
async def generate_image_to_image(payload: GenerationRequest) -> dict:
    job = await state().queue.enqueue(generation_payload("image_to_image", payload))
    return job.model_dump()


@app.post("/generate/text-to-video", status_code=202)
async def generate_text_to_video(payload: GenerationRequest) -> dict:
    job = await state().queue.enqueue(generation_payload("text_to_video", payload))
    return job.model_dump()


@app.post("/generate/image-to-video", status_code=202)
async def generate_image_to_video(payload: GenerationRequest) -> dict:
    job = await state().queue.enqueue(generation_payload("image_to_video", payload))
    return job.model_dump()


@app.post("/flowkit/{account_id}/callback")
async def flowkit_callback(account_id: str, payload: dict) -> dict:
    return await state().accounts.handle_flowkit_callback(account_id, payload)


@app.get("/jobs")
async def list_jobs(limit: int = Query(100, ge=1, le=1000)) -> list[dict]:
    jobs = await state().queue.list_jobs(limit=limit)
    return [job.model_dump() for job in jobs]


@app.get("/jobs/{job_id}")
async def get_job(job_id: str) -> dict:
    job = await state().queue.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job.model_dump()


@app.get("/media/videos/{filename}")
async def get_generated_video(filename: str) -> FileResponse:
    if "/" in filename or "\\" in filename or not filename.endswith(".mp4"):
        raise HTTPException(status_code=400, detail="invalid video filename")
    path = state().settings.paths.logs_dir / "videos" / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="video not found")
    return FileResponse(path, media_type="video/mp4", filename=filename)


@app.get("/")
async def root() -> dict:
    return {"service": "flow-worker-appliance", "docs": "/docs", "health": "/health"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("worker.api.main:app", host="0.0.0.0", port=8080, workers=1, reload=False)
