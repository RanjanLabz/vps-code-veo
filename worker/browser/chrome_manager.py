from __future__ import annotations

import asyncio
import os
from pathlib import Path

from playwright.async_api import async_playwright

from worker.accounts.models import Account, AccountStatus
from worker.browser.runtime import AccountRuntime
from worker.config.settings import Settings


class ChromeManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._playwright = None

    async def start(self, account: Account, runtime: AccountRuntime) -> None:
        if account.display is None:
            raise RuntimeError(f"account {account.id} has no X display")
        Path(account.profile_path).mkdir(parents=True, exist_ok=True)
        account.remote_debugging_port = self._debug_port(account)

        env = os.environ.copy()
        env["DISPLAY"] = account.display
        args = [
            self.settings.browser.chrome_binary,
            f"--user-data-dir={account.profile_path}",
            f"--remote-debugging-address={self.settings.browser.remote_debugging_host}",
            f"--remote-debugging-port={account.remote_debugging_port}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-dev-shm-usage",
            "--disable-background-networking",
            "--disable-features=Translate,AutomationControlled",
            "--start-maximized",
        ]
        extension_dirs = self._extension_dirs(account)
        if extension_dirs:
            extension_arg = ",".join(str(path) for path in extension_dirs)
            args.extend([f"--disable-extensions-except={extension_arg}", f"--load-extension={extension_arg}"])
        if account.proxy_enabled and account.proxy_url:
            args.append(f"--proxy-server={account.proxy_url}")
        args.extend(self.settings.browser.extra_args)
        args.append(account.settings.flow_url or self.settings.browser.default_flow_url)

        runtime.chrome = await asyncio.create_subprocess_exec(
            *args,
            env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        account.browser_pid = runtime.chrome.pid
        account.mark_updated()
        await self.connect(account, runtime)
        await self.open_flow(account, runtime)
        account.status = AccountStatus.READY

    async def connect(self, account: Account, runtime: AccountRuntime) -> None:
        if account.remote_debugging_port is None:
            raise RuntimeError(f"account {account.id} has no debugging port")
        if self._playwright is None:
            self._playwright = await async_playwright().start()
        endpoint = f"http://{self.settings.browser.remote_debugging_host}:{account.remote_debugging_port}"
        deadline = asyncio.get_running_loop().time() + self.settings.browser.launch_timeout_seconds
        last_error: Exception | None = None
        while asyncio.get_running_loop().time() < deadline:
            try:
                runtime.playwright_browser = await self._playwright.chromium.connect_over_cdp(endpoint)
                contexts = runtime.playwright_browser.contexts
                runtime.playwright_context = contexts[0] if contexts else await runtime.playwright_browser.new_context()
                return
            except Exception as exc:
                last_error = exc
                await asyncio.sleep(1)
        raise RuntimeError(f"failed to connect to Chrome for {account.id}: {last_error}")

    async def open_flow(self, account: Account, runtime: AccountRuntime) -> None:
        if runtime.playwright_context is None:
            raise RuntimeError(f"account {account.id} has no Playwright context")
        url = account.settings.flow_url or self.settings.browser.default_flow_url
        page = None
        for candidate in runtime.playwright_context.pages:
            if "labs.google" in candidate.url:
                page = candidate
                break
        if page is None:
            page = await runtime.playwright_context.new_page()
        page.set_default_timeout(self.settings.browser.navigation_timeout_ms)
        await page.goto(url, wait_until="domcontentloaded", timeout=self.settings.browser.navigation_timeout_ms)

    async def stop(self, runtime: AccountRuntime) -> None:
        await runtime.terminate()

    async def shutdown(self) -> None:
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    def _debug_port(self, account: Account) -> int:
        digits = "".join(ch for ch in account.id if ch.isdigit())
        offset = int(digits) if digits else abs(hash(account.id)) % 500
        return self.settings.browser.remote_debugging_start_port + offset

    def _extension_dirs(self, account: Account) -> list[Path]:
        dirs: list[Path] = []
        flowkit_dir = Path(account.extension_runtime_path) if account.extension_runtime_path else self.settings.paths.extension_dir
        if (flowkit_dir / "manifest.json").exists():
            dirs.append(flowkit_dir)

        if account.settings.fleet_extension_enabled:
            fleet_dir = self.settings.paths.fleet_extensions_dir / "current"
            if (fleet_dir / "manifest.json").exists():
                dirs.append(fleet_dir)

        return dirs
