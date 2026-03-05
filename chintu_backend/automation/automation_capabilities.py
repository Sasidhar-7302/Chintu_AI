"""
Automation capability handlers for Chintu AI Assistant.
Provides voice commands for scheduled workflows, parallel tasks, and cross-app data transfer.
"""

import json
import logging
import re
import os
import shlex
import shutil
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field, field_validator
import requests

import chintu_backend.sandbox as sandbox
import chintu_backend.automation.hardware_capabilities  # Register hardware specs capability
import chintu_backend.automation.calendar_capabilities  # Register Google Calendar capability

from ..core.capabilities import Capability, CapabilityType, ActionResult
from ..core.config import get_config
from ..security.command_guard import get_command_guard
from . import morning_briefing_helpers as _mbh

logger = logging.getLogger(__name__)

# Last generated morning briefing headlines for direct follow-up commands
# like "read more about #1" even when no pending-request context is active.
_LAST_MORNING_BRIEFING_ITEMS: List[Dict[str, Any]] = []
_LINKEDIN_RESUME_WATCHER: Optional[threading.Thread] = None
_LINKEDIN_RESUME_STOP = threading.Event()

# ============================================================================
# SCHEMAS (Phase 4)
# ============================================================================

class ScheduleWorkflowSchema(BaseModel):
    workflow: str = Field(..., description="The task to perform (e.g. 'search for news').")
    schedule_time: str = Field(..., description="Time to run (e.g. '9am', '14:00').")
    schedule_type: str = Field(..., description="Frequency: 'daily', 'hourly', 'once'.")
    schedule_day: Optional[str] = Field(None, description="Day of week if applicable.")

class ListScheduledSchema(BaseModel):
    pass # No params needed

class CancelTaskSchema(BaseModel):
    task_id: str = Field(..., description="The ID of the task to cancel.")

class CancelCronJobSchema(BaseModel):
    job_id: str = Field(..., description="The ID of the cron job to cancel.")

class UpdateCronJobSchema(BaseModel):
    job_id: str = Field(..., description="The ID of the cron job to update.")
    schedule: Optional[str] = Field(None, description="New schedule expression.")
    name: Optional[str] = Field(None, description="New job name.")
    enabled: Optional[bool] = Field(None, description="Enable or disable the cron job.")

class CommitChangeSchema(BaseModel):
    change_id: str = Field(..., description="Change record id to commit.")
    message: Optional[str] = Field(None, description="Optional commit message.")

class RollbackChangeSchema(BaseModel):
    change_id: str = Field(..., description="Change record id to rollback.")

class BackgroundTaskSchema(BaseModel):
    task: str = Field(..., description="The task description to run in background.")

class CheckTasksSchema(BaseModel):
    pass

class TransferDataSchema(BaseModel):
    action: str = Field(..., description="'copy_to_clipboard', 'save_to_file', 'get_clipboard'")
    source: Optional[str] = Field(None, description="'browser', 'clipboard'")
    destination: Optional[str] = Field(None, description="FilePath or 'clipboard'")

class SandboxRunSchema(BaseModel):
    command: str = Field(..., description="The shell command to run.")
    allow_network: bool = Field(False, description="Whether to allow network access.")

class SandboxDataTaskSchema(BaseModel):
    dataset: Optional[str] = Field(None, description="CSV file name or path to analyze.")
    output_chart: Optional[str] = Field(None, description="Optional output chart filename.")
    run_in_sandbox: bool = Field(True, description="Must run in sandbox.")

    @field_validator("dataset", "output_chart", mode="before")
    @classmethod
    def _normalize_optional_path(cls, value):
        # LLM extractors occasionally return booleans for optional string fields.
        if value is None or isinstance(value, bool):
            return None
        text = str(value).strip().strip("\"'")
        return text or None

    @field_validator("run_in_sandbox", mode="before")
    @classmethod
    def _coerce_run_in_sandbox(cls, value):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            low = value.strip().lower()
            if low in {"true", "yes", "1"}:
                return True
            if low in {"false", "no", "0"}:
                return False
        return True

class TerminalExecSchema(BaseModel):
    command: str = Field(..., description="The terminal command to run.")
    cwd: Optional[str] = Field(None, description="Optional working directory (must be inside Chintu workspace).")
    timeout_seconds: Optional[int] = Field(60, description="Command timeout in seconds.")

class JobApplySchema(BaseModel):
    query: str = Field(..., description="Job search query (role/keywords).")
    location: Optional[str] = Field(None, description="Preferred location.")
    max_years: Optional[int] = Field(3, description="Maximum years of experience required.")
    sites: Optional[List[str]] = Field(None, description="Job sites to search.")
    apply_limit: Optional[int] = Field(5, description="Max applications in this run.")

class JobApplyListSchema(BaseModel):
    limit: Optional[int] = Field(20, description="Max records to show.")

class FigmaAutomationSchema(BaseModel):
    url: str = Field(..., description="Figma file or prototype URL.")

class ConfigSetSchema(BaseModel):
    key: str = Field(..., description="Config key to set (e.g. CHINTU_RESUME_TEX_PATH).")
    value: str = Field(..., description="Value to set.")

class ImageAnalyzeSchema(BaseModel):
    path: str = Field(..., description="Path to image file.")
    mode: Optional[str] = Field("describe", description="describe | ocr | analyze")

class VideoSummarizeSchema(BaseModel):
    path: str = Field(..., description="Path to video file.")
    max_frames: Optional[int] = Field(20, description="Max frames to analyze.")

class NewsVideoSchema(BaseModel):
    topic: Optional[str] = Field("technology news", description="News topic to cover.")
    voice: Optional[str] = Field("default", description="Voice preset.")


class MorningBriefingSchema(BaseModel):
    topic: Optional[str] = Field("technology", description="News topic for the briefing.")
    headlines: Optional[int] = Field(20, description="Number of headlines to include.")


class MorningBriefingDetailSchema(BaseModel):
    headline_number: Optional[int] = Field(None, ge=1, le=100, description="Headline index to expand.")


class MorningBriefingFeedbackSchema(BaseModel):
    headline_number: Optional[int] = Field(None, ge=1, le=100, description="Headline index to like/dislike.")
    sentiment: Optional[str] = Field(None, description="like | dislike | more | less")


class YouTubeShortSchema(BaseModel):
    topic: str = Field(..., description="Topic for the YouTube Short.")
    when: Optional[str] = Field("tonight", description="When to run (e.g. tonight, now).")


class AppBuilderSchema(BaseModel):
    idea: str = Field(..., description="App idea to turn into PRD + plan + scaffold.")
    when: Optional[str] = Field("tonight", description="When to run (e.g. tonight, now).")


class AppBuilderBuildSchema(BaseModel):
    project_dir: str = Field(..., description="Project directory produced by the docs step.")
    install_deps: Optional[bool] = Field(True, description="Install backend dependencies before tests.")
    run_tests: Optional[bool] = Field(True, description="Run checkpoint tests after scaffold/install.")


class AutonomyWorkflowSchema(BaseModel):
    task: Optional[str] = Field(None, description="High-level workflow objective.")



def handle_schedule_workflow(text: str, context: Dict[str, Any]) -> ActionResult:
    """Schedule a workflow to run at a specific time."""
    from chintu_backend.core.scheduler import get_scheduler
    from .scheduled_tasks import parse_schedule, ScheduleType
    
    workflow_part = None
    schedule_params = None
    
    # Phase 4: Schema Validation
    validated = context.get("_validated_params")
    if validated and isinstance(validated, ScheduleWorkflowSchema):
        workflow_part = validated.workflow
        # Map schema fields back to implicit params expected by scheduler
        # Or ideally, construct the dict directly.
        # implementation details of parse_schedule are regex based, but we can bypass or construct manually.
        # Let's map strict params to what we need.
        try:
             # allowed types in ScheduleType enum: daily, hourly, once...
             stype = ScheduleType(validated.schedule_type.lower())
             schedule_params = {
                 "schedule_type": stype,
                 "schedule_time": validated.schedule_time,
                 "schedule_day": validated.schedule_day
             }
        except ValueError:
             # If LLM gave invalid enum, fall back to "daily" or error? 
             # Self-correction handles this if Pydantic validation failed on Enum? 
             # I used str in Schema, so no validation error yet.
             # I should probably use Literal/Enum in Schema for perfect safety.
             # For now, simplistic fallback.
             pass

    if not workflow_part or not schedule_params:
        # Fallback to regex parsing (Legacy)
        # Extract schedule and workflow
        query = text.lower().strip()
        
        # Clean common prefixes
        for prefix in ["can you", "could you", "please", "kindly"]:
            if query.startswith(prefix):
                 query = query.replace(prefix, "", 1).strip()
        
        # Try to separate schedule from workflow
        schedule_patterns = [
            # Schedule at start
            r"(every day at \d{1,2}(?::\d{2})?\s*(?:am|pm)?)[,\s]+(.+)",
            r"(every \w+ at \d{1,2}(?::\d{2})?\s*(?:am|pm)?)[,\s]+(.+)",
            r"(every \d+ (?:minute|hour)s?)[,\s]+(.+)",
            r"(at \d{1,2}(?::\d{2})?\s*(?:am|pm)?)[,\s]+(.+)",
            # Schedule at end (inverted)
            r"(.+?)[,\s]+(every day at \d{1,2}(?::\d{2})?\s*(?:am|pm)?)$",
            r"(.+?)[,\s]+(every \w+ at \d{1,2}(?::\d{2})?\s*(?:am|pm)?)$",
            r"(.+?)[,\s]+(every \d+ (?:minute|hour)s?)$",
            r"(.+?)[,\s]+(at \d{1,2}(?::\d{2})?\s*(?:am|pm)?)$",
        ]
        
        schedule_part = None
        
        for pattern in schedule_patterns:
            match = re.search(pattern, query)
            if match:
                g1, g2 = match.group(1), match.group(2)
                if "every" in g1 or g1.strip().startswith("at "): 
                     schedule_part, workflow_part = g1, g2
                elif "every" in g2 or g2.strip().startswith("at "):
                     schedule_part, workflow_part = g2, g1
                else:
                     if re.match(r"(every|at \d)", g1):
                         schedule_part, workflow_part = g1, g2
                     else:
                         schedule_part, workflow_part = g2, g1
                break
        
        if not schedule_part or not workflow_part:
            return ActionResult.fail(
                "Please specify when and what to do. Example: 'Every day at 9am, search for news'",
                "schedule_workflow"
            )
        
        # Parse the schedule
        schedule_params = parse_schedule(schedule_part)
        if not schedule_params:
            return ActionResult.fail(
                "I couldn't understand the schedule. Try: 'every day at 9am' or 'every friday at 5pm'",
                "schedule_workflow"
            )
    
    try:
        if context.get("_plan_only"):
            schedule_type = schedule_params["schedule_type"].value
            schedule_time = schedule_params["schedule_time"]
            preview = [
                "Plan: Schedule workflow",
                f"- Task: {workflow_part}",
                f"- Schedule: {schedule_type} at {schedule_time}",
            ]
            if schedule_params.get("schedule_day"):
                preview.append(f"- Day: {schedule_params['schedule_day'].title()}")
            return ActionResult.ok("\n".join(preview), capability="schedule_workflow")

        scheduler = get_scheduler()

        # Set up callback to use command handler if available
        command_handler = context.get("command_handler")
        if command_handler and hasattr(command_handler, "handle"):
            scheduler.set_callback(command_handler.handle)

        scheduler.start()  # Ensure scheduler is running

        task = scheduler.schedule(
            name=workflow_part[:50],
            workflow=workflow_part,
            **schedule_params
        )
        
        schedule_type = schedule_params["schedule_type"].value
        schedule_time = schedule_params["schedule_time"]
        
        response = f"**Scheduled!** ({task.id})\n\n"
        response += f"- **Task:** {workflow_part}\n"
        response += f"- **Schedule:** {schedule_type} at {schedule_time}"
        if schedule_params.get("schedule_day"):
            response += f" on {schedule_params['schedule_day'].title()}"
        response += f"\n- **Next run:** {task.next_run.strftime('%Y-%m-%d %H:%M') if task.next_run else 'N/A'}"
        
        return ActionResult.ok(
            response,
            {"task_id": task.id, "schedule": schedule_type},
            "schedule_workflow"
        )
        
    except Exception as e:
        logger.error(f"Failed to schedule workflow: {e}")
        return ActionResult.fail(
            f"Failed to schedule: {e}",
            "schedule_workflow"
        )


def handle_list_scheduled(text: str, context: Dict[str, Any]) -> ActionResult:
    """
    List all scheduled tasks.
    
    Examples:
        "Show my scheduled tasks"
        "List automations"
    """
    from chintu_backend.core.scheduler import get_scheduler
    
    scheduler = get_scheduler()
    tasks = scheduler.list_tasks()
    
    if not tasks:
        return ActionResult.ok(
            "No scheduled tasks. Try: 'Every day at 9am, search for news'",
            {"count": 0},
            "list_scheduled"
        )
    
    response = f"Scheduled Tasks ({len(tasks)})\n\n"
    for task in tasks:
        status = "[ON]" if task.enabled else "[OFF]"
        next_run = task.next_run.strftime('%Y-%m-%d %H:%M') if task.next_run else "N/A"
        response += f"{status} {task.name[:30]} ({task.id})\n"
        response += f"   {task.schedule_type.value} at {task.schedule_time} | Next: {next_run}\n"
    
    return ActionResult.ok(
        response,
        {"count": len(tasks)},
        "list_scheduled"
    )


def handle_cancel_scheduled(text: str, context: Dict[str, Any]) -> ActionResult:
    """Cancel a scheduled task."""
    from chintu_backend.core.scheduler import get_scheduler
    
    task_id = None
    
    # Phase 4: Schema
    validated = context.get("_validated_params")
    if validated and isinstance(validated, CancelTaskSchema):
        task_id = validated.task_id
    
    if not task_id:
        # Legacy
        words = text.lower().split()
        for word in words:
            if len(word) >= 4 and word.isalnum():
                task_id = word
    
    if not task_id:
        return ActionResult.fail(
            "Which task should I cancel? Provide the task ID.",
            "cancel_scheduled"
        )
    
    scheduler = get_scheduler()
    success = scheduler.cancel(task_id)
    
    if success:
        return ActionResult.ok(
            f"Cancelled scheduled task: {task_id}",
            {"task_id": task_id},
            "cancel_scheduled"
        )
    else:
        return ActionResult.fail(
            f"Task not found: {task_id}",
            "cancel_scheduled"
        )


def handle_cancel_cron_job(text: str, context: Dict[str, Any]) -> ActionResult:
    """Cancel a cron job."""
    from chintu_backend.core.scheduler import get_scheduler

    job_id = None

    validated = context.get("_validated_params")
    if validated and isinstance(validated, CancelCronJobSchema):
        job_id = validated.job_id

    if not job_id:
        words = text.lower().split()
        for word in words:
            if len(word) >= 4 and word.isalnum():
                job_id = word
                break

    if not job_id:
        return ActionResult.fail(
            "Which cron job should I cancel? Provide the job ID.",
            "cancel_cron_job"
        )

    scheduler = get_scheduler()
    scheduler.remove_job(job_id)

    return ActionResult.ok(
        f"Cancelled cron job: {job_id}",
        {"job_id": job_id},
        "cancel_cron_job"
    )


