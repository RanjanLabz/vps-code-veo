from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil

from worker.accounts.manager import AccountManager
from worker.accounts.models import AccountStatus
from worker.config.settings import Settings
from worker.queue.manager import QueueManager


class HealthReporter:
    def __init__(self, settings: Settings, accounts: AccountManager, queue: QueueManager) -> None:
        self.settings = settings
        self.accounts = accounts
        self.queue = queue

    async def snapshot(self) -> dict:
        accounts = self.accounts.list_accounts()
        browser_status: dict[str, dict[str, Any]] = {}
        for account in accounts:
            page_status = await self._page_status(account.id)
            if page_status["auth_required"] and account.status != AccountStatus.TOKEN_EXPIRED:
                await self.accounts.set_account_status(account.id, AccountStatus.TOKEN_EXPIRED)
                account.status = AccountStatus.TOKEN_EXPIRED
            elif page_status["current_url"] and not page_status["auth_required"] and account.status == AccountStatus.TOKEN_EXPIRED:
                await self.accounts.set_account_status(account.id, AccountStatus.READY)
                account.status = AccountStatus.READY
            browser_status[account.id] = {
                "pid": account.browser_pid,
                "running": bool(account.browser_pid and psutil.pid_exists(account.browser_pid)),
                "display": account.display,
                "vnc_port": account.vnc_port,
                "debug_port": account.remote_debugging_port,
                "current_url": page_status["current_url"],
                "auth_required": page_status["auth_required"],
                "flowkit": self.accounts.flowkit.status(account.id),
            }
        queue_stats = await self.queue.stats()
        running_accounts = sum(
            1 for account in accounts if account.browser_pid and psutil.pid_exists(account.browser_pid)
        )
        return {
            "worker_id": self.settings.worker_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cpu_percent": psutil.cpu_percent(interval=None),
            "ram_percent": psutil.virtual_memory().percent,
            "total_accounts": len(accounts),
            "running_accounts": running_accounts,
            "active_accounts": running_accounts,
            "busy_accounts": sum(1 for account in accounts if account.status == AccountStatus.BUSY),
            "browser_status": browser_status,
            "extension_status": {
                "path": str(self.settings.paths.extension_dir),
                "manifest_present": (self.settings.paths.extension_dir / "manifest.json").exists(),
                "flowkit_runtime_dir": str(self.settings.paths.runtime_extension_dir),
            },
            "queue": queue_stats,
        }

    async def _page_status(self, account_id: str) -> dict[str, Any]:
        try:
            runtime = self.accounts.runtime_for(account_id)
        except Exception:
            return {"current_url": None, "auth_required": False}
        context = runtime.playwright_context
        if context is None:
            return {"current_url": None, "auth_required": False}
        current_url = None
        for page in context.pages:
            if "labs.google" in page.url or "accounts.google.com" in page.url:
                current_url = page.url
                break
        auth_required = bool(current_url and ("accounts.google.com" in current_url or "ServiceLogin" in current_url))
        return {"current_url": current_url, "auth_required": auth_required}
