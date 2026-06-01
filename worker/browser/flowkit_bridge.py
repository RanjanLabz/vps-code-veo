from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

import websockets
from websockets.server import WebSocketServerProtocol

from worker.accounts.models import Account
from worker.config.settings import Settings

logger = logging.getLogger(__name__)


class FlowKitBridge:
    """Per-account WebSocket bridge compatible with FlowKit's extension protocol."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._servers: dict[str, Any] = {}
        self._connections: dict[str, WebSocketServerProtocol] = {}
        self._pending: dict[str, dict[str, asyncio.Future]] = {}
        self._flow_keys: dict[str, str] = {}

    async def start(self, account: Account) -> None:
        if account.flowkit_ws_port is None:
            account.flowkit_ws_port = self._bridge_port(account)
        if account.flowkit_callback_url is None:
            account.flowkit_callback_url = f"http://127.0.0.1:{self.settings.api_port}/flowkit/{account.id}/callback"

        await self.stop(account.id)
        self._pending.setdefault(account.id, {})
        server = await websockets.serve(
            lambda websocket: self._handler(account.id, websocket),
            self.settings.flowkit.ws_host,
            account.flowkit_ws_port,
        )
        self._servers[account.id] = server
        logger.info("FlowKit bridge listening account=%s ws=%s:%s", account.id, self.settings.flowkit.ws_host, account.flowkit_ws_port)

    async def stop(self, account_id: str) -> None:
        connection = self._connections.pop(account_id, None)
        if connection is not None:
            await connection.close()
        server = self._servers.pop(account_id, None)
        if server is not None:
            server.close()
            await server.wait_closed()
        for future in self._pending.get(account_id, {}).values():
            if not future.done():
                future.set_exception(ConnectionError("FlowKit bridge stopped"))
        self._pending.pop(account_id, None)

    async def shutdown(self) -> None:
        for account_id in list(self._servers):
            await self.stop(account_id)

    async def send(self, account_id: str, method: str, params: dict[str, Any], timeout: float = 300) -> dict[str, Any]:
        websocket = self._connections.get(account_id)
        if websocket is None:
            logger.warning("FlowKit send blocked account=%s method=%s reason=extension-not-connected", account_id, method)
            return {"error": "Extension not connected"}
        request_id = str(uuid4())
        future = asyncio.get_running_loop().create_future()
        self._pending.setdefault(account_id, {})[request_id] = future
        try:
            logger.info("FlowKit send account=%s method=%s request_id=%s timeout=%ss", account_id, method, request_id, timeout)
            await websocket.send(json.dumps({"id": request_id, "method": method, "params": params}))
            result = await asyncio.wait_for(future, timeout=timeout)
            logger.info("FlowKit response account=%s method=%s request_id=%s keys=%s", account_id, method, request_id, sorted(result.keys()))
            return dict(result)
        except asyncio.TimeoutError:
            logger.warning(
                "FlowKit timeout account=%s method=%s request_id=%s pending=%s connected=%s",
                account_id,
                method,
                request_id,
                len(self._pending.get(account_id, {})),
                account_id in self._connections,
            )
            return {"error": f"Timeout ({timeout}s) waiting for {method}"}
        except Exception as exc:
            logger.exception("FlowKit send failed account=%s method=%s request_id=%s", account_id, method, request_id)
            return {"error": str(exc)}
        finally:
            self._pending.get(account_id, {}).pop(request_id, None)

    async def handle_callback(self, account_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        request_id = payload.get("id")
        future = self._pending.get(account_id, {}).get(request_id)
        if future is not None and not future.done():
            logger.info("FlowKit callback matched account=%s request_id=%s keys=%s", account_id, request_id, sorted(payload.keys()))
            future.set_result(payload)
            return {"ok": True}
        logger.warning("FlowKit callback unmatched account=%s request_id=%s pending=%s", account_id, request_id, list(self._pending.get(account_id, {}).keys()))
        return {"ok": False, "reason": "no matching pending request"}

    def status(self, account_id: str) -> dict[str, Any]:
        return {
            "connected": account_id in self._connections,
            "flow_key_present": account_id in self._flow_keys,
            "pending": len(self._pending.get(account_id, {})),
        }

    def prepare_extension(self, account: Account) -> Path:
        source = self.settings.paths.extension_dir
        manifest = source / "manifest.json"
        if not manifest.exists():
            raise FileNotFoundError(f"FlowKit extension manifest not found at {manifest}")
        runtime_root = self.settings.paths.runtime_extension_dir
        target = runtime_root / account.id
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)

        background = target / "background.js"
        if background.exists():
            text = background.read_text(encoding="utf-8")
            ws_url = f"ws://127.0.0.1:{account.flowkit_ws_port}"
            callback_url = account.flowkit_callback_url or f"http://127.0.0.1:{self.settings.api_port}/flowkit/{account.id}/callback"
            text = text.replace("ws://127.0.0.1:9222", ws_url)
            text = text.replace("http://127.0.0.1:8100/api/ext/callback", callback_url)
            background.write_text(text, encoding="utf-8")
            logger.info("Prepared FlowKit extension account=%s ws=%s callback=%s path=%s", account.id, ws_url, callback_url, target)
        self._patch_manifest_permissions(target / "manifest.json")
        account.extension_runtime_path = str(target)
        account.mark_updated()
        return target

    def _patch_manifest_permissions(self, manifest_path: Path) -> None:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        permissions = manifest.setdefault("host_permissions", [])
        callback_origin = f"http://127.0.0.1:{self.settings.api_port}/*"
        if callback_origin not in permissions:
            permissions.append(callback_origin)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    async def _handler(self, account_id: str, websocket: WebSocketServerProtocol) -> None:
        self._connections[account_id] = websocket
        logger.info("FlowKit extension connected account=%s", account_id)
        try:
            await websocket.send(json.dumps({"type": "callback_secret", "secret": "worker-local-callback"}))
            async for raw in websocket:
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("invalid FlowKit bridge JSON account=%s", account_id)
                    continue
                await self._handle_message(account_id, websocket, data)
        finally:
            if self._connections.get(account_id) is websocket:
                self._connections.pop(account_id, None)
            logger.warning("FlowKit extension disconnected account=%s", account_id)

    async def _handle_message(self, account_id: str, websocket: WebSocketServerProtocol, data: dict[str, Any]) -> None:
        if data.get("type") == "ping":
            await websocket.send(json.dumps({"type": "pong"}))
            return
        if data.get("type") == "token_captured":
            flow_key = data.get("flowKey")
            if flow_key:
                self._flow_keys[account_id] = flow_key
                logger.info("FlowKit token captured account=%s", account_id)
            return
        if data.get("type") == "extension_ready":
            logger.info("FlowKit extension ready account=%s flowKey=%s", account_id, data.get("flowKeyPresent"))
            return
        request_id = data.get("id")
        future = self._pending.get(account_id, {}).get(request_id)
        if future is not None and not future.done():
            future.set_result(data)

    def _bridge_port(self, account: Account) -> int:
        digits = "".join(ch for ch in account.id if ch.isdigit())
        offset = int(digits) if digits else abs(hash(account.id)) % 500
        return self.settings.flowkit.ws_start_port + offset
