"""WebSocket server for Flutter UI communication."""

import asyncio
import json
from pathlib import Path
from typing import Optional, Set, Dict, Any
import logging
import socket
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
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        
        self.state_manager = get_state_manager()
        self.event_bus = get_event_bus()
        
        # Subscribe to state changes
        self.state_manager.add_listener(self._on_state_change)
        self.event_bus.subscribe(EventType.ERROR, self._on_error_event)
    
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
        
        # Send current state
        await self._send_state(websocket)
        
        try:
            async for message in websocket:
                await self._handle_message(websocket, message)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self._clients.discard(websocket)
            self._client_caps.pop(client_id, None)
            logger.info(f"Client disconnected: {client_id}")
            
            await self.event_bus.publish(Event(
                type=EventType.UI_DISCONNECTED,
                data={"client_id": client_id},
            ))
    
    async def _handle_message(self, websocket, message: str):
        """Handle incoming message from client."""
        try:
            data = json.loads(message)
            msg_type = data.get("type")
            
            if msg_type == "ping":
                await websocket.send(json.dumps({"type": "pong"}))
            
            elif msg_type == "get_state":
                await self._send_state(websocket)
            
            elif msg_type == "simulate_wake_word":
                # For testing - simulate wake word detection
                await self.event_bus.publish(Event(
                    type=EventType.WAKE_WORD_DETECTED,
                    source="ui",
                ))
            
            elif msg_type == "command":
                # Direct text command from UI
                text = data.get("text", "")
                await self.event_bus.publish(Event(
                    type=EventType.TRANSCRIPT_READY,
                    data={"text": text, "source": "ui"},
                ))
                # Send acknowledgment so UI can clear the input field
                await websocket.send(json.dumps({
                    "type": "command_received",
                    "text": text,
                }))

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
                    "data": caps
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
            
            else:
                logger.warning(f"Unknown message type: {msg_type}")
                
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON message: {message}")
    
    async def _send_state(self, websocket):
        """Send current state to a client."""
        state_dict = self.state_manager.to_dict()
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
            "data": {"command": command}
        })
        
        await asyncio.gather(
            *[client.send(message) for client in self._clients],
            return_exceptions=True,
        )
    
    async def _broadcast_state(self):
        """Broadcast state to all connected clients."""
        if not self._clients:
            return
        
        state_dict = self.state_manager.to_dict()
        message = json.dumps({
            "type": "state_update",
            "data": state_dict,
        })
        
        # Send to all clients
        await asyncio.gather(
            *[client.send(message) for client in self._clients],
            return_exceptions=True,
        )

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
