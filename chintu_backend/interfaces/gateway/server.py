"""Gateway server (FastAPI + WebSocket JSON-RPC)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import uvicorn

from ...core.state import get_state_manager
from ...core.events import get_event_bus, EventType, Event
from .protocol import parse_message, is_request, make_result, make_error
from .bus import GatewayEventBus

logger = logging.getLogger(__name__)


class GatewayServer:
    """JSON-RPC 2.0 gateway for external clients."""

    def __init__(
        self,
        command_handler,
        host: str = "127.0.0.1",
        port: int = 18789,
        auth_token: Optional[str] = None,
    ):
        self.command_handler = command_handler
        self.host = host
        self.port = port
        self.auth_token = auth_token

        self.app = FastAPI(title="Chintu Gateway", version="0.1")
        self._clients: Dict[int, WebSocket] = {}
        self._server: Optional[uvicorn.Server] = None
        self._server_task: Optional[asyncio.Task] = None
        self._bus = GatewayEventBus()
        self._state = get_state_manager()
        self._event_bus = get_event_bus()

        self._whatsapp_gateway = None
        self._register_routes()
        self._attach_event_forwarders()

    def _register_routes(self) -> None:
        @self.app.post("/webhook/whatsapp")
        async def whatsapp_webhook(request):
            if not self._whatsapp_gateway:
                try:
                    from ..channels.whatsapp import WhatsAppGateway

                    self._whatsapp_gateway = WhatsAppGateway(self.command_handler)
                except Exception:
                    return {"status": "disabled"}
            if not self._whatsapp_gateway.is_enabled():
                return {"status": "disabled"}
            status, _ = await self._whatsapp_gateway.handle_webhook(request)
            return {"status": "ok" if status == 200 else "denied"}

        @self.app.websocket("/ws")
        async def websocket_endpoint(ws: WebSocket):
            token = ws.query_params.get("token") or ws.headers.get("x-gateway-token")
            if self.auth_token and token != self.auth_token:
                await ws.close(code=4403)
                return
            await ws.accept()
            client_id = id(ws)
            self._clients[client_id] = ws
            await self._send(ws, {"type": "session.started", "session_id": str(client_id)})
            try:
                while True:
                    raw = await ws.receive_text()
                    await self._handle_message(ws, raw)
            except WebSocketDisconnect:
                pass
            finally:
                self._clients.pop(client_id, None)

    def _attach_event_forwarders(self) -> None:
        async def forward_event(event: Event):
            payload = {
                "type": "event",
                "event": event.type.value,
                "data": event.data,
                "source": event.source,
            }
            await self.broadcast(payload)

        for evt in (
            EventType.TRANSCRIPT_READY,
            EventType.COMMAND_EXECUTED,
            EventType.COMMAND_FAILED,
            EventType.ERROR,
            EventType.STATE_CHANGED,
        ):
            self._event_bus.subscribe(evt, lambda e, evt=evt: asyncio.create_task(forward_event(e)), is_async=False)

    async def _handle_message(self, ws: WebSocket, raw: str) -> None:
        message, err = parse_message(raw)
        if err or not message:
            await self._send(ws, make_error(None, -32700, "Parse error", err))
            return

        if not is_request(message):
            await self._send(ws, make_error(message.get("id"), -32600, "Invalid Request"))
            return

        req_id = message.get("id")
        method = message.get("method")
        params = message.get("params") or {}

        try:
            if method == "health.ping":
                await self._send(ws, make_result(req_id, {"ok": True}))
                return

            if method == "state.get":
                await self._send(ws, make_result(req_id, self._state.state.to_dict()))
                return

            if method == "session.create":
                await self._send(ws, make_result(req_id, {"session_id": str(id(ws))}))
                return

            if method == "assistant.handle":
                text = params.get("text", "")
                source = params.get("source", "gateway")
                response = await asyncio.to_thread(self.command_handler.handle, text, source)
                await self._send(ws, make_result(req_id, {"response": response}))
                return

            if method == "event.emit":
                event_type = params.get("type", "custom")
                payload = params.get("data", {})
                await self._bus.publish_safe(event_type, payload)
                await self._send(ws, make_result(req_id, {"ok": True}))
                return

            await self._send(ws, make_error(req_id, -32601, f"Method not found: {method}"))
        except Exception as exc:
            await self._send(ws, make_error(req_id, -32000, "Server error", str(exc)))

    async def _send(self, ws: WebSocket, payload: Dict[str, Any]) -> None:
        await ws.send_json(payload)

    async def broadcast(self, payload: Dict[str, Any]) -> None:
        for ws in list(self._clients.values()):
            try:
                await ws.send_json(payload)
            except Exception:
                continue

    async def start(self) -> None:
        config = uvicorn.Config(self.app, host=self.host, port=self.port, log_level="info")
        self._server = uvicorn.Server(config)
        self._server_task = asyncio.create_task(asyncio.to_thread(self._server.run))
        logger.info("Gateway server starting on %s:%s", self.host, self.port)

    async def stop(self) -> None:
        if self._server:
            self._server.should_exit = True
        if self._server_task:
            await asyncio.sleep(0)
        logger.info("Gateway server stopped")
