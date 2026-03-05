from typing import Optional, Dict, Any, List, Union
from pydantic import BaseModel, Field
import time
import uuid

from .enums import MessageType, Role

# ============================================================================
# BASE FRAME
# ============================================================================

class BaseFrame(BaseModel):
    """Base Pydantic model for all protocol frames."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: MessageType
    timestamp: float = Field(default_factory=time.time)

# ============================================================================
# LIFECYCLE FRAMES
# ============================================================================

class ConnectFrame(BaseFrame):
    """Client -> Gateway: Initial connection request."""
    type: MessageType = MessageType.CONNECT
    role: Role
    device_id: str
    capabilities: List[str] = Field(default_factory=list)  # ["camera", "screen", "tts"]
    metadata: Dict[str, Any] = Field(default_factory=dict)

class WelcomeFrame(BaseFrame):
    """Gateway -> Client: Challenge/Salt for auth."""
    type: MessageType = MessageType.WELCOME
    gateway_version: str = "1.0.0"
    server_time: float = Field(default_factory=time.time)
    auth_required: bool = True
    challenge: Optional[str] = None  # Nonce for signing

class AuthFrame(BaseFrame):
    """Client -> Gateway: Authentication response."""
    type: MessageType = MessageType.AUTH
    token: str  # JWT or signed challenge
    
class ReadyFrame(BaseFrame):
    """Gateway -> Client: Authentication successful."""
    type: MessageType = MessageType.READY
    session_id: str
    node_id: str

# ============================================================================
# DATA FRAMES
# ============================================================================

class DataFrame(BaseFrame):
    """Generic data payload."""
    type: MessageType
    source: str  # node_id or role
    target: Union[str, Role, None] = None  # None = Broadcast
    payload: Dict[str, Any]

class CommandFrame(BaseFrame):
    """Execute a capability."""
    type: MessageType = MessageType.COMMAND
    command: str
    args: Dict[str, Any] = Field(default_factory=dict)
    requester: str

class ErrorFrame(BaseFrame):
    """Standard error response."""
    type: MessageType = MessageType.ERROR
    code: int
    message: str
    details: Optional[Dict[str, Any]] = None
    original_msg_id: Optional[str] = None
