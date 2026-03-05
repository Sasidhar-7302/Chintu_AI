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
    RETRYING = "retrying"
    DEAD_LETTER = "dead_letter"


class TaskType(Enum):
    """Type of task."""
    REMINDER = "reminder"           # Time-based notification
    DEFERRED_ACTION = "deferred"    # Action to execute later
    CONFIRMATION = "confirmation"   # Awaiting user confirmation
    SCHEDULED = "scheduled"         # Recurring or scheduled task
    TODO = "todo"                   # Task list item


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
    # Reliability / retry metadata (added in v5.1)
    attempts: int = 0
    last_attempt_at: Optional[str] = None
    last_error: Optional[str] = None
    max_attempts: int = 3
    backoff_until: Optional[str] = None
    dead_letter: bool = False
    
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
        # Backwards-compatible: older DBs may not have all columns yet.
        # Column order (new schema):
        # 0 id, 1 task_type, 2 content, 3 trigger_time, 4 status,
        # 5 metadata, 6 created_at, 7 completed_at,
        # 8 attempt_count, 9 last_attempt_at, 10 last_error,
        # 11 max_attempts, 12 backoff_until, 13 dead_letter
        base = {
            "id": row[0],
            "task_type": row[1],
            "content": row[2],
            "trigger_time": row[3],
            "status": row[4],
            "metadata": json.loads(row[5]) if row[5] else {},
            "created_at": row[6],
            "completed_at": row[7],
        }
        # Optional reliability fields
        if len(row) > 8:
            base["attempts"] = int(row[8] or 0)
        if len(row) > 9:
            base["last_attempt_at"] = row[9]
        if len(row) > 10:
            base["last_error"] = row[10]
        if len(row) > 11:
            try:
                base["max_attempts"] = int(row[11]) if row[11] is not None else 3
            except Exception:
                base["max_attempts"] = 3
        if len(row) > 12:
            base["backoff_until"] = row[12]
        if len(row) > 13:
            base["dead_letter"] = bool(row[13])
        return cls(**base)


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
                completed_at TEXT,
                -- Reliability columns (added in v5.1)
                attempt_count INTEGER DEFAULT 0,
                last_attempt_at TEXT,
                last_error TEXT,
                max_attempts INTEGER,
                backoff_until TEXT,
                dead_letter INTEGER DEFAULT 0
            )
        """)
        # Backwards-compatible migrations for existing installs.
        try:
            cursor = conn.execute("PRAGMA table_info(tasks)")
            existing_cols = {row[1] for row in cursor.fetchall()}
            migrations = [
                ("attempt_count", "ALTER TABLE tasks ADD COLUMN attempt_count INTEGER DEFAULT 0"),
                ("last_attempt_at", "ALTER TABLE tasks ADD COLUMN last_attempt_at TEXT"),
                ("last_error", "ALTER TABLE tasks ADD COLUMN last_error TEXT"),
                ("max_attempts", "ALTER TABLE tasks ADD COLUMN max_attempts INTEGER"),
                ("backoff_until", "ALTER TABLE tasks ADD COLUMN backoff_until TEXT"),
                ("dead_letter", "ALTER TABLE tasks ADD COLUMN dead_letter INTEGER DEFAULT 0"),
            ]
            for col_name, ddl in migrations:
                if col_name not in existing_cols:
                    try:
                        conn.execute(ddl)
                    except Exception:
                        # Best-effort migration; continue even if a column already exists
                        # in a slightly different form.
                        pass
            conn.commit()
        except Exception:
            # Never fail startup because of migration issues.
            conn.commit()
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
    # TODO TASKS
    # =========================================================================

    def add_task(self, content: str, metadata: Dict[str, Any] | None = None) -> Task:
        """Add a simple todo task (no trigger time)."""
        task = Task(
            task_type=TaskType.TODO.value,
            content=content,
            trigger_time=None,
            metadata=metadata or {},
        )
        task.id = self._save_task(task)
        logger.info("Added task: %s", content)
        return task

    def list_tasks(self, limit: int = 50) -> List[Task]:
        """List pending todo tasks."""
        conn = self._get_conn()
        cursor = conn.execute(
            """
            SELECT id, task_type, content, trigger_time, status,
                   metadata, created_at, completed_at
            FROM tasks
            WHERE status = ? AND task_type = ?
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (TaskStatus.PENDING.value, TaskType.TODO.value, int(limit)),
        )
        return [Task.from_row(row) for row in cursor.fetchall()]

    def complete_task(self, task_id: int) -> bool:
        """Mark a todo task as completed."""
        conn = self._get_conn()
        now = datetime.now().isoformat()
        cur = conn.execute(
            "UPDATE tasks SET status = ?, completed_at = ? WHERE id = ?",
            (TaskStatus.COMPLETED.value, now, task_id),
        )
        conn.commit()
        return cur.rowcount > 0
    
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
                   metadata, created_at, completed_at,
                   attempt_count, last_attempt_at, last_error,
                   max_attempts, backoff_until, dead_letter
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
                   metadata, created_at, completed_at,
                   attempt_count, last_attempt_at, last_error,
                   max_attempts, backoff_until, dead_letter
            FROM tasks 
            WHERE status IN (?, ?) 
              AND trigger_time <= ?
              AND (backoff_until IS NULL OR backoff_until <= ?)
            ORDER BY trigger_time ASC
            """,
            (
                TaskStatus.PENDING.value,
                TaskStatus.RETRYING.value,
                now,
                now,
            )
        )
        return [Task.from_row(row) for row in cursor.fetchall()]
    
    def get_task(self, task_id: int) -> Optional[Task]:
        """Get a specific task by ID."""
        conn = self._get_conn()
        cursor = conn.execute(
            """
            SELECT id, task_type, content, trigger_time, status,
                   metadata, created_at, completed_at,
                   attempt_count, last_attempt_at, last_error,
                   max_attempts, backoff_until, dead_letter
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
                   metadata, created_at, completed_at,
                   attempt_count, last_attempt_at, last_error,
                   max_attempts, backoff_until, dead_letter
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
            INSERT INTO tasks (
                task_type,
                content,
                trigger_time,
                status, 
                metadata,
                created_at,
                completed_at,
                attempt_count,
                last_attempt_at,
                last_error,
                max_attempts,
                backoff_until,
                dead_letter
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task.task_type,
                task.content,
                task.trigger_time,
                task.status,
                json.dumps(task.metadata) if task.metadata else None,
                task.created_at,
                task.completed_at,
                int(task.attempts or 0),
                task.last_attempt_at,
                task.last_error,
                int(task.max_attempts or 0) or 3,
                task.backoff_until,
                1 if task.dead_letter else 0,
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
        from chintu_backend.core.events import get_event_bus, Event, EventType  # Local import to avoid cycles
        conn = self._get_conn()
        now_iso = datetime.now().isoformat()

        # Mark as running + increment attempts (best-effort).
        try:
            current_attempts = int(task.attempts or 0)
            max_attempts = int(task.max_attempts or 0) or 3
            conn.execute(
                """
                UPDATE tasks
                SET status = ?, attempt_count = ?, last_attempt_at = ?, max_attempts = COALESCE(max_attempts, ?),
                    backoff_until = NULL
                WHERE id = ?
                """,
                (
                    TaskStatus.RUNNING.value,
                    current_attempts + 1,
                    now_iso,
                    max_attempts,
                    task.id,
                ),
            )
            conn.commit()
            task.status = TaskStatus.RUNNING.value
            task.attempts = current_attempts + 1
            task.last_attempt_at = now_iso
            task.max_attempts = max_attempts
        except Exception as db_err:
            logger.warning(f"Failed to update task {task.id} as RUNNING: {db_err}")

        # Emit TASK_STARTED event (best-effort, non-blocking).
        try:
            bus = get_event_bus()
            bus.publish_sync(
                Event(
                    type=EventType.TASK_STARTED,
                    source="task_manager",
                    data={
                        "task_id": task.id,
                        "task_type": task.task_type,
                        "status": task.status,
                        "content": task.content,
                        "attempts": task.attempts,
                        "trigger_time": task.trigger_time,
                    },
                )
            )
        except Exception:
            pass

        try:
            if task.task_type == TaskType.REMINDER.value:
                if self._on_reminder:
                    self._on_reminder(task)
                logger.info(f"Reminder triggered: {task.content}")
            
            elif task.task_type == TaskType.DEFERRED_ACTION.value:
                if self._on_task_due:
                    self._on_task_due(task)
                logger.info(f"Deferred action triggered: {task.content}")
            
            # On success, mark as completed.
            self.complete_task(task.id)

            # Emit TASK_COMPLETED event.
            try:
                bus = get_event_bus()
                bus.publish_sync(
                    Event(
                        type=EventType.TASK_COMPLETED,
                        source="task_manager",
                        data={
                            "task_id": task.id,
                            "task_type": task.task_type,
                            "status": TaskStatus.COMPLETED.value,
                            "content": task.content,
                            "attempts": task.attempts,
                        },
                    )
                )
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Failed to handle task {task.id}: {e}")

            # On failure, record error and schedule retry / dead-letter.
            try:
                # Simple exponential backoff in seconds: 30, 120, 300...
                base_backoff = 30
                backoff_factor = min(task.attempts, 5)
                backoff_seconds = base_backoff * backoff_factor if backoff_factor > 0 else base_backoff
                backoff_until = datetime.now() + timedelta(seconds=backoff_seconds)

                next_status = TaskStatus.RETRYING.value
                dead_letter = 0
                if task.attempts >= task.max_attempts:
                    next_status = TaskStatus.DEAD_LETTER.value
                    dead_letter = 1

                conn.execute(
                    """
                    UPDATE tasks
                    SET status = ?, last_error = ?, backoff_until = ?, dead_letter = ?
                    WHERE id = ?
                    """,
                    (
                        next_status,
                        str(e),
                        backoff_until.isoformat(),
                        dead_letter,
                        task.id,
                    ),
                )
                conn.commit()

                task.status = next_status
                task.last_error = str(e)
                task.backoff_until = backoff_until.isoformat()
                task.dead_letter = bool(dead_letter)

                # Emit TASK_FAILED event with retry/dead-letter info.
                try:
                    bus = get_event_bus()
                    bus.publish_sync(
                        Event(
                            type=EventType.TASK_FAILED,
                            source="task_manager",
                            data={
                                "task_id": task.id,
                                "task_type": task.task_type,
                                "status": task.status,
                                "content": task.content,
                                "attempts": task.attempts,
                                "max_attempts": task.max_attempts,
                                "last_error": task.last_error,
                                "backoff_until": task.backoff_until,
                                "dead_letter": task.dead_letter,
                            },
                        )
                    )
                except Exception:
                    pass
            except Exception as rec_err:
                logger.error(f"Failed to record failure for task {task.id}: {rec_err}")
    
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