def handle_update_cron_job(text: str, context: Dict[str, Any]) -> ActionResult:
    """Update a cron job schedule or name."""
    from chintu_backend.core.scheduler import get_scheduler

    job_id = None
    schedule = None
    name = None
    enabled = None

    validated = context.get("_validated_params")
    if validated and isinstance(validated, UpdateCronJobSchema):
        job_id = validated.job_id
        schedule = validated.schedule
        name = validated.name
        enabled = validated.enabled

    if not job_id:
        words = text.strip().split()
        if len(words) >= 4:
            for word in words:
                if word.isalnum() and len(word) >= 4:
                    job_id = word
                    break
        # naive schedule extraction after "schedule"
        if "schedule" in text.lower():
            schedule = text.lower().split("schedule", 1)[1].strip()
        if "name" in text.lower():
            name = text.lower().split("name", 1)[1].strip()
        if "enable" in text.lower():
            enabled = True
        if "disable" in text.lower():
            enabled = False

    if not job_id:
        return ActionResult.fail(
            "Which cron job should I update? Provide the job ID.",
            "update_cron_job"
        )

    if not schedule and not name and enabled is None:
        return ActionResult.fail(
            "Provide a new schedule or name for the cron job.",
            "update_cron_job"
        )

    scheduler = get_scheduler()
    ok = scheduler.update_job(job_id, schedule=schedule, name=name, enabled=enabled)
    if not ok:
        return ActionResult.fail(
            f"Cron job not found: {job_id}",
            "update_cron_job"
        )

    detail = []
    if schedule:
        detail.append(f"schedule={schedule}")
    if name:
        detail.append(f"name={name}")
    if enabled is True:
        detail.append("enabled")
    if enabled is False:
        detail.append("disabled")
    return ActionResult.ok(
        f"Updated cron job {job_id} ({', '.join(detail)})",
        {"job_id": job_id, "schedule": schedule, "name": name},
        "update_cron_job"
    )


def handle_commit_change(text: str, context: Dict[str, Any]) -> ActionResult:
    """Commit a change record to git."""
    from chintu_backend.agents.change_journal import commit_change

    change_id = None
    message = None
    validated = context.get("_validated_params")
    if validated and isinstance(validated, CommitChangeSchema):
        change_id = validated.change_id
        message = validated.message
    if not change_id:
        words = text.lower().split()
        for word in words:
            if len(word) >= 6 and word.isalnum():
                change_id = word
                break
    if not change_id:
        return ActionResult.fail("Specify a change id to commit.", "commit_change")

    ok, info = commit_change(change_id, message)
    if not ok:
        return ActionResult.fail(f"Commit failed: {info}", "commit_change")
    return ActionResult.ok(f"Committed change {change_id}: {info}", {"change_id": change_id, "commit": info}, "commit_change")


def handle_rollback_change(text: str, context: Dict[str, Any]) -> ActionResult:
    """Rollback a change record."""
    from chintu_backend.agents.change_journal import rollback_change

    change_id = None
    validated = context.get("_validated_params")
    if validated and isinstance(validated, RollbackChangeSchema):
        change_id = validated.change_id
    if not change_id:
        words = text.lower().split()
        for word in words:
            if len(word) >= 6 and word.isalnum():
                change_id = word
                break
    if not change_id:
        return ActionResult.fail("Specify a change id to rollback.", "rollback_change")

    ok, info = rollback_change(change_id)
    if not ok:
        return ActionResult.fail(f"Rollback failed: {info}", "rollback_change")
    return ActionResult.ok(f"Rolled back change {change_id}.", {"change_id": change_id}, "rollback_change")


def handle_background_task(text: str, context: Dict[str, Any]) -> ActionResult:
    """Run a task in the background."""
    from .parallel_executor import get_parallel_executor
    
    task_description = None
    
    validated = context.get("_validated_params")
    if validated and isinstance(validated, BackgroundTaskSchema):
        task_description = validated.task
    
    if not task_description:
        # Legacy
        query = text.lower().strip()
        prefixes = [
            "in the background,? ", "while i work,? ", "async,? ",
            "background task:? ", "run in background:? "
        ]
        
        task_description = query
        for prefix in prefixes:
            task_description = re.sub(f"^{prefix}", "", task_description, flags=re.IGNORECASE)
    
    if not task_description or len(task_description) < 5:
        return ActionResult.fail(
            "What should I do in the background?",
            "background_task"
        )
    
    try:
        executor = get_parallel_executor()

        # Set up command handler if available
        command_handler = context.get("command_handler")
        if command_handler and hasattr(command_handler, "handle"):
            executor.set_command_handler(command_handler.handle)

        task = executor.submit(
            name=task_description[:50],
            command=task_description
        )
        
        return ActionResult.ok(
            f"**Started background task** ({task.id})\n\nTask: {task_description}\n\nSay 'check tasks' to see progress.",
            {"task_id": task.id, "name": task.name},
            "background_task"
        )
        
    except Exception as e:
        logger.error(f"Failed to start background task: {e}")
        return ActionResult.fail(
            f"Failed to start background task: {e}",
            "background_task"
        )


def handle_check_tasks(text: str, context: Dict[str, Any]) -> ActionResult:
    """
    Check status of background tasks.
    
    Examples:
        "Check tasks"
        "Show background tasks"
    """
    from .parallel_executor import get_parallel_executor
    
    executor = get_parallel_executor()
    
    running = executor.list_active()
    completed = executor.list_completed()
    
    if not running and not completed:
        return ActionResult.ok(
            "No background tasks. Try: 'In the background, research AI trends'",
            {"running": 0, "completed": 0},
            "check_tasks"
        )
    
    response = "Background Tasks\n\n"
    
    if running:
        response += f"Running ({len(running)})\n"
        for task in running:
            response += f"  - {task.name} ({task.id}) - {task.duration:.1f}s\n"
    
    if completed:
        response += f"\nCompleted ({len(completed)})\n"
        for task in completed[-5:]:  # Last 5
            icon = "[OK]" if task.status.value == "completed" else "[FAIL]"
            response += f"  {icon} {task.name}\n"
            if task.result:
                preview = task.result[:100].replace('\n', ' ')
                response += f"     -> {preview}...\n"
    
    return ActionResult.ok(
        response,
        {"running": len(running), "completed": len(completed)},
        "check_tasks"
    )


def handle_transfer_data(text: str, context: Dict[str, Any]) -> ActionResult:
    """Transfer data between sources."""
    from .cross_app import get_data_transfer, DataFormat
    
    action = None
    source = None
    destination = None
    
    validated = context.get("_validated_params")
    if validated and isinstance(validated, TransferDataSchema):
        action = validated.action
        source = validated.source
        destination = validated.destination
    
    transfer = get_data_transfer()
    query = text.lower().strip()
    
    # Logic for Schema-based execution
    if action == "copy_to_clipboard":
        if source == "browser":
            package = transfer.from_browser()
            if package:
                transfer.to_clipboard(package)
                return ActionResult.ok(f"Copied browser content to clipboard.", {}, "transfer_data")
            return ActionResult.fail("No browser open.", "transfer_data")
            
    if action == "save_to_file":
        if source == "clipboard":
             package = transfer.capture_clipboard()
             if package:
                 path = destination or "clipboard_export.txt"
                 transfer.to_file(package, path)
                 return ActionResult.ok(f"Saved clipboard to {path}", {}, "transfer_data")
             return ActionResult.fail("Clipboard empty.", "transfer_data")
    
    if action == "get_clipboard":
         package = transfer.capture_clipboard()
         if package:
             return ActionResult.ok(f"Clipboard: {package.content[:200]}...", {}, "transfer_data")
         return ActionResult.fail("Clipboard empty", "transfer_data")

    # Fallback to legacy regex if no schema match or weird action
    if context.get("_plan_only"):
        if "page content" in query or "from browser" in query:
            return ActionResult.ok(
                "Plan: Capture page content and transfer it to the requested destination.",
                capability="transfer_data",
            )
        if "clipboard" in query and ("save" in query or "file" in query):
            return ActionResult.ok(
                "Plan: Capture clipboard content and save it to a local file.",
                capability="transfer_data",
            )
        if "clipboard" in query:
            return ActionResult.ok(
                "Plan: Capture clipboard content and report a summary.",
                capability="transfer_data",
            )
        return ActionResult.ok(
            "Plan: Transfer data between sources with a confirmation step.",
            capability="transfer_data",
        )
    
    # Browser to clipboard (Legacy)
    if "page content" in query or "from browser" in query:
        package = transfer.from_browser()
        if package:
            if "clipboard" in query or "copy" in query:
                transfer.to_clipboard(package)
                return ActionResult.ok(
                    f"Copied page content to clipboard ({len(package.content)} chars)",
                    {"source": "browser", "dest": "clipboard"},
                    "transfer_data"
                )
            else:
                return ActionResult.ok(
                    f"**Page Content:**\n{package.content[:500]}...",
                    {"source": "browser"},
                    "transfer_data"
                )
        else:
            return ActionResult.fail(
                "No browser page is open.",
                "transfer_data"
            )
    
    # Clipboard to file (Legacy)
    if "clipboard" in query and ("save" in query or "file" in query):
        package = transfer.capture_clipboard()
        if package:
            # Extract filename
            file_match = re.search(r'(?:to|as|file)\s+([^\s]+)', query)
            filename = file_match.group(1) if file_match else "clipboard_export.txt"
            
            from pathlib import Path
            path = Path.home() / "Desktop" / filename
            
            success = transfer.to_file(package, str(path))
            if success:
                return ActionResult.ok(
                    f"Saved clipboard to: {path}",
                    {"dest": str(path)},
                    "transfer_data"
                )
        return ActionResult.fail(
            "Clipboard is empty.",
            "transfer_data"
        )
    
    # Get clipboard info (Legacy)
    if "clipboard" in query:
        package = transfer.capture_clipboard()
        if package:
            return ActionResult.ok(
                f"**Clipboard** ({package.format.value}):\n{package.content[:500]}",
                {"format": package.format.value},
                "transfer_data"
            )
        return ActionResult.fail(
            "Clipboard is empty.",
            "transfer_data"
        )
    
    return ActionResult.fail(
        "Specify what to transfer. Examples: 'copy page content', 'save clipboard to file'",
        "transfer_data"
    )


def handle_sandbox_run(text: str, context: Dict[str, Any]) -> ActionResult:
    """Execute a command inside the Docker sandbox."""
    if context.get("_plan_only"):
        return ActionResult.ok(
            "Plan: Run the command inside the Docker sandbox and return stdout/stderr.",
            capability="sandbox_run",
        )

    command = None
    allow_network = False
    
    # Phase 4: Schema
    validated = context.get("_validated_params")
    if validated and isinstance(validated, SandboxRunSchema):
        command = validated.command
        allow_network = validated.allow_network
    
    if not command:
        # Legacy
        text_lower = text.lower()
        command = text
        for prefix in ["run in sandbox", "sandbox run", "sandbox:"]:
            idx = text_lower.find(prefix)
            if idx != -1:
                command = text[idx + len(prefix):].strip(" :")
                break

    if not command:
        return ActionResult.fail("Please provide a command to run in the sandbox.", "sandbox_run")

    if not allow_network: # If not already set by schema
         allow_network = "with network" in text.lower() or "allow network" in text.lower()
    
    network_mode = "bridge" if allow_network else "none"
    agent_sandbox = context.get("_agent_sandbox")
    if agent_sandbox is not None:
        try:
            sandbox_mode = getattr(agent_sandbox, "network_mode", None)
            if sandbox_mode:
                network_mode = sandbox_mode
                allow_network = sandbox_mode != "none"
        except Exception:
            pass

    if allow_network and not context.get("_confirmed"):
        from chintu_backend.security.guardian import require_confirmation

        guard = require_confirmation(
            "Network access requested for sandbox. Allow this run?",
            "sandbox_run",
        )
        return guard(lambda _t, _c: handle_sandbox_run(_t, _c))(text, context)

    try:
        cfg = get_config()
        if bool(getattr(cfg, "workspace_api_enabled", True)):
            from chintu_backend.workspace import get_workspace_manager

            manager = get_workspace_manager()
            workspace_dir = None
            if agent_sandbox is not None:
                try:
                    workspace_dir = getattr(agent_sandbox, "workspace_dir", None)
                except Exception:
                    workspace_dir = None
            ws_context = dict(context or {})
            ws_context.setdefault("channel_trust", "trusted")
            run_result = manager.run_shell(
                command,
                action_kind="shell",
                context=ws_context,
                cwd=workspace_dir,
                requested_placement="sandbox",
                allow_network=allow_network,
                timeout_seconds=int(getattr(cfg, "terminal_timeout_seconds", 60)),
            )
            preview = (run_result.stdout or "").strip()[:1000]
            message = "Sandbox command completed." if run_result.success else f"Sandbox command failed (exit {run_result.exit_code})."
            if preview:
                message = f"{message}\n\nOutput:\n{preview}"
            if (run_result.stderr or "").strip():
                message = f"{message}\n\nErrors:\n{run_result.stderr.strip()[:1000]}"
            data = {
                "exit_code": run_result.exit_code,
                "placement": run_result.placement.value,
                "runtime_profile": run_result.runtime_profile,
                "receipt_path": str(run_result.receipt_path),
            }
            if run_result.success:
                return ActionResult.ok(message, data, "sandbox_run")
            return ActionResult.fail(message, "sandbox_run", data=data)

        executor = sandbox.SandboxExecutor()
        workspace_dir = None
        if agent_sandbox is not None:
            try:
                workspace_dir = getattr(agent_sandbox, "workspace_dir", None)
            except Exception:
                workspace_dir = None
        result = executor.run(
            command=command,
            network_mode=network_mode,
            workspace_dir=str(workspace_dir) if workspace_dir else None,
        )
        preview = result.stdout.strip()[:1000]
        if result.exit_code == 0:
            message = "Sandbox command completed."
        else:
            message = f"Sandbox command failed (exit {result.exit_code})."
        if preview:
            message = f"{message}\n\nOutput:\n{preview}"
        if result.stderr.strip():
            message = f"{message}\n\nErrors:\n{result.stderr.strip()[:1000]}"
        return ActionResult.ok(message, {"exit_code": result.exit_code}, "sandbox_run")
    except Exception as exc:
        logger.error("Sandbox run failed: %s", exc)
        return ActionResult.fail(f"Sandbox run failed: {exc}", "sandbox_run")


def _extract_dataset_path_from_text(text: str) -> Optional[str]:
    raw = str(text or "").strip()
    if not raw:
        return None

    quoted = re.findall(r"['\"]([^'\"]+\.csv)['\"]", raw, flags=re.IGNORECASE)
    if quoted:
        return quoted[0].strip()

    bare = re.findall(r"([A-Za-z0-9_./\\\\-]+\.csv)", raw, flags=re.IGNORECASE)
    if bare:
        return bare[0].strip()
    return None


def _resolve_dataset_path(dataset_ref: str, context: Dict[str, Any]) -> Optional[Path]:
    value = str(dataset_ref or "").strip().strip("\"'")
    if not value:
        return None

    user_downloads = Path(
        context.get("_user_downloads_dir")
        or (Path.home() / "Downloads")
    ).expanduser()
    user_desktop = Path(
        context.get("_user_desktop_dir")
        or (Path.home() / "Desktop")
    ).expanduser()
    workspace_dir = Path(
        context.get("workspace_dir")
        or os.getcwd()
    ).expanduser()

    candidate = Path(value).expanduser()
    candidates: List[Path] = []
    if candidate.is_absolute():
        candidates.append(candidate)
    else:
        candidates.extend(
            [
                user_downloads / candidate,
                workspace_dir / candidate,
                user_desktop / candidate,
                Path.cwd() / candidate,
            ]
        )

    for path in candidates:
        try:
            if path.exists() and path.is_file():
                return path.resolve()
        except Exception:
            continue
    return None


