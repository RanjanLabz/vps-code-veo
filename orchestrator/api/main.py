from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import os
import secrets
import time
from typing import Any, AsyncIterator, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from orchestrator.capacity.manager import CapacityManager
from orchestrator.config.settings import load_settings
from orchestrator.core import OrchestratorState
from orchestrator.db.store import OrchestratorStore
from orchestrator.flow_config.catalog import MODEL_CATALOG
from orchestrator.flow_config.manager import FlowConfigManager
from orchestrator.queue.manager import GlobalQueue
from orchestrator.queue.models import GenerationType, GlobalJob
from orchestrator.scheduler.service import GlobalScheduler
from orchestrator.workers.client import WorkerClient
from orchestrator.workers.registry import WorkerRegistry


class GenerationRequest(BaseModel):
    prompt: str = Field(min_length=1)
    caption: str | None = None
    aspect_ratio: Literal["16:9", "9:16", "1:1"] = "16:9"
    inputs: dict[str, Any] | None = None
    presets: dict[str, Any] | None = None
    flow_override: dict[str, Any] | None = None
    preferred_worker_id: str | None = None
    preferred_account_id: str | None = None
    metadata: dict[str, Any] | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = load_settings()
    settings.ensure_directories()
    queue = GlobalQueue(settings.redis_url, settings.queue)
    await queue.connect()
    store = OrchestratorStore(settings.database_url, settings.mongodb_uri, settings.mongodb_database)
    await store.connect()
    worker_client = WorkerClient(
        timeout_seconds=settings.queue.dispatch_timeout_seconds,
        api_key=settings.security.trusted_worker_api_key,
    )
    registry = WorkerRegistry(settings.workers, worker_client, store)
    await registry.load()
    capacity = CapacityManager(registry)
    flow_config = FlowConfigManager(settings.config_path, settings.flow_settings)
    scheduler = GlobalScheduler(settings, queue, capacity, worker_client, store)
    state = OrchestratorState(
        settings=settings,
        flow_config=flow_config,
        queue=queue,
        workers=registry,
        capacity=capacity,
        worker_client=worker_client,
        scheduler=scheduler,
        store=store,
    )
    app.state.orchestrator = state
    await registry.refresh_all()
    await scheduler.start()
    yield
    await scheduler.stop()
    await worker_client.close()
    await queue.close()
    await store.close()


app = FastAPI(
    title="Flow Global Orchestrator",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if load_settings().security.allow_public_docs else None,
    redoc_url="/redoc" if load_settings().security.allow_public_docs else None,
    openapi_url="/openapi.json" if load_settings().security.allow_public_docs else None,
)
_rate_buckets: dict[str, list[float]] = {}


def state() -> OrchestratorState:
    return app.state.orchestrator


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    settings = state().settings if hasattr(app.state, "orchestrator") else load_settings()
    path = request.url.path
    if is_public_path(path, settings.security.allow_public_health, settings.security.allow_public_docs):
        return await call_next(request)
    if not settings.security.api_key:
        return JSONResponse({"detail": "ORCHESTRATOR_API_KEY is required before exposing this service"}, status_code=503)
    provided = request.headers.get("x-api-key") or bearer_token(request.headers.get("authorization"))
    if not provided or not secrets.compare_digest(provided, settings.security.api_key):
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    if path.startswith("/generate/"):
        allowed = rate_limit(request, settings.security.rate_limit_per_minute)
        if not allowed:
            return JSONResponse({"detail": "rate limit exceeded"}, status_code=429)
    return await call_next(request)


def is_public_path(path: str, allow_public_health: bool, allow_public_docs: bool) -> bool:
    if path == "/":
        return True
    if path == "/version":
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


def rate_limit(request: Request, limit: int) -> bool:
    now = time.monotonic()
    client = request.client.host if request.client else "unknown"
    key = f"{client}:{request.url.path}"
    window_start = now - 60
    bucket = [item for item in _rate_buckets.get(key, []) if item >= window_start]
    if len(bucket) >= limit:
        _rate_buckets[key] = bucket
        return False
    bucket.append(now)
    _rate_buckets[key] = bucket
    return True


@app.get("/")
async def root() -> dict:
    docs = "/docs" if state().settings.security.allow_public_docs else None
    return {
        "service": "flow-global-orchestrator",
        "docs": docs,
        "health": "/health",
        "version": deployment_version(),
    }


@app.get("/version")
async def version() -> dict[str, str | None]:
    return deployment_version()


def deployment_version() -> dict[str, str | None]:
    return {
        "commit": os.getenv("RENDER_GIT_COMMIT") or os.getenv("GIT_COMMIT"),
        "branch": os.getenv("RENDER_GIT_BRANCH") or os.getenv("GIT_BRANCH"),
        "service": os.getenv("RENDER_SERVICE_NAME"),
    }


@app.get("/health")
async def health() -> dict:
    statuses = await state().workers.refresh_all()
    for status in statuses:
        await state().store.save_worker_status(status)
    return {
        "orchestrator_id": state().settings.orchestrator_id,
        "queue": await state().queue.stats(),
        "database": state().store.status(),
        "storage": {
            "r2_configured": bool(
                state().settings.storage.r2_endpoint_url
                and state().settings.storage.r2_bucket
                and state().settings.storage.r2_access_key_id
                and state().settings.storage.r2_secret_access_key
            ),
            "r2_bucket": state().settings.storage.r2_bucket,
        },
        "workers_total": len(state().workers.list_workers()),
        "workers_online": len([status for status in statuses if status.online]),
        "workers": [status.model_dump() for status in statuses],
    }


@app.get("/metrics")
async def metrics(limit: int = Query(1000, ge=1, le=5000)) -> dict:
    jobs = await state().queue.list_jobs(limit=limit)
    statuses = await state().workers.refresh_all()
    now = datetime.now(timezone.utc)
    by_state: dict[str, int] = {}
    by_type: dict[str, int] = {}
    total_seconds: list[float] = []
    global_queue_seconds: list[float] = []
    local_account_queue_seconds: list[float] = []
    queue_to_account_seconds: list[float] = []
    processing_seconds: list[float] = []
    last_15m = 0
    last_1h = 0
    failed = 0
    completed = 0

    for job in jobs:
        by_state[job.state.value] = by_state.get(job.state.value, 0) + 1
        by_type[job.generation_type] = by_type.get(job.generation_type, 0) + 1
        if job.state.value in {"FAILED", "TIMEOUT"}:
            failed += 1
        if job.state.value == "COMPLETED":
            completed += 1
        if job.created_at >= now - timedelta(minutes=15):
            last_15m += 1
        if job.created_at >= now - timedelta(hours=1):
            last_1h += 1

        created = job.timeline.get("api_received") or job.created_at
        vps_selected = job.timeline.get("vps_selected") or job.assigned_at
        completed_at = job.completed_at
        if vps_selected:
            global_queue_seconds.append((vps_selected - created).total_seconds())

        worker_result = metrics_worker_result(job)
        local_queued = parse_datetime(worker_result.get("queued_at")) if worker_result else None
        account_started = (
            parse_datetime((worker_result.get("timeline") or {}).get("account_selected"))
            or parse_datetime(worker_result.get("started_at"))
            if worker_result
            else None
        )
        if local_queued and account_started:
            local_account_queue_seconds.append((account_started - local_queued).total_seconds())
        if account_started:
            queue_to_account_seconds.append((account_started - created).total_seconds())

        processing_started = account_started or vps_selected
        if processing_started and completed_at:
            processing_seconds.append((completed_at - processing_started).total_seconds())
        if completed_at:
            total_seconds.append((completed_at - created).total_seconds())

    free_slots = sum(status.capacity_remaining for status in statuses if status.online)
    queue_depth = by_state.get("QUEUED", 0) + by_state.get("RETRYING", 0)
    active_jobs = by_state.get("ASSIGNED", 0) + by_state.get("PROCESSING", 0)
    recommendations: list[str] = []
    if queue_depth > 0 and free_slots == 0:
        recommendations.append("Add more logged-in accounts or another VPS: jobs are waiting with no free account slots.")
    if queue_depth > free_slots and free_slots > 0:
        recommendations.append("Queue is larger than free capacity; add accounts if this stays high.")
    if any(status.cpu >= 92 for status in statuses if status.online):
        recommendations.append("At least one VPS is CPU saturated; add another VPS or reduce accounts running per VPS.")
    if failed > completed and failed > 0:
        recommendations.append("Failures exceed completions; check account auth, FlowKit token, and model access before scaling.")

    return {
        "sample_size": len(jobs),
        "total_jobs": len(jobs),
        "by_state": by_state,
        "by_type": by_type,
        "completed_jobs": completed,
        "failed_jobs": failed,
        "active_jobs": active_jobs,
        "global_queue_depth": queue_depth,
        "requested_last_15m": last_15m,
        "requested_last_1h": last_1h,
        "avg_total_job_seconds": average(total_seconds),
        "avg_wait_seconds": average(queue_to_account_seconds),
        "avg_global_queue_seconds": average(global_queue_seconds),
        "avg_local_account_queue_seconds": average(local_account_queue_seconds),
        "avg_queue_to_account_seconds": average(queue_to_account_seconds),
        "avg_processing_seconds": average(processing_seconds),
        "total_job_seconds": round(sum(total_seconds), 2),
        "total_wait_seconds": round(sum(queue_to_account_seconds), 2),
        "total_global_queue_seconds": round(sum(global_queue_seconds), 2),
        "total_local_account_queue_seconds": round(sum(local_account_queue_seconds), 2),
        "total_queue_to_account_seconds": round(sum(queue_to_account_seconds), 2),
        "total_processing_seconds": round(sum(processing_seconds), 2),
        "free_account_slots": free_slots,
        "workers_online": len([status for status in statuses if status.online]),
        "workers_total": len(statuses),
        "recommendations": recommendations,
    }


