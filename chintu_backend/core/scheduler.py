"""
Advanced Scheduler for Chintu AI.
Manages cron jobs and scheduled tasks with session isolation.

Features:
- Spawns isolated Session(type=CRON) for each run
- Supports cron expressions and intervals
- Posts summaries to MAIN session if configured
- Handles recurring and one-off tasks
"""

import logging
import asyncio
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Callable, Optional, Union
from dataclasses import dataclass
from uuid import uuid4

from chintu_backend.core.session_manager import get_session_manager, SessionType, Visibility
from chintu_backend.core.state import get_state_manager
from pathlib import Path
import json
from chintu_backend.core.config import get_config
from chintu_backend.core.events import get_event_bus, Event, EventType

logger = logging.getLogger(__name__)


@dataclass
class Job:
    """Represents a scheduled job."""
    id: str
    name: str
    schedule: str  # Cron expression or "every Xs"
    task_type: str
    task_payload: Dict[str, Any]
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    enabled: bool = True
    post_summary_to_main: bool = False
    # Lightweight reliability metadata (in-memory only).
    status: str = "idle"  # idle|running|succeeded|failed
    attempts: int = 0
    last_error: Optional[str] = None


@dataclass
class ScheduledTask:
    id: str
    name: str
    workflow: str
    schedule_type: str
    schedule_time: str
    schedule_day: Optional[str] = None
    interval_minutes: int = 0
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "workflow": self.workflow,
            "schedule_type": self.schedule_type,
            "schedule_time": self.schedule_time,
            "schedule_day": self.schedule_day,
            "interval_minutes": self.interval_minutes,
            "enabled": self.enabled,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "next_run": self.next_run.isoformat() if self.next_run else None,
        }


