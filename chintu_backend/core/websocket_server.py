"""WebSocket server for Flutter UI communication."""

import asyncio
import json
import os
from pathlib import Path
from typing import Optional, Set, Dict, Any
import logging
import socket
import time
from datetime import datetime

logger = logging.getLogger(__name__)

try:
    import websockets
    from websockets.asyncio.server import serve as ws_serve
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False
    ws_serve = None
    logger.warning("websockets package not installed")

from .state import get_state_manager, SystemState
from .events import get_event_bus, EventType, Event
from .gateway_auth import get_gateway_auth, GatewaySession, AuthRole, PROTOCOL_VERSION


class WebSocketServer:
    """
    WebSocket server for communication with Flutter UI.
    Broadcasts state updates and receives commands.
    """
    
    def __init__(self, host: str = "127.0.0.1", port: int = 8765):
        self.host = host
        self.port = port
        self._server = None
        self._clients: Set = set()
        self._client_caps: Dict[int, Dict[str, Any]] = {}
        self._client_sessions: Dict[int, GatewaySession] = {}  # Client ID -> Session
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        
        self.state_manager = get_state_manager()
        self.event_bus = get_event_bus()
        
        # Initialize gateway auth (auth_required from config or env)
        auth_required = os.environ.get("CHINTU_GATEWAY_AUTH", "false").lower() == "true"
        secret_key = os.environ.get("CHINTU_GATEWAY_SECRET", None)
        self.auth = get_gateway_auth(secret_key=secret_key, auth_required=auth_required)
        
        # Subscribe to state changes
        self.state_manager.add_listener(self._on_state_change)
        self.event_bus.subscribe(EventType.ERROR, self._on_error_event)
        self.event_bus.subscribe(EventType.CANVAS_UPDATE, self._on_canvas_event)
    
    async def start(self) -> bool:
        """Start the WebSocket server."""
        logger.info("WebSocketServer.start() called")
        if not HAS_WEBSOCKETS:
            logger.error("✗ websockets package not installed - cannot start WebSocket server")
            logger.error("Install with: pip install websockets")
            return False

        logger.info(f"Websockets package available, attempting to start on {self.host}:{self.port}")
        self._loop = asyncio.get_running_loop()
        started = await self._start_with_port(self.port)
        if started:
            logger.info(f"✓ WebSocket server started successfully on {self.host}:{self.port}")
            return True

        # If default port is in use, auto-select a free port and retry.
        logger.warning(f"Port {self.port} unavailable, searching for free port...")
        free_port = self._find_free_port()
        if free_port and free_port != self.port:
            logger.warning(f"Retrying WebSocket server on free port {free_port}")
            self.port = free_port
            started = await self._start_with_port(self.port)
            if started:
                logger.info(f"✓ WebSocket server started successfully on {self.host}:{self.port}")
            return started

        logger.error("✗ Failed to start WebSocket server on any port")
        return False

    async def _start_with_port(self, port: int) -> bool:
        try:
            self._server = await ws_serve(
                self._handle_client,
                self.host,
                port,
                ping_interval=None, # Disable protocol-level pings to avoid disconnects on mobile sleep
                ping_timeout=None,
            )
            self._running = True
            self.port = port
            self._write_port_file()
            logger.info(f"WebSocket server started on ws://{self.host}:{self.port} (Keep-Alive optimized)")
            return True
        except OSError as e:
            if getattr(e, "errno", None) == 10048:
                logger.warning(
                    "WebSocket port %s already in use. Another instance may be running.",
                    port,
                )
            else:
                logger.error(f"Failed to start WebSocket server: {e}")
            self._running = False
            return False
        except Exception as e:
            logger.error(f"Failed to start WebSocket server: {e}")
            self._running = False
            return False

    def _find_free_port(self) -> Optional[int]:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind((self.host, 0))
                return sock.getsockname()[1]
        except Exception as exc:
            logger.warning("Failed to find free port: %s", exc)
            return None

    def _write_port_file(self) -> None:
        try:
            path = self._port_file_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "host": self.host,
                "port": self.port,
                "updated_at": datetime.now().isoformat(),
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            logger.info(f"✓ Port file written to {path}: {json.dumps(payload)}")
        except Exception as exc:
            logger.error(f"✗ Failed to write port file to {self._port_file_path()}: {exc}", exc_info=True)

    @staticmethod
    def _port_file_path() -> Path:
        return Path.home() / ".chintu" / "ws_port.json"
    
    async def stop(self):
        """Stop the WebSocket server."""
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        logger.info("WebSocket server stopped")
    
    async def _handle_client(self, websocket):
        """Handle a connected client."""
        self._clients.add(websocket)
        client_id = id(websocket)
        logger.info(f"Client connected: {client_id}")
        
        # Publish connection event
        await self.event_bus.publish(Event(
            type=EventType.UI_CONNECTED,
            data={"client_id": client_id},
        ))
        
        # Send current state (for backwards compatibility)
        # New clients should send 'connect' message first for auth flow
        await self._send_state(websocket)
        # Send a run snapshot so the UI can render timelines immediately.
        try:
            from chintu_backend.core.run_manager import get_run_manager

            await websocket.send(
                json.dumps(
                    {
                        "type": "run_snapshot",
                        "data": get_run_manager().snapshot(limit=30),
                    }
                )
            )
        except Exception:
            pass
        # Send an orchestrator overview on connect (best-effort).
        try:
            from chintu_backend.orchestrator import get_orchestrator_manager

            await websocket.send(
                json.dumps(
                    {
                        "type": "orchestrator_snapshot",
                        "data": get_orchestrator_manager().get_overview(limit=50),
                    }
                )
            )
        except Exception:
            pass
        
        try:
            async for message in websocket:
                await self._handle_message(websocket, message)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self._clients.discard(websocket)
            self._client_caps.pop(client_id, None)
            # Invalidate session on disconnect
            session = self._client_sessions.pop(client_id, None)
            if session:
                self.auth.invalidate_session(session.session_id)
            logger.info(f"Client disconnected: {client_id}")
            
            await self.event_bus.publish(Event(
                type=EventType.UI_DISCONNECTED,
                data={"client_id": client_id},
            ))
    
    def _get_client_session(self, websocket) -> Optional[GatewaySession]:
        """Get the session for a client websocket."""
        return self._client_sessions.get(id(websocket))
    
    def _check_permission(self, websocket, require_execute: bool = False, require_system: bool = False) -> bool:
        """Check if client has required permissions."""
        session = self._get_client_session(websocket)
        if not session:
            # No session = legacy client, allow for backwards compatibility
            # Set auth_required=True in env to enforce
            return not self.auth.auth_required
        if require_system:
            return session.can_exec_system()
        if require_execute:
            return session.can_execute()
        return True
    
    async def _handle_message(self, websocket, message: str):
        """Handle incoming message from client."""
        try:
            data = json.loads(message)
            msg_type = data.get("type")
            client_id = id(websocket)

            # Log safely (avoid secrets / big payloads).
            if msg_type not in ("ping", "connect"):
                try:
                    if msg_type in ("connect.auth", "auth"):
                        logger.info("Received message: %s", msg_type)
                    elif msg_type == "event":
                        payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
                        event_name = payload.get("event")
                        event_data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
                        action = event_data.get("action")
                        if action == "orchestrator_set_input":
                            logger.info(
                                "Received ui_action: %s (project_id=%s key=%s is_secret=%s)",
                                action,
                                event_data.get("project_id"),
                                event_data.get("key"),
                                bool(event_data.get("is_secret")),
                            )
                        else:
                            logger.info("Received ui_action: %s", action or event_name or "event")
                    elif msg_type == "command":
                        text = str(data.get("text") or "")
                        logger.info("Received command (%d chars)", len(text))
                    elif msg_type in ("copy_to_clipboard", "cron_update", "cron_cancel", "code_approval_response"):
                        logger.info("Received message: %s", msg_type)
                    else:
                        logger.info("Received message: %s", data)
                except Exception:
                    logger.info("Received message: %s", msg_type)
            
            # === AUTH PROTOCOL HANDLERS ===
            if msg_type == "connect":
                # Step 1: Client initiates connection, server sends challenge
                device_id = data.get("device_id", f"unknown_{client_id}")
                client_version = data.get("protocol_version", "1.0")
                capabilities = data.get("capabilities", [])
                metadata = data.get("metadata", {}) if isinstance(data.get("metadata"), dict) else {}
                
                # Check protocol version
                version_ok, negotiated = self.auth.check_protocol_version(client_version)
                if not version_ok:
                    logger.warning(f"Client {client_id} has unsupported protocol version: {client_version}")
                
                # Create challenge
                challenge_msg = self.auth.create_challenge(device_id, capabilities)
                await websocket.send(json.dumps(challenge_msg))
                # Protocol alias for the newer Connect->Welcome->Ready flow.
                try:
                    await websocket.send(
                        json.dumps(
                            {
                                "type": "welcome",
                                "gateway_version": "1.0.0",
                                "server_time": time.time(),
                                "auth_required": bool(challenge_msg.get("auth_required", True)),
                                "challenge": challenge_msg.get("challenge"),
                            }
                        )
                    )
                except Exception:
                    pass

                # If auth is not required, auto-approve and send Ready immediately so
                # UIs don't need to implement the challenge-response roundtrip.
                if not bool(challenge_msg.get("auth_required", True)):
                    session_id = str(challenge_msg.get("session_id") or "")
                    success, session, error = self.auth.validate_auth(
                        session_id=session_id,
                        response="",
                        requested_role=data.get("role", "primary"),
                        capabilities=capabilities,
                        metadata=metadata,
                    )
                    if success and session:
                        self._client_sessions[client_id] = session
                        ready_msg = self.auth.create_ready_message(session)
                        await websocket.send(json.dumps(ready_msg))
                        # Protocol alias: "ready" (used by Flutter UI / Node protocol).
                        try:
                            alias_ready = dict(ready_msg)
                            alias_ready["type"] = "ready"
                            await websocket.send(json.dumps(alias_ready))
                        except Exception:
                            pass
                        logger.info(f"Client {client_id} auto-authenticated as {session.role.value}")
                    else:
                        error_msg = self.auth.create_error_message(error)
                        await websocket.send(json.dumps(error_msg))
                        logger.warning(f"Client {client_id} auto-auth failed: {error}")
                else:
                    logger.info(f"Sent challenge to client {client_id}")
                return
            
            elif msg_type in ("connect.auth", "auth"):
                # Step 2: Client responds to challenge
                session_id = data.get("session_id", "")
                response = data.get("response", "")
                if not response and isinstance(data.get("token"), str):
                    response = data.get("token", "")
                requested_role = data.get("role", "primary")
                capabilities = data.get("capabilities", [])
                metadata = data.get("metadata", {}) if isinstance(data.get("metadata"), dict) else {}
                
                success, session, error = self.auth.validate_auth(
                    session_id=session_id,
                    response=response,
                    requested_role=requested_role,
                    capabilities=capabilities,
                    metadata=metadata
                )
                
                if success and session:
                    self._client_sessions[client_id] = session
                    ready_msg = self.auth.create_ready_message(session)
                    await websocket.send(json.dumps(ready_msg))
                    # Alias for protocol clients.
                    try:
                        alias_ready = dict(ready_msg)
                        alias_ready["type"] = "ready"
                        await websocket.send(json.dumps(alias_ready))
                    except Exception:
                        pass
                    logger.info(f"Client {client_id} authenticated as {session.role.value}")
                else:
                    error_msg = self.auth.create_error_message(error)
                    await websocket.send(json.dumps(error_msg))
                    logger.warning(f"Client {client_id} auth failed: {error}")
                return
            
            elif msg_type == "disconnect":
                # Client gracefully disconnecting
                session = self._client_sessions.pop(client_id, None)
                if session:
                    self.auth.invalidate_session(session.session_id)
                await websocket.close()
                return
            
            # === STANDARD MESSAGE HANDLERS ===
            if msg_type == "ping":
                await websocket.send(json.dumps({"type": "pong"}))
            
            elif msg_type == "get_state":
                await self._send_state(websocket)

            elif msg_type == "get_runs":
                try:
                    from chintu_backend.core.run_manager import get_run_manager

                    await websocket.send(
                        json.dumps(
                            {
                                "type": "run_snapshot",
                                "data": get_run_manager().snapshot(limit=50),
                            }
                        )
                    )
                except Exception:
                    pass

            elif msg_type == "event":
                # Gateway-style frames from the Flutter UI:
                # { type: "event", payload: { event: "ui_action", data: { action: "text_input", ... } } }
                payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
                event_name = payload.get("event")
                event_data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
                if event_name != "ui_action":
                    return

                action_type = str(event_data.get("action") or "").strip()
                session = self._get_client_session(websocket)
                session_id = session.session_id if session else ""
                base_context = {"session_id": session_id} if session_id else {}

                if action_type == "text_input":
                    text = event_data.get("text", "")
                    attachments = event_data.get("attachments", [])
                    await self.event_bus.publish(
                        Event(
                            type=EventType.TRANSCRIPT_READY,
                            data={
                                "text": text,
                                "source": "ui",
                                "context": {"attachments": attachments, **base_context},
                            },
                        )
                    )
                    return

                if action_type == "push_to_talk":
                    state = str(event_data.get("state") or "").strip()
                    if state == "start":
                        await self.event_bus.publish(Event(type=EventType.PUSH_TO_TALK_START, source="ui"))
                    elif state == "stop":
                        await self.event_bus.publish(Event(type=EventType.PUSH_TO_TALK_STOP, source="ui"))
                    return

                if action_type == "typing_start":
                    await self.event_bus.publish(Event(type=EventType.TYPING_START, source="ui"))
                    return
                if action_type == "typing_stop":
                    await self.event_bus.publish(Event(type=EventType.TYPING_STOP, source="ui"))
                    return

                if action_type == "wake_word_status_request":
                    await self.event_bus.publish(Event(type=EventType.WAKE_WORD_STATUS_REQUEST, source="ui"))
                    return

                if action_type == "wake_word_record_sample":
                    await self.event_bus.publish(
                        Event(
                            type=EventType.WAKE_WORD_RECORD_REQUEST,
                            data={
                                "index": event_data.get("index"),
                                "kind": event_data.get("kind", "positive"),
                            },
                            source="ui",
                        )
                    )
                    return

                if action_type == "wake_word_train":
                    await self.event_bus.publish(Event(type=EventType.WAKE_WORD_TRAIN_REQUEST, source="ui"))
                    return

                if action_type == "canvas_action":
                    try:
                        from chintu_backend.canvas import get_canvas_manager

                        manager = get_canvas_manager()
                        action = event_data.get("canvas") or event_data.get("canvas_action") or event_data
                        if isinstance(action, dict):
                            manager.apply_action(action)
                    except Exception as exc:
                        logger.debug("canvas_action failed: %s", exc)
                    return

                if action_type in ("ui_ready", "orchestrator_snapshot_request"):
                    # Send an initial orchestrator snapshot so the UI can render dashboards immediately.
                    try:
                        from chintu_backend.orchestrator import get_orchestrator_manager

                        await websocket.send(
                            json.dumps(
                                {
                                    "type": "orchestrator_snapshot",
                                    "data": get_orchestrator_manager().get_overview(limit=50),
                                }
                            )
                        )
                    except Exception:
                        pass
                    # And a fresh run snapshot.
                    try:
                        from chintu_backend.core.run_manager import get_run_manager

                        await websocket.send(
                            json.dumps(
                                {
                                    "type": "run_snapshot",
                                    "data": get_run_manager().snapshot(limit=50),
                                }
                            )
                        )
                    except Exception:
                        pass
                    return

                if action_type == "run_cancel":
                    rid = str(event_data.get("run_id") or "").strip()
                    if rid:
                        try:
                            from chintu_backend.core.run_manager import get_run_manager

                            get_run_manager().cancel_run(rid, reason="cancelled via ui")
                        except Exception:
                            pass
                    return

                if action_type == "run_receipt_get":
                    rid = str(event_data.get("run_id") or "").strip()
                    req_id = str(event_data.get("request_id") or "").strip()
                    if not rid:
                        return
                    receipt_text = ""
                    receipt_path = ""
                    try:
                        from chintu_backend.core.run_manager import get_run_manager

                        rm = get_run_manager()
                        # 1) In-memory record path (if available)
                        try:
                            record = getattr(rm, "_runs", {}).get(rid)  # type: ignore[attr-defined]
                            if record and isinstance(getattr(record, "meta", None), dict):
                                receipt_path = str(record.meta.get("receipt_path") or "").strip()
                        except Exception:
                            receipt_path = ""
                        # 2) Disk fallback
                        if not receipt_path:
                            runs_dir = getattr(rm, "_runs_dir", None)  # type: ignore[attr-defined]
                            if not runs_dir:
                                runs_dir = Path.home() / ".chintu" / "runs"
                            receipt_path = str(Path(runs_dir) / rid / "receipt.md")
                        p = Path(receipt_path)
                        if p.exists():
                            receipt_text = p.read_text(encoding="utf-8", errors="ignore")
                        else:
                            receipt_text = ""
                    except Exception as exc:
                        receipt_text = ""
                        receipt_path = receipt_path or ""
                        try:
                            await websocket.send(
                                json.dumps(
                                    {
                                        "type": "run_receipt",
                                        "data": {
                                            "run_id": rid,
                                            "request_id": req_id,
                                            "error": str(exc),
                                            "receipt_path": receipt_path,
                                            "receipt": "",
                                        },
                                    }
                                )
                            )
                        except Exception:
                            pass
                        return

                    try:
                        await websocket.send(
                            json.dumps(
                                {
                                    "type": "run_receipt",
                                    "data": {
                                        "run_id": rid,
                                        "request_id": req_id,
                                        "receipt_path": receipt_path,
                                        "receipt": receipt_text,
                                    },
                                }
                            )
                        )
                    except Exception:
                        pass
                    return

                if action_type == "memory_search":
                    query = str(event_data.get("query") or event_data.get("text") or "").strip()
                    req_id = str(event_data.get("request_id") or "").strip()
                    try:
                        limit = int(event_data.get("limit") or 5)
                    except Exception:
                        limit = 5
                    limit = max(1, min(50, limit))
                    if not query:
                        try:
                            await websocket.send(
                                json.dumps(
                                    {
                                        "type": "memory_search_result",
                                        "data": {
                                            "query": query,
                                            "request_id": req_id,
                                            "results": [],
                                        },
                                    }
                                )
                            )
                        except Exception:
                            pass
                        return

                    results_payload = []
                    try:
                        from chintu_backend.brain.memory.hybrid_memory import HybridMemoryManager, get_hybrid_memory

                        mem = get_hybrid_memory() or HybridMemoryManager()
                        hits = mem.search(query, limit=limit)
                        for hit in hits:
                            try:
                                results_payload.append(
                                    {
                                        "id": int(getattr(hit, "id", 0) or 0),
                                        "content": str(getattr(hit, "content", "") or ""),
                                        "score": float(getattr(hit, "score", 0.0) or 0.0),
                                        "match_type": str(getattr(hit, "match_type", "") or ""),
                                        "created_at": str(getattr(hit, "created_at", "") or ""),
                                        "metadata": dict(getattr(hit, "metadata", {}) or {}),
                                    }
                                )
                            except Exception:
                                continue
                    except Exception as exc:
                        try:
                            await websocket.send(
                                json.dumps(
                                    {
                                        "type": "memory_search_result",
                                        "data": {
                                            "query": query,
                                            "request_id": req_id,
                                            "error": str(exc),
                                            "results": [],
                                        },
                                    }
                                )
                            )
                        except Exception:
                            pass
                        return

                    try:
                        await websocket.send(
                            json.dumps(
                                {
                                    "type": "memory_search_result",
                                    "data": {
                                        "query": query,
                                        "request_id": req_id,
                                        "results": results_payload,
                                    },
                                }
                            )
                        )
                    except Exception:
                        pass
                    return

                if action_type == "integrations_snapshot_request":
                    req_id = str(event_data.get("request_id") or "").strip()
                    try:
                        from chintu_backend.integrations.status import get_integrations_snapshot

                        await websocket.send(
                            json.dumps(
                                {
                                    "type": "integrations_snapshot",
                                    "data": {"request_id": req_id, "integrations": get_integrations_snapshot()},
                                }
                            )
                        )
                    except Exception as exc:
                        try:
                            await websocket.send(
                                json.dumps(
                                    {
                                        "type": "integrations_snapshot",
                                        "data": {"request_id": req_id, "error": str(exc), "integrations": {}},
                                    }
                                )
                            )
                        except Exception:
                            pass
                    return

                if action_type == "google_calendar_save_credentials":
                    json_content = str(
                        event_data.get("credentials_json")
                        or event_data.get("json")
                        or event_data.get("content")
                        or ""
                    )
                    ok = False
                    try:
                        from chintu_backend.integrations.google_calendar import get_calendar

                        ok = get_calendar().save_credentials(json_content)
                    except Exception:
                        ok = False
                    try:
                        from chintu_backend.integrations.status import get_integrations_snapshot

                        await websocket.send(
                            json.dumps(
                                {
                                    "type": "integrations_action_result",
                                    "data": {
                                        "action": "google_calendar_save_credentials",
                                        "ok": bool(ok),
                                        "message": "Saved credentials." if ok else "Failed to save credentials.",
                                        "integrations": get_integrations_snapshot(),
                                    },
                                }
                            )
                        )
                    except Exception:
                        pass
                    self._schedule_broadcast_state()
                    return

                if action_type == "google_calendar_authenticate":
                    ok = False
                    err = ""
                    try:
                        from chintu_backend.integrations.google_calendar import get_calendar

                        cal = get_calendar()
                        # Authentication is blocking (browser OAuth). Run off the event loop.
                        ok = bool(await asyncio.to_thread(cal.authenticate))
                    except Exception as exc:
                        ok = False
                        err = str(exc)
                    try:
                        from chintu_backend.integrations.status import get_integrations_snapshot

                        await websocket.send(
                            json.dumps(
                                {
                                    "type": "integrations_action_result",
                                    "data": {
                                        "action": "google_calendar_authenticate",
                                        "ok": bool(ok),
                                        "message": "Calendar authenticated." if ok else (err or "Calendar authentication failed."),
                                        "integrations": get_integrations_snapshot(),
                                    },
                                }
                            )
                        )
                    except Exception:
                        pass
                    self._schedule_broadcast_state()
                    return

                if action_type == "oauth_action":
                    provider = str(event_data.get("provider") or "").strip().lower()
                    operation = str(event_data.get("operation") or "").strip().lower()
                    ok = False
                    msg = ""
                    details: Dict[str, Any] = {}

                    if provider != "google_calendar":
                        ok = False
                        msg = f"OAuth provider '{provider or 'unknown'}' is not supported yet."
                    elif operation not in {"wizard", "health", "connect", "revoke"}:
                        ok = False
                        msg = f"Unsupported OAuth operation '{operation or 'unknown'}'."
                    else:
                        try:
                            from chintu_backend.integrations.oauth_onboarding import (
                                connect_google_calendar,
                                get_google_calendar_onboarding_steps,
                                google_calendar_health,
                                revoke_google_calendar,
                            )

                            if operation == "wizard":
                                write_access = bool(event_data.get("write_access", False))
                                steps = get_google_calendar_onboarding_steps(write_access=write_access)
                                details = {"provider": provider, "operation": operation, "steps": steps}
                                ok = True
                                msg = "Google Calendar OAuth wizard steps loaded."
                            elif operation == "health":
                                health = google_calendar_health()
                                details = {"provider": provider, "operation": operation, "health": health}
                                ok = bool(health.get("ok"))
                                msg = "Google Calendar OAuth is healthy." if ok else "Google Calendar OAuth requires attention."
                            elif operation == "connect":
                                write_access = bool(event_data.get("write_access", False))
                                force_reauth = bool(event_data.get("force_reauth", False))
                                credentials_path = str(event_data.get("credentials_path") or "").strip() or None
                                result = await asyncio.to_thread(
                                    connect_google_calendar,
                                    credentials_path=credentials_path,
                                    write_access=write_access,
                                    force_reauth=force_reauth,
                                )
                                details = {"provider": provider, "operation": operation, "result": result}
                                ok = bool(result.get("ok"))
                                msg = str(
                                    result.get("message")
                                    or ("Google Calendar connected." if ok else "Google Calendar connection failed.")
                                )
                            else:  # revoke
                                remove_credentials = bool(event_data.get("remove_credentials", False))
                                result = await asyncio.to_thread(
                                    revoke_google_calendar,
                                    remove_credentials=remove_credentials,
                                )
                                details = {"provider": provider, "operation": operation, "result": result}
                                ok = bool(result.get("ok"))
                                msg = str(
                                    result.get("message")
                                    or ("Google Calendar OAuth revoked." if ok else "Google Calendar revoke failed.")
                                )
                        except Exception as exc:
                            ok = False
                            msg = str(exc)

                    try:
                        from chintu_backend.integrations.status import get_integrations_snapshot

                        await websocket.send(
                            json.dumps(
                                {
                                    "type": "integrations_action_result",
                                    "data": {
                                        "action": "oauth_action",
                                        "provider": provider,
                                        "operation": operation,
                                        "ok": bool(ok),
                                        "message": msg,
                                        "details": details,
                                        "integrations": get_integrations_snapshot(),
                                    },
                                }
                            )
                        )
                    except Exception:
                        pass
                    self._schedule_broadcast_state()
                    return

                if action_type == "email_imap_save_config":
                    host = str(event_data.get("host") or "").strip()
                    user = str(event_data.get("user") or event_data.get("username") or "").strip()
                    folder = str(event_data.get("folder") or "INBOX").strip() or "INBOX"
                    password = str(event_data.get("password") or "").strip()
                    try:
                        port = int(event_data.get("port") or 993)
                    except Exception:
                        port = 993

                    ok = False
                    msg = ""
                    try:
                        from chintu_backend.integrations.integration_store import EmailImapConfig, upsert_email_imap_config

                        if not host or not user:
                            raise ValueError("Host and user are required.")
                        email_cfg = EmailImapConfig(host=host, port=int(port), user=user, folder=folder)
                        ok, msg = upsert_email_imap_config(email_cfg)
                    except Exception as exc:
                        ok = False
                        msg = str(exc)

                    vault_ok = False
                    vault_msg = ""
                    if password:
                        try:
                            from chintu_backend.security.identity_vault import get_identity_vault

                            vault = get_identity_vault()
                            if vault.available:
                                vault_ok, vault_msg = vault.store_secret(
                                    "email", "imap_password", password, note="IMAP password for Inbox triage"
                                )
                                # Update environment for current process.
                                os.environ["CHINTU_EMAIL_IMAP_PASSWORD"] = password
                        except Exception as exc:
                            vault_ok = False
                            vault_msg = str(exc)

                    # Update in-memory config for this process immediately.
                    try:
                        from chintu_backend.core.config import get_config

                        cfg = get_config()
                        cfg.email_imap_host = host
                        cfg.email_imap_port = int(port)
                        cfg.email_imap_user = user
                        cfg.email_imap_folder = folder
                        if password:
                            cfg.email_imap_password = password
                    except Exception:
                        pass

                    try:
                        from chintu_backend.integrations.status import get_integrations_snapshot

                        combined = "Saved email settings."
                        if not ok:
                            combined = f"Failed to save email settings: {msg}"
                        elif password and not vault_ok:
                            combined = f"Saved host/user, but failed to store password: {vault_msg}"

                        await websocket.send(
                            json.dumps(
                                {
                                    "type": "integrations_action_result",
                                    "data": {
                                        "action": "email_imap_save_config",
                                        "ok": bool(ok and (vault_ok or not password)),
                                        "message": combined,
                                        "integrations": get_integrations_snapshot(),
                                    },
                                }
                            )
                        )
                    except Exception:
                        pass
                    self._schedule_broadcast_state()
                    return

                if action_type == "email_imap_test_connection":
                    ok = False
                    msg = ""
                    try:
                        from chintu_backend.automation.tools.email_reader import get_email_reader

                        reader = get_email_reader()
                        ok, msg = reader.test_connection()
                    except Exception as exc:
                        ok = False
                        msg = str(exc)
                    try:
                        await websocket.send(
                            json.dumps(
                                {
                                    "type": "integrations_action_result",
                                    "data": {
                                        "action": "email_imap_test_connection",
                                        "ok": bool(ok),
                                        "message": msg or ("IMAP connection OK." if ok else "IMAP connection failed."),
                                    },
                                }
                            )
                        )
                    except Exception:
                        pass
                    return

                if action_type == "provider_key_save":
                    provider = str(event_data.get("provider") or "").strip().lower()
                    api_key = str(event_data.get("api_key") or event_data.get("key") or "").strip()

                    allowed = {
                        "nvidia": ("nvidia", "api_key", "NVIDIA_API_KEY", "nvidia_api_key"),
                        "groq": ("groq", "api_key", "GROQ_API_KEY", "groq_api_key"),
                        "gemini": ("gemini", "api_key", "GOOGLE_AI_KEY", "google_ai_key"),
                        "deepseek": ("deepseek", "api_key", "DEEPSEEK_API_KEY", "deepseek_api_key"),
                    }

                    ok = False
                    msg = ""
                    if not provider or provider not in allowed:
                        ok = False
                        msg = "Unknown provider. Use one of: nvidia, groq, gemini, deepseek."
                    elif not api_key:
                        ok = False
                        msg = "API key is empty."
                    else:
                        service, username, env_var, cfg_attr = allowed[provider]
                        try:
                            from chintu_backend.security.identity_vault import get_identity_vault

                            vault = get_identity_vault()
                            if not vault.available:
                                ok = False
                                msg = f"Identity vault unavailable: {vault.unavailable_reason}"
                            else:
                                ok, msg = vault.store_secret(service, username, api_key, note=f"{provider} API key")
                                if ok:
                                    os.environ[env_var] = api_key
                                    try:
                                        from chintu_backend.core.config import get_config

                                        cfg = get_config()
                                        if hasattr(cfg, cfg_attr):
                                            setattr(cfg, cfg_attr, api_key)
                                    except Exception:
                                        pass
                        except Exception as exc:
                            ok = False
                            msg = str(exc)

                    try:
                        from chintu_backend.integrations.status import get_integrations_snapshot

                        await websocket.send(
                            json.dumps(
                                {
                                    "type": "integrations_action_result",
                                    "data": {
                                        "action": "provider_key_save",
                                        "ok": bool(ok),
                                        "message": msg or ("Saved." if ok else "Failed to save."),
                                        "integrations": get_integrations_snapshot(),
                                    },
                                }
                            )
                        )
                    except Exception:
                        pass
                    self._schedule_broadcast_state()
                    return

                if action_type == "orchestrator_pause_project":
                    pid = str(event_data.get("project_id") or "").strip()
                    if pid:
                        try:
                            from chintu_backend.orchestrator import get_orchestrator_manager

                            get_orchestrator_manager().pause_project(pid)
                        except Exception:
                            pass
                    return

                if action_type == "orchestrator_resume_project":
                    pid = str(event_data.get("project_id") or "").strip()
                    if pid:
                        try:
                            from chintu_backend.orchestrator import get_orchestrator_manager

                            get_orchestrator_manager().resume_project(pid)
                        except Exception:
                            pass
                    return

                if action_type == "orchestrator_cancel_project":
                    pid = str(event_data.get("project_id") or "").strip()
                    if pid:
                        try:
                            from chintu_backend.orchestrator import get_orchestrator_manager

                            get_orchestrator_manager().cancel_project(pid)
                        except Exception:
                            pass
                    return

                if action_type == "orchestrator_approve_step":
                    step_id = str(event_data.get("step_id") or "").strip()
                    approve = bool(event_data.get("approve", False))
                    if step_id:
                        try:
                            from chintu_backend.orchestrator import get_orchestrator_manager

                            get_orchestrator_manager().approve_step(step_id, approve)
                        except Exception:
                            pass
                    return

                if action_type == "orchestrator_set_input":
                    key = str(event_data.get("key") or "").strip()
                    value = str(event_data.get("value") or "")
                    is_secret = bool(event_data.get("is_secret", False))
                    project_id = event_data.get("project_id")
                    pid = str(project_id).strip() if project_id else None
                    if key:
                        try:
                            from chintu_backend.orchestrator import get_orchestrator_manager

                            get_orchestrator_manager().set_input(key, value, is_secret=is_secret, project_id=pid)
                        except Exception:
                            pass
                    return

                if action_type == "a2ui_action":
                    await self.event_bus.publish(Event(type=EventType.A2UI_ACTION, data=event_data, source="ui"))
                    return

                return
            
            elif msg_type == "simulate_wake_word":
                # For testing - simulate wake word detection
                await self.event_bus.publish(Event(
                    type=EventType.WAKE_WORD_DETECTED,
                    source="ui",
                ))
            
            elif msg_type == "command":
                # Direct text command from UI
                text = data.get("text", "")
                attachments = data.get("attachments", [])
                
                await self.event_bus.publish(Event(
                    type=EventType.TRANSCRIPT_READY,
                    data={
                        "text": text, 
                        "source": "ui",
                        "context": {"attachments": attachments}
                    },
                ))
                # Send acknowledgment so UI can clear the input field
                await websocket.send(json.dumps({
                    "type": "command_received",
                    "status": "ok",
                    "text": text,
                }))
            
            elif msg_type == "copy_to_clipboard":
                text = data.get("text", "") or ""
                try:
                    from chintu_backend.automation.platform.clipboard import get_clipboard
                    clipboard = get_clipboard()
                    if not clipboard.is_available:
                        raise RuntimeError("Clipboard unavailable")
                    clipboard.set(text)
                    await websocket.send(json.dumps({
                        "type": "copy_to_clipboard",
                        "status": "ok",
                    }))
                except Exception as exc:
                    await websocket.send(json.dumps({
                        "type": "copy_to_clipboard",
                        "status": "error",
                        "error": str(exc),
                    }))
            
            elif msg_type == "cron_update":
                job_id = data.get("job_id") or ""
                schedule = data.get("schedule")
                name = data.get("name")
                enabled = data.get("enabled")
                try:
                    from chintu_backend.core.scheduler import get_scheduler
                    scheduler = get_scheduler()
                    ok = scheduler.update_job(
                        job_id=str(job_id),
                        schedule=str(schedule) if schedule is not None else None,
                        name=str(name) if name is not None else None,
                        enabled=bool(enabled) if enabled is not None else None,
                    )
                    await websocket.send(json.dumps({
                        "type": "cron_update",
                        "status": "ok" if ok else "error",
                        "job_id": job_id,
                    }))
                    self._schedule_broadcast_state()
                except Exception as exc:
                    await websocket.send(json.dumps({
                        "type": "cron_update",
                        "status": "error",
                        "job_id": job_id,
                        "error": str(exc),
                    }))
            
            elif msg_type == "cron_cancel":
                job_id = data.get("job_id") or ""
                try:
                    from chintu_backend.core.scheduler import get_scheduler
                    scheduler = get_scheduler()
                    scheduler.remove_job(str(job_id))
                    await websocket.send(json.dumps({
                        "type": "cron_cancel",
                        "status": "ok",
                        "job_id": job_id,
                    }))
                    self._schedule_broadcast_state()
                except Exception as exc:
                    await websocket.send(json.dumps({
                        "type": "cron_cancel",
                        "status": "error",
                        "job_id": job_id,
                        "error": str(exc),
                    }))
            
            elif msg_type == "typing_start":
                await self.event_bus.publish(Event(
                    type=EventType.TYPING_START,
                    source="ui",
                ))
            
            elif msg_type == "typing_stop":
                await self.event_bus.publish(Event(
                    type=EventType.TYPING_STOP,
                    source="ui",
                ))

            elif msg_type == "push_to_talk":
                action = data.get("action")
                if action == "start":
                    await self.event_bus.publish(Event(
                        type=EventType.PUSH_TO_TALK_START,
                        source="ui",
                    ))
                elif action == "stop":
                    await self.event_bus.publish(Event(
                        type=EventType.PUSH_TO_TALK_STOP,
                        source="ui",
                    ))

            elif msg_type == "record_wake_word_sample":
                index = data.get("index")
                kind = data.get("kind", "positive")
                await self.event_bus.publish(Event(
                    type=EventType.WAKE_WORD_RECORD_REQUEST,
                    data={"index": index, "kind": kind},
                    source="ui",
                ))

            elif msg_type == "get_wake_word_status":
                await self.event_bus.publish(Event(
                    type=EventType.WAKE_WORD_STATUS_REQUEST,
                    source="ui",
                ))

            elif msg_type == "wake_word_train":
                await self.event_bus.publish(Event(
                    type=EventType.WAKE_WORD_TRAIN_REQUEST,
                    source="ui",
                ))

            elif msg_type == "code_approval_response":
                await self.event_bus.publish(Event(
                    type=EventType.CODE_APPROVAL_RESPONSE,
                    data=data,
                    source="ui",
                ))

            elif msg_type == "get_capabilities":
                # UI requests capabilities tree
                from .capabilities_registry import get_capabilities_tree
                caps = get_capabilities_tree()
                await websocket.send(json.dumps({
                    "type": "capabilities_list",
                    "capabilities": caps
                }))

            elif msg_type == "client_capabilities":
                client_id = id(websocket)
                caps = data.get("data") if isinstance(data.get("data"), dict) else data
                # Store a lightweight, future-proof capability map.
                self._client_caps[client_id] = dict(caps or {})
                logger.info("Client capabilities registered: %s", client_id)

            elif msg_type == "a2ui_action":
                payload = data.get("data") if isinstance(data.get("data"), dict) else data
                await self.event_bus.publish(
                    Event(
                        type=EventType.A2UI_ACTION,
                        data=payload,
                        source="ui",
                    )
                )

            elif msg_type == "canvas_action":
                payload = data.get("data") if isinstance(data.get("data"), dict) else data
                try:
                    from chintu_backend.canvas import get_canvas_manager

                    manager = get_canvas_manager()
                    ok = manager.apply_action(payload or {})
                    await websocket.send(json.dumps({
                        "type": "canvas_action_result",
                        "success": ok,
                    }))
                except Exception as exc:
                    await websocket.send(json.dumps({
                        "type": "canvas_action_result",
                        "success": False,
                        "error": str(exc),
                    }))
            elif msg_type == "session_history":
                session_id = data.get("session_id", "")
                limit = int(data.get("limit") or 50)
                try:
                    from chintu_backend.core.session_manager import get_session_manager

                    mgr = get_session_manager()
                    history = mgr.get_history(session_id, limit=limit)
                    await websocket.send(json.dumps({
                        "type": "session_history",
                        "session_id": session_id,
                        "data": history,
                    }))
                except Exception as exc:
                    await websocket.send(json.dumps({
                        "type": "session_history",
                        "session_id": session_id,
                        "error": str(exc),
                    }))
            
            else:
                logger.warning(f"Unknown message type: {msg_type}")
                
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON message: {message}")
    
    async def _send_state(self, websocket):
        """Send current state to a client."""
        state_dict = self._build_state_payload()
        message = json.dumps({
            "type": "state_update",
            "data": state_dict,
        })
        await websocket.send(message)
    
    def _on_state_change(self, state: SystemState):
        """Called when system state changes."""
        if self._clients and self._running:
            self._schedule_broadcast_state()

    def _on_error_event(self, event: Event):
        """Handle error events for UI."""
        if self._clients and self._running:
            self._schedule_broadcast_error(event.data)

    def _on_canvas_event(self, event: Event):
        """Handle canvas updates for UI."""
        if self._clients and self._running:
            payload = {
                "type": "canvas_update",
                "data": event.data,
            }
            self._schedule_broadcast_message(payload)

    def _schedule_broadcast_state(self):
        """Schedule a state broadcast on the server loop."""
        if not self._loop or not self._loop.is_running():
            return
        try:
            if asyncio.get_running_loop() == self._loop:
                asyncio.create_task(self._broadcast_state())
            else:
                asyncio.run_coroutine_threadsafe(self._broadcast_state(), self._loop)
        except RuntimeError:
            asyncio.run_coroutine_threadsafe(self._broadcast_state(), self._loop)

    def _schedule_broadcast_error(self, data: dict):
        """Schedule an error broadcast on the server loop."""
        if not self._loop or not self._loop.is_running():
            return
        try:
            if asyncio.get_running_loop() == self._loop:
                asyncio.create_task(self._broadcast_error(data))
            else:
                asyncio.run_coroutine_threadsafe(self._broadcast_error(data), self._loop)
        except RuntimeError:
            asyncio.run_coroutine_threadsafe(self._broadcast_error(data), self._loop)

    def _schedule_broadcast_message(self, payload: dict):
        """Schedule a custom payload broadcast."""
        if not self._loop or not self._loop.is_running():
            return
        try:
            if asyncio.get_running_loop() == self._loop:
                asyncio.create_task(self.broadcast_message(payload))
            else:
                asyncio.run_coroutine_threadsafe(self.broadcast_message(payload), self._loop)
        except RuntimeError:
            asyncio.run_coroutine_threadsafe(self.broadcast_message(payload), self._loop)
    
    def bring_ui_to_front(self):
        """Tell the UI to come to front (when wake word detected or user summons)."""
        self._schedule_window_command("bring_to_front")
    
    def send_ui_to_back(self):
        """Tell the UI to go to back (when opening other apps)."""
        self._schedule_window_command("send_to_back")
    
    def _schedule_window_command(self, command: str):
        """Schedule a window control command broadcast."""
        if not self._loop or not self._loop.is_running():
            return
        try:
            if asyncio.get_running_loop() == self._loop:
                asyncio.create_task(self._broadcast_window_command(command))
            else:
                asyncio.run_coroutine_threadsafe(self._broadcast_window_command(command), self._loop)
        except RuntimeError:
            asyncio.run_coroutine_threadsafe(self._broadcast_window_command(command), self._loop)
    
    async def _broadcast_window_command(self, command: str):
        """Broadcast window control command to all clients."""
        if not self._clients:
            return
        
        message = json.dumps({
            "type": "window_control",
            "action": command 
        })
        
        await asyncio.gather(
            *[client.send(message) for client in self._clients],
            return_exceptions=True,
        )
    
    async def _broadcast_state(self):
        """Broadcast state to all connected clients."""
        if not self._clients:
            return
        
        state_dict = self._build_state_payload()
        message = json.dumps({
            "type": "state_update",
            "data": state_dict,
        })
        
        # Send to all clients
        await asyncio.gather(
            *[client.send(message) for client in self._clients],
            return_exceptions=True,
        )

    def _build_state_payload(self) -> Dict[str, Any]:
        """Build state payload with sessions + cron jobs."""
        state_dict = self.state_manager.to_dict()
        try:
            from chintu_backend.core.session_manager import get_session_manager
            from chintu_backend.core.scheduler import get_scheduler
            from chintu_backend.agents.change_journal import list_changes
            from chintu_backend.policy.budget_manager import get_budget_manager
            from chintu_backend.automation.job_apply import JobApplicationStore
            from chintu_backend.integrations.status import get_integrations_snapshot

            mgr = get_session_manager()
            sessions = mgr.list_sessions(active_only=True)
            state_dict["sessions"] = [
                {
                    "id": s.id,
                    "name": s.name,
                    "type": s.type.value,
                    "visibility": s.visibility.value,
                    "created_at": s.created_at.isoformat(),
                    "updated_at": s.updated_at.isoformat(),
                    "expires_at": s.expires_at.isoformat() if s.expires_at else None,
                    "transcript_path": str(mgr.sessions_dir / s.id / "transcript.jsonl"),
                }
                for s in sessions
            ]

            scheduler = get_scheduler()
            jobs = list(getattr(scheduler, "jobs", {}).values())
            state_dict["cron_jobs"] = [
                {
                    "id": j.id,
                    "name": j.name,
                    "schedule": j.schedule,
                    "task_type": j.task_type,
                    "last_run": j.last_run.isoformat() if j.last_run else None,
                    "next_run": j.next_run.isoformat() if j.next_run else None,
                    "enabled": j.enabled,
                    "post_summary": j.post_summary_to_main,
                }
                for j in jobs
            ]

            state_dict["change_log"] = list_changes(limit=50)
            try:
                state_dict["usage"] = get_budget_manager().get_usage_stats()
            except Exception:
                state_dict["usage"] = {}
            try:
                state_dict["job_applications"] = JobApplicationStore().list_applications(limit=50)
            except Exception:
                state_dict["job_applications"] = []
            try:
                state_dict["integrations"] = get_integrations_snapshot()
            except Exception:
                state_dict["integrations"] = {}
        except Exception:
            pass
        return state_dict

    async def _broadcast_error(self, data: dict):
        """Broadcast an error payload to all clients."""
        if not self._clients:
            return

        message = json.dumps({
            "type": "error",
            "data": data,
        })

        await asyncio.gather(
            *[client.send(message) for client in self._clients],
            return_exceptions=True,
        )
    
    async def broadcast_audio_level(self, level: float):
        """Broadcast audio level for waveform visualization."""
        if not self._clients:
            return
        
        message = json.dumps({
            "type": "audio_level",
            "level": level,
        })
        
        await asyncio.gather(
            *[client.send(message) for client in self._clients],
            return_exceptions=True,
        )
    
    async def broadcast_response(self, response: str):
        """Broadcast LLM/command response."""
        message = json.dumps({
            "type": "response",
            "text": response,
        })
        
        await asyncio.gather(
            *[client.send(message) for client in self._clients],
            return_exceptions=True,
        )

    async def broadcast_message(self, payload: dict):
        """Broadcast a custom payload to all clients."""
        if not self._clients:
            return
        message = json.dumps(payload)
        await asyncio.gather(
            *[client.send(message) for client in self._clients],
            return_exceptions=True,
        )
    
    async def broadcast_debug_info(self):
        """
        Broadcast debug metrics to all clients.
        
        Includes:
        - Model routing stats
        - Latency metrics
        - Budget status
        - Error counts
        """
        if not self._clients:
            return
        
        debug_data = {}
        
        # Get metrics if available
        try:
            from .metrics import get_metrics
            metrics = get_metrics()
            debug_data["metrics"] = metrics.get_debug_info()
        except ImportError:
            pass
        
        # Get budget status if available
        try:
            from .budget_manager import get_budget_manager
            budget = get_budget_manager()
            debug_data["budget"] = budget.get_usage_stats()
        except ImportError:
            pass
        
        # Get degraded mode status if available
        try:
            from .degraded_mode import get_degraded_mode
            degraded = get_degraded_mode()
            debug_data["system_mode"] = degraded.get_status_report()
        except ImportError:
            pass
        
        if debug_data:
            message = json.dumps({
                "type": "debug_info",
                "data": debug_data,
            })
            
            await asyncio.gather(
                *[client.send(message) for client in self._clients],
                return_exceptions=True,
            )

    async def broadcast_suggestion(self, suggestion_text: str, rule_id: str, priority: int = 5):
        """
        Broadcast a proactive suggestion to the UI.
        """
        if not self._clients:
            return
            
        message = json.dumps({
            'type': 'suggestion',
            'data': {
                'text': suggestion_text,
                'rule_id': rule_id,
                'priority': priority,
                'timestamp': __import__("time").time()
            }
        })
        
        await asyncio.gather(
            *[client.send(message) for client in self._clients],
            return_exceptions=True,
        )

    async def broadcast_log(self, log_entry: Dict[str, Any]):
        """Broadcast a raw backend log entry to all clients."""
        if not self._clients or not self._running:
            return
            
        message = json.dumps({
            'type': 'log_event',
            'data': log_entry
        })
        
        await asyncio.gather(
            *[client.send(message) for client in self._clients],
            return_exceptions=True,
        )


# Singleton accessor
_ws_server_instance: Optional[WebSocketServer] = None


def set_ws_server(server: WebSocketServer):
    """Set the global WebSocket server instance."""
    global _ws_server_instance
    _ws_server_instance = server


def get_ws_server() -> Optional[WebSocketServer]:
    """Get the global WebSocket server instance."""
    return _ws_server_instance
