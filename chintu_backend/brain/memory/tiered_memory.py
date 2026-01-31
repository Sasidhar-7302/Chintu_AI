"""
Tiered Memory System for Chintu Assistant.
Separates memory into: Facts (about user), History (conversations), Notes (tasks).
"""

import json
import logging
import sqlite3
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Any
from pathlib import Path
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)


class MemoryType(Enum):
    """Types of memory for tiered storage."""
    FACT = "fact"           # Facts about the user (persistent)
    HISTORY = "history"     # Conversation history (time-limited)
    NOTE = "note"           # User notes and tasks (persistent)
    PREFERENCE = "pref"     # Learned preferences (persistent)


@dataclass
class MemoryItem:
    """A single memory item."""
    id: Optional[int] = None
    memory_type: str = "fact"
    content: str = ""
    metadata: Dict[str, Any] = None
    created_at: str = None
    expires_at: Optional[str] = None
    importance: float = 0.5  # 0-1 scale
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_row(cls, row: tuple) -> "MemoryItem":
        """Create from SQLite row."""
        return cls(
            id=row[0],
            memory_type=row[1],
            content=row[2],
            metadata=json.loads(row[3]) if row[3] else {},
            created_at=row[4],
            expires_at=row[5],
            importance=row[6] or 0.5
        )


