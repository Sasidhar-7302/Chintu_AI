"""
Task Management System for Chintu Assistant.
Supports reminders, deferred actions, and pending confirmations.
"""

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass, asdict, field
from typing import Optional, List, Dict, Any, Callable
from pathlib import Path
from datetime import datetime, timedelta
from enum import Enum
import time

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """Status of a task."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskType(Enum):
    """Type of task."""
    REMINDER = "reminder"           # Time-based notification
    DEFERRED_ACTION = "deferred"    # Action to execute later
    CONFIRMATION = "confirmation"   # Awaiting user confirmation
    SCHEDULED = "scheduled"         # Recurring or scheduled task


@dataclass
class Task:
    """A task or reminder."""
    id: Optional[int] = None
    task_type: str = "reminder"
    content: str = ""
    trigger_time: Optional[str] = None  # ISO format datetime
    status: str = "pending"
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: Optional[str] = None
    
    def is_due(self) -> bool:
        """Check if this task is due to execute."""
        if self.status != TaskStatus.PENDING.value:
            return False
        if not self.trigger_time:
            return False
        return datetime.fromisoformat(self.trigger_time) <= datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_row(cls, row: tuple) -> "Task":
        """Create from SQLite row."""
        return cls(
            id=row[0],
            task_type=row[1],
            content=row[2],
            trigger_time=row[3],
            status=row[4],
            metadata=json.loads(row[5]) if row[5] else {},
            created_at=row[6],
            completed_at=row[7]
        )


class TaskManager:
    """
    Manages tasks, reminders, and deferred actions.
    Runs a background thread to check for due tasks.
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or Path.home() / ".chintu" / "tasks.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()
        
        # Callbacks
        self._on_reminder: Optional[Callable[[Task], None]] = None
        self._on_task_due: Optional[Callable[[Task], None]] = None
        
        # Background thread for checking due tasks
        self._running = False
        self._stop_event = threading.Event()  # For interruptible sleep
        self._check_thread: Optional[threading.Thread] = None
        
        logger.info(f"TaskManager initialized: {self.db_path}")
    
    def _get_conn(self) -> sqlite3.Connection:
        """Get or create database connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        return self._conn
    
    def _init_db(self) -> None:
        """Initialize database schema."""
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_type TEXT NOT NULL,
                content TEXT NOT NULL,
                trigger_time TEXT,
                status TEXT DEFAULT 'pending',
                metadata TEXT,
                created_at TEXT NOT NULL,
                completed_at TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON tasks(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trigger_time ON tasks(trigger_time)")
        conn.commit()
    
    # =========================================================================
    # REMINDER OPERATIONS
    # =========================================================================
    
    def add_reminder(
        self, 
        content: str, 
        trigger_time: datetime,
        metadata: Dict = None
    ) -> Task:
        """Add a reminder to be triggered at a specific time."""
        task = Task(
            task_type=TaskType.REMINDER.value,
            content=content,
            trigger_time=trigger_time.isoformat(),
            metadata=metadata or {}
        )
        task.id = self._save_task(task)
        logger.info(f"Added reminder: {content} at {trigger_time}")
        return task
    
    def add_reminder_in(
        self, 
        content: str, 
        minutes: int = 0,
        hours: int = 0,
        seconds: int = 0
    ) -> Task:
        """Add a reminder to be triggered after a delay."""
        trigger_time = datetime.now() + timedelta(
            hours=hours, 
            minutes=minutes, 
            seconds=seconds
        )
        return self.add_reminder(content, trigger_time)
    
    # =========================================================================
    # DEFERRED ACTION OPERATIONS
    # =========================================================================
    
    def add_deferred_action(
        self,
        content: str,
        action_data: Dict[str, Any],
        trigger_time: datetime
    ) -> Task:
        """Add an action to be executed later."""
        task = Task(
            task_type=TaskType.DEFERRED_ACTION.value,
            content=content,
            trigger_time=trigger_time.isoformat(),
            metadata={"action": action_data}
        )
        task.id = self._save_task(task)
        logger.info(f"Added deferred action: {content}")
        return task
    
    # =========================================================================
    # TASK QUERIES
    # =========================================================================
    
    def get_pending_tasks(self) -> List[Task]:
        """Get all pending tasks."""
        conn = self._get_conn()
        cursor = conn.execute(
            """
            SELECT id, task_type, content, trigger_time, status, 
                   metadata, created_at, completed_at
            FROM tasks 
            WHERE status = ?
            ORDER BY trigger_time ASC
            """,
            (TaskStatus.PENDING.value,)
        )
        return [Task.from_row(row) for row in cursor.fetchall()]
    
    def get_due_tasks(self) -> List[Task]:
        """Get all tasks that are due to execute."""
        now = datetime.now().isoformat()
        conn = self._get_conn()
        cursor = conn.execute(
            """
            SELECT id, task_type, content, trigger_time, status,
                   metadata, created_at, completed_at
            FROM tasks 
            WHERE status = ? AND trigger_time <= ?
            ORDER BY trigger_time ASC
            """,
            (TaskStatus.PENDING.value, now)
        )
        return [Task.from_row(row) for row in cursor.fetchall()]
    
    def get_task(self, task_id: int) -> Optional[Task]:
        """Get a specific task by ID."""
        conn = self._get_conn()
        cursor = conn.execute(
            """
            SELECT id, task_type, content, trigger_time, status,
                   metadata, created_at, completed_at
            FROM tasks WHERE id = ?
            """,
            (task_id,)
        )
        row = cursor.fetchone()
        return Task.from_row(row) if row else None
    
    def get_upcoming_tasks(self, hours: int = 24) -> List[Task]:
        """Get tasks due within the next N hours."""
        cutoff = (datetime.now() + timedelta(hours=hours)).isoformat()
        conn = self._get_conn()
        cursor = conn.execute(
            """
            SELECT id, task_type, content, trigger_time, status,
                   metadata, created_at, completed_at
            FROM tasks 
            WHERE status = ? AND trigger_time <= ?
            ORDER BY trigger_time ASC
            """,
            (TaskStatus.PENDING.value, cutoff)
        )
        return [Task.from_row(row) for row in cursor.fetchall()]
    
    # =========================================================================
    # TASK MANAGEMENT
    # =========================================================================
    
    def complete_task(self, task_id: int) -> bool:
        """Mark a task as completed."""
        conn = self._get_conn()
        cursor = conn.execute(
            """
            UPDATE tasks 
            SET status = ?, completed_at = ?
            WHERE id = ?
            """,
            (TaskStatus.COMPLETED.value, datetime.now().isoformat(), task_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    
    def cancel_task(self, task_id: int) -> bool:
        """Cancel a task."""
        conn = self._get_conn()
        cursor = conn.execute(
            "UPDATE tasks SET status = ? WHERE id = ?",
            (TaskStatus.CANCELLED.value, task_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    
    def delete_task(self, task_id: int) -> bool:
        """Delete a task permanently."""
        conn = self._get_conn()
        cursor = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
        return cursor.rowcount > 0
    
    def clear_completed(self) -> int:
        """Clear all completed tasks."""
        conn = self._get_conn()
        cursor = conn.execute(
            "DELETE FROM tasks WHERE status IN (?, ?)",
            (TaskStatus.COMPLETED.value, TaskStatus.CANCELLED.value)
        )
        conn.commit()
        return cursor.rowcount
    
    # =========================================================================
    # INTERNAL OPERATIONS
    # =========================================================================
    
    def _save_task(self, task: Task) -> int:
        """Save a task to the database."""
        conn = self._get_conn()
        cursor = conn.execute(
            """
            INSERT INTO tasks (task_type, content, trigger_time, status, 
                             metadata, created_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task.task_type,
                task.content,
                task.trigger_time,
                task.status,
                json.dumps(task.metadata) if task.metadata else None,
                task.created_at,
                task.completed_at
            )
        )
        conn.commit()
        return cursor.lastrowid
    
    # =========================================================================
    # BACKGROUND TASK CHECKING
    # =========================================================================
    
    def set_reminder_callback(self, callback: Callable[[Task], None]) -> None:
        """Set callback for when a reminder is due."""
        self._on_reminder = callback
    
    def set_task_callback(self, callback: Callable[[Task], None]) -> None:
        """Set callback for when a deferred task is due."""
        self._on_task_due = callback
    
    def start(self) -> None:
        """Start the background task checker."""
        if self._running:
            return
        
        self._running = True
        self._check_thread = threading.Thread(target=self._check_loop, daemon=True)
        self._check_thread.start()
        logger.info("TaskManager background checker started")
    
    def stop(self) -> None:
        """Stop the background task checker."""
        self._running = False
        self._stop_event.set()  # Signal thread to wake up
        if self._check_thread:
            self._check_thread.join(timeout=2)
        logger.info("TaskManager background checker stopped")
    
    def _check_loop(self) -> None:
        """Background loop to check for due tasks."""
        while self._running:
            try:
                due_tasks = self.get_due_tasks()
                for task in due_tasks:
                    self._handle_due_task(task)
            except Exception as e:
                logger.error(f"Task check error: {e}")
            
            self._stop_event.wait(10)  # Interruptible sleep (10 seconds)
    
    def _handle_due_task(self, task: Task) -> None:
        """Handle a task that is due."""
        try:
            if task.task_type == TaskType.REMINDER.value:
                if self._on_reminder:
                    self._on_reminder(task)
                logger.info(f"Reminder triggered: {task.content}")
            
            elif task.task_type == TaskType.DEFERRED_ACTION.value:
                if self._on_task_due:
                    self._on_task_due(task)
                logger.info(f"Deferred action triggered: {task.content}")
            
            self.complete_task(task.id)
        except Exception as e:
            logger.error(f"Failed to handle task {task.id}: {e}")
    
    def get_stats(self) -> Dict[str, int]:
        """Get task statistics."""
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT status, COUNT(*) FROM tasks GROUP BY status"
        )
        return {row[0]: row[1] for row in cursor.fetchall()}
    
    def close(self) -> None:
        """Close the task manager."""
        self.stop()
        if self._conn:
            self._conn.close()
            self._conn = None


# Global instance
_task_manager: Optional[TaskManager] = None


def get_task_manager() -> TaskManager:
    """Get or create the global task manager."""
    global _task_manager
    if _task_manager is None:
        _task_manager = TaskManager()
    return _task_manager