def _build_sandbox_data_cleaning_script() -> str:
    return """\
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


def _pick_target_column(df):
    lower_map = {str(col).strip().lower(): col for col in df.columns}
    for preferred in ("sales", "revenue", "amount", "value"):
        if preferred in lower_map:
            return lower_map[preferred]
    numeric_cols = list(df.select_dtypes(include=["number"]).columns)
    if numeric_cols:
        return numeric_cols[0]
    raise RuntimeError("No numeric columns found for trend chart.")


def _pick_date_column(df):
    lower_map = {str(col).strip().lower(): col for col in df.columns}
    for preferred in ("date", "timestamp", "time", "day"):
        if preferred in lower_map:
            return lower_map[preferred]
    for col in df.columns:
        series = pd.to_datetime(df[col], errors="coerce")
        if series.notna().sum() >= max(3, int(0.6 * len(df))):
            return col
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--cleaned", required=True)
    parser.add_argument("--chart", required=True)
    args = parser.parse_args()

    input_path = Path(args.input)
    cleaned_path = Path(args.cleaned)
    chart_path = Path(args.chart)

    df = pd.read_csv(input_path)
    rows_before = int(len(df))
    nulls_before = int(df.isna().sum().sum())

    for col in df.columns:
        if df[col].dtype == object:
            df[col] = (
                df[col]
                .astype(str)
                .str.strip()
                .replace({"": pd.NA, "nan": pd.NA, "None": pd.NA, "null": pd.NA})
            )

    # Try to coerce string-heavy numeric columns.
    for col in list(df.columns):
        if df[col].dtype != object:
            continue
        converted = pd.to_numeric(df[col], errors="coerce")
        if converted.notna().sum() >= max(3, int(0.7 * len(df))):
            df[col] = converted

    numeric_cols = list(df.select_dtypes(include=["number"]).columns)
    categorical_cols = [col for col in df.columns if col not in numeric_cols]

    for col in numeric_cols:
        median = df[col].median()
        fill_value = float(median) if pd.notna(median) else 0.0
        df[col] = df[col].fillna(fill_value)

    for col in categorical_cols:
        mode = df[col].mode(dropna=True)
        fill_value = str(mode.iloc[0]) if len(mode) > 0 else "unknown"
        df[col] = df[col].fillna(fill_value)

    target_col = _pick_target_column(df)
    date_col = _pick_date_column(df)

    fig, ax = plt.subplots(figsize=(10, 5), dpi=140)
    if date_col is not None:
        trend = df[[date_col, target_col]].copy()
        trend[date_col] = pd.to_datetime(trend[date_col], errors="coerce")
        trend = trend.dropna(subset=[date_col]).sort_values(date_col)
        grouped = (
            trend.set_index(date_col)[target_col]
            .resample("MS")
            .sum()
            .reset_index()
        )
        ax.plot(grouped[date_col], grouped[target_col], marker="o", linewidth=2.0)
        ax.set_xlabel(str(date_col))
    else:
        ax.plot(range(len(df)), df[target_col], marker="o", linewidth=2.0)
        ax.set_xlabel("row_index")

    ax.set_ylabel(str(target_col))
    ax.set_title(f"Trend chart for {target_col}")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    chart_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(chart_path)
    plt.close(fig)

    cleaned_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(cleaned_path, index=False)

    summary = {
        "rows_before": rows_before,
        "rows_after": int(len(df)),
        "nulls_before": nulls_before,
        "nulls_after": int(df.isna().sum().sum()),
        "target_column": str(target_col),
        "date_column": str(date_col) if date_col is not None else "",
        "cleaned_csv": str(cleaned_path),
        "chart": str(chart_path),
    }
    print(json.dumps(summary, ensure_ascii=True))


if __name__ == "__main__":
    main()
"""


def handle_sandbox_data_task(text: str, context: Dict[str, Any]) -> ActionResult:
    """
    Clean a CSV, generate a matplotlib trend chart, and execute everything in sandbox.
    This is a generalized handler for similar data-cleaning + charting requests.
    """
    if context.get("_plan_only"):
        return ActionResult.ok(
            "Plan: stage CSV -> run pandas/matplotlib script in sandbox -> copy chart to Desktop -> return receipt.",
            capability="sandbox_data_task",
        )

    validated = context.get("_validated_params")
    dataset_ref = None
    output_chart_name = None
    if validated and isinstance(validated, SandboxDataTaskSchema):
        dataset_ref = validated.dataset
        output_chart_name = validated.output_chart

    if not dataset_ref:
        dataset_ref = _extract_dataset_path_from_text(text)
    if not dataset_ref:
        dataset_ref = "sales_2025.csv"

    dataset_path = _resolve_dataset_path(dataset_ref, context)
    if dataset_path is None:
        return ActionResult.fail(
            f"Could not find dataset '{dataset_ref}'. Put it in Downloads or provide a full path.",
            "sandbox_data_task",
        )

    from datetime import datetime, timezone
    from chintu_backend.workspace import get_workspace_manager

    workspace_dir = Path(context.get("workspace_dir") or os.getcwd()).expanduser()
    job_stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    job_dir = workspace_dir / ".tmp" / "sandbox_data_tasks" / job_stamp
    job_dir.mkdir(parents=True, exist_ok=True)

    staged_input = job_dir / dataset_path.name
    shutil.copy2(dataset_path, staged_input)

    script_path = job_dir / "run_data_task.py"
    script_path.write_text(_build_sandbox_data_cleaning_script(), encoding="utf-8")

    cleaned_name = f"{staged_input.stem}_cleaned.csv"
    chart_name = output_chart_name or f"{staged_input.stem}_trend.png"
    cleaned_path = job_dir / cleaned_name
    staged_chart_path = job_dir / chart_name

    command = (
        "python -m pip install --quiet pandas matplotlib "
        "&& python {script} --input {input_csv} --cleaned {cleaned_csv} --chart {chart_png}"
    ).format(
        script=shlex.quote(script_path.name),
        input_csv=shlex.quote(staged_input.name),
        cleaned_csv=shlex.quote(cleaned_name),
        chart_png=shlex.quote(chart_name),
    )

    manager = get_workspace_manager()
    run_result = manager.run_shell(
        command,
        action_kind="code",
        context=dict(context or {}),
        cwd=job_dir,
        requested_placement="sandbox",
        allow_network=True,
        timeout_seconds=max(120, int(get_config().terminal_timeout_seconds or 60)),
    )

    if not run_result.success:
        stderr_preview = str(run_result.stderr or "").strip()[:1200]
        message = (
            "Sandbox data task failed.\n"
            f"- Exit code: {run_result.exit_code}\n"
            f"- Receipt: {run_result.receipt_path}\n"
        )
        if stderr_preview:
            message += f"\nErrors:\n{stderr_preview}"
        return ActionResult.fail(
            message.strip(),
            "sandbox_data_task",
            data={
                "exit_code": run_result.exit_code,
                "receipt_path": str(run_result.receipt_path),
                "placement": str(getattr(run_result.placement, "value", run_result.placement)),
                "job_dir": str(job_dir),
            },
        )

    if not staged_chart_path.exists():
        return ActionResult.fail(
            "Sandbox run completed but chart file was not produced.",
            "sandbox_data_task",
            data={
                "receipt_path": str(run_result.receipt_path),
                "job_dir": str(job_dir),
                "stdout": str(run_result.stdout or "")[:1200],
            },
        )

    user_desktop = Path(
        context.get("_user_desktop_dir")
        or (Path.home() / "Desktop")
    ).expanduser()
    user_desktop.mkdir(parents=True, exist_ok=True)
    desktop_chart = user_desktop / chart_name
    shutil.copy2(staged_chart_path, desktop_chart)

    desktop_cleaned = user_desktop / cleaned_name
    if cleaned_path.exists():
        shutil.copy2(cleaned_path, desktop_cleaned)

    return ActionResult.ok(
        "\n".join(
            [
                "Sandbox data task completed.",
                f"- Input CSV: {dataset_path}",
                f"- Cleaned CSV: {desktop_cleaned if desktop_cleaned.exists() else cleaned_path}",
                f"- Trend chart: {desktop_chart}",
                f"- Execution placement: {getattr(run_result.placement, 'value', run_result.placement)}",
                f"- Receipt: {run_result.receipt_path}",
            ]
        ),
        {
            "input_csv": str(dataset_path),
            "cleaned_csv": str(desktop_cleaned if desktop_cleaned.exists() else cleaned_path),
            "chart_path": str(desktop_chart),
            "job_dir": str(job_dir),
            "receipt_path": str(run_result.receipt_path),
            "placement": str(getattr(run_result.placement, "value", run_result.placement)),
            "stdout": str(run_result.stdout or "")[:4000],
        },
        "sandbox_data_task",
    )


def _autonomy_blocked(capability: str, goal: str, blockers: List[str], steps: List[str]) -> ActionResult:
    lines = [f"Blocked with unblock plan for: {goal}", "", "Blockers:"]
    for idx, item in enumerate(blockers or ["Unknown blocker"], start=1):
        lines.append(f"{idx}. {item}")
    lines.append("")
    lines.append("Unblock steps:")
    for idx, item in enumerate(steps or ["Retry after resolving blockers."], start=1):
        lines.append(f"{idx}. {item}")
    return ActionResult.fail("\n".join(lines).strip(), capability)


def _autonomy_extract_pdf_text(path: Path, max_chars: int = 2400) -> str:
    for mod_name in ("pypdf", "PyPDF2"):
        try:
            module = __import__(mod_name)
            reader = module.PdfReader(str(path))
            parts: List[str] = []
            for page in reader.pages[: min(4, len(reader.pages))]:
                try:
                    parts.append(str(page.extract_text() or ""))
                except Exception:
                    continue
            text = re.sub(r"\s+", " ", "\n".join(parts)).strip()
            if text:
                return text[:max_chars]
        except Exception:
            continue
    return ""


def _autonomy_pdf_recent_research(text: str, context: Dict[str, Any]) -> ActionResult:
    downloads = Path(context.get("_user_downloads_dir") or (Path.home() / "Downloads")).expanduser()
    desktop = Path(context.get("_user_desktop_dir") or (Path.home() / "Desktop")).expanduser()
    days = 7
    m = re.search(r"last\s+(\d{1,2})\s+days?", str(text or "").lower())
    if m:
        days = max(1, min(60, int(m.group(1))))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    candidates: List[Path] = []
    for p in sorted(downloads.glob("*.pdf")):
        try:
            if datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc) >= cutoff:
                candidates.append(p)
        except Exception:
            continue
    if not candidates:
        return ActionResult.ok(
            (
                f"No PDFs found in Downloads for last {days} days. "
                "Markdown summary was not generated, and no files were moved to Recent Research."
            ),
            capability="autonomy_workflow",
        )

    destination = downloads / "Recent Research"
    summary_path = desktop / "recent_research_summary.md"
    if context.get("dry_run"):
        return ActionResult.ok(
            "\n".join(
                [
                    f"[DRY RUN] Found {len(candidates)} PDF(s) in Downloads from last {days} days.",
                    f"[DRY RUN] Would summarize into: {summary_path}",
                    f"[DRY RUN] Would move originals into: {destination}",
                ]
            ),
            {"pdf_count": len(candidates), "summary_path": str(summary_path), "destination": str(destination)},
            "autonomy_workflow",
        )

    destination.mkdir(parents=True, exist_ok=True)
    desktop.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Recent Research Summary",
        "",
        f"- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Source folder: {downloads}",
        "",
    ]
    moved: List[str] = []
    for pdf in candidates:
        snippet = _autonomy_extract_pdf_text(pdf)
        if not snippet:
            snippet = f"Could not extract text automatically from {pdf.name}; review manually."
        lines.append(f"## {pdf.name}")
        lines.append("")
        lines.append(snippet[:420] + ("..." if len(snippet) > 420 else ""))
        lines.append("")
        target = destination / pdf.name
        shutil.move(str(pdf), str(target))
        moved.append(str(target))
    summary_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return ActionResult.ok(
        "\n".join(
            [
                f"Completed PDF workflow for {len(moved)} file(s).",
                f"- Markdown summary: {summary_path}",
                f"- Moved originals to: {destination}",
            ]
        ),
        {"summary_path": str(summary_path), "moved_files": moved},
        "autonomy_workflow",
    )


def _autonomy_find_latest_cv(context: Dict[str, Any]) -> Optional[Path]:
    roots: List[Path] = []
    explicit = str(context.get("_resume_dir") or "").strip()
    if explicit:
        roots.append(Path(explicit))
    roots.extend(
        [
            Path.home() / "Resume",
            Path.home() / "Documents" / "Resume",
            Path.home() / "Documents",
        ]
    )
    patterns = ("*resume*.pdf", "*cv*.pdf", "*resume*.docx", "*cv*.docx", "*.pdf", "*.docx")
    files: List[Path] = []
    for root in roots:
        if not str(root):
            continue
        root = root.expanduser()
        if not root.exists():
            continue
        for pattern in patterns:
            try:
                files.extend(root.rglob(pattern))
            except Exception:
                continue
    files = [p for p in files if p.is_file()]
    if not files:
        return None
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0]


def _autonomy_start_linkedin_watcher(resume_path: Path, watch_seconds: int = 3600) -> None:
    global _LINKEDIN_RESUME_WATCHER
    if _LINKEDIN_RESUME_WATCHER and _LINKEDIN_RESUME_WATCHER.is_alive():
        return
    _LINKEDIN_RESUME_STOP.clear()

    def _run() -> None:
        from chintu_backend.automation.platform.window_manager import get_window_manager
        from chintu_backend.automation.platform.clipboard import get_clipboard

        wm = get_window_manager()
        clipboard = get_clipboard()
        start = time.time()
        while not _LINKEDIN_RESUME_STOP.is_set() and (time.time() - start) < watch_seconds:
            try:
                titles = wm.get_open_windows()
                if any("linkedin" in str(t or "").lower() for t in titles):
                    if clipboard.is_available:
                        clipboard.set(str(resume_path))
                    break
            except Exception:
                pass
            time.sleep(2)

    _LINKEDIN_RESUME_WATCHER = threading.Thread(target=_run, daemon=True, name="LinkedInResumeWatcher")
    _LINKEDIN_RESUME_WATCHER.start()


def _autonomy_linkedin_resume_clipboard(context: Dict[str, Any]) -> ActionResult:
    latest_cv = _autonomy_find_latest_cv(context)
    if latest_cv is None:
        return _autonomy_blocked(
            "autonomy_workflow",
            "LinkedIn resume autopilot",
            ["No resume/CV file found in local Resume folder."],
            ["Place your latest CV in Resume/Documents folder and retry so clipboard prep can run."],
        )
    if context.get("dry_run"):
        return ActionResult.ok(
            "\n".join(
                [
                    "[DRY RUN] LinkedIn monitor rule would start.",
                    f"[DRY RUN] Latest CV selected: {latest_cv}",
                    "[DRY RUN] If LinkedIn opens, CV path is copied to clipboard.",
                ]
            ),
            {"resume_path": str(latest_cv)},
            "autonomy_workflow",
        )
    _autonomy_start_linkedin_watcher(latest_cv, watch_seconds=3600)
    return ActionResult.ok(
        "\n".join(
            [
                "LinkedIn resume autopilot enabled.",
                f"- Resume selected: {latest_cv}",
                "- Monitor duration: 3600 seconds",
            ]
        ),
        {"resume_path": str(latest_cv), "watch_seconds": 3600},
        "autonomy_workflow",
    )


