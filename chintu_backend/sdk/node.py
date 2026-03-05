import asyncio
import json
import logging
import websockets
import uuid
import inspect
import hashlib
import hmac
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Callable, Any, Union

from ..protocol.enums import MessageType, Role
from ..protocol.frames import (
    ConnectFrame, WelcomeFrame, AuthFrame, ReadyFrame,
    DataFrame, CommandFrame, ErrorFrame, CommandResultFrame
)
from chintu_backend.core.safe_exec import get_safe_executor, SafeExecutor

logger = logging.getLogger("ChintuNode")


class ChintuNode:
    """
    A client SDK for connecting to the Chintu Gateway.
    Handles handshake, authentication, and automatic reconnection.
    
    Features:
    - Token-based authentication
    - Certificate/HMAC support
    - Auto-reconnection with backoff
    - Event-driven handlers
    """
    def __init__(
        self, 
        role: Role, 
        device_id: Optional[str] = None,
        gateway_url: str = "ws://localhost:18789",
        capabilities: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        auth_token: Optional[str] = None,
        auth_secret: Optional[str] = None
    ):
        self.role = role
        self.device_id = device_id or f"{role}_{uuid.uuid4().hex[:8]}"
        self.gateway_url = gateway_url
        self.capabilities = capabilities or []
        self.metadata = metadata or {}
        
        # Authentication
        self.auth_token = auth_token or self._load_token()
        self.auth_secret = auth_secret or self._load_secret()
        self._authenticated = False
        
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.session_id: Optional[str] = None
        self._handlers: Dict[str, List[Callable]] = {}
        self._running = False
        self._ready_event = asyncio.Event()
        self._reconnect_delay = 3  # Start with 3s, exponential backoff
        self._max_reconnect_delay = 60
        self.executor: SafeExecutor = get_safe_executor()
        
        # Register default command handler
        self._handlers[MessageType.COMMAND] = [self._handle_command]

    def _load_token(self) -> Optional[str]:
        """Load auth token from file or environment."""
        import os
        
        # Check environment first
        token = os.environ.get("CHINTU_NODE_TOKEN")
        if token:
            return token
        
        # Check token file
        token_file = Path.home() / ".chintu" / "node_token"
        if token_file.exists():
            return token_file.read_text().strip()
        
        return None

    def _load_secret(self) -> Optional[str]:
        """Load shared gateway secret from env or file."""
        import os

        secret = os.environ.get("CHINTU_GATEWAY_SECRET")
        if secret:
            return secret
        secret_file = Path.home() / ".chintu" / "gateway_secret"
        if secret_file.exists():
            return secret_file.read_text().strip()
        return None
    
    def _generate_auth_signature(self, challenge: str) -> str:
        """Generate HMAC signature for challenge-response auth."""
        if not self.auth_secret:
            return ""
        
        signature = hmac.new(
            self.auth_secret.encode(),
            challenge.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return signature

    def on(self, event_type: str):
        """Decorator to register an event handler."""
        def decorator(func):
            if event_type not in self._handlers:
                self._handlers[event_type] = []
            self._handlers[event_type].append(func)
            return func
        return decorator

    async def connect(self):
        """Connect to Gateway and run the loop."""
        self._running = True
        while self._running:
            try:
                logger.info(f"Connecting to {self.gateway_url}...")
                async with websockets.connect(self.gateway_url) as ws:
                    self.websocket = ws
                    self._reconnect_delay = 3  # Reset on successful connect
                    
                    # --- HANDSHAKE START ---
                    
                    # 1. Send Connect
                    connect = ConnectFrame(
                        role=self.role,
                        device_id=self.device_id,
                        capabilities=self.capabilities,
                        metadata=self.metadata
                    )
                    await ws.send(connect.model_dump_json())
                    
                    # 2. Receive Welcome
                    raw_welcome = await ws.recv()
                    welcome = WelcomeFrame.model_validate_json(raw_welcome)
                    
                    # 3. Handle Authentication
                    if welcome.auth_required:
                        auth_success = await self._handle_auth(ws, welcome)
                        if not auth_success:
                            logger.error("Authentication failed")
                            await asyncio.sleep(self._reconnect_delay)
                            continue
                    
                    self._authenticated = True
                        
                    # 4. Receive Ready
                    raw_ready = await ws.recv()
                    ready = ReadyFrame.model_validate_json(raw_ready)
                    self.session_id = ready.session_id
                    
                    logger.info(f"Connected! Session: {self.session_id}, Authenticated: {self._authenticated}")
                    self._ready_event.set()
                    
                    # --- HANDSHAKE COMPLETE ---
                    
                    # 5. Message Loop
                    async for message in ws:
                        await self._handle_message(message)
                            
            except (websockets.exceptions.ConnectionClosed, OSError) as e:
                logger.warning(f"Connection lost: {e}. Retrying in {self._reconnect_delay}s...")
                self._ready_event.clear()
                self.websocket = None
                self._authenticated = False
                await asyncio.sleep(self._reconnect_delay)
                # Exponential backoff
                self._reconnect_delay = min(self._reconnect_delay * 2, self._max_reconnect_delay)
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                await asyncio.sleep(self._reconnect_delay)

    async def _handle_auth(self, ws, welcome: WelcomeFrame) -> bool:
        """Handle authentication handshake."""
        try:
            # Build auth frame
            auth_data = {
                "type": MessageType.AUTH,
                "device_id": self.device_id,
                "timestamp": datetime.now().isoformat(),
            }
            
            # Token-based auth
            if self.auth_token:
                auth_data["token"] = self.auth_token
            
            # Challenge-response auth (if challenge provided)
            challenge = getattr(welcome, 'challenge', None)
            if challenge and self.auth_secret:
                auth_data["signature"] = self._generate_auth_signature(challenge)
                auth_data["challenge"] = challenge
            
            # Capabilities claim
            auth_data["capabilities"] = self.capabilities
            
            auth_frame = AuthFrame(**auth_data)
            await ws.send(auth_frame.model_dump_json())
            
            # Wait for auth response
            raw_response = await asyncio.wait_for(ws.recv(), timeout=10)
            response = json.loads(raw_response)
            
            if response.get("type") == "auth_success":
                logger.info("Authentication successful")
                return True
            elif response.get("type") == "auth_failure":
                logger.error(f"Auth rejected: {response.get('reason', 'Unknown')}")
                return False
            else:
                # Might be Ready frame if auth was auto-approved
                return True
                
        except asyncio.TimeoutError:
            logger.error("Authentication timed out")
            return False
        except Exception as e:
            logger.error(f"Auth error: {e}")
            return False

    async def _handle_command(self, data: Dict[str, Any]):
        """Handle incoming command."""
        try:
            cmd_frame = CommandFrame.model_validate(data)
            
            # Authorization check (basic: is it targeting me?)
            if cmd_frame.target != self.device_id and cmd_frame.target != "*":
                return
            
            logger.info(f"Received command: {cmd_frame.command} from {cmd_frame.source}")
            
            result_data = None
            success = False
            error = None
            
            # Handle system.run
            if cmd_frame.command == "system.run":
                args = cmd_frame.args.get("args", [])
                if isinstance(args, str):
                    import shlex
                    args = shlex.split(args)
                
                # Execute securely
                exec_result = self.executor.run(args)
                success = exec_result.success
                if success:
                    result_data = {"stdout": exec_result.stdout, "stderr": exec_result.stderr}
                else:
                    error = exec_result.error
            else:
                error = f"Unknown command: {cmd_frame.command}"
            
            # Determine success status
            status = "success" if success else "error"
            
            # Send result back
            result_frame = CommandResultFrame(
                type=MessageType.COMMAND_RESULT,
                source=self.device_id,
                target=cmd_frame.source,
                command_id=cmd_frame.id if hasattr(cmd_frame, 'id') else str(uuid.uuid4()),
                status=status,
                result=result_data,
                error=error
            )
            await self.send(result_frame.model_dump())
            
        except Exception as e:
            logger.error(f"Error handling command: {e}")

    async def _handle_message(self, message: str):
        """Process incoming message."""
        try:
            data = json.loads(message)
            msg_type = data.get("type")
            
            # Dispatch to handlers
            handlers = self._handlers.get(msg_type, [])
            
            # Special handling for EVENT type dispatching by event name
            if msg_type == MessageType.EVENT:
                payload = data.get("payload", {})
                event_name = payload.get("event")
                if event_name and event_name in self._handlers:
                    handlers.extend(self._handlers[event_name])
            
            # Execute handlers
            for handler in handlers:
                if inspect.iscoroutinefunction(handler):
                    await handler(data)
                else:
                    handler(data)
                        
        except Exception as e:
            logger.error(f"Error processing message: {e}")

    async def wait_until_ready(self):
        await self._ready_event.wait()

    async def send(self, data: Dict[str, Any]):
        """Send raw data (must comply with protocol)."""
        if self.websocket:
            await self.websocket.send(json.dumps(data))
        else:
            logger.warning("Cannot send: Disconnected")

    async def send_command(self, target: str, command: str, args: Optional[Dict] = None):
        """Helper to send a CommandFrame."""
        frame = CommandFrame(
            type=MessageType.COMMAND,
            source=self.device_id,
            target=target,
            command=command,
            args=args or {},
            requester=self.device_id
        )
        await self.send(frame.model_dump())

    async def emit(self, event_type: str, payload: Dict[str, Any], target: Optional[str] = None):
        """Helper to send a generic DataFrame/Event."""
        frame = DataFrame(
            type=MessageType.EVENT,
            source=self.device_id,
            target=target,
            payload={"event": event_type, "data": payload}
        )
        await self.send(frame.model_dump())

    @property
    def is_authenticated(self) -> bool:
        """Check if currently authenticated."""
        return self._authenticated and self.session_id is not None

    async def disconnect(self):
        self._running = False
        if self.websocket:
            await self.websocket.close()

