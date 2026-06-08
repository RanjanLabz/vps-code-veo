from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException
import httpx
import psutil

from worker.accounts.models import Account, AccountSettings, AccountStatus
from worker.browser.chrome_manager import ChromeManager
from worker.browser.flowkit_bridge import FlowKitBridge
from worker.browser.runtime import AccountRuntime
from worker.browser.vnc_manager import VncManager
from worker.config.settings import Settings
from worker.recovery.engine import RecoveryEngine
from worker.storage.account_store import AccountStore

logger = logging.getLogger(__name__)


class AccountManager:
    def __init__(self, settings: Settings, store: AccountStore) -> None:
        self.settings = settings
        self.store = store
        self.chrome = ChromeManager(settings)
        self.vnc = VncManager(settings)
        self.flowkit = FlowKitBridge(settings)
        self.recovery = RecoveryEngine(settings, self.chrome, self.vnc)
        self._accounts: dict[str, Account] = {}
        self._runtimes: dict[str, AccountRuntime] = {}
        self._lock = asyncio.Lock()

    async def load_existing_accounts(self) -> None:
        for account in await self.store.load_all():
            if account.status in {AccountStatus.BUSY, AccountStatus.COOLDOWN}:
                account.status = AccountStatus.READY
            account.jobs_running = 0
            account.browser_pid = None
            account.mark_updated()
            self._accounts[account.id] = account
            self._runtimes[account.id] = AccountRuntime()
            await self.store.save(account)
        if self.settings.autostart_accounts:
            for account in list(self._accounts.values()):
                if not account.settings.keep_warm:
                    continue
                try:
                    await self.start_account(account.id)
                except Exception:
                    logger.exception("failed to autostart account=%s", account.id)
                    account.status = AccountStatus.BROKEN_SESSION
                    account.health_score = max(0, account.health_score - 20)
                    account.mark_updated()
                    await self.store.save(account)

    def list_accounts(self) -> list[Account]:
        return sorted(self._accounts.values(), key=lambda account: account.id)

    def get_account(self, account_id: str) -> Account | None:
        return self._accounts.get(account_id)

    def runtime_for(self, account_id: str) -> AccountRuntime:
        runtime = self._runtimes.get(account_id)
        if runtime is None:
            raise HTTPException(status_code=404, detail="account runtime not found")
        return runtime

    async def create_account(self, payload: dict[str, Any]) -> Account:
        async with self._lock:
            account_id = str(payload.get("id") or "").strip()
            if not account_id:
                account_id = self._next_account_id()
            if account_id in self._accounts:
                raise HTTPException(status_code=409, detail="account already exists")
            profile_path = str(payload.get("profile_path") or self.settings.paths.chrome_profiles_dir / account_id)
            settings = AccountSettings.model_validate(payload.get("settings") or {})
            account = Account(
                id=account_id,
                profile_path=profile_path,
                proxy_enabled=bool(payload.get("proxy_enabled", False)),
                proxy_url=payload.get("proxy_url"),
                settings=settings,
            )
            if account.settings.flow_url is None:
                account.settings.flow_url = self.settings.browser.default_flow_url
            Path(account.profile_path).mkdir(parents=True, exist_ok=True)
            self._accounts[account.id] = account
            self._runtimes[account.id] = AccountRuntime()
            await self.store.save(account)

        await self.start_account(account.id)
        return self._accounts[account.id]

    async def delete_account(self, account_id: str, remove_profile: bool) -> None:
        account = self._require(account_id)
        await self.stop_account(account_id)
        async with self._lock:
            self._accounts.pop(account_id, None)
            self._runtimes.pop(account_id, None)
            await self.store.delete(account_id)
            if remove_profile:
                shutil.rmtree(account.profile_path, ignore_errors=True)

    async def start_account(self, account_id: str) -> Account:
        account = self._require(account_id)
        runtime = self.runtime_for(account_id)
        if self._browser_is_running(account):
            if runtime.playwright_context is None:
                await self.chrome.connect(account, runtime)
            account.status = AccountStatus.READY
            account.mark_updated()
            await self.store.save(account)
            return account

        await runtime.terminate()
        if self.settings.flowkit.enabled:
            await self.flowkit.start(account)
            self.flowkit.prepare_extension(account)
        await self.vnc.start(account, runtime)
        await self.chrome.start(account, runtime)
        await self.store.save(account)
        return account

    async def stop_account(self, account_id: str) -> Account:
        account = self._require(account_id)
        runtime = self.runtime_for(account_id)
        await runtime.terminate()
        await self.flowkit.stop(account_id)
        account.browser_pid = None
        account.status = AccountStatus.STOPPED
        account.mark_updated()
        await self.store.save(account)
        return account

    async def restart_account(self, account_id: str) -> Account:
        await self.stop_account(account_id)
        return await self.start_account(account_id)

    async def recover_account(self, account_id: str, reason: str) -> Account:
        account = self._require(account_id)
        if not self._browser_is_running(account):
            logger.warning("starting stopped browser during recovery account=%s reason=%s", account.id, reason)
            account.status = AccountStatus.BROKEN_SESSION
            account.health_score = max(0, account.health_score - 5)
            account.mark_updated()
            await self.store.save(account)
            return await self.start_account(account_id)
        runtime = self.runtime_for(account_id)
        await self.recovery.recover(account, runtime, reason)
        await self.store.save(account)
        return account

    async def ensure_account_running(self, account_id: str) -> Account:
        account = self._require(account_id)
        if self._browser_is_running(account):
            return account
        logger.info("starting browser for scheduled job account=%s", account.id)
        return await self.start_account(account_id)

    async def update_proxy(self, account_id: str, payload: dict[str, Any]) -> Account:
        account = self._require(account_id)
        account.proxy_enabled = bool(payload.get("proxy_enabled", account.proxy_enabled))
        account.proxy_url = payload.get("proxy_url", account.proxy_url)
        if "proxy_health_score" in payload:
            account.proxy_health_score = int(payload["proxy_health_score"])
        account.mark_updated()
        await self.store.save(account)
        if account.browser_pid:
            await self.restart_account(account_id)
        return account

    async def update_settings(self, account_id: str, payload: dict[str, Any]) -> Account:
        account = self._require(account_id)
        was_running = self._browser_is_running(account)
        fleet_extension_enabled = account.settings.fleet_extension_enabled
        keep_warm = account.settings.keep_warm
        current = account.settings.model_dump()
        current.update(payload)
        account.settings = AccountSettings.model_validate(current)
        account.mark_updated()
        await self.store.save(account)
        if was_running and account.settings.fleet_extension_enabled != fleet_extension_enabled:
            return await self.restart_account(account_id)
        if was_running and not account.settings.keep_warm and keep_warm != account.settings.keep_warm and account.jobs_running == 0:
            return await self.stop_account(account_id)
        if not was_running and account.settings.keep_warm and keep_warm != account.settings.keep_warm:
            return await self.start_account(account_id)
        return account

    async def mark_job_started(self, account_id: str) -> None:
        account = self._require(account_id)
        account.jobs_running += 1
        account.status = AccountStatus.BUSY
        account.last_used = datetime.now(timezone.utc)
        account.mark_updated()
        await self.store.save(account)

    async def mark_job_finished(self, account_id: str, success: bool) -> None:
        account = self._require(account_id)
        account.jobs_running = max(0, account.jobs_running - 1)
        if success:
            account.success_count += 1
            account.health_score = min(100, account.health_score + 2)
        else:
            account.failure_count += 1
            account.health_score = max(0, account.health_score - 10)
        account.status = AccountStatus.READY if account.jobs_running == 0 else AccountStatus.BUSY
        account.mark_updated()
        await self.store.save(account)

    async def set_account_status(self, account_id: str, status: AccountStatus) -> None:
        account = self._require(account_id)
        account.status = status
        account.mark_updated()
        await self.store.save(account)

    async def refresh_flowkit_auth_states(self) -> None:
        for account in self._accounts.values():
            if account.status not in {AccountStatus.TOKEN_EXPIRED, AccountStatus.BROKEN_SESSION}:
                continue
            flowkit_status = self.flowkit.status(account.id)
            if (
                self._browser_is_running(account)
                and flowkit_status.get("connected")
                and flowkit_status.get("flow_key_present")
            ):
                account.status = AccountStatus.READY
                account.health_score = max(20, account.health_score)
                account.mark_updated()
                await self.store.save(account)

    async def shutdown(self) -> None:
        for runtime in list(self._runtimes.values()):
            await runtime.terminate()
        await self.flowkit.shutdown()
        await self.chrome.shutdown()

    async def handle_flowkit_callback(self, account_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._require(account_id)
        return await self.flowkit.handle_callback(account_id, payload)

    async def install_extension_package(self, extension_url: str, version: str | None = None, restart_accounts: bool = True) -> dict[str, Any]:
        archive = await self._download_extension_archive(extension_url)
        extension_root = await asyncio.to_thread(self._unpack_extension_archive, archive)
        running_accounts = [account.id for account in self.list_accounts() if self._browser_is_running(account)]

        async with self._lock:
            target = self.settings.paths.fleet_extensions_dir / "current"
            backup = target.with_name(f"{target.name}.backup")
            shutil.rmtree(backup, ignore_errors=True)
            target.mkdir(parents=True, exist_ok=True)
            if any(target.iterdir()):
                shutil.copytree(target, backup)
                self._clear_directory_contents(target)
            self._copy_directory_contents(extension_root, target)
            shutil.rmtree(backup, ignore_errors=True)
            cleanup_root = extension_root.parent.parent if extension_root.parent.name == "extract" else extension_root.parent
            shutil.rmtree(cleanup_root, ignore_errors=True)

        restarted: list[str] = []
        failed: dict[str, str] = {}
        if restart_accounts:
            for account_id in running_accounts:
                try:
                    await self.restart_account(account_id)
                    restarted.append(account_id)
                except Exception as exc:
                    logger.exception("failed to restart account after extension install account=%s", account_id)
                    failed[account_id] = str(exc)

        return {
            "installed": True,
            "version": version,
            "extension_dir": str(target),
            "base_flowkit_extension_dir": str(self.settings.paths.extension_dir),
            "running_accounts_before_install": running_accounts,
            "restarted_accounts": restarted,
            "failed_accounts": failed,
            "future_accounts": "will load this extension next to the FlowKit bridge automatically",
        }

    async def _download_extension_archive(self, extension_url: str) -> bytes:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            response = await client.get(extension_url)
            response.raise_for_status()
            body = response.content
        if len(body) > 25 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="extension ZIP is larger than 25MB")
        return body

    def _unpack_extension_archive(self, archive: bytes) -> Path:
        temp_root = Path(tempfile.mkdtemp(prefix="flow-extension-"))
        try:
            archive_path = temp_root / "extension.zip"
            archive_path.write_bytes(archive)
            extract_root = temp_root / "extract"
            extract_root.mkdir()
            with zipfile.ZipFile(archive_path) as zip_file:
                for member in zip_file.infolist():
                    member_path = extract_root / member.filename
                    if not member_path.resolve().is_relative_to(extract_root.resolve()):
                        raise HTTPException(status_code=400, detail=f"unsafe ZIP path: {member.filename}")
                zip_file.extractall(extract_root)

            manifest = extract_root / "manifest.json"
            if not manifest.exists():
                matches = list(extract_root.glob("*/manifest.json"))
                if len(matches) == 1:
                    manifest = matches[0]
            if not manifest.exists():
                raise HTTPException(status_code=400, detail="extension ZIP must contain manifest.json at root or inside one top-level folder")
            return manifest.parent
        except Exception:
            shutil.rmtree(temp_root, ignore_errors=True)
            raise

    def _clear_directory_contents(self, path: Path) -> None:
        for child in path.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()

    def _copy_directory_contents(self, source: Path, target: Path) -> None:
        for child in source.iterdir():
            destination = target / child.name
            if child.is_dir() and not child.is_symlink():
                shutil.copytree(child, destination)
            else:
                shutil.copy2(child, destination)

    def _require(self, account_id: str) -> Account:
        account = self._accounts.get(account_id)
        if account is None:
            raise HTTPException(status_code=404, detail="account not found")
        return account

    def _next_account_id(self) -> str:
        index = 1
        while f"acc-{index}" in self._accounts:
            index += 1
        return f"acc-{index}"

    def _browser_is_running(self, account: Account) -> bool:
        return bool(account.browser_pid and psutil.pid_exists(account.browser_pid))
