"""
Unified Session Manager for Chintu AI.
Manages session lifecycles, typing, visibility, and pruning.

Aligns with the internal session model:
- Types: MAIN, GROUP, CRON, HOOK, NODE
- Scopes: PUBLIC, PRIVATE, INTERNAL
- Auto-pruning for ephemeral sessions
"""

import logging
import json
import shutil
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
import uuid

from chintu_backend.core.config import get_config

logger = logging.getLogger(__name__)


class SessionType(Enum):
    MAIN = "main"       # Primary user interaction (persistent)
    GROUP = "group"     # Multi-agent swarm (semi-persistent)
    CRON = "cron"       # Scheduled background tasks (ephemeral)
    HOOK = "hook"       # Webhook/Event reactor (ephemeral)
    NODE = "node"       # Remote device session (persistent)


class Visibility(Enum):
    PUBLIC = "public"     # Visible to user in UI
    PRIVATE = "private"   # Visible but locked/archived
    INTERNAL = "internal" # Hidden system session (e.g. cron logs)


@dataclass
class Session:
    """Represents a conversational context or execution environment."""
    id: str
    type: SessionType
    name: str
    visibility: Visibility = Visibility.PUBLIC
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None  # For auto-pruning
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Message history is stored separately on disk to keep memory light
    
    @property
    def is_expired(self) -> bool:
        if self.expires_at and datetime.now() > self.expires_at:
            return True
        return False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "name": self.name,
            "visibility": self.visibility.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Session':
        return cls(
            id=data["id"],
            type=SessionType(data["type"]),
            name=data["name"],
            visibility=Visibility(data.get("visibility", "public")),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            expires_at=datetime.fromisoformat(data["expires_at"]) if data.get("expires_at") else None,
            metadata=data.get("metadata", {})
        )