@app.get("/workers")
async def list_workers(refresh: bool = Query(True)) -> list[dict]:
    if refresh:
        await state().workers.refresh_all()
    return [worker.model_dump() for worker in state().workers.list_workers()]


@app.post("/workers", status_code=201)
async def upsert_worker(payload: dict) -> dict:
    worker = await state().workers.upsert(payload)
    await state().workers.refresh_one(worker)
    return worker.model_dump()


@app.get("/workers/{worker_id}/accounts")
async def list_worker_accounts(worker_id: str) -> list[dict]:
    worker = state().workers.get(worker_id)
    if worker is None:
        raise HTTPException(status_code=404, detail="worker not found")
    return await state().worker_client.accounts(worker)


@app.post("/workers/{worker_id}/accounts", status_code=201)
async def create_worker_account(worker_id: str, payload: dict) -> dict:
    worker = state().workers.get(worker_id)
    if worker is None:
        raise HTTPException(status_code=404, detail="worker not found")
    return await state().worker_client.create_account(worker, payload)


@app.delete("/workers/{worker_id}/accounts/{account_id}")
async def delete_worker_account(worker_id: str, account_id: str, remove_profile: bool = Query(False)) -> dict:
    worker = state().workers.get(worker_id)
    if worker is None:
        raise HTTPException(status_code=404, detail="worker not found")
    return await state().worker_client.delete_account(worker, account_id, remove_profile)


@app.post("/workers/{worker_id}/accounts/{account_id}/{action}")
async def worker_account_action(worker_id: str, account_id: str, action: str) -> dict:
    if action not in {"start", "stop", "restart", "recover"}:
        raise HTTPException(status_code=400, detail="action must be start, stop, restart, or recover")
    worker = state().workers.get(worker_id)
    if worker is None:
        raise HTTPException(status_code=404, detail="worker not found")
    return await state().worker_client.account_action(worker, account_id, action)


@app.patch("/workers/{worker_id}/accounts/{account_id}/settings")
async def update_worker_account_settings(worker_id: str, account_id: str, payload: dict) -> dict:
    worker = state().workers.get(worker_id)
    if worker is None:
        raise HTTPException(status_code=404, detail="worker not found")
    return await state().worker_client.update_account_settings(worker, account_id, payload)


@app.patch("/workers/{worker_id}/accounts/{account_id}/proxy")
async def update_worker_account_proxy(worker_id: str, account_id: str, payload: dict) -> dict:
    worker = state().workers.get(worker_id)
    if worker is None:
        raise HTTPException(status_code=404, detail="worker not found")
    return await state().worker_client.update_account_proxy(worker, account_id, payload)