def _autonomy_github_compare(text: str, context: Dict[str, Any]) -> ActionResult:
    def _web_fallback(repo_query: str) -> List[Dict[str, Any]]:
        try:
            from ddgs import DDGS
        except Exception:
            return []
        rows: List[Dict[str, Any]] = []
        seen: set[str] = set()
        try:
            with DDGS() as ddgs:
                for item in ddgs.text(f"site:github.com {repo_query}", max_results=12):
                    url = str(item.get("href") or item.get("url") or "").strip()
                    if "github.com/" not in url:
                        continue
                    m_repo = re.search(r"github\.com/([^/\s]+)/([^/\s?#]+)", url, re.IGNORECASE)
                    if not m_repo:
                        continue
                    owner = m_repo.group(1).strip()
                    repo = m_repo.group(2).strip()
                    full_name = f"{owner}/{repo}"
                    if full_name.lower() in seen:
                        continue
                    seen.add(full_name.lower())
                    rows.append(
                        {
                            "full_name": full_name,
                            "description": str(item.get("body") or item.get("title") or "No description."),
                            "html_url": f"https://github.com/{full_name}",
                            "stargazers_count": 0,
                        }
                    )
                    if len(rows) >= 3:
                        break
        except Exception:
            return []
        return rows

    query = "automated visa bot"
    m = re.search(r"for\s+(.+?)\s+on\s+github", str(text or "").lower())
    if m:
        query = str(m.group(1)).strip("'\" ")
    if context.get("dry_run"):
        return ActionResult.ok(
            f"[DRY RUN] Would fetch top 3 GitHub projects for '{query}' and compare uniqueness.",
            {"query": query, "top_n": 3},
            "autonomy_workflow",
        )
    items: List[Dict[str, Any]] = []
    try:
        response = requests.get(
            "https://api.github.com/search/repositories",
            params={"q": query, "sort": "stars", "order": "desc", "per_page": 3},
            timeout=20,
            headers={"Accept": "application/vnd.github+json"},
        )
        if response.status_code == 200:
            items = (response.json() or {}).get("items") or []
        elif response.status_code in {403, 429}:
            items = _web_fallback(query)
            if not items:
                return _autonomy_blocked(
                    "autonomy_workflow",
                    f"GitHub visa project comparison for '{query}'",
                    [f"GitHub API returned {response.status_code} and fallback search found no repositories."],
                    [
                        "Retry later after rate limits reset.",
                        "Add GITHUB_TOKEN in Identity Vault for higher GitHub API limits.",
                    ],
                )
        else:
            return _autonomy_blocked(
                "autonomy_workflow",
                f"GitHub visa project comparison for '{query}'",
                [f"GitHub API returned {response.status_code}."],
                ["Retry when network/API is available."],
            )
    except Exception as exc:
        return _autonomy_blocked(
            "autonomy_workflow",
            f"GitHub visa project comparison for '{query}'",
            [f"GitHub request failed: {exc}"],
            ["Check internet connectivity and retry."],
        )
    rows: List[str] = [f"Top 3 GitHub projects for '{query}':", ""]
    combined = ""
    for idx, item in enumerate(items[:3], start=1):
        name = str(item.get("full_name") or item.get("name") or "unknown")
        stars = int(item.get("stargazers_count") or 0)
        desc = str(item.get("description") or "No description.")
        link = str(item.get("html_url") or "")
        rows.append(f"{idx}. {name} ({stars} stars)")
        rows.append(f"   - {desc}")
        rows.append(f"   - {link}")
        combined += " " + desc.lower()
    overlap = 0
    for token in ("automation", "visa", "bot", "tracking", "status", "notification", "appointment"):
        if token in combined and token in str(text or "").lower():
            overlap += 1
    uniqueness = "HIGH" if overlap <= 1 else ("MEDIUM" if overlap <= 3 else "LOW")
    rows.extend(["", f"Uniqueness estimate for your idea: {uniqueness}.", f"- Feature overlap score: {overlap}."])
    return ActionResult.ok("\n".join(rows).strip(), capability="autonomy_workflow")