class TieredMemoryStore:
    """
    SQLite-based tiered memory storage.
    
    Memory tiers:
    - FACT: Persistent facts about the user (never auto-deleted)
    - HISTORY: Conversation history (auto-deleted after N days)
    - NOTE: User notes and tasks (persistent until deleted)
    - PREFERENCE: Learned preferences (persistent)
    
    ChromaDB is used separately for semantic search.
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or Path.home() / ".chintu" / "memory.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()
        logger.info(f"TieredMemoryStore initialized: {self.db_path}")
    
    def _get_conn(self) -> sqlite3.Connection:
        """Get or create database connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        return self._conn
    
    def _init_db(self) -> None:
        """Initialize database schema."""
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_type TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT,
                created_at TEXT NOT NULL,
                expires_at TEXT,
                importance REAL DEFAULT 0.5
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memory_type ON memories(memory_type)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_expires_at ON memories(expires_at)
        """)
        conn.commit()
    
    # =========================================================================
    # FACT OPERATIONS (About the user - persistent)
    # =========================================================================
    
    def add_fact(self, content: str, metadata: Dict = None, importance: float = 0.5) -> int:
        """
        Store a fact about the user.
        Facts persist forever and are never auto-deleted.
        """
        return self._add_memory(MemoryType.FACT, content, metadata, importance=importance)
    
    def get_facts(self, limit: int = 20) -> List[MemoryItem]:
        """Get all facts about the user."""
        return self._get_by_type(MemoryType.FACT, limit)
    
    def search_facts(self, query: str) -> List[MemoryItem]:
        """Search facts by keyword."""
        return self._search(MemoryType.FACT, query)
    
    def delete_fact(self, fact_id: int) -> bool:
        """Delete a specific fact by ID."""
        return self._delete(fact_id)
    
    # =========================================================================
    # HISTORY OPERATIONS (Conversations - time-limited)
    # =========================================================================
    
    def add_history(
        self, 
        content: str, 
        role: str = "user",
        metadata: Dict = None,
        retention_days: int = 30
    ) -> int:
        """
        Store conversation history.
        History auto-expires after retention_days.
        """
        meta = metadata or {}
        meta["role"] = role
        
        expires_at = datetime.now() + timedelta(days=retention_days)
        return self._add_memory(
            MemoryType.HISTORY, content, meta, 
            expires_at=expires_at.isoformat()
        )
    
    def get_recent_history(self, limit: int = 20) -> List[MemoryItem]:
        """Get recent conversation history."""
        return self._get_by_type(MemoryType.HISTORY, limit)
    
    def get_history_context(self, limit: int = 5) -> str:
        """Get formatted history for LLM context."""
        history = self.get_recent_history(limit)
        if not history:
            return ""
        
        lines = []
        for item in reversed(history):  # Oldest first
            role = item.metadata.get("role", "user")
            lines.append(f"[{role.capitalize()}]: {item.content}")
        
        return "\n".join(lines)
    
    # =========================================================================
    # NOTE OPERATIONS (User notes - persistent)
    # =========================================================================
    
    def add_note(self, content: str, metadata: Dict = None) -> int:
        """
        Store a user note.
        Notes persist forever until explicitly deleted.
        """
        return self._add_memory(MemoryType.NOTE, content, metadata, importance=0.8)
    
    def get_notes(self, limit: int = 50) -> List[MemoryItem]:
        """Get all user notes."""
        return self._get_by_type(MemoryType.NOTE, limit)
    
    def delete_note(self, note_id: int) -> bool:
        """Delete a specific note."""
        return self._delete(note_id)
    
    def clear_notes(self) -> int:
        """Clear all notes. Returns count deleted."""
        return self._clear_type(MemoryType.NOTE)
    
    def search_notes(self, query: str) -> List[MemoryItem]:
        """Search notes by keyword."""
        return self._search(MemoryType.NOTE, query)
    
    # =========================================================================
    # PREFERENCE OPERATIONS (Learned preferences)
    # =========================================================================
    
    def add_preference(self, key: str, value: Any) -> int:
        """Store a learned preference."""
        content = json.dumps({"key": key, "value": value})
        # Delete existing with same key
        self._delete_by_content_key(MemoryType.PREFERENCE, key)
        return self._add_memory(MemoryType.PREFERENCE, content, {"key": key})
    
    def get_preference(self, key: str) -> Optional[Any]:
        """Get a learned preference."""
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT content FROM memories WHERE memory_type = ? AND metadata LIKE ?",
            (MemoryType.PREFERENCE.value, f'%"{key}"%')
        )
        row = cursor.fetchone()
        if row:
            data = json.loads(row[0])
            return data.get("value")
        return None
    
    # =========================================================================
    # INTERNAL OPERATIONS
    # =========================================================================
    
    def _add_memory(
        self, 
        memory_type: MemoryType, 
        content: str, 
        metadata: Dict = None,
        expires_at: str = None,
        importance: float = 0.5
    ) -> int:
        """Add a memory item."""
        conn = self._get_conn()
        cursor = conn.execute(
            """
            INSERT INTO memories (memory_type, content, metadata, created_at, expires_at, importance)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                memory_type.value,
                content,
                json.dumps(metadata) if metadata else None,
                datetime.now().isoformat(),
                expires_at,
                importance
            )
        )
        conn.commit()
        logger.debug(f"Added {memory_type.value} memory: {content[:50]}...")
        return cursor.lastrowid
    
    def _get_by_type(self, memory_type: MemoryType, limit: int = 20) -> List[MemoryItem]:
        """Get memories by type."""
        conn = self._get_conn()
        cursor = conn.execute(
            """
            SELECT id, memory_type, content, metadata, created_at, expires_at, importance
            FROM memories 
            WHERE memory_type = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (memory_type.value, limit)
        )
        return [MemoryItem.from_row(row) for row in cursor.fetchall()]
    
    def _search(self, memory_type: MemoryType, query: str) -> List[MemoryItem]:
        """Search memories by content."""
        conn = self._get_conn()
        cursor = conn.execute(
            """
            SELECT id, memory_type, content, metadata, created_at, expires_at, importance
            FROM memories 
            WHERE memory_type = ? AND content LIKE ?
            ORDER BY importance DESC, created_at DESC
            LIMIT 20
            """,
            (memory_type.value, f"%{query}%")
        )
        return [MemoryItem.from_row(row) for row in cursor.fetchall()]
    
    def _delete(self, memory_id: int) -> bool:
        """Delete a memory by ID."""
        conn = self._get_conn()
        cursor = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        conn.commit()
        return cursor.rowcount > 0
    
    def _delete_by_content_key(self, memory_type: MemoryType, key: str) -> None:
        """Delete memories containing a specific key."""
        conn = self._get_conn()
        conn.execute(
            "DELETE FROM memories WHERE memory_type = ? AND metadata LIKE ?",
            (memory_type.value, f'%"{key}"%')
        )
        conn.commit()
    
    def _clear_type(self, memory_type: MemoryType) -> int:
        """Clear all memories of a type."""
        conn = self._get_conn()
        cursor = conn.execute(
            "DELETE FROM memories WHERE memory_type = ?",
            (memory_type.value,)
        )
        conn.commit()
        return cursor.rowcount
    
    def cleanup_expired(self) -> int:
        """Remove expired memories. Returns count deleted."""
        conn = self._get_conn()
        now = datetime.now().isoformat()
        cursor = conn.execute(
            "DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at < ?",
            (now,)
        )
        conn.commit()
        count = cursor.rowcount
        if count > 0:
            logger.info(f"Cleaned up {count} expired memories")
        return count
    
    def get_stats(self) -> Dict[str, int]:
        """Get memory statistics."""
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT memory_type, COUNT(*) FROM memories GROUP BY memory_type"
        )
        return {row[0]: row[1] for row in cursor.fetchall()}
    
    def close(self) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None


# Global instance
_memory_store: Optional[TieredMemoryStore] = None


def get_memory_store() -> TieredMemoryStore:
    """Get or create the global memory store."""
    global _memory_store
    if _memory_store is None:
        _memory_store = TieredMemoryStore()
    return _memory_store