@app.delete("/workers/{worker_id}")
async def delete_worker(worker_id: str) -> dict:
    await state().workers.delete(worker_id)
    return {"deleted": True, "id": worker_id}


@app.get("/flow-settings")
async def get_flow_settings() -> dict:
    return state().flow_config.snapshot().model_dump(exclude_none=True)


@app.get("/flow-models")
async def get_flow_models() -> dict:
    return MODEL_CATALOG


@app.patch("/flow-settings")
async def patch_flow_settings(payload: dict) -> dict:
    try:
        updated = state().flow_config.patch(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return updated.model_dump(exclude_none=True)


@app.post("/generate/text-to-image", status_code=202)
async def generate_text_to_image(payload: GenerationRequest) -> dict:
    return public_job_dump(await enqueue_generation("text_to_image", payload))


@app.post("/generate/image-to-image", status_code=202)
async def generate_image_to_image(payload: GenerationRequest) -> dict:
    return public_job_dump(await enqueue_generation("image_to_image", payload))


@app.post("/generate/text-to-video", status_code=202)
async def generate_text_to_video(payload: GenerationRequest) -> dict:
    return public_job_dump(await enqueue_generation("text_to_video", payload))


@app.post("/generate/image-to-video", status_code=202)
async def generate_image_to_video(payload: GenerationRequest) -> dict:
    return public_job_dump(await enqueue_generation("image_to_video", payload))


@app.get("/jobs")
async def list_jobs(limit: int = Query(100, ge=1, le=1000)) -> list[dict]:
    jobs = await state().queue.list_jobs(limit=limit)
    return [await enriched_job(job) for job in jobs]


@app.get("/jobs/{job_id}")
async def get_job(job_id: str) -> dict:
    job = await state().queue.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return await enriched_job(job)


async def enriched_job(job: GlobalJob) -> dict:
    data = public_job_dump(job)
    if not job.assigned_worker_id:
        data["routing_status"] = "waiting_for_vps"
        data["capacity_snapshot"] = capacity_snapshot()
        data["progress"] = await job_progress(job, data)
        return data
    worker = state().workers.get(job.assigned_worker_id)
    if worker is None:
        data["routing_status"] = "assigned_worker_missing"
        data["worker_status_error"] = "Assigned VPS is no longer registered"
        data["progress"] = await job_progress(job, data)
        return data
    if not job.worker_job_id:
        data["routing_status"] = "assigned_to_vps_waiting_for_local_job"
        data["progress"] = await job_progress(job, data)
        return data
    try:
        data["live_worker_job"] = redact_large_payload(await state().worker_client.job(worker, job.worker_job_id))
        data["routing_status"] = "local_job_visible"
    except Exception as exc:
        data["routing_status"] = "local_job_unreachable"
        data["worker_status_error"] = str(exc)
    data["progress"] = await job_progress(job, data)
    return data


def public_job_dump(job: GlobalJob) -> dict[str, Any]:
    return redact_large_payload(job.model_dump())


def redact_large_payload(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, child in value.items():
            if key in {"image_data_url", "imageBytes", "encodedImage", "encodedVideo"}:
                redacted[key] = f"<redacted:{len(child)} chars>" if isinstance(child, str) else "<redacted>"
            else:
                redacted[key] = redact_large_payload(child)
        return redacted
    if isinstance(value, list):
        return [redact_large_payload(item) for item in value]
    return value


async def job_progress(job: GlobalJob, data: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    metrics_snapshot = await progress_metrics()
    worker_job = data.get("live_worker_job") if isinstance(data.get("live_worker_job"), dict) else None
    worker_timeline = worker_job.get("timeline") if isinstance(worker_job, dict) and isinstance(worker_job.get("timeline"), dict) else {}
    global_timeline = data.get("timeline") if isinstance(data.get("timeline"), dict) else {}
    state_value = str(data.get("state") or job.state.value)
    worker_state = str(worker_job.get("state") or "") if worker_job else ""
    effective_state = worker_state or state_value
    created = parse_datetime(global_timeline.get("api_received")) or job.created_at
    elapsed = max(0.0, (now - created).total_seconds())
    started = (
        parse_datetime(worker_timeline.get("local_processing_started"))
        or parse_datetime(worker_job.get("started_at")) if worker_job else None
    )
    outputs = worker_job.get("output_urls") if worker_job else None
    if not isinstance(outputs, list):
        outputs = []

    phase = "queued"
    message = "Waiting in global queue for a free VPS/account."
    percent = 5
    if job.assigned_worker_id:
        phase = "vps_selected"
        message = f"VPS selected: {job.assigned_worker_id}."
        percent = 18
    if job.worker_job_id:
        phase = "local_queue"
        message = "Accepted by VPS, waiting for local account scheduler."
        percent = 28
    if worker_job:
        if worker_job.get("account_id"):
            phase = "account_selected"
            message = f"Account selected: {worker_job.get('account_id')}."
            percent = 38
        if started or effective_state == "PROCESSING":
            phase = "generating"
            message = "FlowKit/Google Flow generation is running."
            percent = estimated_generation_percent(job.generation_type, started, now)
        if outputs:
            phase = "outputs_ready"
            message = f"{len(outputs)} output file{'s' if len(outputs) != 1 else ''} returned."
            percent = 98
    if effective_state == "COMPLETED":
        phase = "completed"
        message = "Completed successfully."
        percent = 100
    elif effective_state in {"FAILED", "TIMEOUT"}:
        phase = "failed"
        message = data.get("last_error") or (worker_job or {}).get("last_error") or "Job failed."
        percent = 100
    elif effective_state == "RETRYING":
        phase = "retrying"
        message = data.get("last_error") or (worker_job or {}).get("last_error") or "Retry scheduled."
        percent = min(percent, 45)

    queue_position = await queue_position_for(job)
    estimated_queue_seconds = estimate_queue_seconds(queue_position, metrics_snapshot)
    eta_seconds = estimate_eta_seconds(job, phase, started, now, estimated_queue_seconds, metrics_snapshot)
    return {
        "phase": phase,
        "percent": max(0, min(100, int(percent))),
        "percent_source": "estimated",
        "veo_native_percent": None,
        "veo_native_percent_available": False,
        "message": message,
        "elapsed_seconds": round(elapsed, 1),
        "queue_position": queue_position,
        "estimated_queue_seconds": estimated_queue_seconds,
        "eta_seconds": eta_seconds,
        "updated_at": now.isoformat(),
        "user_visible": True,
    }


async def progress_metrics() -> dict[str, float | None]:
    jobs = await state().queue.list_jobs(limit=500)
    queue_to_account_seconds: list[float] = []
    processing_by_type: dict[str, list[float]] = {}
    for job in jobs:
        worker_result = metrics_worker_result(job)
        if not worker_result:
            continue
        created = job.timeline.get("api_received") or job.created_at
        timeline = worker_result.get("timeline") if isinstance(worker_result.get("timeline"), dict) else {}
        account_started = parse_datetime(timeline.get("account_selected")) or parse_datetime(worker_result.get("started_at"))
        completed = parse_datetime(worker_result.get("completed_at")) or job.completed_at
        if account_started:
            queue_to_account_seconds.append((account_started - created).total_seconds())
        if account_started and completed:
            processing_by_type.setdefault(job.generation_type, []).append((completed - account_started).total_seconds())
    return {
        "avg_queue_to_account_seconds": average(queue_to_account_seconds),
        "avg_text_to_image_seconds": average(processing_by_type.get("text_to_image", [])),
        "avg_image_to_image_seconds": average(processing_by_type.get("image_to_image", [])),
        "avg_text_to_video_seconds": average(processing_by_type.get("text_to_video", [])),
        "avg_image_to_video_seconds": average(processing_by_type.get("image_to_video", [])),
    }


def estimated_generation_percent(generation_type: str, started: datetime | None, now: datetime) -> int:
    if started is None:
        return 45
    elapsed = max(0.0, (now - started).total_seconds())
    expected = default_expected_processing_seconds(generation_type)
    return min(95, max(45, int(45 + (elapsed / expected) * 45)))


def default_expected_processing_seconds(generation_type: str) -> int:
    if generation_type in {"text_to_video", "image_to_video"}:
        return 420
    return 90


async def queue_position_for(job: GlobalJob) -> int | None:
    if job.assigned_worker_id:
        return None
    jobs = await state().queue.list_jobs(limit=1000)
    waiting = [
        item
        for item in sorted(jobs, key=lambda item: item.queued_at)
        if item.state.value in {"QUEUED", "RETRYING"} and not item.assigned_worker_id
    ]
    for index, item in enumerate(waiting, start=1):
        if item.id == job.id:
            return index
    return None


def estimate_queue_seconds(queue_position: int | None, metrics_snapshot: dict[str, float | None]) -> float | None:
    if queue_position is None:
        return None
    avg_wait = metrics_snapshot.get("avg_queue_to_account_seconds") or 30
    statuses = [worker.status for worker in state().workers.list_workers() if worker.status and worker.status.online]
    free_slots = max(1, sum(status.capacity_remaining for status in statuses))
    return round(((queue_position - 1) / free_slots) * float(avg_wait), 1)


def estimate_eta_seconds(
    job: GlobalJob,
    phase: str,
    started: datetime | None,
    now: datetime,
    estimated_queue_seconds: float | None,
    metrics_snapshot: dict[str, float | None],
) -> float | None:
    if phase in {"completed", "failed"}:
        return 0.0
    expected_processing = (
        metrics_snapshot.get(f"avg_{job.generation_type}_seconds")
        or default_expected_processing_seconds(job.generation_type)
    )
    if started:
        elapsed_processing = max(0.0, (now - started).total_seconds())
        return round(max(5.0, float(expected_processing) - elapsed_processing), 1)
    queue_seconds = estimated_queue_seconds or 0
    return round(queue_seconds + float(expected_processing), 1)


def capacity_snapshot() -> list[dict]:
    snapshot = []
    for worker in state().workers.list_workers():
        status = worker.status
        if status is None:
            snapshot.append(
                {
                    "vps_id": worker.id,
                    "enabled": worker.enabled,
                    "online": False,
                    "capacity_remaining": 0,
                    "reason": "No health report yet",
                }
            )
            continue
        reason = "Available"
        if not worker.enabled:
            reason = "VPS disabled"
        elif not status.online:
            reason = status.error or "VPS offline"
        elif status.capacity_remaining <= 0:
            reason = "No free account slots"
        elif status.cpu >= 92:
            reason = f"Available, but CPU high ({status.cpu:.0f}%); dispatch allowed with low score"
        elif status.ram >= 92:
            reason = f"RAM too high ({status.ram:.0f}%)"
        snapshot.append(
            {
                "vps_id": worker.id,
                "enabled": worker.enabled,
                "online": status.online,
                "accounts_ready": status.accounts_ready,
                "accounts_busy": status.accounts_busy,
                "capacity_remaining": status.capacity_remaining,
                "queue_size": status.queue_size,
                "active_jobs": status.active_jobs,
                "cpu": status.cpu,
                "ram": status.ram,
                "health_score": status.health_score,
                "reason": reason,
            }
        )
    return snapshot


def average(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def metrics_worker_result(job: GlobalJob) -> dict[str, Any] | None:
    cached = job.payload.get("worker_result")
    if isinstance(cached, dict):
        return cached
    return None


async def enqueue_generation(generation_type: GenerationType, payload: GenerationRequest) -> GlobalJob:
    flow_settings = state().flow_config.resolve(generation_type, payload.flow_override)
    production_defaults_used = payload.flow_override is None
    job = GlobalJob(
        prompt=payload.prompt,
        generation_type=generation_type,
        flow_settings=flow_settings,
        production_defaults_used=production_defaults_used,
        preferred_worker_id=payload.preferred_worker_id,
        preferred_account_id=payload.preferred_account_id,
        max_retries=state().settings.queue.max_retries,
        payload=payload.model_dump(exclude_none=True),
    )
    job.stamp("api_received")
    job.stamp("global_queued")
    await state().queue.enqueue(job)
    await state().store.save_job(job)
    return job


if __name__ == "__main__":
    import uvicorn

    loaded = load_settings()
    uvicorn.run("orchestrator.api.main:app", host=loaded.api_host, port=loaded.api_port, workers=1, reload=False)
