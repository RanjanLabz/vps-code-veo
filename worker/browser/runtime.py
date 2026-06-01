from __future__ import annotations

import asyncio
from dataclasses import dataclass

from playwright.async_api import Browser, BrowserContext


@dataclass(slots=True)
class AccountRuntime:
    xvfb: asyncio.subprocess.Process | None = None
    fluxbox: asyncio.subprocess.Process | None = None
    x11vnc: asyncio.subprocess.Process | None = None
    novnc: asyncio.subprocess.Process | None = None
    chrome: asyncio.subprocess.Process | None = None
    playwright_browser: Browser | None = None
    playwright_context: BrowserContext | None = None

    async def terminate(self) -> None:
        for process in [self.playwright_context, self.playwright_browser]:
            if process is not None:
                try:
                    await process.close()
                except Exception:
                    pass
        self.playwright_context = None
        self.playwright_browser = None

        for process in [self.chrome, self.novnc, self.x11vnc, self.fluxbox, self.xvfb]:
            if process is not None and process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=8)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
        self.chrome = None
        self.novnc = None
        self.x11vnc = None
        self.fluxbox = None
        self.xvfb = None
