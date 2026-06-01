from __future__ import annotations

import asyncio
import os

from worker.accounts.models import Account
from worker.browser.runtime import AccountRuntime
from worker.config.settings import Settings


class VncManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def start(self, account: Account, runtime: AccountRuntime) -> None:
        display_number = self._display_number(account)
        vnc_port = self._vnc_port(account)
        display = f":{display_number}"
        geometry = f"{self.settings.vnc.width}x{self.settings.vnc.height}x{self.settings.vnc.depth}"

        runtime.xvfb = await asyncio.create_subprocess_exec(
            "Xvfb",
            display,
            "-screen",
            "0",
            geometry,
            "-ac",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.sleep(0.4)

        env = os.environ.copy()
        env["DISPLAY"] = display
        runtime.fluxbox = await asyncio.create_subprocess_exec(
            "fluxbox",
            env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

        vnc_args = ["x11vnc", "-display", display, "-rfbport", str(vnc_port), "-forever", "-shared", "-quiet"]
        if self.settings.vnc.password:
            vnc_args.extend(["-passwd", self.settings.vnc.password])
        else:
            vnc_args.append("-nopw")
        runtime.x11vnc = await asyncio.create_subprocess_exec(
            *vnc_args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

        account.display = display
        account.vnc_port = vnc_port
        account.mark_updated()

        novnc_port = self.novnc_port_for(account)
        runtime.novnc = await asyncio.create_subprocess_exec(
            "websockify",
            "--web",
            self.settings.vnc.novnc_web_dir,
            f"0.0.0.0:{novnc_port}",
            f"127.0.0.1:{vnc_port}",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

    def novnc_port_for(self, account: Account) -> int:
        return self.settings.vnc.novnc_start_port + self._numeric_suffix(account.id)

    def _display_number(self, account: Account) -> int:
        return self.settings.vnc.display_start + self._numeric_suffix(account.id)

    def _vnc_port(self, account: Account) -> int:
        return self.settings.vnc.vnc_start_port + self._numeric_suffix(account.id)

    @staticmethod
    def _numeric_suffix(value: str) -> int:
        digits = "".join(ch for ch in value if ch.isdigit())
        if digits:
            return int(digits)
        return abs(hash(value)) % 500
