"""Task scheduler utilities for the swarm DAG."""

from __future__ import annotations

from typing import Iterable, List

from .persistence import Task, TaskStatus


def ready_tasks(tasks: Iterable[Task]) -> List[Task]:
    """Return tasks that are ready to execute (pending with all deps done)."""
    task_map = {task.id: task for task in tasks}
    ready: List[Task] = []
    for task in tasks:
        if task.status != TaskStatus.PENDING:
            continue
        dependencies = task.dependencies or []
        if all(task_map.get(dep_id) and task_map[dep_id].status == TaskStatus.DONE for dep_id in dependencies):
            ready.append(task)
    return ready
