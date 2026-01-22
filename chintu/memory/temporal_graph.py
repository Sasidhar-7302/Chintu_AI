"""Temporal Knowledge Graph - Time-aware memory storage.

Stores facts, conversations, and events with timestamps.
Enables queries like "what did I say last week about X".
Uses SQLite for persistence (no Docker needed).
"""

import os
import sqlite3
import json
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class TemporalFact:
    """A fact stored with temporal information."""
    id: int
    subject: str
    predicate: str
    object_value: str
    timestamp: datetime
    source: str  # conversation, user_stated, inferred
    confidence: float = 1.0
    valid_until: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object_value,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "confidence": self.confidence
        }


@dataclass
class Conversation:
    """A logged conversation with timestamp."""
    id: int
    user_input: str
    assistant_response: str
    timestamp: datetime
    topics: List[str]
    sentiment: str = "neutral"


class TemporalGraph:
    """SQLite-based temporal knowledge graph."""
    
    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = Path.home() / ".chintu" / "temporal_memory.db"
        
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._init_db()
        logger.info(f"Temporal graph initialized at {self.db_path}")
    
    def _init_db(self):
        """Initialize database schema."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Facts table - stores knowledge triples
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT NOT NULL,
                predicate TEXT NOT NULL,
                object_value TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                source TEXT DEFAULT 'conversation',
                confidence REAL DEFAULT 1.0,
                valid_until DATETIME,
                UNIQUE(subject, predicate, object_value)
            )
        """)
        
        # Conversations table - stores chat history
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_input TEXT NOT NULL,
                assistant_response TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                topics TEXT,
                sentiment TEXT DEFAULT 'neutral'
            )
        """)
        
        # Events table - stores time-based events
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                description TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                metadata TEXT
            )
        """)
        
        # Create indexes for fast temporal queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_facts_timestamp ON facts(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_facts_subject ON facts(subject)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_conv_timestamp ON conversations(timestamp)")
        
        conn.commit()
        conn.close()
    
    # =========================================================================
    # FACT MANAGEMENT
    # =========================================================================
    
    def add_fact(self, subject: str, predicate: str, object_value: str,
                 source: str = "conversation", confidence: float = 1.0,
                 valid_until: datetime = None) -> int:
        """Add a fact to the knowledge graph.
        
        Examples:
            add_fact("user", "likes", "coffee")
            add_fact("user", "birthday", "May 15")
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO facts 
                (subject, predicate, object_value, source, confidence, valid_until)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (subject.lower(), predicate.lower(), object_value, 
                  source, confidence, valid_until))
            
            fact_id = cursor.lastrowid
            conn.commit()
            logger.debug(f"Added fact: {subject} {predicate} {object_value}")
            return fact_id
            
        except Exception as e:
            logger.error(f"Failed to add fact: {e}")
            return -1
        finally:
            conn.close()
    
    def get_facts_about(self, subject: str, 
                        since: datetime = None) -> List[TemporalFact]:
        """Get all facts about a subject, optionally filtered by time."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        query = "SELECT * FROM facts WHERE subject LIKE ?"
        params = [f"%{subject.lower()}%"]
        
        if since:
            query += " AND timestamp >= ?"
            params.append(since)
        
        query += " ORDER BY timestamp DESC"
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        return [self._row_to_fact(row) for row in rows]
    
    def search_facts(self, query: str, 
                     time_range: Tuple[datetime, datetime] = None) -> List[TemporalFact]:
        """Search facts by keyword with optional time range."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        sql = """
            SELECT * FROM facts 
            WHERE subject LIKE ? OR predicate LIKE ? OR object_value LIKE ?
        """
        params = [f"%{query}%", f"%{query}%", f"%{query}%"]
        
        if time_range:
            sql += " AND timestamp BETWEEN ? AND ?"
            params.extend(time_range)
        
        sql += " ORDER BY timestamp DESC LIMIT 20"
        
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        conn.close()
        
        return [self._row_to_fact(row) for row in rows]
    
    def get_facts_from_period(self, period: str) -> List[TemporalFact]:
        """Get facts from a named time period.
        
        Args:
            period: "today", "yesterday", "this_week", "last_week", "this_month"
        """
        now = datetime.now()
        
        if period == "today":
            since = now.replace(hour=0, minute=0, second=0)
        elif period == "yesterday":
            since = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0)
            until = now.replace(hour=0, minute=0, second=0)
        elif period == "this_week":
            since = now - timedelta(days=now.weekday())
        elif period == "last_week":
            since = now - timedelta(days=now.weekday() + 7)
            until = now - timedelta(days=now.weekday())
        elif period == "this_month":
            since = now.replace(day=1, hour=0, minute=0, second=0)
        else:
            since = now - timedelta(days=7)  # Default: last 7 days
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if period in ["yesterday", "last_week"]:
            cursor.execute(
                "SELECT * FROM facts WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp DESC",
                (since, until)
            )
        else:
            cursor.execute(
                "SELECT * FROM facts WHERE timestamp >= ? ORDER BY timestamp DESC",
                (since,)
            )
        
        rows = cursor.fetchall()
        conn.close()
        
        return [self._row_to_fact(row) for row in rows]
    
    # =========================================================================
    # CONVERSATION HISTORY
    # =========================================================================
    
    def log_conversation(self, user_input: str, assistant_response: str,
                         topics: List[str] = None, sentiment: str = "neutral") -> int:
        """Log a conversation exchange."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO conversations (user_input, assistant_response, topics, sentiment)
            VALUES (?, ?, ?, ?)
        """, (user_input, assistant_response, json.dumps(topics or []), sentiment))
        
        conv_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return conv_id
    
    def get_conversations(self, since: datetime = None, 
                          limit: int = 10) -> List[Conversation]:
        """Get recent conversations."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if since:
            cursor.execute("""
                SELECT * FROM conversations 
                WHERE timestamp >= ?
                ORDER BY timestamp DESC LIMIT ?
            """, (since, limit))
        else:
            cursor.execute("""
                SELECT * FROM conversations 
                ORDER BY timestamp DESC LIMIT ?
            """, (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [self._row_to_conversation(row) for row in rows]
    
    def search_conversations(self, query: str, 
                             time_range: Tuple[datetime, datetime] = None) -> List[Conversation]:
        """Search conversation history."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        sql = """
            SELECT * FROM conversations 
            WHERE user_input LIKE ? OR assistant_response LIKE ?
        """
        params = [f"%{query}%", f"%{query}%"]
        
        if time_range:
            sql += " AND timestamp BETWEEN ? AND ?"
            params.extend(time_range)
        
        sql += " ORDER BY timestamp DESC LIMIT 20"
        
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        conn.close()
        
        return [self._row_to_conversation(row) for row in rows]
    
    # =========================================================================
    # TEMPORAL QUERIES
    # =========================================================================
    
    def when_did_i_mention(self, topic: str) -> Optional[datetime]:
        """Find when a topic was last mentioned."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT timestamp FROM conversations 
            WHERE user_input LIKE ? OR topics LIKE ?
            ORDER BY timestamp DESC LIMIT 1
        """, (f"%{topic}%", f"%{topic}%"))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return datetime.fromisoformat(row[0])
        return None
    
    def what_did_i_say_about(self, topic: str, 
                              period: str = None) -> List[str]:
        """Recall what user said about a topic."""
        if period:
            # Get time range from period
            now = datetime.now()
            if period == "yesterday":
                since = (now - timedelta(days=1)).replace(hour=0, minute=0)
                until = now.replace(hour=0, minute=0)
            elif period == "last_week":
                since = now - timedelta(days=7)
                until = now
            else:
                since = now - timedelta(days=30)
                until = now
        else:
            since = datetime.now() - timedelta(days=365)
            until = datetime.now()
        
        convs = self.search_conversations(topic, (since, until))
        return [c.user_input for c in convs]
    
    def get_timeline(self, days: int = 7) -> Dict[str, List[str]]:
        """Get a timeline of topics discussed over recent days."""
        since = datetime.now() - timedelta(days=days)
        convs = self.get_conversations(since=since, limit=100)
        
        timeline = {}
        for conv in convs:
            date_key = conv.timestamp.strftime("%Y-%m-%d")
            if date_key not in timeline:
                timeline[date_key] = []
            
            # Extract snippet
            snippet = conv.user_input[:50] + "..." if len(conv.user_input) > 50 else conv.user_input
            timeline[date_key].append(snippet)
        
        return timeline
    
    # =========================================================================
    # HELPERS
    # =========================================================================
    
    def _row_to_fact(self, row: tuple) -> TemporalFact:
        """Convert database row to TemporalFact."""
        return TemporalFact(
            id=row[0],
            subject=row[1],
            predicate=row[2],
            object_value=row[3],
            timestamp=datetime.fromisoformat(row[4]) if row[4] else datetime.now(),
            source=row[5],
            confidence=row[6] or 1.0,
            valid_until=datetime.fromisoformat(row[7]) if row[7] else None
        )
    
    def _row_to_conversation(self, row: tuple) -> Conversation:
        """Convert database row to Conversation."""
        return Conversation(
            id=row[0],
            user_input=row[1],
            assistant_response=row[2] or "",
            timestamp=datetime.fromisoformat(row[3]) if row[3] else datetime.now(),
            topics=json.loads(row[4]) if row[4] else [],
            sentiment=row[5] or "neutral"
        )
    
    def get_stats(self) -> Dict[str, int]:
        """Get database statistics."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM facts")
        fact_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM conversations")
        conv_count = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            "facts": fact_count,
            "conversations": conv_count
        }


# Global instance
_graph: Optional[TemporalGraph] = None


def get_temporal_graph() -> TemporalGraph:
    """Get the global TemporalGraph instance."""
    global _graph
    if _graph is None:
        _graph = TemporalGraph()
    return _graph