class Scheduler:
    """
    Central scheduler for Chintu.
    Uses asyncio logic to wake up and spawn independent sessions.
    """
    
    def __init__(self):
        self.jobs: Dict[str, Job] = {}
        self._tasks: Dict[str, ScheduledTask] = {}
        self._running = False
        self._task = None
        self.session_manager = get_session_manager()
        self.event_bus = get_event_bus()
        self.config = get_config()
        self._callback: Optional[Callable[..., Any]] = None
        self._storage_path = self._get_storage_path()
        self._load_tasks()
        self._load_tasks()
        self._schedule_heartbeat()
        self._schedule_finetuning()

    def _schedule_heartbeat(self):
        """Auto-schedule local system heartbeat if enabled."""
        if not hasattr(self.config, "heartbeat_enabled") or not self.config.heartbeat_enabled:
            return
            
        interval = getattr(self.config, "heartbeat_interval_minutes", 60)
        minutes = interval if isinstance(interval, int) else 60
        
        # Check if already exists
        for job in self.jobs.values():
            if job.name == "System Heartbeat":
                return

        # Add heartbeat job (runs every X minutes)
        # Payload uses 'local' model explicitly for cost saving
        self.add_job(
            name="System Heartbeat",
            schedule=f"every {minutes}m",
            task_type="heartbeat",
            payload={
                "model": getattr(self.config, "heartbeat_model", "ollama/llama3.2:3b"), 
                "message": getattr(self.config, "heartbeat_message", "Status check.")
            },
            post_summary=False # Keep it internal unless issues found
        )

    def _schedule_finetuning(self):
        """Auto-schedule automated fine-tuning loop."""
        if not getattr(self.config, "learning_weekly_enabled", True):
            return

        for job in self.jobs.values():
            if job.name == "Auto Finetuning":
                return

        interval_days = int(getattr(self.config, "learning_schedule_days", 14))
        interval_days = max(1, interval_days)
        self.add_job(
            name="Auto Finetuning",
            schedule=f"every {interval_days}d",
            task_type="finetune",
            payload={},
            post_summary=True
        )


    def _get_storage_path(self) -> Path:
        path = self.config.data_dir / "scheduled_tasks.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _load_tasks(self) -> None:
        try:
            if self._storage_path.exists():
                data = json.loads(self._storage_path.read_text())
                for item in data:
                    task = ScheduledTask(
                        id=item["id"],
                        name=item["name"],
                        workflow=item["workflow"],
                        schedule_type=item["schedule_type"],
                        schedule_time=item["schedule_time"],
                        schedule_day=item.get("schedule_day"),
                        interval_minutes=item.get("interval_minutes", 0),
                        enabled=item.get("enabled", True),
                        last_run=datetime.fromisoformat(item["last_run"]) if item.get("last_run") else None,
                        next_run=datetime.fromisoformat(item["next_run"]) if item.get("next_run") else None,
                    )
                    self._tasks[task.id] = task
            get_state_manager().update_scheduled_tasks([t.to_dict() for t in self._tasks.values()])
        except Exception as exc:
            logger.warning("Failed to load scheduled tasks: %s", exc)

    def _save_tasks(self) -> None:
        try:
            payload = [t.to_dict() for t in self._tasks.values()]
            self._storage_path.write_text(json.dumps(payload, indent=2))
            get_state_manager().update_scheduled_tasks(payload)
        except Exception as exc:
            logger.warning("Failed to save scheduled tasks: %s", exc)

    def set_callback(self, callback: Callable[..., Any]) -> None:
        self._callback = callback
        
    def start(self):
        """Start the scheduler loop."""
        if not self._running:
            self._running = True
            try:
                loop = asyncio.get_event_loop()
                self._task = loop.create_task(self._run_loop())
                logger.info("Scheduler started")
            except RuntimeError:
                # No running loop (e.g. during tests)
                pass

    def stop(self):
        """Stop the scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            
    async def _run_loop(self):
        """Main scheduling loop."""
        while self._running:
            now = datetime.now()
            
            # Legacy scheduled tasks
            for task in list(self._tasks.values()):
                if not task.enabled:
                    continue
                if not task.next_run:
                    task.next_run = self._calculate_next_run_task(task)
                    continue
                if task.next_run and now >= task.next_run:
                    asyncio.create_task(self._execute_task(task))
                    task.last_run = now
                    task.next_run = self._calculate_next_run_task(task)
                    self._save_tasks()

            for job in list(self.jobs.values()):
                if not job.enabled:
                    continue
                
                if not job.next_run:
                    self._calculate_next_run(job)
                    continue
                
                if now >= job.next_run:
                    # Time to run!
                    asyncio.create_task(self._execute_job(job))
                    
                    job.last_run = now
                    self._calculate_next_run(job)
            
            # Sleep briefly
            await asyncio.sleep(1)
            
            # Prune sessions occasionally (e.g. every hour)
            if now.minute == 0 and now.second == 0:
                self.session_manager.prune_expired()

    def add_job(
        self,
        name: str,
        schedule: str,
        task_type: str,
        payload: Dict[str, Any] = None,
        post_summary: bool = False
    ) -> str:
        """Add a new scheduled job."""
        job_id = str(uuid4())[:8]
        job = Job(
            id=job_id,
            name=name,
            schedule=schedule,
            task_type=task_type,
            task_payload=payload or {},
            post_summary_to_main=post_summary
        )
        self._calculate_next_run(job)
        self.jobs[job_id] = job
        logger.info(f"Scheduled job '{name}' ({schedule}): {job_id}")
        return job_id
        
    def remove_job(self, job_id: str):
        if job_id in self.jobs:
            del self.jobs[job_id]

    def update_job(
        self,
        job_id: str,
        schedule: Optional[str] = None,
        name: Optional[str] = None,
        enabled: Optional[bool] = None,
        post_summary: Optional[bool] = None,
    ) -> bool:
        job = self.jobs.get(job_id)
        if not job:
            return False
        if schedule:
            job.schedule = schedule
            self._calculate_next_run(job)
        if name:
            job.name = name
        if enabled is not None:
            job.enabled = enabled
        if post_summary is not None:
            job.post_summary_to_main = post_summary
        return True

    # ------------------------------------------------------------------
    # Scheduled task compatibility layer
    # ------------------------------------------------------------------
    def schedule(
        self,
        name: str,
        workflow: str,
        schedule_type: Any,
        schedule_time: str,
        schedule_day: Optional[str] = None,
        interval_minutes: int = 0,
    ) -> ScheduledTask:
        task_id = str(uuid4())[:8]
        schedule_type_value = schedule_type.value if hasattr(schedule_type, "value") else str(schedule_type)
        task = ScheduledTask(
            id=task_id,
            name=name,
            workflow=workflow,
            schedule_type=schedule_type_value,
            schedule_time=schedule_time,
            schedule_day=schedule_day,
            interval_minutes=interval_minutes or 0,
        )
        task.next_run = self._calculate_next_run_task(task)
        self._tasks[task_id] = task
        self._save_tasks()
        return task

    def list_tasks(self) -> List[ScheduledTask]:
        return list(self._tasks.values())

    def cancel(self, task_id: str) -> bool:
        if task_id in self._tasks:
            del self._tasks[task_id]
            self._save_tasks()
            return True
        return False

    async def _execute_task(self, task: ScheduledTask) -> None:
        logger.info("Executing scheduled task: %s", task.name)
        session = self.session_manager.create_session(
            name=f"Cron: {task.name}",
            type=SessionType.CRON,
            visibility=Visibility.INTERNAL,
            metadata={"task_id": task.id, "trigger": "scheduler"},
        )
        get_state_manager().log_activity(f"Running scheduled task: {task.name}")
        try:
            await self.event_bus.publish(
                Event(
                    type=EventType.TASK_SCHEDULED,
                    source="scheduler",
                    data={
                        "task_id": task.id,
                        "session_id": session.id,
                        "task_type": "workflow",
                        "payload": {"workflow": task.workflow},
                    },
                )
            )
        except Exception:
            pass
        if self._callback:
            try:
                try:
                    await asyncio.to_thread(
                        self._callback,
                        task.workflow,
                        "schedule",
                        {"session_id": session.id, "session_type": "cron"},
                    )
                except TypeError:
                    await asyncio.to_thread(self._callback, task.workflow)
            except Exception as exc:
                logger.error("Scheduled task callback failed: %s", exc)

    def _calculate_next_run_task(self, task: ScheduledTask) -> Optional[datetime]:
        now = datetime.now()
        try:
            hour, minute = map(int, task.schedule_time.split(":"))
        except Exception:
            hour, minute = 9, 0

        if task.schedule_type == "once":
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target <= now:
                return None
            return target
        if task.schedule_type == "daily":
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            return target
        if task.schedule_type == "weekly":
            days_map = {
                "monday": 0,
                "tuesday": 1,
                "wednesday": 2,
                "thursday": 3,
                "friday": 4,
                "saturday": 5,
                "sunday": 6,
            }
            target_day = days_map.get((task.schedule_day or "").lower(), 0)
            days_ahead = target_day - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return target + timedelta(days=days_ahead)
        if task.schedule_type == "interval":
            if task.last_run:
                return task.last_run + timedelta(minutes=task.interval_minutes)
            return now + timedelta(minutes=task.interval_minutes)
        return now + timedelta(hours=1)

    async def _execute_job(self, job: Job):
        """Execute a job in an isolated session."""
        logger.info(f"Executing job: {job.name} ({job.id})")
        
        # 1. Create isolated session
        session = self.session_manager.create_session(
            name=f"Cron: {job.name}",
            type=SessionType.CRON,
            visibility=Visibility.INTERNAL,
            metadata={"job_id": job.id, "trigger": "scheduler"}
        )

        # 1b. Best-effort run tracking so cron jobs appear in the global run queue.
        run_mgr = None
        run_id: Optional[str] = None
        try:
            from chintu_backend.core.run_manager import get_run_manager

            run_mgr = get_run_manager()
            run = run_mgr.create_run(
                session_id=session.id,
                source=f"cron:{job.task_type}",
                user_text=f"Cron job: {job.name}",
                meta={
                    "job_id": job.id,
                    "schedule": job.schedule,
                    "task_type": job.task_type,
                    "payload": job.task_payload,
                },
            )
            run_id = run.id
            # Do not block if the lane is busy; cron work is best-effort.
            run_mgr.acquire_run_turn(run_id, timeout_s=0.0)
        except Exception:
            run_mgr = None
            run_id = None

        job.status = "running"

        try:
            # Handle special system tasks directly
            if job.task_type == "finetune":
                from chintu_backend.brain.learning.weekly_trainer import run_biweekly_learning

                status = await asyncio.to_thread(run_biweekly_learning, False)
                job.status = "succeeded"
                job.attempts = 0
                if run_mgr and run_id:
                    msg = getattr(status, "message", "") or "Auto finetuning completed."
                    run_mgr.mark_completed(run_id, message=msg)
                if job.post_summary_to_main:
                    await self._post_summary(job, session.id, detail=getattr(status, "message", ""))
                return

            # 2. Publish execution event
            # Agents/Tools should listen for this event and act
            await self.event_bus.publish(
                Event(
                    type=EventType.TASK_SCHEDULED,
                    source="scheduler",
                    data={
                        "job_id": job.id,
                        "session_id": session.id,
                        "task_type": job.task_type,
                        "payload": job.task_payload,
                    },
                )
            )

            job.status = "succeeded"
            job.attempts = 0
            if run_mgr and run_id:
                run_mgr.mark_completed(run_id, message=f"Cron job '{job.name}' dispatched.")

            # 3. Handle result / summary
            # (In a real implementation, we'd wait for completion event)
            if job.post_summary_to_main:
                await self._post_summary(job, session.id)

        except Exception as e:
            job.status = "failed"
            job.last_error = str(e)
            job.attempts = int(job.attempts or 0) + 1
            logger.error(f"Job execution failed: {e}")
            if run_mgr and run_id:
                run_mgr.mark_failed(run_id, error=str(e))
        finally:
            if run_mgr and run_id:
                try:
                    run_mgr.release_run_turn(run_id)
                except Exception:
                    pass
            
    async def _post_summary(self, job: Job, session_id: str, detail: str = ""):
        """Post a summary to the main session."""
        # Find active main session
        mains = self.session_manager.list_sessions(type=SessionType.MAIN)
        if mains:
            main_id = mains[0].id
            detail_line = f"\nDetails: {detail}" if detail else ""
            await self.event_bus.publish(Event(
                type=EventType.MESSAGE_RECEIVED, # Simulate message
                source="system",
                data={
                    "session_id": main_id,
                    "content": f"ℹ️ **Cron Job Completed**: {job.name}{detail_line}\nSee internal session `{session_id}` for details."
                }
            ))

    def _calculate_next_run(self, job: Job):
        """Calculate next run time based on schedule string."""
        now = datetime.now()
        
        if job.schedule.startswith("every "):
            # Simple interval: "every 30s", "every 1h"
            parts = job.schedule.split(" ")
            if len(parts) == 2:
                unit = parts[1][-1].lower()
                val = int(parts[1][:-1])
                
                delta = None
                if unit == 's': delta = timedelta(seconds=val)
                elif unit == 'm': delta = timedelta(minutes=val)
                elif unit == 'h': delta = timedelta(hours=val)
                elif unit == 'd': delta = timedelta(days=val)
                
                if delta:
                    job.next_run = now + delta
                    return

        # Cron format: "m h dom mon dow"
        parts = job.schedule.split()
        if len(parts) == 5:
            next_run = self._next_cron_time(now, parts)
            if next_run:
                job.next_run = next_run
                return

        # Fallback to 1 hour if parse fails to avoid loops
        job.next_run = now + timedelta(hours=1)

    def _next_cron_time(self, start: datetime, parts: List[str]) -> Optional[datetime]:
        """Compute the next cron time (basic parser)."""
        minute, hour, dom, mon, dow = parts
        current = start.replace(second=0, microsecond=0) + timedelta(minutes=1)
        for _ in range(60 * 24 * 14):  # search up to 2 weeks
            if self._cron_match(current, minute, hour, dom, mon, dow):
                return current
            current += timedelta(minutes=1)
        return None

    def _cron_match(self, dt: datetime, minute: str, hour: str, dom: str, mon: str, dow: str) -> bool:
        def _match(value: int, field: str) -> bool:
            if field == "*":
                return True
            if field.startswith("*/"):
                try:
                    step = int(field[2:])
                    return step > 0 and value % step == 0
                except ValueError:
                    return False
            try:
                return value == int(field)
            except ValueError:
                return False

        if not _match(dt.minute, minute):
            return False
        if not _match(dt.hour, hour):
            return False
        if not _match(dt.day, dom):
            return False
        if not _match(dt.month, mon):
            return False
        # dow: 0=Sunday or 7=Sunday
        dow_val = (dt.weekday() + 1) % 7
        if dow in ("7", "0"):
            return _match(dow_val, "0")
        return _match(dow_val, dow)


# Global instance
_scheduler: Optional[Scheduler] = None

def get_scheduler() -> Scheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = Scheduler()
    return _scheduler