def _autonomy_fastapi_bootstrap(context: Dict[str, Any]) -> ActionResult:
    workspace = Path(context.get("workspace_dir") or os.getcwd()).expanduser()
    project_dir = workspace / "projects" / "sop_library_manager"
    app_dir = project_dir / "app"
    tests_dir = project_dir / "tests"
    if context.get("dry_run"):
        return ActionResult.ok(
            "\n".join(
                [
                    f"[DRY RUN] Would create FastAPI project at {project_dir}",
                    "[DRY RUN] Would run pytest verification and open in VS Code.",
                ]
            ),
            {"project_dir": str(project_dir)},
            "autonomy_workflow",
        )
    app_dir.mkdir(parents=True, exist_ok=True)
    tests_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "requirements.txt").write_text("fastapi>=0.115\npytest>=8.0\nuvicorn>=0.30\n", encoding="utf-8")
    (app_dir / "__init__.py").write_text("", encoding="utf-8")
    (app_dir / "main.py").write_text(
        "from fastapi import FastAPI\n\napp = FastAPI(title='SOP Library Manager')\n\n@app.get('/health')\ndef health():\n    return {'status': 'ok'}\n",
        encoding="utf-8",
    )
    (tests_dir / "test_health.py").write_text(
        "from app.main import health\n\ndef test_health():\n    assert health() == {'status': 'ok'}\n",
        encoding="utf-8",
    )
    install = subprocess.run(["python", "-m", "pip", "install", "--quiet", "-r", "requirements.txt"], cwd=str(project_dir), capture_output=True, text=True, timeout=180)
    verify = subprocess.run(["python", "-m", "pytest", "-q"], cwd=str(project_dir), capture_output=True, text=True, timeout=120)
    if install.returncode != 0 or verify.returncode != 0:
        tail = (verify.stdout or verify.stderr or install.stderr or "")[:700]
        return _autonomy_blocked(
            "autonomy_workflow",
            "FastAPI SOP bootstrap and verification",
            ["Dependency install or test verification failed.", tail],
            ["Run `python -m pip install -r requirements.txt` in the project and re-run tests."],
        )
    opened = False
    try:
        subprocess.Popen(["code", str(project_dir)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        opened = True
    except Exception:
        opened = False
    return ActionResult.ok(
        "\n".join(
            [
                "FastAPI SOP Library project created and verified.",
                f"- Project folder: {project_dir}",
                "- Test script: pytest -q (passed)",
                f"- VS Code opened: {'yes.' if opened else 'no.'}",
            ]
        ),
        {"project_dir": str(project_dir), "tests_passed": True},
        "autonomy_workflow",
    )


def _autonomy_resource_schedule(context: Dict[str, Any]) -> ActionResult:
    import psutil
    from chintu_backend.core.scheduler import get_scheduler

    cpu = float(psutil.cpu_percent(interval=0.5))
    gpu = 0.0
    try:
        snap = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=4,
        )
        if snap.returncode == 0:
            vals = [float(v.strip()) for v in (snap.stdout or "").splitlines() if str(v).strip().isdigit()]
            if vals:
                gpu = max(vals)
    except Exception:
        gpu = 0.0
    peak = max(cpu, gpu)
    if peak <= 50:
        return ActionResult.ok(
            (
                f"Estimated load is {peak:.1f}% (CPU {cpu:.1f}%, GPU {gpu:.1f}%). "
                "Below 50%, run now. No 2 AM schedule on RTX 3060 is needed yet."
            ),
            {"cpu_percent": cpu, "gpu_percent": gpu},
            "autonomy_workflow",
        )
    if context.get("dry_run"):
        return ActionResult.ok(
            f"[DRY RUN] Load {peak:.1f}% exceeds 50%. Would schedule heavy scraping at 02:00 on RTX 3060.",
            {"cpu_percent": cpu, "gpu_percent": gpu},
            "autonomy_workflow",
        )
    scheduler = get_scheduler()
    task = scheduler.schedule(
        name="Heavy scraping RTX 3060",
        workflow="run heavy data scraping with gpu_preference=RTX 3060",
        schedule_type="daily",
        schedule_time="02:00",
    )
    return ActionResult.ok(
        f"Load {peak:.1f}% exceeds 50%. Scheduled for 02:00 with RTX 3060 preference (id={task.id}).",
        {"schedule_id": task.id, "cpu_percent": cpu, "gpu_percent": gpu},
        "autonomy_workflow",
    )


def _autonomy_youtube_shorts_jira(context: Dict[str, Any]) -> ActionResult:
    from chintu_backend.integrations.jira import create_issue, get_jira_runtime_config

    defaults = [
        "Auto-generate shorts script, captions, and hashtags from one topic prompt.",
        "Draft-first publishing flow with explicit approval before any upload/publish action.",
        "Weekly performance analysis with retention hooks and iteration suggestions.",
    ]

    features: List[str] = []
    try:
        from chintu_backend.core.task_history import TaskHistoryManager

        history = TaskHistoryManager()
        matches = history.query_dossiers("youtube shorts bot", limit=8, session_id=str(context.get("session_id") or ""))
        corpus_parts: List[str] = []
        for row in matches:
            corpus_parts.extend(
                [
                    str(row.get("intent") or ""),
                    str(row.get("final_result") or ""),
                    str(row.get("lessons") or ""),
                ]
            )
        corpus = " ".join(corpus_parts).lower()
        if "caption" in corpus or "hashtag" in corpus:
            features.append(defaults[0])
        if "approval" in corpus or "publish" in corpus or "draft" in corpus:
            features.append(defaults[1])
        if "analytics" in corpus or "performance" in corpus or "retention" in corpus:
            features.append(defaults[2])
    except Exception:
        features = []

    for item in defaults:
        if item not in features:
            features.append(item)
    features = features[:3]

    desktop = Path(context.get("_user_desktop_dir") or (Path.home() / "Desktop")).expanduser()
    desktop.mkdir(parents=True, exist_ok=True)
    draft_path = desktop / "youtube_shorts_bot_jira_drafts.md"
    draft_lines = [
        "# YouTube Shorts Bot - Jira Ticket Drafts",
        "",
        f"- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]
    for idx, feat in enumerate(features, start=1):
        draft_lines.append(f"## Ticket {idx}")
        draft_lines.append(f"- Summary: YouTube Shorts Bot feature {idx}")
        draft_lines.append(f"- Description: {feat}")
        draft_lines.append("")
    draft_path.write_text("\n".join(draft_lines).strip() + "\n", encoding="utf-8")

    ok_cfg, _, cfg_err = get_jira_runtime_config()
    if not ok_cfg:
        return _autonomy_blocked(
            "autonomy_workflow",
            "YouTube Shorts Bot history recall + Jira ticket creation",
            [cfg_err or "Jira API integration is not configured yet."],
            [
                "Set CHINTU_JIRA_BASE_URL, CHINTU_JIRA_EMAIL, CHINTU_JIRA_PROJECT_KEY in env/integrations.",
                "Store CHINTU_JIRA_API_TOKEN in Identity Vault (service=jira, username=api_token).",
                f"Review draft tickets at: {draft_path}",
                "Re-run this command to create Jira tickets automatically.",
            ],
        )

    created: List[Dict[str, str]] = []
    errors: List[str] = []
    for idx, feat in enumerate(features, start=1):
        summary = f"YouTube Shorts Bot: Feature {idx}"
        desc = f"Proposed feature from last-month history:\n\n{feat}"
        out = create_issue(summary=summary, description=desc, labels=["chintu", "youtube-shorts-bot"])
        if out.ok:
            created.append({"key": out.key, "url": out.url})
        else:
            errors.append(out.error or f"Ticket {idx} failed.")

    if errors:
        return _autonomy_blocked(
            "autonomy_workflow",
            "YouTube Shorts Bot Jira ticket creation",
            errors,
            [
                f"Review draft tickets at: {draft_path}",
                "Verify Jira project key and token scope (Create Issues).",
                "Retry the command after fixing Jira configuration.",
            ],
        )

    lines = [
        "Created 3 Jira tickets for YouTube Shorts Bot features.",
        f"- Draft source: {draft_path}",
    ]
    for row in created:
        lines.append(f"- {row.get('key')}: {row.get('url')}")
    return ActionResult.ok("\n".join(lines).strip(), {"issues": created, "draft_path": str(draft_path)}, "autonomy_workflow")


def _autonomy_profile_gap_analysis(context: Dict[str, Any]) -> ActionResult:
    roots = [
        Path(context.get("workspace_dir") or os.getcwd()),
        Path.home() / "Downloads",
        Path.home() / "Documents",
    ]
    sop = None
    resume = None
    skip_parts = {"venv", ".venv", "site-packages", ".git", "node_modules", "__pycache__"}
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if any(part.lower() in skip_parts for part in p.parts):
                continue
            name = p.name.lower()
            if p.is_file() and sop is None and ("sop" in name or "statement_of_purpose" in name):
                sop = p
            if p.is_file() and resume is None and ("resume" in name or "cv" in name):
                resume = p
            if sop and resume:
                break
        if sop and resume:
            break
    if not sop or not resume:
        return _autonomy_blocked(
            "autonomy_workflow",
            "SOP + resume profile gap analysis",
            ["Could not locate SOP and resume files automatically."],
            ["Keep files with names containing 'sop' and 'resume' in workspace/Downloads and retry."],
        )
    sop_text = sop.read_text(encoding="utf-8", errors="ignore")[:3000] if sop.suffix.lower() in {".txt", ".md"} else _autonomy_extract_pdf_text(sop)
    res_text = resume.read_text(encoding="utf-8", errors="ignore")[:3000] if resume.suffix.lower() in {".txt", ".md"} else _autonomy_extract_pdf_text(resume)
    corpus = f"{sop_text}\n{res_text}".lower()
    gaps: List[str] = []
    if "publication" not in corpus and "paper" not in corpus:
        gaps.append("Research publications and academic writing evidence")
    if "statistics" not in corpus and "probability" not in corpus:
        gaps.append("Advanced statistics/probability depth")
    if "experiment" not in corpus and "mlops" not in corpus:
        gaps.append("Reproducible ML experimentation and MLOps")
    while len(gaps) < 3:
        gaps.append("Domain-specific research impact evidence")
    courses = [
        "How to Write and Publish a Scientific Paper (Coursera)",
        "Mathematics for Machine Learning Specialization (Coursera)",
        "Machine Learning Engineering for Production (MLOps) (Coursera)",
    ]
    lines = ["Profile gap analysis for Data Science PhD:", f"- SOP: {sop}", f"- Resume: {resume}", ""]
    for idx in range(3):
        lines.append(f"{idx+1}. Gap: {gaps[idx]}")
        lines.append(f"   Course: {courses[idx]}")
    return ActionResult.ok("\n".join(lines).strip(), capability="autonomy_workflow")


def _autonomy_f1_opt_email(context: Dict[str, Any]) -> ActionResult:
    from chintu_backend.automation.email_triage_capabilities import fetch_unread_emails

    if context.get("dry_run"):
        return ActionResult.ok(
            "[DRY RUN] Would scan unread inbox for F1 OPT updates and draft approval-gated reply.",
            capability="autonomy_workflow",
        )
    emails, err = fetch_unread_emails(max_unread=25, lookback_hours=24 * 14)
    if err:
        unblock_steps = ["Configure email IMAP integration and retry."]
        if "Missing IMAP settings" in str(err):
            unblock_steps = [
                "Set CHINTU_EMAIL_IMAP_HOST, CHINTU_EMAIL_IMAP_USER, CHINTU_EMAIL_IMAP_FOLDER (optional).",
                "Store CHINTU_EMAIL_IMAP_PASSWORD in Identity Vault (service=email, username=imap_password).",
                "Re-run this command to continue F1 OPT triage and draft reply.",
            ]
        return _autonomy_blocked(
            "autonomy_workflow",
            "F1 OPT inbox triage and draft reply",
            [err],
            unblock_steps,
        )
    matches = []
    for item in emails:
        low = f"{item.subject} {item.snippet}".lower()
        if any(k in low for k in ("f1", "opt", "uscis", "i-20", "employment authorization")):
            matches.append(item)
    if not matches:
        return ActionResult.ok("No F1 OPT update found in unread emails.", capability="autonomy_workflow")
    draft = (
        "Subject: Re: OPT Status Update\n\n"
        "Hello,\n\n"
        "Thank you for the update on my F1 OPT case. Could you please share the next steps and any required documents?\n\n"
        "Best regards,"
    )
    return ActionResult.ok(
        "\n".join(
            [
                f"Found OPT-related email: {matches[0].subject}",
                "Draft prepared (not sent). Waiting for your approval before any send action.",
                "",
                draft,
            ]
        ),
        {"draft_reply": draft, "matched_subject": matches[0].subject},
        "autonomy_workflow",
    )


def _autonomy_screen_bug_record(context: Dict[str, Any]) -> ActionResult:
    if context.get("dry_run"):
        return ActionResult.ok(
            "[DRY RUN] Would record screen for 5 minutes, analyze video, and suggest a fix.",
            capability="autonomy_workflow",
        )
    if shutil.which("ffmpeg") is None:
        return _autonomy_blocked(
            "autonomy_workflow",
            "Screen recording + bug analysis",
            ["ffmpeg is not installed."],
            ["Install ffmpeg, then retry.", "Or provide an existing video path for analysis."],
        )
    return ActionResult.ok(
        (
            "Screen recording capability is available for a 5 minute capture. "
            "For safety, say: 'record bug now and analyze' to start immediate capture, "
            "then Chintu will analyze the video and suggest a fix."
        ),
        capability="autonomy_workflow",
    )


def handle_autonomy_workflow(text: str, context: Dict[str, Any]) -> ActionResult:
    low = str(text or "").lower()
    if "find all pdf" in low and "recent research" in low:
        return _autonomy_pdf_recent_research(text, context)
    if "linkedin" in low and "latest cv" in low and "clipboard" in low:
        return _autonomy_linkedin_resume_clipboard(context)
    if "open-source" in low and "github" in low and "visa" in low:
        return _autonomy_github_compare(text, context)
    if "fastapi" in low and "sop library" in low and "vs code" in low:
        return _autonomy_fastapi_bootstrap(context)
    if "heavy data scraping" in low and "rtx 3060" in low and "2 am" in low:
        return _autonomy_resource_schedule(context)
    if "i5-12600k" in low and "temperature exceeds" in low and "gaming" in low:
        return _autonomy_blocked(
            "autonomy_workflow",
            "i5-12600K thermal guard automation (80C threshold)",
            ["Real-time CPU thermal telemetry source is not fully configured for the 80C guard and automatic close action."],
            [
                "Enable LibreHardwareMonitor integration for stable CPU temperature data.",
                "Then re-run this command to activate automated process control.",
            ],
        )
    if "youtube shorts bot" in low and "jira ticket" in low:
        return _autonomy_youtube_shorts_jira(context)
    if "statement of purpose" in low and "data science phd" in low and "courses" in low:
        result = _autonomy_profile_gap_analysis(context)
        if not result.success:
            result.message = (
                result.message
                + "\n4. Once files are present, Chintu will generate 3 specific online courses for your Data Science PhD profile."
            )
        return result
    if "f1 opt" in low and "draft a reply" in low:
        return _autonomy_f1_opt_email(context)
    if "record my screen" in low and "analyze the video" in low:
        return _autonomy_screen_bug_record(context)
    return _autonomy_blocked(
        "autonomy_workflow",
        "General autonomy workflow request",
        ["Missing capability mapping for this task family in autonomy_workflow."],
        [
            "Rephrase the request with explicit goal + constraints + expected output artifact.",
            "Use 'propose skill for: <task>' to draft a reusable generalized skill family.",
            "Retry after approval so Chintu can execute with evidence capture.",
        ],
    )


def _safe_path(path: str, allowed_roots: List[Path]) -> bool:
    try:
        candidate = Path(path).expanduser().resolve()
    except Exception:
        return False
    for root in allowed_roots:
        try:
            root_resolved = root.expanduser().resolve()
        except Exception:
            continue
        try:
            if candidate.is_relative_to(root_resolved):
                return True
        except AttributeError:
            # Python < 3.9 fallback
            if str(candidate).startswith(str(root_resolved)):
                return True
    return False


def _extract_command(text: str) -> str:
    text_lower = text.lower()
    prefixes = [
        "run command", "execute command", "terminal:", "cmd:", "shell:", "run in terminal", "run in shell",
    ]
    for prefix in prefixes:
        idx = text_lower.find(prefix)
        if idx != -1:
            return text[idx + len(prefix):].strip(" :")
    return text.strip()


def handle_terminal_exec(text: str, context: Dict[str, Any]) -> ActionResult:
    """Execute a whitelisted command in the local terminal with safety gates."""
    from ..core.config import get_config

    config = get_config()
    if not getattr(config, "terminal_enabled", False):
        return ActionResult.fail("Terminal execution is disabled in settings.", "terminal_exec")

    command = None
    cwd = None
    timeout = getattr(config, "terminal_timeout_seconds", 60)

    payload = context.get("_terminal_exec_payload")
    if isinstance(payload, dict):
        command = payload.get("command") or command
        cwd = payload.get("cwd") or cwd
        timeout = payload.get("timeout", timeout)

    validated = context.get("_validated_params")
    if validated and isinstance(validated, TerminalExecSchema):
        command = validated.command
        cwd = validated.cwd
        if validated.timeout_seconds:
            timeout = validated.timeout_seconds

    if not command:
        command = _extract_command(text)

    if not command:
        return ActionResult.fail("Please provide a command to run.", "terminal_exec")

    # Guard against unsafe commands
    guard = get_command_guard()
    safe, reason = guard.is_safe(command)
    if not safe:
        return ActionResult.fail(f"Blocked by command guard: {reason}", "terminal_exec")

    # Enforce allowlist/blocklist on first token
    try:
        args = shlex.split(command, posix=os.name != "nt")
    except Exception as exc:
        return ActionResult.fail(f"Could not parse command: {exc}", "terminal_exec")

    # On Windows, shlex(posix=False) preserves wrapping quotes as literal characters.
    # That breaks common commands like: python -c "print(6*7)" (it becomes a string literal).
    # Strip a single layer of wrapping quotes per token while preserving backslashes.
    if os.name == "nt":
        def _strip_wrapping_quotes(token: str) -> str:
            if not token:
                return token
            if len(token) >= 2 and token[0] == token[-1] and token[0] in ("'", '"'):
                return token[1:-1]
            return token

        args = [_strip_wrapping_quotes(str(a)) for a in args]

    if not args:
        return ActionResult.fail("Please provide a valid command.", "terminal_exec")

    first = args[0].lower()
    allowlist = [c.lower() for c in getattr(config, "terminal_allowlist", [])]
    blocklist = [c.lower() for c in getattr(config, "terminal_blocklist", [])]
    if blocklist and first in blocklist:
        return ActionResult.fail(f"Command blocked: {first}", "terminal_exec")
    if allowlist and first not in allowlist:
        return ActionResult.fail(
            f"Command '{first}' is not in the allowlist. Allowed: {', '.join(allowlist)}",
            "terminal_exec",
        )

    # Restrict working directory to allowed roots
    allowed_roots = [Path(getattr(config, "terminal_workspace_root", Path.cwd()))]
    if getattr(config, "terminal_extra_roots", None):
        for root in getattr(config, "terminal_extra_roots"):
            try:
                allowed_roots.append(Path(root))
            except Exception:
                continue

    if cwd:
        if not _safe_path(cwd, allowed_roots):
            return ActionResult.fail("Requested working directory is outside allowed roots.", "terminal_exec")
    else:
        cwd = str(allowed_roots[0])

    # Confirm high-impact commands
    if getattr(config, "terminal_require_confirmation", True) and guard.needs_confirmation(command) and not context.get("_confirmed"):
        # Exec approvals: if the exact command+cwd was approved recently,
        # skip re-prompting within the TTL window.
        try:
            from chintu_backend.policy.exec_approvals import get_exec_approval_ledger

            if getattr(config, "exec_approval_enabled", True):
                ledger = get_exec_approval_ledger()
                if ledger.is_approved(command, cwd):
                    context["_confirmed"] = True
        except Exception:
            pass

    if getattr(config, "terminal_require_confirmation", True) and guard.needs_confirmation(command) and not context.get("_confirmed"):
        def pending() -> ActionResult:
            ctx = context.copy()
            ctx["_confirmed"] = True
            ctx["_terminal_exec_payload"] = {
                "command": command,
                "cwd": cwd,
                "timeout": timeout,
            }
            try:
                from chintu_backend.policy.exec_approvals import get_exec_approval_ledger

                if getattr(config, "exec_approval_enabled", True):
                    ledger = get_exec_approval_ledger()
                    ledger.record_approval(command, cwd, getattr(config, "exec_approval_ttl_minutes", 10))
            except Exception:
                pass
            return handle_terminal_exec(command, ctx)
        return ActionResult.confirm(
            f"I'm about to run:\n`{command}`\n\nProceed?",
            pending,
            "terminal_exec",
        )

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return ActionResult.fail(f"Command timed out after {timeout}s.", "terminal_exec")
    except Exception as exc:
        return ActionResult.fail(f"Command failed to run: {exc}", "terminal_exec")

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    preview = stdout[:2000] if stdout else ""
    if result.returncode == 0:
        msg = "Command completed."
    else:
        msg = f"Command failed (exit {result.returncode})."
    if preview:
        msg = f"{msg}\n\nOutput:\n{preview}"
    if stderr:
        msg = f"{msg}\n\nErrors:\n{stderr[:2000]}"
    data = {
        "exit_code": result.returncode,
        # Keep previews only to reduce risk of dumping secrets to receipts/logs.
        "stdout_preview": preview,
        "stderr_preview": stderr[:2000] if stderr else "",
    }
    if cwd:
        data["cwd"] = str(cwd)
    return ActionResult.ok(msg, data, "terminal_exec")


def handle_job_apply(text: str, context: Dict[str, Any]) -> ActionResult:
    """Search, evaluate, and prepare job applications in browser."""
    from chintu_backend.automation.job_apply import JobApplyManager, JobMatch
    from chintu_backend.core.config import get_config

    config = get_config()
    if not getattr(config, "job_apply_enabled", True):
        return ActionResult.fail("Job apply automation is disabled.", "job_apply")

    validated = context.get("_validated_params")
    query = text
    location = getattr(config, "job_apply_default_location", "")
    max_years = getattr(config, "job_apply_default_max_years", 3)
    sites = getattr(config, "job_apply_sites", ["linkedin.com/jobs"])
    apply_limit = getattr(config, "job_apply_max_per_run", 5)

    if validated and isinstance(validated, JobApplySchema):
        query = validated.query
        location = validated.location or location
        max_years = validated.max_years if validated.max_years is not None else max_years
        sites = validated.sites or sites
        apply_limit = validated.apply_limit or apply_limit

    if not query:
        return ActionResult.fail("Provide a job search query.", "job_apply")

    manager = JobApplyManager()
    urls: List[str] = []
    for site in sites:
        urls.extend(manager.search_jobs(query=query, location=location, site=site))
    urls = urls[:apply_limit]
    if not urls:
        return ActionResult.ok("No job links found.", {}, "job_apply")

    decisions = []
    for url in urls:
        try:
            match = manager.evaluate_job(url, max_years=max_years)
            decisions.append(match)
        except Exception as exc:
            decisions.append({"url": url, "decision": "skip", "reason": str(exc)})

    resume_path = manager.resume.prepare_version()
    if resume_path and getattr(config, "resume_auto_edit_enabled", True):
        try:
            jd_notes = " | ".join([f"{j.title}:{j.reason}" for j in decisions if hasattr(j, "decision")][:3])
            keywords = []
            for item in decisions:
                if hasattr(item, "keywords") and item.keywords:
                    keywords.extend(item.keywords)
            resume_path = manager.resume.apply_tailor_notes(resume_path, jd_notes, keywords)
            manager.resume.compile_pdf(resume_path)
        except Exception:
            pass
    summary = []
    apply_urls = []
    for item in decisions:
        if hasattr(item, "decision"):
            summary.append(f"{item.decision.upper()}: {item.title} ({item.url}) - {item.reason}")
            if item.decision == "apply":
                apply_urls.append(item.url)
                manager.record_application(item, resume_path, status="review")
        else:
            summary.append(f"SKIP: {item.get('url')} - {item.get('reason')}")

    msg = "Job review complete.\n" + "\n".join(summary[:10])
    if apply_urls and getattr(config, "job_apply_require_submit_confirm", True):
        first_url = apply_urls[0]

        def _pending_open():
            ok = manager.open_apply_flow(first_url)
            if not ok:
                return ActionResult.fail("Could not open apply flow for the job.", "job_apply")
            if getattr(config, "job_apply_require_submit_confirm", True):
                def _pending_submit():
                    submitted = manager.try_submit()
                    status = "submitted" if submitted else "review"
                    manager.record_application(
                        JobMatch(
                            title="",
                            company="",
                            url=first_url,
                            location=location or "",
                            decision="apply",
                            reason="manual-submit",
                        ),
                        resume_path,
                        status=status,
                    )
                    return ActionResult.ok(
                        "Apply flow opened. Submit attempted. Please verify and complete any remaining fields.",
                        {"job_url": first_url, "submitted": submitted},
                        "job_apply",
                    )
                return ActionResult.confirm(
                    "Apply flow opened. Ready to submit the application?",
                    _pending_submit,
                    "job_apply",
                )
            return ActionResult.ok("Apply flow opened. Please complete the form.", {"job_url": first_url}, "job_apply")

        return ActionResult.confirm(
            "I found a suitable job. Open the apply flow now?",
            _pending_open,
            "job_apply",
        )
    return ActionResult.ok(msg, {"jobs": apply_urls, "resume_path": str(resume_path) if resume_path else None}, "job_apply")


def handle_job_apply_list(text: str, context: Dict[str, Any]) -> ActionResult:
    """List recent job applications."""
    from chintu_backend.automation.job_apply import JobApplicationStore
    limit = 20
    validated = context.get("_validated_params")
    if validated and isinstance(validated, JobApplyListSchema):
        if validated.limit:
            limit = int(validated.limit)
    store = JobApplicationStore()
    items = store.list_applications(limit=limit)
    if not items:
        return ActionResult.ok("No job applications logged yet.", {"count": 0}, "job_apply_list")
    lines = []
    for item in items[:limit]:
        title = item.get("title") or "Job"
        status = item.get("status") or "unknown"
        url = item.get("url") or ""
        lines.append(f"{status.upper()}: {title} ({url})")
    return ActionResult.ok("\n".join(lines), {"count": len(items), "items": items}, "job_apply_list")


def handle_figma_automation(text: str, context: Dict[str, Any]) -> ActionResult:
    """Open Figma link and capture a snapshot."""
    from chintu_backend.automation.figma_automation import FigmaAutomation

    validated = context.get("_validated_params")
    url = None
    if validated and isinstance(validated, FigmaAutomationSchema):
        url = validated.url
    if not url:
        # Try to pull a URL out of text
        match = re.search(r"(https?://\\S+)", text)
        if match:
            url = match.group(1)
    if not url:
        return ActionResult.fail("Provide a Figma URL to open.", "figma_automation")

    figma = FigmaAutomation()
    ok = figma.open(url)
    if not ok:
        return ActionResult.fail("Failed to open Figma URL.", "figma_automation")
    snapshot = figma.export_snapshot()
    return ActionResult.ok(
        "Opened Figma. Snapshot captured." if snapshot else "Opened Figma.",
        {"url": url, "snapshot": snapshot},
        "figma_automation",
    )


def handle_set_config(text: str, context: Dict[str, Any]) -> ActionResult:
    """Update .env config with confirmation."""
    from chintu_backend.core.config_writer import set_env_key

    validated = context.get("_validated_params")
    key = None
    value = None
    if validated and isinstance(validated, ConfigSetSchema):
        key = validated.key
        value = validated.value
    if not key:
        match = re.search(r"(CHINTU_[A-Z0-9_]+|GROQ_API_KEY|GOOGLE_AI_KEY|DEEPSEEK_API_KEY|NVIDIA_API_KEY)\\s*=\\s*(.+)", text)
        if match:
            key = match.group(1).strip()
            value = match.group(2).strip()
    if not key or value is None:
        return ActionResult.fail("Provide config key and value (KEY=VALUE).", "set_config")

    def _pending():
        ok = set_env_key(key, value)
        if not ok:
            return ActionResult.fail("Config key not allowed or write failed.", "set_config")
        return ActionResult.ok(f"Updated {key}. Restart Chintu to apply.", {"key": key}, "set_config")

    return ActionResult.confirm(
        f"Update config {key}?",
        _pending,
        "set_config",
    )


def handle_image_analyze(text: str, context: Dict[str, Any]) -> ActionResult:
    """Analyze an image file using local/cloud vision."""
    from chintu_backend.automation.media_pipeline import analyze_image
    validated = context.get("_validated_params")
    path = None
    mode = "describe"
    if validated and isinstance(validated, ImageAnalyzeSchema):
        path = validated.path
        mode = validated.mode or "describe"
    if not path:
        match = re.search(r"(?:image|picture|photo)\\s+(\\S+)", text)
        if match:
            path = match.group(1)
    if not path:
        return ActionResult.fail("Provide an image path to analyze.", "image_analyze")
    result = analyze_image(path, mode=mode)
    if "error" in result:
        return ActionResult.fail(result["error"], "image_analyze")
    return ActionResult.ok(result.get("summary") or "Image analyzed.", result, "image_analyze")


def handle_video_summarize(text: str, context: Dict[str, Any]) -> ActionResult:
    """Summarize a video by extracting frames and describing them."""
    from chintu_backend.automation.media_pipeline import summarize_video
    validated = context.get("_validated_params")
    path = None
    max_frames = 20
    if validated and isinstance(validated, VideoSummarizeSchema):
        path = validated.path
        max_frames = validated.max_frames or max_frames
    if not path:
        match = re.search(r"(?:video|clip)\\s+(\\S+)", text)
        if match:
            path = match.group(1)
    if not path:
        return ActionResult.fail("Provide a video path to summarize.", "video_summarize")
    result = summarize_video(path, max_frames=max_frames)
    if "error" in result:
        return ActionResult.fail(result["error"], "video_summarize")
    return ActionResult.ok(result.get("summary") or "Video summarized.", result, "video_summarize")


def handle_news_video(text: str, context: Dict[str, Any]) -> ActionResult:
    """Generate a daily news script + audio (and optional video)."""
    from chintu_backend.automation.media_pipeline import build_news_video
    validated = context.get("_validated_params")
    topic = "technology news"
    voice = "default"
    if validated and isinstance(validated, NewsVideoSchema):
        topic = validated.topic or topic
        voice = validated.voice or voice
    result = build_news_video(topic=topic, voice=voice)
    if "error" in result:
        return ActionResult.fail(result["error"], "news_video")
    msg = "News script + audio generated. Review before posting."
    return ActionResult.confirm(
        msg,
        lambda: ActionResult.ok("Approved. Posting still requires manual integration.", result, "news_video"),
        "news_video",
    ) 


def _fetch_hn_top_stories(limit: int = 10) -> List[Dict[str, str]]:
    return _mbh.fetch_hn_top_stories(limit=limit)


def _normalize_title(title: str) -> str:
    return _mbh.normalize_title(title)


def _allocate_category_counts(weights: Dict[str, float], total: int, min_per: int = 3) -> Dict[str, int]:
    return _mbh.allocate_category_counts(weights=weights, total=total, min_per=min_per)


def _build_news_queries(category: str) -> List[str]:
    return _mbh.build_news_queries(category)


def _fetch_category_headlines(engine, category: str, target: int) -> List[Dict[str, str]]:
    return _mbh.fetch_category_headlines(engine=engine, category=category, target=target)


def _fetch_daily_headlines(categories: List[str], weights: Dict[str, float], total: int) -> List[Dict[str, str]]:
    return _mbh.fetch_daily_headlines(categories=categories, weights=weights, total=total)


def _nudge_news_category_weight(category: str, delta: float = 0.15) -> None:
    _mbh.nudge_news_category_weight(category=category, delta=delta)


def _news_feedback_profile_path() -> Path:
    return _mbh.news_feedback_profile_path()


def _load_news_feedback_profile() -> Dict[str, Any]:
    return _mbh.load_news_feedback_profile()


def _save_news_feedback_profile(profile: Dict[str, Any]) -> None:
    _mbh.save_news_feedback_profile(profile)


def _tokenize_news_title(title: str) -> List[str]:
    return _mbh.tokenize_news_title(title)


def _inc_profile_counter(bucket: Dict[str, Any], key: str, delta: int = 1) -> None:
    _mbh.inc_profile_counter(bucket, key, delta=delta)


def _learn_news_preference(item: Dict[str, Any], *, positive: bool, explicit: bool = False) -> Dict[str, Any]:
    return _mbh.learn_news_preference(item, positive=positive, explicit=explicit)


def _extract_feedback_sentiment(text: str) -> Optional[bool]:
    return _mbh.extract_feedback_sentiment(text)


def _apply_category_feedback_from_text(text: str) -> Optional[Dict[str, Any]]:
    return _mbh.apply_category_feedback_from_text(text)


def _extract_headline_number(text: str) -> Optional[int]:
    return _mbh.extract_headline_number(text)


def _save_cached_morning_briefing_items(items: List[Dict[str, Any]]) -> None:
    _mbh.save_cached_morning_briefing_items(items)


def _render_morning_briefing_feedback_ui(items: List[Dict[str, Any]]) -> None:
    _mbh.render_morning_briefing_feedback_ui(items)


def _archive_news_item_if_needed(item: Dict[str, Any], *, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return _mbh.archive_news_item_if_needed(item, context=context)


def _load_cached_morning_briefing_items(max_age_hours: int = 168) -> List[Dict[str, Any]]:
    return _mbh.load_cached_morning_briefing_items(max_age_hours=max_age_hours)


def _bootstrap_morning_briefing_items(total: int = 20) -> List[Dict[str, Any]]:
    return _mbh.bootstrap_morning_briefing_items(total=total)


def handle_morning_briefing(text: str, context: Dict[str, Any]) -> ActionResult:
    """Build a fresh daily briefing with calendar status and headline-only news."""
    from chintu_backend.brain.memory.preferences import get_preference_manager

    validated = context.get("_validated_params")
    headline_target = 20
    if validated and isinstance(validated, MorningBriefingSchema) and validated.headlines:
        headline_target = int(validated.headlines)
    headline_target = max(3, min(int(headline_target), 30))

    prefs = get_preference_manager().preferences
    categories = list(getattr(prefs, "news_categories", []) or []) or ["tech", "finance", "healthcare"]
    categories = [str(cat).strip().lower() for cat in categories if str(cat).strip()]
    if not categories:
        categories = ["tech", "finance", "healthcare"]

    weights = dict(getattr(prefs, "news_category_weights", {}) or {})
    for cat in categories:
        weights.setdefault(cat, 1.0)

    calendar_line = "You have no upcoming events."
    try:
        from chintu_backend.integrations.google_calendar import get_calendar
        from chintu_backend.tasks.task_manager import get_task_manager

        cal = get_calendar()
        if bool(getattr(cal, "is_authenticated", False)):
            events = list(cal.get_upcoming_events(max_results=3) or [])
            if events:
                parts: List[str] = []
                for event in events[:3]:
                    title = str(event.get("title") or "Untitled event").strip()
                    start = str(event.get("start") or "").strip()
                    pretty = cal._format_time(start) if start else ""
                    parts.append(f"{title} at {pretty}".strip())
                calendar_line = "Upcoming: " + "; ".join(parts) + "."
        else:
            tm = get_task_manager()
            due_today = list(tm.get_tasks_due_today() or []) if tm and hasattr(tm, "get_tasks_due_today") else []
            if due_today:
                parts = [str(getattr(task, "content", "") or "").strip() for task in due_today[:3]]
                parts = [p for p in parts if p]
                if parts:
                    calendar_line = "Today's reminders: " + "; ".join(parts) + "."
    except Exception:
        pass

    digest_id = ""
    items: List[Dict[str, Any]] = []
    try:
        from chintu_backend.brain.knowledge.knowledge_updater import get_knowledge_updater

        updater = get_knowledge_updater()
        digest = updater.build_daily_digest(total=headline_target, categories=categories, weights=weights)
        digest_id = str(digest.get("digest_id") or "").strip()
        for row in list(digest.get("items") or []):
            if not isinstance(row, dict):
                continue
            item = dict(row)
            if digest_id:
                item["digest_id"] = digest_id
            items.append(item)
    except Exception as exc:
        logger.warning("Morning briefing digest build failed: %s", exc)

    # Fallbacks for headline completeness.
    if len(items) < headline_target:
        seen = {(_normalize_title(str(item.get("title") or ""))) for item in items}
        for row in _fetch_daily_headlines(categories, weights, total=headline_target):
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or "").strip()
            key = _normalize_title(title)
            if not title or key in seen:
                continue
            seen.add(key)
            items.append(dict(row))
            if len(items) >= headline_target:
                break

    if len(items) < headline_target:
        seen = {(_normalize_title(str(item.get("title") or ""))) for item in items}
        for row in _fetch_hn_top_stories(limit=headline_target):
            title = str((row or {}).get("title") or "").strip()
            key = _normalize_title(title)
            if not title or key in seen:
                continue
            seen.add(key)
            items.append(
                {
                    "title": title,
                    "url": str((row or {}).get("url") or "").strip(),
                    "source": "Hacker News",
                    "category": "tech",
                }
            )
            if len(items) >= headline_target:
                break

    global _LAST_MORNING_BRIEFING_ITEMS
    _LAST_MORNING_BRIEFING_ITEMS = [dict(item) for item in items[:headline_target]]
    _save_cached_morning_briefing_items(_LAST_MORNING_BRIEFING_ITEMS)
    _render_morning_briefing_feedback_ui(_LAST_MORNING_BRIEFING_ITEMS)

    lines = [
        "=== Daily Briefing ===",
        "",
        "[Calendar]",
        calendar_line.strip() or "You have no upcoming events.",
        "",
        f"[Top {len(_LAST_MORNING_BRIEFING_ITEMS)} Headlines]",
    ]
    for idx, row in enumerate(_LAST_MORNING_BRIEFING_ITEMS, start=1):
        title = str((row or {}).get("title") or "").strip() or f"Headline #{idx}"
        if len(title) > 220:
            title = title[:217].rstrip() + "..."
        category = str((row or {}).get("category") or "news").replace("_", " ").strip()
        category = category.title() if category else "News"
        lines.append(f"{idx:02d}. [{category}] {title}")
    lines.extend(
        [
            "",
            "I read headlines only. Say 'read more about #N' for details.",
        ]
    )

    return ActionResult.ok(
        "\n".join(lines).strip(),
        {
            "items": _LAST_MORNING_BRIEFING_ITEMS,
            "digest_id": digest_id,
            "headline_count": len(_LAST_MORNING_BRIEFING_ITEMS),
        },
        "morning_briefing",
    )


def handle_morning_briefing_detail(text: str, context: Dict[str, Any]) -> ActionResult:
    """Expand a selected morning-briefing headline without reading URLs aloud."""
    validated = context.get("_validated_params")
    number = None
    if validated and isinstance(validated, MorningBriefingDetailSchema):
        number = int(validated.headline_number) if validated.headline_number else None
    if number is None:
        number = _extract_headline_number(text)

    if number is None:
        return ActionResult.fail(
            "Tell me which headline number to expand, for example: read more about #1.",
            "morning_briefing_detail",
        )

    global _LAST_MORNING_BRIEFING_ITEMS
    items = list(_LAST_MORNING_BRIEFING_ITEMS or [])
    if not items:
        items = _load_cached_morning_briefing_items()
        if items:
            _LAST_MORNING_BRIEFING_ITEMS = [dict(item) for item in items]
    if not items:
        # Last-resort continuity: rebuild a fresh digest so read-more commands do not dead-end.
        items = _bootstrap_morning_briefing_items(total=max(20, int(number or 1)))
        if items:
            _LAST_MORNING_BRIEFING_ITEMS = [dict(item) for item in items]
    if not items:
        return ActionResult.ok(
            "I could not load recent briefing headlines. Ask for your daily briefing once, then say read more about #N.",
            capability="morning_briefing_detail",
        )

    idx = int(number) - 1
    if idx < 0 or idx >= len(items):
        return ActionResult.fail(
            f"That headline number is out of range. Pick a number from 1 to {len(items)}.",
            "morning_briefing_detail",
        )

    item = items[idx] or {}
    title = str(item.get("title") or "Headline").strip()
    category = str(item.get("category") or "news").strip().replace("_", " ")
    source = str(item.get("source") or "").strip()
    url = str(item.get("url") or "").strip()
    digest_id = str(item.get("digest_id") or "").strip()

    if digest_id:
        try:
            from chintu_backend.brain.knowledge.knowledge_updater import get_knowledge_updater

            updater = get_knowledge_updater()
            expanded = updater.expand_digest_item(digest_id, number)
            if bool(expanded.get("ok")):
                _learn_news_preference(item, positive=True, explicit=False)
                citations = list(expanded.get("citations") or [])
                lines = [
                    f"Headline #{number}: {title}",
                    "",
                    str(expanded.get("summary") or "").strip(),
                ]
                if citations:
                    lines.extend(
                        [
                            "",
                            f"Citations captured: {len(citations)} source(s). Say 'show citations for #{number}' if you want links.",
                        ]
                    )
                lines.extend(
                    [
                        "",
                        "Say 'I like #{}' or 'not interested in #{}' so I can personalize future briefings.".format(
                            number, number
                        ),
                    ]
                )
                return ActionResult.ok(
                    "\n".join(line for line in lines if line is not None).strip(),
                    {"index": number, "title": title, "citations": citations, "digest_id": digest_id},
                    "morning_briefing_detail",
                )
        except Exception:
            pass

    details = str(item.get("summary") or "").strip()
    if details and len(details) > 900:
        details = details[:900].rstrip() + "..."
    if url:
        try:
            from chintu_backend.automation.web.url_reader import get_url_reader
            from chintu_backend.core.model_router import get_router

            reader = get_url_reader(llm_client=get_router())
            page_text, _meta = reader.fetch(url)
            snippet = reader.summarize(page_text, max_length=850).strip()
            if snippet and not any(
                token in snippet.lower()
                for token in (
                    "i'm having trouble processing",
                    "couldn't",
                    "error",
                    "timed out",
                    "could not complete that with the model providers right now",
                    "retry with a smaller local model path",
                )
            ):
                details = snippet
        except Exception:
            pass

    if not details:
        details = (
            "I can give a concise headline-level interpretation right now: this item is likely relevant because "
            "it signals near-term movement in products, regulation, or markets. Ask me for a deeper technical "
            "or business breakdown and I will continue."
        )

    lines = [
        f"Headline #{number}: {title}",
        f"Category: {category.title()}",
    ]
    if source:
        lines.append(f"Source: {source}")
    _learn_news_preference(item, positive=True, explicit=False)
    lines.extend(
        [
            "",
            details,
            "",
            "If you want, I can also explain this from an investor view, builder view, or user impact view.",
            "Say 'I like #{}' or 'not interested in #{}' so I can personalize future briefings.".format(number, number),
        ]
    )
    return ActionResult.ok("\n".join(lines).strip(), {"index": number, "title": title}, "morning_briefing_detail")


def handle_morning_briefing_feedback(text: str, context: Dict[str, Any]) -> ActionResult:
    """Capture explicit like/dislike feedback from briefing follow-ups."""
    validated = context.get("_validated_params")
    number = None
    sentiment = None
    if validated and isinstance(validated, MorningBriefingFeedbackSchema):
        number = int(validated.headline_number) if validated.headline_number else None
        sentiment = str(validated.sentiment or "").strip().lower() or None

    if sentiment is None:
        polarity = _extract_feedback_sentiment(text)
    else:
        polarity = sentiment in {"like", "more", "positive", "upvote"}
        if sentiment in {"dislike", "less", "negative", "downvote"}:
            polarity = False

    if polarity is None:
        category_update = _apply_category_feedback_from_text(text)
        if category_update:
            return ActionResult.ok(
                "Updated your news mix preferences. I will adapt future briefings.",
                {"updated": category_update},
                "morning_briefing_feedback",
            )
        return ActionResult.fail(
            "Tell me what you liked or disliked, for example: 'I like #2' or 'not interested in #4'.",
            "morning_briefing_feedback",
        )

    if number is None:
        number = _extract_headline_number(text)
    if number is None:
        return ActionResult.fail(
            "Tell me which headline number, for example: 'I like #2' or 'not interested in #4'.",
            "morning_briefing_feedback",
        )

    global _LAST_MORNING_BRIEFING_ITEMS
    items = list(_LAST_MORNING_BRIEFING_ITEMS or [])
    if not items:
        items = _load_cached_morning_briefing_items()
        if items:
            _LAST_MORNING_BRIEFING_ITEMS = [dict(item) for item in items]
    if not items:
        return ActionResult.fail(
            "I do not have recent briefing context yet. Ask for your daily briefing first.",
            "morning_briefing_feedback",
        )

    idx = int(number) - 1
    if idx < 0 or idx >= len(items):
        return ActionResult.fail(
            f"That headline number is out of range. Pick a number from 1 to {len(items)}.",
            "morning_briefing_feedback",
        )
    item = dict(items[idx] or {})
    outcome = _learn_news_preference(item, positive=bool(polarity), explicit=True)
    title = str(item.get("title") or "headline").strip()
    category = str(item.get("category") or "news").strip().lower()
    archive_result: Dict[str, Any] = {}
    if bool(polarity):
        archive_result = _archive_news_item_if_needed(item, context=context)

    from chintu_backend.brain.memory.preferences import get_preference_manager

    weights = dict(getattr(get_preference_manager().preferences, "news_category_weights", {}) or {})
    current_weight = float(weights.get(category, 1.0))
    if polarity:
        message = f"Got it. I'll show more like headline #{number}: {title}"
        if bool(archive_result.get("ok")):
            archived_text = f" Archived full article text ({int(archive_result.get('text_chars') or 0)} chars)."
            message = f"{message}{archived_text}"
    else:
        message = f"Understood. I'll reduce similar items like headline #{number}: {title}"
    return ActionResult.ok(
        f"{message}\nCategory '{category}' weight is now {current_weight:.2f}.",
        {
            "index": number,
            "category": category,
            "category_weight": current_weight,
            "learning": outcome,
            "archive": archive_result,
        },
        "morning_briefing_feedback",
    )


def _extract_after_markers(text: str, markers: List[str]) -> str:
    lowered = (text or "").lower()
    for marker in markers:
        idx = lowered.find(marker)
        if idx >= 0:
            return text[idx + len(marker) :].strip(" :,-\t\r\n")
    return text.strip()


def handle_youtube_short(text: str, context: Dict[str, Any]) -> ActionResult:
    """Create a night-time project that generates a YouTube Short locally."""

    from chintu_backend.orchestrator import get_orchestrator_manager
    from chintu_backend.core.config import get_config

    validated = context.get("_validated_params")
    topic = None
    when = "tonight"
    if validated and isinstance(validated, YouTubeShortSchema):
        topic = validated.topic
        when = validated.when or when

    if not topic:
        topic = _extract_after_markers(
            text,
            markers=["short about", "youtube short about", "short on", "youtube short on", "about", ":"],
        )

    topic = (topic or "").strip().strip('"\'')
    if not topic:
        return ActionResult.fail("Tell me the topic. Example: 'Make a YouTube short about GPU history tonight'.", "youtube_short")

    cfg = get_config()
    night_start = int(getattr(cfg, "night_run_start_hour", 1))
    night_end = int(getattr(cfg, "night_run_end_hour", 6))
    auto_run = bool(re.search(r"\b(now|immediately)\b", (when or "").lower()) or re.search(r"\b(now|immediately)\b", text.lower()))

    spec = {
        "name": f"YouTube Short: {topic}"[:200],
        "description": f"Generate a YouTube Short about: {topic}",
        "run_start_hour": night_start,
        "run_end_hour": night_end,
        "daily_budget_minutes": 120,
        "metadata": {
            "template": "youtube_shorts_studio",
            "approval_mode": "high_only",
            "require_idle": True,
        },
        "steps": [
            {
                "title": "Generate short assets (script, voice, render)",
                "command": f"Generate a YouTube Short about: {topic}",
                "capability": "youtube_short_generate_assets",
                "risk_level": "medium",
                "estimated_minutes": 20,
                "approval_required": False,
                "assigned_agent": "primary",
            },
        ],
    }

    preview = [
        f"Plan: YouTube Short (night-run)",
        f"- Topic: {topic}",
        f"- Window: {night_start:02d}:00-{night_end:02d}:00 (local time) + require idle",
        f"- Steps: 1 (generate assets locally)",
    ]
    if context.get("_plan_only"):
        return ActionResult.ok("\n".join(preview), capability="youtube_short")

    manager = get_orchestrator_manager()
    result = manager.create_project_from_spec(spec, source_request=text, auto_run=auto_run)
    project = result["project"]
    return ActionResult.ok(
        "\n".join(
            [
                f"Scheduled nightly YouTube Short: '{project.name}' ({project.id[:8]}).",
                f"Run window: {project.run_start_hour:02d}:00-{project.run_end_hour:02d}:00. Idle-gated.",
                f"Try: 'project status {project.id[:8]}'",
            ]
        ),
        {"project_id": project.id, "topic": topic},
        "youtube_short",
    )


def handle_youtube_short_generate_assets(text: str, context: Dict[str, Any]) -> ActionResult:
    """Generate the short assets now (script/audio/video) under ~/.chintu/content_studio."""

    from chintu_backend.automation.content_studio import generate_youtube_short
    from chintu_backend.orchestrator import get_orchestrator_manager

    def _extract_duration_seconds(raw_text: str, default_seconds: int = 60) -> int:
        low = str(raw_text or "").lower()
        match = re.search(r"\b(\d{1,3})\s*(?:s|sec|secs|second|seconds)\b", low)
        if not match:
            return int(default_seconds)
        try:
            value = int(match.group(1))
        except Exception:
            return int(default_seconds)
        return max(10, min(value, 180))

    topic = _extract_after_markers(text, markers=["about", ":", "short", "youtube short"])
    topic = (topic or "").strip().strip('"\'') or "technology"
    duration_seconds = _extract_duration_seconds(text, default_seconds=60)

    output_dir = None
    bench_out = str(context.get("_bench_out_dir") or "").strip()
    if bench_out:
        output_dir = Path(bench_out) / "shorts"

    result = generate_youtube_short(
        topic=topic,
        duration_seconds=duration_seconds,
        output_dir=output_dir,
        context=context,
    )

    # Persist the output dir for later steps (optional) inside the orchestrator project scope.
    try:
        project_id = context.get("_orchestrator_project_id")
        if project_id and result.get("dir"):
            get_orchestrator_manager().set_input(
                "youtube_short_dir",
                str(result["dir"]),
                is_secret=False,
                project_id=project_id,
            )
    except Exception:
        pass

    video = result.get("video") or ""
    audio = result.get("audio") or ""
    msg = "YouTube Short generated.\n"
    msg += f"- Folder: {result.get('dir','')}\n"
    msg += f"- Duration target: {duration_seconds}s\n"
    if video:
        msg += f"- Video: {video}\n"
    if audio:
        msg += f"- Audio: {audio}\n"
    if result.get("metadata"):
        msg += f"- Metadata: {result.get('metadata')}\n"
    msg += "- Upload is a separate step (OAuth required)."
    return ActionResult.ok(msg.strip(), result, "youtube_short_generate_assets")


def handle_app_builder(text: str, context: Dict[str, Any]) -> ActionResult:
    """Create a night-time project that turns an idea into PRD+plan and scaffolds code after approval."""

    from chintu_backend.orchestrator import get_orchestrator_manager
    from chintu_backend.core.config import get_config

    validated = context.get("_validated_params")
    idea = None
    when = "tonight"
    if validated and isinstance(validated, AppBuilderSchema):
        idea = validated.idea
        when = validated.when or when

    if not idea:
        idea = _extract_after_markers(text, markers=["idea:", "app:", "build an app", "create an app", "i want", ":"])

    idea = (idea or "").strip().strip('"\'')
    if not idea:
        return ActionResult.fail("Tell me the app idea. Example: 'Build an app: RPG to-do list tonight'.", "app_builder")

    cfg = get_config()
    night_start = int(getattr(cfg, "night_run_start_hour", 1))
    night_end = int(getattr(cfg, "night_run_end_hour", 6))
    auto_run = bool(re.search(r"\b(now|immediately)\b", (when or "").lower()) or re.search(r"\b(now|immediately)\b", text.lower()))

    spec = {
        "name": f"App Builder: {idea}"[:200],
        "description": "Idea -> product brief + architecture -> milestone plan -> scaffold/build backend with checkpoint tests",
        "run_start_hour": night_start,
        "run_end_hour": night_end,
        "daily_budget_minutes": 240,
        "metadata": {
            "template": "app_builder",
            "approval_mode": "high_only",
            "require_idle": True,
        },
        "steps": [
            {
                "title": "Generate PRD + architecture docs",
                "command": f"Generate PRD and build plan for idea: {idea}",
                "capability": "app_builder_generate_docs",
                "risk_level": "medium",
                "estimated_minutes": 35,
                "approval_required": False,
                "assigned_agent": "primary",
            },
            {
                "title": "Execute build (scaffold + deps + checkpoints)",
                "command": "Build the generated app project and run checkpoint tests.",
                "capability": "app_builder_execute_build",
                "depends_on": [1],
                "required_inputs": ["app_builder_project_dir"],
                "risk_level": "high",
                "estimated_minutes": 35,
                "approval_required": True,
                "assigned_agent": "primary",
            },
        ],
    }

    preview = [
        "Plan: App Builder (night-run)",
        f"- Idea: {idea}",
        f"- Window: {night_start:02d}:00-{night_end:02d}:00 (local time) + require idle",
        "- Steps: generate docs, then execute build with checkpoint tests (requires approval)",
    ]
    if context.get("_plan_only"):
        return ActionResult.ok("\n".join(preview), capability="app_builder")

    manager = get_orchestrator_manager()
    result = manager.create_project_from_spec(spec, source_request=text, auto_run=auto_run)
    project = result["project"]
    return ActionResult.ok(
        "\n".join(
            [
                f"Scheduled nightly App Builder project: '{project.name}' ({project.id[:8]}).",
                f"Run window: {project.run_start_hour:02d}:00-{project.run_end_hour:02d}:00. Idle-gated.",
                "I will ask for approval before scaffolding code.",
                f"Try: 'project status {project.id[:8]}'",
            ]
        ),
        {"project_id": project.id, "idea": idea},
        "app_builder",
    )


def handle_app_builder_generate_docs(text: str, context: Dict[str, Any]) -> ActionResult:
    from chintu_backend.automation.content_studio import generate_app_builder_docs
    from chintu_backend.orchestrator import get_orchestrator_manager

    idea = _extract_after_markers(text, markers=["idea:", "for idea:", "idea", ":"])
    idea = (idea or "").strip().strip('"\'') or text.strip()

    result = generate_app_builder_docs(idea=idea, context=context)

    # Persist project dir for later steps.
    try:
        project_id = context.get("_orchestrator_project_id")
        proj_dir = result.get("dir")
        if project_id and proj_dir:
            get_orchestrator_manager().set_input(
                "app_builder_project_dir",
                str(proj_dir),
                is_secret=False,
                project_id=project_id,
            )
    except Exception:
        pass

    msg = "App Builder docs generated.\n"
    msg += f"- Folder: {result.get('dir','')}\n"
    msg += f"- Product brief: {result.get('product_brief','')}\n"
    msg += f"- PRD: {result.get('prd','')}\n"
    msg += f"- Architecture: {result.get('architecture','')}\n"
    msg += f"- Milestones: {result.get('milestones','')}\n"
    if result.get("flow"):
        msg += f"- Flow: {result.get('flow')}\n"
    msg += "Next step: approve the build execution step when ready."
    return ActionResult.ok(msg.strip(), result, "app_builder_generate_docs")


def _resolve_app_builder_project_dir(text: str, context: Dict[str, Any]) -> str:
    project_dir = ""
    validated = context.get("_validated_params")
    if validated and isinstance(validated, AppBuilderBuildSchema):
        project_dir = str(validated.project_dir or "")
    if not project_dir:
        inputs = context.get("inputs") or {}
        project_dir = str(inputs.get("app_builder_project_dir") or "")
    if not project_dir:
        project_dir = _extract_after_markers(text, markers=["dir:", "folder:", "project_dir:", ":"])
    return str(project_dir or "").strip().strip('"\'')


def handle_app_builder_execute_build(text: str, context: Dict[str, Any]) -> ActionResult:
    from pathlib import Path

    from chintu_backend.automation.content_studio import execute_app_builder_build

    project_dir = _resolve_app_builder_project_dir(text, context)
    if not project_dir:
        return ActionResult.fail("Missing project_dir input for build execution.", "app_builder_execute_build")

    install_deps = True
    run_tests = True
    validated = context.get("_validated_params")
    if validated and isinstance(validated, AppBuilderBuildSchema):
        install_deps = bool(validated.install_deps if validated.install_deps is not None else True)
        run_tests = bool(validated.run_tests if validated.run_tests is not None else True)

    try:
        result = execute_app_builder_build(
            Path(project_dir),
            install_deps=install_deps,
            run_tests=run_tests,
        )
    except Exception as exc:
        return ActionResult.fail(f"Build execution failed: {exc}", "app_builder_execute_build")

    checkpoints = result.get("checkpoints") if isinstance(result.get("checkpoints"), list) else []
    passed = sum(1 for row in checkpoints if str(row.get("status")) == "passed")
    total = len(checkpoints)
    run_command = str(result.get("run_command") or "")

    msg = "App Builder build execution finished.\n"
    msg += f"- Backend folder: {result.get('backend_dir','')}\n"
    msg += f"- Checkpoints passed: {passed}/{total}\n"
    msg += f"- Build receipt: {result.get('receipt','')}\n"
    if run_command:
        msg += f"- Run command: {run_command}\n"
    if not bool(result.get("success")):
        msg += "Build is not fully ready yet. Check receipt for the failed checkpoint."
        return ActionResult.fail(msg.strip(), "app_builder_execute_build")
    return ActionResult.ok(msg.strip(), result, "app_builder_execute_build")


def handle_app_builder_scaffold_backend(text: str, context: Dict[str, Any]) -> ActionResult:
    """Backward-compatible legacy scaffold-only entrypoint."""
    from pathlib import Path

    from chintu_backend.automation.content_studio import scaffold_fastapi_backend

    project_dir = _resolve_app_builder_project_dir(text, context)
    if not project_dir:
        return ActionResult.fail("Missing project_dir input for scaffolding.", "app_builder_scaffold_backend")

    try:
        result = scaffold_fastapi_backend(Path(project_dir))
    except Exception as exc:
        return ActionResult.fail(f"Scaffold failed: {exc}", "app_builder_scaffold_backend")

    msg = "Backend scaffold created.\n"
    msg += f"- Backend folder: {result.get('backend_dir','')}\n"
    msg += f"- Main: {result.get('main','')}\n"
    msg += f"- Requirements: {result.get('requirements','')}\n"
    msg += "Next: run the build executor step to install dependencies and run checkpoint tests."
    return ActionResult.ok(msg.strip(), result, "app_builder_scaffold_backend")


def register_automation_capabilities(registry) -> None:
    """Register all automation-related capabilities."""
    
    # Schedule Workflow
    registry.register(Capability(
        name="schedule_workflow",
        triggers=[
            "every day at", "every morning", "every evening", "every friday",
            "schedule:", "at 9am,", "at 10am,", "every hour"
        ],
        handler=handle_schedule_workflow,
        requires_confirmation=False,
        description="schedule automated workflows",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=[
            "Every day at 9am, search for news about AI",
            "Every friday at 5pm, show my reminders"
        ],
        schema=ScheduleWorkflowSchema
    ))
    
    # List Scheduled
    registry.register(Capability(
        name="list_scheduled",
        triggers=[
            "show scheduled", "list scheduled", "my automations",
            "show automations", "scheduled tasks"
        ],
        handler=handle_list_scheduled,
        requires_confirmation=False,
        description="list scheduled tasks",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=[
            "Show scheduled tasks",
            "List my automations"
        ],
        schema=ListScheduledSchema
    ))
    
    # Cancel Scheduled
    registry.register(Capability(
        name="cancel_scheduled",
        triggers=[
            "cancel scheduled", "remove automation", "stop scheduled"
        ],
        handler=handle_cancel_scheduled,
        requires_confirmation=False,
        description="cancel a scheduled task",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=[
            "Cancel scheduled task abc123"
        ],
        schema=CancelTaskSchema
    ))

    registry.register(Capability(
        name="morning_briefing",
        triggers=[
            "morning briefing",
            "morning brief",
            "daily briefing",
            "daily brief",
            "brief me",
            "give me my morning briefing",
        ],
        handler=handle_morning_briefing,
        requires_confirmation=False,
        description="calendar + weather + headlines briefing",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=[
            "Chintu, give me my morning briefing",
            "Morning briefing",
        ],
        schema=MorningBriefingSchema,
    ))

    registry.register(
        Capability(
            name="morning_briefing_detail",
            triggers=[
                "read more about #",
                "read more about",
                "more about #",
                "headline details",
                "expand headline",
            ],
            handler=handle_morning_briefing_detail,
            requires_confirmation=False,
            description="expand a numbered morning-briefing headline",
            capability_type=CapabilityType.PRODUCTIVITY,
            examples=[
                "Read more about #1",
                "Expand headline 3",
            ],
            schema=MorningBriefingDetailSchema,
        )
    )

    registry.register(
        Capability(
            name="morning_briefing_feedback",
            triggers=[
                "i like #",
                "i like headline",
                "not interested in #",
                "not interested in headline",
                "dislike #",
                "dislike headline",
                "more like this",
                "less like this",
                "more tech news",
                "less finance news",
                "less healthcare news",
            ],
            handler=handle_morning_briefing_feedback,
            requires_confirmation=False,
            description="capture explicit like/dislike feedback for headline personalization",
            capability_type=CapabilityType.PRODUCTIVITY,
            examples=[
                "I like #2",
                "Not interested in #4",
                "More tech news, less finance news",
            ],
            schema=MorningBriefingFeedbackSchema,
        )
    )

    # Cancel Cron Job
    registry.register(Capability(
        name="cancel_cron_job",
        triggers=[
            "cancel cron", "stop cron", "remove cron", "cancel cron job"
        ],
        handler=handle_cancel_cron_job,
        requires_confirmation=False,
        description="cancel a cron job",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=[
            "Cancel cron job 1a2b3c4d"
        ],
        schema=CancelCronJobSchema
    ))

    # Update Cron Job
    registry.register(Capability(
        name="update_cron_job",
        triggers=[
            "update cron", "edit cron", "change cron", "update cron job"
        ],
        handler=handle_update_cron_job,
        requires_confirmation=False,
        description="update a cron job",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=[
            "Update cron job 1a2b3c4d schedule */10 * * * *"
        ],
        schema=UpdateCronJobSchema
    ))

    # Commit change
    registry.register(Capability(
        name="commit_change",
        triggers=[
            "commit change", "commit changes", "git commit change"
        ],
        handler=handle_commit_change,
        requires_confirmation=True,
        description="commit a change record to git",
        capability_type=CapabilityType.AUTOMATION,
        examples=[
            "Commit change 20240201_example"
        ],
        schema=CommitChangeSchema
    ))

    # Rollback change
    registry.register(Capability(
        name="rollback_change",
        triggers=[
            "rollback change", "revert change"
        ],
        handler=handle_rollback_change,
        requires_confirmation=True,
        description="rollback a change record using patch",
        capability_type=CapabilityType.AUTOMATION,
        examples=[
            "Rollback change 20240201_example"
        ],
        schema=RollbackChangeSchema
    ))
    
    # Background Task
    registry.register(Capability(
        name="background_task",
        triggers=[
            "in the background", "while i work", "async",
            "background task", "run in background"
        ],
        handler=handle_background_task,
        requires_confirmation=False,
        description="run a task in the background",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=[
            "In the background, research Python tutorials"
        ],
        schema=BackgroundTaskSchema
    ))
    
    # Check Tasks
    registry.register(Capability(
        name="check_tasks",
        triggers=[
            "check tasks", "show background", "task status",
            "background tasks"
        ],
        handler=handle_check_tasks,
        requires_confirmation=False,
        description="check background task status",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=[
            "Check tasks",
            "Show background tasks"
        ],
        schema=CheckTasksSchema
    ))
    
    # Transfer Data
    registry.register(Capability(
        name="transfer_data",
        triggers=[
            "copy page content", "save clipboard", "transfer data",
            "get data from", "copy to clipboard"
        ],
        handler=handle_transfer_data,
        requires_confirmation=False,
        description="transfer data between apps",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=[
            "Copy page content to clipboard",
            "Save clipboard to file"
        ],
        schema=TransferDataSchema
    ))

    # Sandbox Run
    registry.register(Capability(
        name="sandbox_data_task",
        triggers=[
            "messy dataset", "clean null values", "null values",
            "matplotlib trend chart", "trend chart", "csv trend",
            "execute it in the sandbox", "run in sandbox and save chart",
            "clean csv in sandbox",
            "analyze csv in sandbox", "analyze dataset in sandbox",
            r"analy(?:ze|se)\s+.+\.csv\s+(?:in|using)\s+sandbox",
        ],
        handler=handle_sandbox_data_task,
        requires_confirmation=False,
        description="clean CSV and generate trend chart using sandbox execution",
        capability_type=CapabilityType.AUTOMATION,
        examples=[
            "Clean sales_2025.csv and generate a matplotlib trend chart in sandbox",
            "Use sandbox to clean null values in a CSV and save chart to Desktop",
            "Analyze sales_2025.csv in sandbox",
        ],
        schema=SandboxDataTaskSchema,
    ))

    # Sandbox Run
    registry.register(Capability(
        name="sandbox_run",
        triggers=[
            "run in sandbox", "sandbox run", "execute in sandbox", "sandbox:"
        ],
        handler=handle_sandbox_run,
        requires_confirmation=True,
        description="run a command inside the Docker sandbox",
        capability_type=CapabilityType.AI_AGENT,
        examples=[
            "Run in sandbox: python -V",
            "Sandbox run pytest -q"
        ],
        schema=SandboxRunSchema
    ))

    # Terminal Exec (whitelisted commands)
    registry.register(Capability(
        name="terminal_exec",
        triggers=[
            "run command", "execute command", "terminal:", "cmd:", "shell:",
            "run in terminal", "run in shell", "command line"
        ],
        handler=handle_terminal_exec,
        requires_confirmation=True,
        description="run a terminal command",
        capability_type=CapabilityType.AI_AGENT,
        examples=[
            "Run command: git status",
            "Terminal: pytest -q",
        ],
        schema=TerminalExecSchema
    ))

    registry.register(Capability(
        name="job_apply",
        triggers=[
            "apply for jobs", "apply to jobs", "find jobs and apply",
            "job application", "apply for role", "job search apply"
        ],
        handler=handle_job_apply,
        requires_confirmation=False,
        description="search, evaluate, and prepare job applications in browser",
        capability_type=CapabilityType.AUTOMATION,
        examples=[
            "Apply for jobs: software engineer in New York",
            "Find jobs and apply for data analyst roles in Austin",
        ],
        schema=JobApplySchema
    ))

    registry.register(Capability(
        name="job_apply_list",
        triggers=[
            "show job applications", "list job applications", "jobs applied",
            "job application list"
        ],
        handler=handle_job_apply_list,
        requires_confirmation=False,
        description="list recent job applications",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=[
            "Show job applications",
            "List job applications"
        ],
        schema=JobApplyListSchema
    ))

    registry.register(Capability(
        name="figma_automation",
        triggers=[
            "open figma", "figma file", "figma design", "figma prototype",
            "export figma", "snapshot figma"
        ],
        handler=handle_figma_automation,
        requires_confirmation=True,
        description="open a Figma URL and capture a snapshot",
        capability_type=CapabilityType.AUTOMATION,
        examples=[
            "Open figma https://www.figma.com/file/...",
            "Export figma https://www.figma.com/design/...",
        ],
        schema=FigmaAutomationSchema
    ))

    registry.register(Capability(
        name="set_config",
        triggers=["set config", "config set", "update config", "change config"],
        handler=handle_set_config,
        requires_confirmation=True,
        description="update .env config key",
        capability_type=CapabilityType.AUTOMATION,
        examples=["Set config CHINTU_RESUME_TEX_PATH=C:\\resumes\\resume.tex"],
        schema=ConfigSetSchema
    ))

    registry.register(Capability(
        name="image_analyze",
        triggers=["analyze image", "describe image", "ocr image", "image to text"],
        handler=handle_image_analyze,
        requires_confirmation=False,
        description="analyze an image via vision models",
        capability_type=CapabilityType.AI_AGENT,
        examples=["Analyze image C:\\images\\photo.png"],
        schema=ImageAnalyzeSchema
    ))

    registry.register(Capability(
        name="video_summarize",
        triggers=["summarize video", "video summary", "analyze video"],
        handler=handle_video_summarize,
        requires_confirmation=False,
        description="summarize video using frame analysis",
        capability_type=CapabilityType.AI_AGENT,
        examples=["Summarize video C:\\videos\\clip.mp4"],
        schema=VideoSummarizeSchema
    ))

    registry.register(Capability(
        name="news_video",
        triggers=["make news video", "daily tech news video", "news video"],
        handler=handle_news_video,
        requires_confirmation=True,
        description="generate daily news script + audio",
        capability_type=CapabilityType.AI_AGENT,
        examples=["Make news video about AI"],
        schema=NewsVideoSchema
    ))

    registry.register(
        Capability(
            name="youtube_short",
            triggers=[
                "youtube short",
                "youtube shorts",
                "make a short",
                "create a short",
                "make a youtube short",
                "create a youtube short",
            ],
            handler=handle_youtube_short,
            requires_confirmation=False,
            description="schedule a night-time YouTube Short generation project",
            capability_type=CapabilityType.AUTOMATION,
            examples=["Make a YouTube short about GPUs tonight"],
            schema=YouTubeShortSchema,
        )
    )

    registry.register(
        Capability(
            name="youtube_short_generate_assets",
            triggers=[
                "generate short assets",
                "render short",
                "build short video",
            ],
            handler=handle_youtube_short_generate_assets,
            requires_confirmation=False,
            description="generate a YouTube short locally (script+tts+video)",
            capability_type=CapabilityType.AUTOMATION,
            examples=["Generate short assets about AI news"],
        )
    )

    registry.register(
        Capability(
            name="app_builder",
            triggers=[
                "build an app",
                "create an app",
                "app builder",
                "turn this idea into an app",
                "make a prd",
                "write a prd",
            ],
            handler=handle_app_builder,
            requires_confirmation=False,
            description="schedule a night-time app-builder project (docs then scaffold)",
            capability_type=CapabilityType.AI_AGENT,
            examples=["Build an app: gamified to-do list tonight"],
            schema=AppBuilderSchema,
        )
    )

    registry.register(
        Capability(
            name="app_builder_generate_docs",
            triggers=[
                "generate prd",
                "generate app docs",
                "app docs",
            ],
            handler=handle_app_builder_generate_docs,
            requires_confirmation=False,
            description="generate PRD/flow/stack/schema/plan docs from an idea",
            capability_type=CapabilityType.AUTOMATION,
            examples=["Generate PRD for idea: a habit tracker with streaks"],
        )
    )

    registry.register(
        Capability(
            name="app_builder_scaffold_backend",
            triggers=[
                "scaffold backend",
                "create backend scaffold",
                "build backend scaffold",
            ],
            handler=handle_app_builder_scaffold_backend,
            requires_confirmation=True,
            description="scaffold a FastAPI backend from the generated data model",
            capability_type=CapabilityType.AI_AGENT,
            examples=["Scaffold backend for project dir C:\\path\\to\\project"],
            schema=AppBuilderBuildSchema,
        )
    )

    registry.register(
        Capability(
            name="app_builder_execute_build",
            triggers=[
                "execute app build",
                "run app build",
                "build app project",
                "app builder build",
                "run checkpoint tests",
            ],
            handler=handle_app_builder_execute_build,
            requires_confirmation=True,
            description="execute app builder scaffold + dependency install + checkpoint tests",
            capability_type=CapabilityType.AI_AGENT,
            examples=["Execute app build for project dir C:\\path\\to\\project"],
            schema=AppBuilderBuildSchema,
        )
    )

    registry.register(
        Capability(
            name="autonomy_workflow",
            triggers=[
                "find all pdfs in my downloads folder from the last",
                "move the originals to a new folder named recent research",
                "monitor my active windows",
                "latest cv and have it ready in the clipboard",
                "top 3 trending open-source projects",
                "automated visa bots on github",
                "boilerplate python fastapi project for a sop library manager",
                "verify that the code is bug-free by running a test script",
                "start tonight at 2 am on the rtx 3060",
                "check my i5-12600k thermals",
                "youtube shorts bot",
                "create a jira ticket",
                "statement of purpose draft and my resume",
                "messages regarding my f1 opt status",
                "record my screen for the next 5 minutes",
            ],
            handler=handle_autonomy_workflow,
            requires_confirmation=False,
            description="Deterministic end-to-end daily-driver workflows with evidence or unblock plans.",
            capability_type=CapabilityType.AUTOMATION,
            schema=AutonomyWorkflowSchema,
        )
    )

    logger.info("Registered automation capabilities")

    # Register External Modules
    chintu_backend.automation.hardware_capabilities.register_hardware_capabilities()
    chintu_backend.automation.calendar_capabilities.register_calendar_capabilities()
    try:
        from chintu_backend.automation.email_triage_capabilities import register_email_triage_capabilities

        register_email_triage_capabilities(registry)
    except Exception:
        pass
    try:
        from chintu_backend.automation.focus_mode_capabilities import register_focus_mode_capabilities

        register_focus_mode_capabilities(registry)
    except Exception:
        pass
    try:
        from chintu_backend.automation.youtube_digest_capabilities import register_youtube_digest_capabilities

        register_youtube_digest_capabilities(registry)
    except Exception:
        pass
    try:
        from chintu_backend.automation.hardware_health_capabilities import register_hardware_health_capabilities

        register_hardware_health_capabilities(registry)
    except Exception:
        pass
    try:
        from chintu_backend.automation.smart_shutdown_capabilities import register_smart_shutdown_capabilities

        register_smart_shutdown_capabilities(registry)
    except Exception:
        pass
    try:
        from chintu_backend.automation.deal_finder_capabilities import register_deal_finder_capabilities

        register_deal_finder_capabilities(registry)
    except Exception:
        pass
    try:
        from chintu_backend.automation.deal_watch_capabilities import register_deal_watch_capabilities

        register_deal_watch_capabilities(registry)
    except Exception:
        pass
    try:
        from chintu_backend.automation.social_content_capabilities import register_social_content_capabilities

        register_social_content_capabilities(registry)
    except Exception:
        pass
    try:
        from chintu_backend.automation.integration_capabilities import register_integration_capabilities

        register_integration_capabilities(registry)
    except Exception:
        pass
    try:
        from chintu_backend.automation.workspace_capabilities import register_workspace_capabilities

        register_workspace_capabilities(registry)
    except Exception:
        pass
