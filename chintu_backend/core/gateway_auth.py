"""Gateway authentication and session management.

Implements:
- Token-based authentication (connect.challenge / connect.auth)
- Scoped roles (primary, sandbox, readonly)
- Session management with timeout/keepalive
- Protocol version negotiation
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Any
import logging

logger = logging.getLogger(__name__)

# Protocol version for negotiation
PROTOCOL_VERSION = "1.0"
SUPPORTED_VERSIONS = ["1.0"]

# Session configuration
SESSION_TIMEOUT_SECONDS = 3600  # 1 hour
CHALLENGE_EXPIRY_SECONDS = 30
TOKEN_LENGTH_BYTES = 32


class AuthRole(Enum):
    """Authorization roles with different permission levels."""
    PRIMARY = "primary"      # Full access: all tools, exec, config
    SANDBOX = "sandbox"      # Limited: no exec, no system changes
    READONLY = "readonly"    # View only: state, responses, no commands
    ANONYMOUS = "anonymous"  # Unauthenticated: challenge required


@dataclass
class GatewaySession:
    """Represents an authenticated gateway session."""
    session_id: str
    role: AuthRole
    device_id: str
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    capabilities: list = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def is_expired(self) -> bool:
        return (time.time() - self.last_activity) > SESSION_TIMEOUT_SECONDS
    
    def touch(self) -> None:
        """Update last activity timestamp."""
        self.last_activity = time.time()
    
    def can_execute(self) -> bool:
        """Check if session can execute commands."""
        return self.role in (AuthRole.PRIMARY, AuthRole.SANDBOX)
    
    def can_exec_system(self) -> bool:
        """Check if session can execute system commands."""
        return self.role == AuthRole.PRIMARY
    
    def can_modify_config(self) -> bool:
        """Check if session can modify configuration."""
        return self.role == AuthRole.PRIMARY


@dataclass  
class PendingChallenge:
    """A pending challenge awaiting auth response."""
    challenge: str
    device_id: str
    created_at: float = field(default_factory=time.time)
    
    @property
    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > CHALLENGE_EXPIRY_SECONDS


@dataclass
class PendingHITLChallenge:
    """A pending HITL approval awaiting user response."""
    action_id: str
    action_type: str
    details: Dict[str, Any]
    session_id: str
    created_at: float = field(default_factory=time.time)
    
    @property
    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > 300  # 5 minutes expiry

class GatewayAuth:
    """
    Gateway authentication manager.
    
    Protocol flow:
    1. Client connects and sends: {"type": "connect", "device_id": "...", "protocol_version": "1.0"}
    2. Server responds with: {"type": "connect.challenge", "challenge": "...", "session_id": "..."}
    3. Client responds with: {"type": "connect.auth", "session_id": "...", "response": hmac(challenge, secret)}
    4. Server validates and sends: {"type": "connect.ready", "role": "primary", ...}
    """
    
    def __init__(self, secret_key: Optional[str] = None, auth_required: bool = True):
        """
        Initialize gateway auth.
        
        Args:
            secret_key: Shared secret for HMAC validation. If None, generates random.
            auth_required: If False, skip auth and grant PRIMARY role.
        """
        self.secret_key = secret_key or self._load_secret_key() or secrets.token_hex(32)
        self.auth_required = auth_required
        self.sessions: Dict[str, GatewaySession] = {}
        self.pending_challenges: Dict[str, PendingChallenge] = {}
        self.pending_hitl: Dict[str, PendingHITLChallenge] = {}
        
        logger.info(f"GatewayAuth initialized (auth_required={auth_required})")

    def _load_secret_key(self) -> Optional[str]:
        """Load shared secret from environment or file."""
        import os
        from pathlib import Path

        env_secret = os.environ.get("CHINTU_GATEWAY_SECRET")
        if env_secret:
            return env_secret
        secret_path = Path.home() / ".chintu" / "gateway_secret"
        if secret_path.exists():
            return secret_path.read_text().strip()
        return None
    
    def create_challenge(self, device_id: str, client_capabilities: list = None) -> Dict[str, Any]:
        """
        Create a challenge for a connecting client.
        
        Returns connect.challenge message.
        """
        session_id = secrets.token_urlsafe(16)
        challenge = secrets.token_hex(CHALLENGE_EXPIRY_SECONDS)
        
        self.pending_challenges[session_id] = PendingChallenge(
            challenge=challenge,
            device_id=device_id
        )
        
        # Clean up expired challenges
        self._cleanup_expired_challenges()
        
        return {
            "type": "connect.challenge",
            "session_id": session_id,
            "challenge": challenge,
            "protocol_version": PROTOCOL_VERSION,
            "auth_required": self.auth_required
        }
    
    def validate_auth(
        self, 
        session_id: str, 
        response: str, 
        requested_role: str = "primary",
        capabilities: list = None,
        metadata: Dict[str, Any] = None
    ) -> tuple[bool, Optional[GatewaySession], str]:
        """
        Validate an auth response.
        
        Returns (success, session, error_message).
        """
        pending = self.pending_challenges.get(session_id)
        
        if not pending:
            return False, None, "Invalid or expired session_id"
        
        if pending.is_expired:
            del self.pending_challenges[session_id]
            return False, None, "Challenge expired"
        
        # Skip auth validation if not required
        if not self.auth_required:
            session = self._create_session(
                session_id=session_id,
                device_id=pending.device_id,
                role=AuthRole.PRIMARY,
                capabilities=capabilities or [],
                metadata=metadata or {}
            )
            del self.pending_challenges[session_id]
            return True, session, ""
        
        # Validate HMAC response
        expected_response = hmac.new(
            self.secret_key.encode(),
            pending.challenge.encode(),
            hashlib.sha256
        ).hexdigest()
        
        if not hmac.compare_digest(response, expected_response):
            return False, None, "Invalid auth response"
        
        # Create session with requested role
        try:
            role = AuthRole(requested_role)
        except ValueError:
            role = AuthRole.READONLY
        
        session = self._create_session(
            session_id=session_id,
            device_id=pending.device_id,
            role=role,
            capabilities=capabilities or [],
            metadata=metadata or {}
        )
        
        del self.pending_challenges[session_id]
        return True, session, ""
    
    def _create_session(
        self,
        session_id: str,
        device_id: str,
        role: AuthRole,
        capabilities: list,
        metadata: Dict[str, Any]
    ) -> GatewaySession:
        """Create and store a new session."""
        session = GatewaySession(
            session_id=session_id,
            role=role,
            device_id=device_id,
            capabilities=capabilities,
            metadata=metadata
        )
        self.sessions[session_id] = session
        logger.info(f"Session created: {session_id} (role={role.value}, device={device_id})")
        return session
    
    def get_session(self, session_id: str) -> Optional[GatewaySession]:
        """Get a session by ID, checking expiry."""
        session = self.sessions.get(session_id)
        if session and session.is_expired:
            logger.info(f"Session expired: {session_id}")
            del self.sessions[session_id]
            return None
        if session:
            session.touch()
        return session
    
    def invalidate_session(self, session_id: str) -> bool:
        """Invalidate a session."""
        if session_id in self.sessions:
            del self.sessions[session_id]
            logger.info(f"Session invalidated: {session_id}")
            return True
        return False
    
    def create_ready_message(self, session: GatewaySession) -> Dict[str, Any]:
        """Create connect.ready message for successful auth."""
        return {
            "type": "connect.ready",
            "session_id": session.session_id,
            "role": session.role.value,
            "protocol_version": PROTOCOL_VERSION,
            "capabilities": session.capabilities,
            "permissions": {
                "execute": session.can_execute(),
                "exec_system": session.can_exec_system(),
                "modify_config": session.can_modify_config()
            }
        }
    
    def create_error_message(self, error: str, code: str = "auth_failed") -> Dict[str, Any]:
        """Create connect.error message."""
        return {
            "type": "connect.error",
            "error": error,
            "code": code
        }
    
    def create_hitl_challenge(self, action_id: str, action_type: str, details: Dict[str, Any], session_id: str) -> Dict[str, Any]:
        """Create a HITL approval challenge for the client."""
        self.pending_hitl[action_id] = PendingHITLChallenge(
            action_id=action_id,
            action_type=action_type,
            details=details,
            session_id=session_id
        )
        return {
            "type": "hitl.challenge",
            "action_id": action_id,
            "action_type": action_type,
            "details": details,
            "timeout_seconds": 300
        }
        
    def resolve_hitl(self, action_id: str, approved: bool, session_id: str) -> bool:
        """Resolve a HITL token after user responds from the UI."""
        if action_id in self.pending_hitl:
            challenge = self.pending_hitl[action_id]
            if not challenge.is_expired and challenge.session_id == session_id:
                del self.pending_hitl[action_id]
                from chintu_backend.core.action_interceptor import get_action_interceptor
                get_action_interceptor().resolve_action(action_id, approved)
                return True
        return False

    def _cleanup_expired_challenges(self) -> None:
        """Remove expired pending challenges."""
        expired = [
            sid for sid, c in self.pending_challenges.items()
            if c.is_expired
        ]
        for sid in expired:
            del self.pending_challenges[sid]
    
    def cleanup_expired_sessions(self) -> int:
        """Remove expired sessions. Returns count of removed."""
        expired = [
            sid for sid, s in self.sessions.items()
            if s.is_expired
        ]
        for sid in expired:
            del self.sessions[sid]
        if expired:
            logger.info(f"Cleaned up {len(expired)} expired sessions")
        return len(expired)
    
    def get_active_session_count(self) -> int:
        """Get count of active (non-expired) sessions."""
        self.cleanup_expired_sessions()
        return len(self.sessions)
    
    def check_protocol_version(self, client_version: str) -> tuple[bool, str]:
        """
        Check if client protocol version is supported.
        
        Returns (supported, negotiated_version).
        """
        if client_version in SUPPORTED_VERSIONS:
            return True, client_version
        # Return latest supported version for upgrade
        return False, PROTOCOL_VERSION


# Singleton instance
_gateway_auth: Optional[GatewayAuth] = None


def get_gateway_auth(secret_key: Optional[str] = None, auth_required: bool = True) -> GatewayAuth:
    """Get or create gateway auth singleton."""
    global _gateway_auth
    if _gateway_auth is None:
        _gateway_auth = GatewayAuth(secret_key=secret_key, auth_required=auth_required)
    return _gateway_auth
