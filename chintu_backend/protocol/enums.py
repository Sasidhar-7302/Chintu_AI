from enum import Enum

class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    HANDSHAKE = "handshake"
    CONNECTED = "connected"
    AUTHENTICATED = "authenticated"
    ERROR = "error"

class MessageType(str, Enum):
    # Lifecycle
    CONNECT = "connect"           # Client -> Gateway (Initial)
    WELCOME = "welcome"           # Gateway -> Client (Challenge/Salt)
    AUTH = "auth"                 # Client -> Gateway (Token/Response)
    READY = "ready"               # Gateway -> Client (Auth Success)
    DISCONNECT = "disconnect"     # Bidirectional

    # Data
    COMMAND = "command"           # Execute an action
    EVENT = "event"               # Fire-and-forget (e.g. log, state change)
    REQUEST = "request"           # RPC-style request (expects response)
    RESPONSE = "response"         # RPC-style response
    ERROR = "error"               # Something went wrong

    # Stream (Audio/Video/Tokens)
    STREAM_START = "stream_start"
    STREAM_CHUNK = "stream_chunk"
    STREAM_END = "stream_end"

class Role(str, Enum):
    GATEWAY = "gateway"           # The Server
    CORE = "core"                 # The Brain (LLM, Routing, State)
    UI = "ui"                     # Flutter/Web Interface
    VISION = "vision"             # Camera/Screen Service
    AUDIO = "audio"               # Mic/Speaker Service
    SKILL = "skill"               # Isolated Skill Process
    WATCHDOG = "watchdog"         # Monitor
