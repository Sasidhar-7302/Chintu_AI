
"""
TaskMaster: The Project Manager Agent.
Manages persistent user goals and tasks using strict SQL persistence.
"""

import logging
import sqlite3
import json
from pathlib import Path
from typing import Dict, Any, Optional, List
from chintu_backend.brain.swarm.base_agent import BaseAgent, AgentState
from chintu_backend.core.config import get_config

logger = logging.getLogger(__name__)

class TaskMaster(BaseAgent):
    def __init__(self):
        super().__init__(name="TaskMaster", description="manages tasks, todo lists, and project state")
        self.config = get_config()
        # No separate DB init; use central TaskManager.

    def run(self, goal: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Execute Task Management Command.
        Supported commands: "add [task]", "list", "complete [id/task]"
        """
        self.update_state(AgentState.PLANNING)
        self.log_step("Processing", goal)
        goal_lower = goal.lower()
        
        self.update_state(AgentState.EXECUTING)
        
        if "add" in goal_lower or "remind" in goal_lower or "create" in goal_lower:
            # Extract task content using case-insensitive regex
            import re
            # Remove command words
            title = re.sub(r'(?i)(add|create|task|remind me to)', '', goal).strip()
            return self._add_task(title)
            
        elif "list" in goal_lower or "show" in goal_lower:
            return self._list_tasks()
            
        elif "complete" in goal_lower or "finish" in goal_lower or "done" in goal_lower:
            # Extract ID if possible, else pattern match title
            import re
            target = re.sub(r'(?i)(complete|finish|mark|done|as)', '', goal).strip()
            return self._complete_task(target)
            
        return {"success": False, "error": "Unknown command. Try 'add', 'list', or 'complete'."}

    def _add_task(self, title: str) -> Dict[str, Any]:
        from chintu_backend.tasks.task_manager import get_task_manager
        tm = get_task_manager()
        task = tm.add_task(title)
        self.log_step("Task Added", f"#{task.id}: {title}")
        return {"success": True, "message": f"Added task #{task.id}: {title}", "task_id": task.id}

    def _list_tasks(self) -> Dict[str, Any]:
        from chintu_backend.tasks.task_manager import get_task_manager
        tm = get_task_manager()
        tasks = tm.list_tasks()
        # Convert to dict list for Swarm response
        task_list = [t.to_dict() for t in tasks]
        return {"success": True, "tasks": task_list, "count": len(task_list)}

    def _complete_task(self, target: str) -> Dict[str, Any]:
        from chintu_backend.tasks.task_manager import get_task_manager
        tm = get_task_manager()
        
        task_id = None
        match_desc = ""
        
        if target.isdigit():
            task_id = int(target)
            match_desc = f"ID {task_id}"
        else:
            # Search by content
            tasks = tm.list_tasks()
            for t in tasks:
                if target.lower() in t.content.lower():
                    task_id = t.id
                    match_desc = f"'{t.content}' (ID {t.id})"
                    break
        
        if task_id:
            success = tm.complete_task(task_id)
            if success:
                self.log_step("Task Completed", match_desc)
                return {"success": True, "message": f"Marked task as completed: {match_desc}"}
            else:
                return {"success": False, "error": f"Task ID {task_id} not found or already completed."}
        
        return {"success": False, "error": f"Could not find task matching '{target}'"}

    def stop(self):
        self.update_state(AgentState.IDLE)
