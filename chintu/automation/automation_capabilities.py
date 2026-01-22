"""
Automation capability handlers for Chintu AI Assistant.
Provides voice commands for scheduled workflows, parallel tasks, and cross-app data transfer.
"""

import logging
import re
from typing import Dict, Any

from ..core.capabilities import Capability, CapabilityType, ActionResult

logger = logging.getLogger(__name__)


def handle_schedule_workflow(text: str, context: Dict[str, Any]) -> ActionResult:
    """
    Schedule a workflow to run at a specific time.
    
    Examples:
        "Every day at 9am, search for news about AI"
        "Every friday at 5pm, check my reminders"
        "At 10am tomorrow, research Python tutorials"
    """
    from .scheduled_tasks import get_scheduler, parse_schedule, ScheduleType
    
    # Extract schedule and workflow
    query = text.lower().strip()
    
    # Try to separate schedule from workflow
    schedule_patterns = [
        r"(every day at \d{1,2}(?::\d{2})?\s*(?:am|pm)?)[,\s]+(.+)",
        r"(every \w+ at \d{1,2}(?::\d{2})?\s*(?:am|pm)?)[,\s]+(.+)",
        r"(every \d+ (?:minute|hour)s?)[,\s]+(.+)",
        r"(at \d{1,2}(?::\d{2})?\s*(?:am|pm)?)[,\s]+(.+)",
    ]
    
    schedule_part = None
    workflow_part = None
    
    for pattern in schedule_patterns:
        match = re.match(pattern, query)
        if match:
            schedule_part = match.group(1)
            workflow_part = match.group(2)
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
    from .scheduled_tasks import get_scheduler
    
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
    """
    Cancel a scheduled task.
    
    Examples:
        "Cancel scheduled task abc123"
        "Remove automation xyz"
    """
    from .scheduled_tasks import get_scheduler
    
    # Extract task ID
    words = text.lower().split()
    task_id = None
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


def handle_background_task(text: str, context: Dict[str, Any]) -> ActionResult:
    """
    Run a task in the background.
    
    Examples:
        "In the background, research Python tutorials"
        "While I work, search for news about AI"
    """
    from .parallel_executor import get_parallel_executor
    
    # Extract the task
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
    """
    Transfer data between sources.
    
    Examples:
        "Copy page content to clipboard"
        "Save clipboard to file"
        "Get data from browser"
    """
    from .cross_app import get_data_transfer, DataFormat
    
    query = text.lower().strip()
    transfer = get_data_transfer()

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
    
    # Browser to clipboard
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
    
    # Clipboard to file
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
    
    # Get clipboard info
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
        ]
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
        ]
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
        ]
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
        ]
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
        ]
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
        ]
    ))
    
    logger.info("Registered automation capabilities")