class SessionManager:
    """
    Manages all Chintu sessions.
    Handles creation, persistence, retrieval, and pruning.
    """
    
    def __init__(self):
        self.config = get_config()
        self.sessions_dir = self.config.data_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        
        self.sessions: Dict[str, Session] = {}
        self._load_sessions()
        
        # Start background pruning
        self._pruning_task = None
    
    def start(self):
        """Start background tasks."""
        if not self._pruning_task:
            try:
                loop = asyncio.get_running_loop()
                self._pruning_task = loop.create_task(self._pruning_loop())
                logger.info("SessionManager background tasks started.")
            except RuntimeError:
                logger.warning("SessionManager started without active event loop.")

    async def close(self):
        """Stop background tasks."""
        if self._pruning_task:
            self._pruning_task.cancel()
            try:
                await self._pruning_task
            except asyncio.CancelledError:
                pass
            self._pruning_task = None

    async def _pruning_loop(self):
        """Background loop to prune expired sessions."""
        while True:
            try:
                self.prune_expired()
                # Run hourly
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in session pruning loop: {e}")
# Retry sooner on error
                await asyncio.sleep(300)
    
    def create_session(
        self,
        name: str,
        type: SessionType = SessionType.MAIN,
        visibility: Visibility = Visibility.PUBLIC,
        metadata: Dict[str, Any] = None,
        ttl_hours: int = None,
        session_id: Optional[str] = None,
    ) -> Session:
        """
        Create a new session.
        
        Args:
            name: Human readable name
            type: Session type
            visibility: Visibility scope
            metadata: Custom data
            ttl_hours: Hours until expiration (default based on type)
        """
        if session_id and session_id in self.sessions:
            return self.sessions[session_id]
        session_id = session_id or str(uuid.uuid4())
        
        # Set default TTL based on type if not provided
        expires_at = None
        if ttl_hours:
            expires_at = datetime.now() + timedelta(hours=ttl_hours)
        elif type in [SessionType.CRON, SessionType.HOOK]:
            # Ephemeral sessions expire in 24h by default
            expires_at = datetime.now() + timedelta(hours=24)
        
        # Internal visibility by default for background tasks
        if type in [SessionType.CRON, SessionType.HOOK] and visibility == Visibility.PUBLIC:
            visibility = Visibility.INTERNAL
            
        session = Session(
            id=session_id,
            type=type,
            name=name,
            visibility=visibility,
            expires_at=expires_at,
            metadata=metadata or {}
        )
        
        self.sessions[session_id] = session
        self._save_session(session)
        logger.info(f"Created session {session_id} ({type.value}): {name}")
        
        return session

    def ensure_session(
        self,
        session_id: str,
        name: str,
        type: SessionType = SessionType.MAIN,
        visibility: Visibility = Visibility.PUBLIC,
        metadata: Dict[str, Any] = None,
        ttl_hours: int = None,
    ) -> Session:
        """Get or create a session by id."""
        existing = self.sessions.get(session_id)
        if existing:
            return existing
        return self.create_session(
            name=name,
            type=type,
            visibility=visibility,
            metadata=metadata,
            ttl_hours=ttl_hours,
            session_id=session_id,
        )
    
    def get_session(self, session_id: str) -> Optional[Session]:
        return self.sessions.get(session_id)
    
    def list_sessions(
        self,
        type: SessionType = None,
        visibility: Visibility = None,
        active_only: bool = True
    ) -> List[Session]:
        """List sessions filtering by criteria."""
        results = []
        for s in self.sessions.values():
            if type and s.type != type:
                continue
            if visibility and s.visibility != visibility:
                continue
            if active_only and s.is_expired:
                continue
            results.append(s)
            
        return sorted(results, key=lambda x: x.updated_at, reverse=True)
    
    def delete_session(self, session_id: str):
        """Delete a session and its data."""
        if session_id in self.sessions:
            del self.sessions[session_id]
            
            # Remove file
            session_file = self.sessions_dir / f"{session_id}.json"
            if session_file.exists():
                session_file.unlink()
                
            # Remove history/artifacts dir if exists
            session_data = self.sessions_dir / session_id
            if session_data.exists():
                shutil.rmtree(session_data)
                
            logger.info(f"Deleted session {session_id}")
            
    def prune_expired(self) -> int:
        """Prune all expired sessions."""
        expired = [s.id for s in self.sessions.values() if s.is_expired]
        for sid in expired:
            self.delete_session(sid)
        
        if expired:
            logger.info(f"Pruned {len(expired)} expired sessions")
        return len(expired)
    
    def touch_session(self, session_id: str):
        """Update session last accessed time."""
        session = self.sessions.get(session_id)
        if session:
            session.updated_at = datetime.now()
            self._save_session(session)

    def append_turn(self, session_id: str, role: str, content: str, meta: Optional[Dict[str, Any]] = None) -> None:
        """Append a turn to the session transcript."""
        if not session_id:
            return
        session = self.sessions.get(session_id)
        if not session:
            session = self.ensure_session(session_id=session_id, name=session_id)
        transcript_dir = self.sessions_dir / session_id
        transcript_dir.mkdir(parents=True, exist_ok=True)
        path = transcript_dir / "transcript.jsonl"
        entry = {
            "ts": datetime.now().isoformat(),
            "role": role,
            "content": content,
            "meta": meta or {},
        }
        try:
            path.write_text("", encoding="utf-8", errors="ignore") if not path.exists() else None
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=True) + "\n")
        except Exception as exc:
            logger.warning("Failed to append session turn: %s", exc)
        try:
            from chintu_backend.core.task_history import get_task_history_manager

            get_task_history_manager().record_conversation_turn(
                session_id=session_id,
                role=role,
                content=content,
                meta=meta or {},
            )
        except Exception:
            pass
        self.touch_session(session_id)

    def get_history(self, session_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Load recent turns for a session."""
        transcript = self.sessions_dir / session_id / "transcript.jsonl"
        if not transcript.exists():
            return []
        try:
            lines = transcript.read_text(encoding="utf-8").splitlines()
            if limit:
                lines = lines[-limit:]
            return [json.loads(line) for line in lines if line.strip()]
        except Exception as exc:
            logger.warning("Failed to read session history: %s", exc)
            return []
            
    def _save_session(self, session: Session):
        """Save session to disk."""
        path = self.sessions_dir / f"{session.id}.json"
        path.write_text(json.dumps(session.to_dict(), indent=2))
        
    def _load_sessions(self):
        """Load sessions from disk."""
        for path in self.sessions_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text())
                session = Session.from_dict(data)
                # Skip if already expired and prune? No, perform explicit prune later
                self.sessions[session.id] = session
            except Exception as e:
                logger.error(f"Failed to load session {path}: {e}")


# Global instance
_session_manager: Optional[SessionManager] = None

def get_session_manager() -> SessionManager:
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager
