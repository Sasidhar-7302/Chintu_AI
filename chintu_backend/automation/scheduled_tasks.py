"""
Scheduled Tasks for Chintu AI Assistant.
Extends TaskManager to support scheduled workflow execution.
"""

import logging
import json
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
from enum import Enum
import re

logger = logging.getLogger(__name__)


class ScheduleType(Enum):
    """Types of schedules."""
    ONCE = "once"              # Run once at specific time
    DAILY = "daily"            # Run every day at specific time
    WEEKLY = "weekly"          # Run every week on specific day
    INTERVAL = "interval"      # Run every X minutes/hours


@dataclass
class ScheduledTask:
    """A scheduled task with workflow."""
    id: str
    name: str
    workflow: str                    # The workflow command to execute
    schedule_type: ScheduleType
    schedule_time: str               # Time in HH:MM format
    schedule_day: Optional[str] = None  # Day of week for weekly
    interval_minutes: int = 0        # For interval type
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    enabled: bool = True
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "workflow": self.workflow,
            "schedule_type": self.schedule_type.value,
            "schedule_time": self.schedule_time,
            "schedule_day": self.schedule_day,
            "interval_minutes": self.interval_minutes,
            "enabled": self.enabled,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "next_run": self.next_run.isoformat() if self.next_run else None,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScheduledTask":
        return cls(
            id=data["id"],
            name=data["name"],
            workflow=data["workflow"],
            schedule_type=ScheduleType(data["schedule_type"]),
            schedule_time=data["schedule_time"],
            schedule_day=data.get("schedule_day"),
            interval_minutes=data.get("interval_minutes", 0),
            enabled=data.get("enabled", True),
            last_run=datetime.fromisoformat(data["last_run"]) if data.get("last_run") else None,
            next_run=datetime.fromisoformat(data["next_run"]) if data.get("next_run") else None,
        )


class Scheduler:
    """
    Manages scheduled task execution.
    Runs as a background thread checking for due tasks.
    """
    
    def __init__(self):
        self._tasks: Dict[str, ScheduledTask] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()  # For interruptible sleep
        self._lock = threading.Lock()
        self._callback: Optional[Callable[[str], None]] = None
        self._storage_path = self._get_storage_path()
        self._load_tasks()
    
    def _get_storage_path(self):
        from pathlib import Path
        path = Path.home() / ".chintu" / "scheduled_tasks.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    
    def _load_tasks(self):
        """Load tasks from persistent storage."""
        try:
            if self._storage_path.exists():
                with open(self._storage_path, 'r') as f:
                    data = json.load(f)
                    for task_data in data:
                        task = ScheduledTask.from_dict(task_data)
                        self._tasks[task.id] = task
                logger.info(f"Loaded {len(self._tasks)} scheduled tasks")
        except Exception as e:
            logger.warning(f"Failed to load scheduled tasks: {e}")
    
    def _save_tasks(self):
        """Save tasks to persistent storage."""
        try:
            with open(self._storage_path, 'w') as f:
                json.dump([t.to_dict() for t in self._tasks.values()], f, indent=2)
            
            # Notify UI
            from ..core.state import get_state_manager
            get_state_manager().update_scheduled_tasks([t.to_dict() for t in self._tasks.values()])
            
        except Exception as e:
            logger.error(f"Failed to save scheduled tasks: {e}")
    
    def set_callback(self, callback: Callable[[str], None]):
        """Set callback for when a scheduled task runs."""
        self._callback = callback
    
    def start(self):
        """Start the scheduler background thread."""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("Scheduler started")
    
    def stop(self):
        """Stop the scheduler."""
        self._running = False
        self._stop_event.set()  # Signal thread to wake up
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Scheduler stopped")
    
    def _run_loop(self):
        """Background loop checking for due tasks."""
        while self._running:
            try:
                self._check_due_tasks()
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
            self._stop_event.wait(30)  # Interruptible sleep (30 seconds)
    
    def _check_due_tasks(self):
        """Check and execute due tasks."""
        now = datetime.now()
        
        with self._lock:
            for task in list(self._tasks.values()):
                if not task.enabled:
                    continue
                
                # Calculate next run if not set
                if task.next_run is None:
                    task.next_run = self._calculate_next_run(task)
                
                # Check if task is due
                if task.next_run and now >= task.next_run:
                    self._execute_task(task)
                    task.last_run = now
                    task.next_run = self._calculate_next_run(task)
                    self._save_tasks()
    
    def _calculate_next_run(self, task: ScheduledTask) -> Optional[datetime]:
        """Calculate the next run time for a task."""
        now = datetime.now()
        
        try:
            hour, minute = map(int, task.schedule_time.split(':'))
        except:
            hour, minute = 9, 0  # Default to 9:00 AM
        
        if task.schedule_type == ScheduleType.ONCE:
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target <= now:
                return None  # Already passed
            return target
        
        elif task.schedule_type == ScheduleType.DAILY:
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            return target
        
        elif task.schedule_type == ScheduleType.WEEKLY:
            days_map = {
                "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                "friday": 4, "saturday": 5, "sunday": 6
            }
            target_day = days_map.get(task.schedule_day.lower(), 0)
            days_ahead = target_day - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            target += timedelta(days=days_ahead)
            return target
        
        elif task.schedule_type == ScheduleType.INTERVAL:
            if task.last_run:
                return task.last_run + timedelta(minutes=task.interval_minutes)
            return now + timedelta(minutes=task.interval_minutes)
        
        return None
    
    def _execute_task(self, task: ScheduledTask):
        """Execute a scheduled task."""
        logger.info(f"Executing scheduled task: {task.name}")
        
        # Log to UI
        from ..core.state import get_state_manager
        get_state_manager().log_activity(f"Running scheduled task: {task.name}")

        try:
            if self._callback:
                # Use the registered callback (typically command_handler.handle)
                self._callback(task.workflow)
            else:
                # Fallback: Use workflow engine directly if no callback set
                logger.warning("No scheduler callback set, using workflow engine fallback")
                from ..agents.workflow_engine import get_workflow_engine
                from ..agents.task_planner import get_task_planner

                planner = get_task_planner()
                plan = planner.plan(task.workflow)

                engine = get_workflow_engine()
                result = engine.execute(plan)

                if result.success:
                    logger.info(f"Scheduled task completed: {task.name} - {result.final_result[:100]}")
                else:
                    logger.warning(f"Scheduled task partial failure: {task.name} - {result.errors}")
        except Exception as e:
            logger.error(f"Scheduled task failed: {task.name} - {e}")
    
    def schedule(self, name: str, workflow: str, schedule_type: ScheduleType,
                 schedule_time: str, schedule_day: Optional[str] = None,
                 interval_minutes: int = 0) -> ScheduledTask:
        """
        Schedule a new task.
        
        Args:
            name: Human-readable name
            workflow: The workflow command to execute
            schedule_type: Type of schedule
            schedule_time: Time in HH:MM format
            schedule_day: Day of week for weekly schedules
            interval_minutes: Minutes between runs for interval type
            
        Returns:
            The created ScheduledTask
        """
        import uuid
        
        task = ScheduledTask(
            id=str(uuid.uuid4())[:8],
            name=name,
            workflow=workflow,
            schedule_type=schedule_type,
            schedule_time=schedule_time,
            schedule_day=schedule_day,
            interval_minutes=interval_minutes
        )
        task.next_run = self._calculate_next_run(task)
        
        with self._lock:
            self._tasks[task.id] = task
            self._save_tasks()
        
        logger.info(f"Scheduled task: {name}, next run: {task.next_run}")
        return task
    
    def cancel(self, task_id: str) -> bool:
        """Cancel a scheduled task."""
        with self._lock:
            if task_id in self._tasks:
                del self._tasks[task_id]
                self._save_tasks()
                return True
        return False
    
    def list_tasks(self) -> List[ScheduledTask]:
        """List all scheduled tasks."""
        with self._lock:
            return list(self._tasks.values())
    
    def get_task(self, task_id: str) -> Optional[ScheduledTask]:
        """Get a specific task by ID."""
        return self._tasks.get(task_id)


# Global instance
_scheduler: Optional[Scheduler] = None


def get_scheduler() -> Scheduler:
    """Get the global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = Scheduler()
    return _scheduler


def parse_schedule(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse a natural language schedule string into schedule parameters.
    
    Examples:
        "every day at 9am" -> daily, 09:00
        "every friday at 5pm" -> weekly, friday, 17:00
        "every 30 minutes" -> interval, 30
        "at 10:30am" -> once, 10:30
    """
    text = text.lower().strip()
    
    # Extract time
    time_match = re.search(r'(\d{1,2}):?(\d{2})?\s*(am|pm)?', text)
    schedule_time = "09:00"
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2)) if time_match.group(2) else 0
        am_pm = time_match.group(3)
        
        if am_pm == "pm" and hour < 12:
            hour += 12
        elif am_pm == "am" and hour == 12:
            hour = 0
        
        schedule_time = f"{hour:02d}:{minute:02d}"
    
    # Determine schedule type
    if "every day" in text or "daily" in text:
        return {
            "schedule_type": ScheduleType.DAILY,
            "schedule_time": schedule_time
        }
    
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    for day in days:
        if day in text:
            return {
                "schedule_type": ScheduleType.WEEKLY,
                "schedule_time": schedule_time,
                "schedule_day": day
            }
    
    interval_match = re.search(r'every\s+(\d+)\s*(minute|hour)', text)
    if interval_match:
        amount = int(interval_match.group(1))
        unit = interval_match.group(2)
        if unit == "hour":
            amount *= 60
        return {
            "schedule_type": ScheduleType.INTERVAL,
            "schedule_time": schedule_time,
            "interval_minutes": amount
        }
    
    # Default to once
    return {
        "schedule_type": ScheduleType.ONCE,
        "schedule_time": schedule_time
    }
