"""
Parallel Executor for Chintu AI Assistant.
Runs multiple tasks concurrently using asyncio.
"""

import asyncio
import logging
import threading
import time
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, Future
import uuid

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """Status of a parallel task."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class BackgroundTask:
    """A task running in the background."""
    id: str
    name: str
    command: str
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    cancel_requested: bool = False
    
    @property
    def duration(self) -> float:
        if self.started_at and self.completed_at:
            return self.completed_at - self.started_at
        elif self.started_at:
            return time.time() - self.started_at
        return 0


class ParallelExecutor:
    """
    Executes multiple tasks in parallel using threads.
    Provides progress tracking and result collection.
    """
    
    def __init__(self, max_workers: int = 4):
        self._tasks: Dict[str, BackgroundTask] = {}
        self._futures: Dict[str, Future] = {}
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._lock = threading.Lock()
        self._command_handler: Optional[Callable[[str], str]] = None
    
    def set_command_handler(self, handler: Callable[[str], str]):
        """Set the handler for executing commands."""
        self._command_handler = handler
    
    def submit(self, name: str, command: str) -> BackgroundTask:
        """
        Submit a task for background execution.
        
        Args:
            name: Human-readable task name
            command: The command/workflow to execute
            
        Returns:
            BackgroundTask object for tracking
        """
        task_id = str(uuid.uuid4())[:8]
        task = BackgroundTask(
            id=task_id,
            name=name,
            command=command
        )
        
        with self._lock:
            self._tasks[task_id] = task
        
        # Submit to thread pool
        future = self._executor.submit(self._execute_task, task)

        with self._lock:
            self._futures[task_id] = future

        logger.info(f"Background task submitted: {name} ({task_id})")
        return task
    
    def _execute_task(self, task: BackgroundTask):
        """Execute a task in the background."""
        if task.cancel_requested or task.status == TaskStatus.CANCELLED:
            task.completed_at = time.time()
            return

        task.status = TaskStatus.RUNNING
        task.started_at = time.time()
        
        try:
            if self._command_handler:
                result = self._command_handler(task.command)
                if not task.cancel_requested:
                    task.result = result
                    task.status = TaskStatus.COMPLETED
            else:
                # Fallback: use workflow engine
                from ..agents.workflow_engine import get_workflow_engine
                from ..agents.task_planner import get_task_planner
                
                planner = get_task_planner()
                plan = planner.plan(task.command)
                
                engine = get_workflow_engine()
                result = engine.execute(plan)
                
                if not task.cancel_requested:
                    task.result = result.final_result
                    task.status = TaskStatus.COMPLETED if result.success else TaskStatus.FAILED
                
        except Exception as e:
            if not task.cancel_requested:
                task.error = str(e)
                task.status = TaskStatus.FAILED
                logger.error(f"Background task failed: {task.name} - {e}")

        if task.cancel_requested:
            task.result = None
            task.status = TaskStatus.CANCELLED
            logger.info(f"Background task cancelled: {task.name} ({task.id})")
        task.completed_at = time.time()

        with self._lock:
            self._futures.pop(task.id, None)

        logger.info(f"Background task completed: {task.name} ({task.status.value})")
    
    def get_task(self, task_id: str) -> Optional[BackgroundTask]:
        """Get a task by ID."""
        return self._tasks.get(task_id)
    
    def list_tasks(self, status: Optional[TaskStatus] = None) -> List[BackgroundTask]:
        """List all tasks, optionally filtered by status."""
        with self._lock:
            tasks = list(self._tasks.values())
        
        if status:
            tasks = [t for t in tasks if t.status == status]
        
        return tasks
    
    def list_active(self) -> List[BackgroundTask]:
        """List currently running tasks."""
        return self.list_tasks(TaskStatus.RUNNING)
    
    def list_completed(self) -> List[BackgroundTask]:
        """List completed tasks (success or failure)."""
        with self._lock:
            return [
                t for t in self._tasks.values()
                if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)
            ]
    
    def cancel(self, task_id: str) -> bool:
        """Cancel a pending/running task."""
        task = self._tasks.get(task_id)
        if task and task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
            task.cancel_requested = True
            future = self._futures.get(task_id)
            if future and future.cancel():
                task.status = TaskStatus.CANCELLED
                task.completed_at = time.time()
                return True
            task.status = TaskStatus.CANCELLED
            return True
        return False
    
    def clear_completed(self):
        """Remove completed tasks from history."""
        with self._lock:
            self._tasks = {
                k: v for k, v in self._tasks.items()
                if v.status in (TaskStatus.PENDING, TaskStatus.RUNNING)
            }
    
    def wait_for(self, task_id: str, timeout: float = 60) -> Optional[BackgroundTask]:
        """
        Wait for a specific task to complete.
        
        Args:
            task_id: The task ID to wait for
            timeout: Maximum seconds to wait
            
        Returns:
            The completed task or None if timeout
        """
        start = time.time()
        while time.time() - start < timeout:
            task = self._tasks.get(task_id)
            if task and task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                return task
            threading.Event().wait(0.5)  # Interruptible poll wait
        return None
    
    def shutdown(self):
        """Shutdown the executor."""
        self._executor.shutdown(wait=False)


# Global instance
_parallel_executor: Optional[ParallelExecutor] = None


def get_parallel_executor() -> ParallelExecutor:
    """Get the global parallel executor instance."""
    global _parallel_executor
    if _parallel_executor is None:
        _parallel_executor = ParallelExecutor()
    return _parallel_executor
