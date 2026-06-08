from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import asyncio

import httpx

from orchestrator.queue.models import GlobalJob
from orchestrator.workers.models import WorkerRecord, WorkerStatus


class WorkerClient:
    def __init__(self, timeout_seconds: float = 20, api_key: str | None = None) -> None:
        timeout = httpx.Timeout(connect=min(8.0, timeout_seconds), read=timeout_seconds, write=timeout_seconds, pool=timeout_seconds)
        limits = httpx.Limits(max_connections=100, max_keepalive_connections=20)
        self._client = httpx.AsyncClient(timeout=timeout, limits=limits)
        self._api_key = api_key
        self._retries = 3
        self._retry_backoff_seconds = 0.6

    async def close(self) -> None:
        await self._client.aclose()

    async def health(self, worker: WorkerRecord) -> WorkerStatus:
        base_url = worker.base_url.rstrip("/")
        try:
            response = await self._client.get(f"{base_url}/health", headers=self._headers())
            response.raise_for_status()
            health = response.json()
            accounts = await self.accounts(worker)
            queue = health.get("queue") or {}
            accounts_busy = int(health.get("busy_accounts") or 0)
            accounts_total = len(accounts)
            accounts_ready = self._available_account_slots(accounts)
            cpu_value = health.get("cpu_percent")
            ram_value = health.get("ram_percent")
            cpu = float(cpu_value if cpu_value is not None else 100)
            ram = float(ram_value if ram_value is not None else 100)
            score = max(0, min(100, int(100 - (cpu * 0.35) - (ram * 0.35) + accounts_ready * 8)))
            return WorkerStatus(
                vps_id=worker.id,
                base_url=base_url,
                online=True,
                accounts_total=accounts_total,
                accounts_busy=accounts_busy,
                accounts_ready=accounts_ready,
                max_jobs=worker.max_jobs,
                active_jobs=int(queue.get("active") or 0),
                queue_size=int(queue.get("ready") or 0) + int(queue.get("delayed") or 0),
                cpu=cpu,
                ram=ram,
                health_score=score,
                last_seen=datetime.now(timezone.utc),
                raw_health=health,
            )
        except Exception as exc:
            return WorkerStatus(vps_id=worker.id, base_url=base_url, online=False, max_jobs=worker.max_jobs, error=str(exc))

    async def accounts(self, worker: WorkerRecord) -> list[dict[str, Any]]:
        response = await self._request_with_retries("GET", f"{worker.base_url.rstrip('/')}/accounts")
        response.raise_for_status()
        data = response.json()
        return list(data) if isinstance(data, list) else []

    async def create_account(self, worker: WorkerRecord, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._client.post(f"{worker.base_url.rstrip('/')}/accounts", json=payload, headers=self._headers())
        response.raise_for_status()
        return dict(response.json())

    async def delete_account(self, worker: WorkerRecord, account_id: str, remove_profile: bool) -> dict[str, Any]:
        response = await self._client.delete(
            f"{worker.base_url.rstrip('/')}/accounts/{account_id}",
            params={"remove_profile": str(remove_profile).lower()},
            headers=self._headers(),
        )
        response.raise_for_status()
        return dict(response.json())

    async def account_action(self, worker: WorkerRecord, account_id: str, action: str) -> dict[str, Any]:
        response = await self._client.post(f"{worker.base_url.rstrip('/')}/accounts/{account_id}/{action}", headers=self._headers())
        response.raise_for_status()
        return dict(response.json())

    async def update_account_settings(self, worker: WorkerRecord, account_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._client.patch(f"{worker.base_url.rstrip('/')}/accounts/{account_id}/settings", json=payload, headers=self._headers())
        response.raise_for_status()
        return dict(response.json())

    async def update_account_proxy(self, worker: WorkerRecord, account_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._client.patch(f"{worker.base_url.rstrip('/')}/accounts/{account_id}/proxy", json=payload, headers=self._headers())
        response.raise_for_status()
        return dict(response.json())

    async def install_extension(self, worker: WorkerRecord, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._client.post(
            f"{worker.base_url.rstrip('/')}/extensions/install",
            json=payload,
            headers=self._headers(),
            timeout=90,
        )
        response.raise_for_status()
        return dict(response.json())

    async def dispatch(self, worker: WorkerRecord, job: GlobalJob) -> dict[str, Any]:
        body = {
            "prompt": job.prompt,
            "generation_type": job.generation_type,
            "flow_settings": job.flow_settings,
            "flow_model": job.flow_model,
            "duration": job.flow_settings.get("duration"),
            "estimated_credits": job.estimated_credits,
            "orchestrator_job_id": job.id,
            "preferred_account_id": job.preferred_account_id,
            **job.payload,
        }
        response = await self._request_with_retries("POST", f"{worker.base_url.rstrip('/')}/jobs", json=body)
        response.raise_for_status()
        return dict(response.json())

    async def job(self, worker: WorkerRecord, job_id: str) -> dict[str, Any]:
        response = await self._request_with_retries("GET", f"{worker.base_url.rstrip('/')}/jobs/{job_id}")
        response.raise_for_status()
        return dict(response.json())

    async def _request_with_retries(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(1, self._retries + 1):
            try:
                return await self._client.request(method, url, headers=self._headers(), **kwargs)
            except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError) as exc:
                last_exc = exc
                if attempt >= self._retries:
                    break
                await asyncio.sleep(self._retry_backoff_seconds * attempt)
        assert last_exc is not None
        raise last_exc

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self._api_key} if self._api_key else {}

    def _available_account_slots(self, accounts: list[dict[str, Any]]) -> int:
        available = 0
        for account in accounts:
            status = account.get("status")
            if status not in {"READY", "BUSY", "COOLDOWN"}:
                continue
            settings = account.get("settings") if isinstance(account.get("settings"), dict) else {}
            max_jobs = int(settings.get("max_concurrent_jobs") or 1)
            running = int(account.get("jobs_running") or 0)
            available += max(0, max_jobs - running)
        return available
