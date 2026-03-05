"""Gateway client for sending JSON-RPC commands."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Optional

import websockets

from .protocol import new_id, parse_message, make_error, make_result

logger = logging.getLogger(__name__)


class GatewayClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 18789, token: Optional[str] = None):
        self.host = host
        self.port = port
        self.token = token
        self._ws = None
        self._lock = asyncio.Lock()
        self._pending: Dict[str, asyncio.Future] = {}
        self._reader_task: Optional[asyncio.Task] = None

    @property
    def url(self) -> str:
        token_param = f"?token={self.token}" if self.token else ""
        return f"ws://{self.host}:{self.port}/ws{token_param}"

    async def connect(self) -> None:
        async with self._lock:
            if self._ws and not self._ws.closed:
                return
            self._ws = await websockets.connect(self.url, ping_interval=None)
            self._reader_task = asyncio.create_task(self._reader())
            try:
                await self.send_request(
                    "gateway.hello",
                    {
                        "client_version": "1.0.0",
                        "client_id": "local-node",
                        "role": "client",
                    },
                )
            except Exception:
                pass

    async def close(self) -> None:
        async with self._lock:
            if self._ws:
                await self._ws.close()
            if self._reader_task:
                self._reader_task.cancel()
            self._ws = None

    async def _reader(self) -> None:
        try:
            async for raw in self._ws:
                msg, err = parse_message(raw)
                if err or not msg:
                    continue
                req_id = msg.get("id")
                if req_id and req_id in self._pending:
                    fut = self._pending.pop(req_id)
                    if "result" in msg:
                        fut.set_result(msg["result"])
                    elif "error" in msg:
                        fut.set_exception(RuntimeError(msg["error"]))
        except Exception as exc:
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(exc)
            self._pending.clear()

    async def send_request(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 20.0) -> Any:
        await self.connect()
        req_id = new_id()
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {},
        }
        fut = asyncio.get_event_loop().create_future()
        self._pending[req_id] = fut
        await self._ws.send(json.dumps(payload))
        return await asyncio.wait_for(fut, timeout=timeout)

    async def handle_text(self, text: str, source: str = "voice") -> str:
        result = await self.send_request("assistant.handle", {"text": text, "source": source})
        return result.get("response", "") if isinstance(result, dict) else str(result)

    async def handle_partial_text(self, text: str) -> None:
        """Send a partial (non-final) transcript to the UI."""
        # This is a notification, we don't wait for a response
        await self.connect()
        payload = {
            "jsonrpc": "2.0",
            "method": "ui.partial_transcript",
            "params": {"text": text},
        }
        await self._ws.send(json.dumps(payload))

    async def update_session(self, **kwargs: Any) -> Dict[str, Any]:
        return await self.send_request("session.update", kwargs)
