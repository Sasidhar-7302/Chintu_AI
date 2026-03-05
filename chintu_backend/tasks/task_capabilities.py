import re
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

from ..core.capabilities import (
    Capability, CapabilityType, ActionResult, get_registry
)
from .task_manager import get_task_manager, TaskStatus

logger = logging.getLogger(__name__)

# ============================================================================
# SCHEMAS
# ============================================================================

class SetReminderSchema(BaseModel):
    content: str = Field(..., description="What to remind about.")
    time: str = Field(..., description="When to remind (e.g. 'in 10 minutes', 'tomorrow at 9am').")

class JobSearchSchema(BaseModel):
    query: str = Field(..., description="Job title or keywords to search for.")
    location: Optional[str] = Field(None, description="Location for the job search.")
    platform: str = Field("linkedin", description="Platform to search on (linkedin, indeed, glassdoor).")

class ListRemindersSchema(BaseModel):
    pass

class CancelReminderSchema(BaseModel):
    target: str = Field(..., description="ID of reminder, or 'all', or 'last'.")

class TaskStatusSchema(BaseModel):
    pass

class AssistantStatusSchema(BaseModel):
    pass


class AddTaskSchema(BaseModel):
    content: str = Field(..., description="Todo task content.")


class ListTasksSchema(BaseModel):
    pass


class CompleteTaskSchema(BaseModel):
    target: str = Field(..., description="Task content or 'last' to complete the most recent task.")


def parse_time_expression(text: str) -> timedelta:
    """Parse time expressions including relative, absolute, and weekdays."""
    # (Existing implementation kept distinct for reuse if needed, 
    # but handlers will try to use this logic to parse the schema's 'time' string)
    text_lower = text.lower()
    now = datetime.now()
    target_time = now
    
    # 1. Check for weekdays (monday, tuesday...)
    weekdays = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    found_day = -1
    for i, day in enumerate(weekdays):
        if day in text_lower:
            found_day = i
            break
            
    if found_day != -1:
        current_day = now.weekday()
        days_ahead = (found_day - current_day)
        if days_ahead <= 0: # If today or past, assume next week
            days_ahead += 7
        target_time += timedelta(days=days_ahead)
        # Reset to morning default unless time specified
        target_time = target_time.replace(hour=9, minute=0, second=0)

    # 2. Check for "tomorrow"
    if "tomorrow" in text_lower:
        target_time += timedelta(days=1)
        # Reset to morning default unless time specified
        if found_day == -1: # Don't double count if day also specified
             target_time = target_time.replace(hour=9, minute=0, second=0)

    # 3. Check for fuzzy times (morning, evening)
    if "morning" in text_lower:
        target_time = target_time.replace(hour=9, minute=0)
    elif "afternoon" in text_lower:
        target_time = target_time.replace(hour=14, minute=0)
    elif "evening" in text_lower:
        target_time = target_time.replace(hour=18, minute=0)
    elif "night" in text_lower:
        target_time = target_time.replace(hour=21, minute=0)
        
    # 4. Check for absolute time (HH:MM or HHam/pm) -> Overrides fuzzy
    # (at|for) HH(:MM)? (am|pm)? OR HH:MM (am/pm)?
    abs_time_match = re.search(r'(?:at|for|by)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?|(\d{1,2}):(\d{2})\s*(am|pm)?|(\d{1,2})\s*(am|pm)', text_lower)
    
    # Only process absolute time if we have a specific match, otherwise keep the day/fuzzy time
    if abs_time_match:
        # Avoid treating durations (e.g. "12 mins") as absolute clock times
        if re.search(r"\b\d+\s*(?:min|mins|minute|minutes|hour|hours|sec|secs|second|seconds)\b", text_lower):
            abs_time_match = None

    if abs_time_match:
        groups = abs_time_match.groups()
        hour, minute, meridiem = 0, 0, None
        
        if groups[0]: # (at|for) HH(:MM)? (am|pm)?
            hour = int(groups[0])
            minute = int(groups[1]) if groups[1] else 0
            meridiem = groups[2]
        elif groups[3]: # HH:MM (am/pm)?
            hour = int(groups[3])
            minute = int(groups[4])
            meridiem = groups[5]
        else: # HH (am/pm)
            hour = int(groups[6])
            minute = 0
            meridiem = groups[7]
            
        if meridiem == 'pm' and hour < 12: hour += 12
        elif meridiem == 'am' and hour == 12: hour = 0
        elif not meridiem and hour < 7: hour += 12 # infer pm for small numbers if ambiguous
            
        target_time = target_time.replace(hour=hour, minute=minute, second=0)
        
        # If no day was specified and time passed, assume tomorrow
        if found_day == -1 and "tomorrow" not in text_lower:
             if target_time <= now + timedelta(minutes=1):
                 target_time += timedelta(days=1)
    
    # 5. Check for relative time (in X minutes) - Only if NO absolute Date/Time was found
    # If we found a day/time, we use that. If purely relative, we add to NOW.
    is_absolute_date = (found_day != -1 or "tomorrow" in text_lower or abs_time_match or "morning" in text_lower or "evening" in text_lower)
    
    if not is_absolute_date:
        total = timedelta()
        hour_match = re.search(r'(\d+)\s*hours?', text_lower)
        if hour_match: total += timedelta(hours=int(hour_match.group(1)))
        
        min_match = re.search(r'(\d+)\s*min(?:ute)?s?', text_lower)
        if min_match: total += timedelta(minutes=int(min_match.group(1)))
        
        sec_match = re.search(r'(\d+)\s*sec(?:ond)?s?', text_lower)
        if sec_match: total += timedelta(seconds=int(sec_match.group(1)))
        
        if total > timedelta():
            return total
        return timedelta(minutes=5) # Default only if NOTHING matched

    return target_time - now


def extract_reminder_content(text: str) -> str:
    """Extract the reminder content from user text."""
    # Remove trigger phrases
    patterns = [
        r'^(?:can|could) (?:you|u) ',
        r'^(?:please|kindly) ',
        r'remind me (?:to|about|that|on)\s+',
        r'set a reminder (?:to|for|about)\s+',
        r'remind me in \d+\s*(?:hours?|minutes?|seconds?)\s*(?:to|about|that)?\s*',
        r'in \d+\s*(?:hours?|minutes?|seconds?)\s*remind me (?:to|about)?\s*',
    ]
    
    result = text
    for pattern in patterns:
        result = re.sub(pattern, '', result, flags=re.IGNORECASE)

    # Strip trailing relative-time fragments so content stays clean.
    # Example: "call mom in 10 minutes" -> "call mom"
    result = re.sub(
        r'\s+\b(in|after)\s+\d+\s*(?:hours?|minutes?|mins?|seconds?|secs?)\s*$',
        '',
        result,
        flags=re.IGNORECASE,
    )

    return result.strip().strip('.')


def extract_timer_content(text: str) -> str:
    """Extract timer content (what the timer is for)."""
    # Prefer quoted content
    quote_match = re.search(r'"([^"]+)"|\'([^\']+)\'', text)
    if quote_match:
        return (quote_match.group(1) or quote_match.group(2) or "").strip()

    patterns = [
        r'set (?:a )?timer (?:for|to)\s+',
        r'timer (?:for|to)\s+',
        r'start (?:a )?timer (?:for|to)\s+',
        r'count(?:\s+)?down (?:for|to)\s+',
    ]
    result = text
    for pattern in patterns:
        result = re.sub(pattern, '', result, flags=re.IGNORECASE)

    # Strip trailing duration ("in 10 minutes", "for 12 mins")
    result = re.sub(r'\b(in|for)\s+\d+\s*(?:hours?|minutes?|mins?|seconds?|secs?)\b', '', result, flags=re.IGNORECASE)
    result = result.strip().strip(".")
    return result or "timer"


# ============================================================================
# REMINDER CAPABILITIES
# ============================================================================

def handle_set_reminder(text: str, context: Dict[str, Any]) -> ActionResult:
    """Set a reminder for the user."""
    task_manager = get_task_manager()
    
    content = None
    time_str = None
    
    validated = context.get("_validated_params")
    if validated and isinstance(validated, SetReminderSchema):
        content = validated.content
        time_str = validated.time
    
    # Logic
    if time_str:
        delay = parse_time_expression(time_str)
    else:
        delay = parse_time_expression(text) # Legacy
        
    if not content:
        content = extract_reminder_content(text) # Legacy
    
    if not content or len(content) < 3:
        return ActionResult.fail(
            "What should I remind you about? Try: 'Remind me in 10 minutes to take a break'",
            "set_reminder"
        )
    
    # Create reminder
    trigger_time = datetime.now() + delay
    task = task_manager.add_reminder(content, trigger_time)
    
    # Format response
    if delay.total_seconds() < 3600:
        time_display = f"{int(delay.total_seconds() // 60)} minutes"
    else:
        hours = delay.total_seconds() / 3600
        time_display = f"{hours:.1f} hours"
    
    return ActionResult.ok(
        f"I'll remind you in {time_display}: '{content}'",
        {"task_id": task.id, "trigger_time": trigger_time.isoformat()},
        "set_reminder"
    )


def handle_list_reminders(text: str, context: Dict[str, Any]) -> ActionResult:
    """List pending reminders."""
    task_manager = get_task_manager()
    
    # Setup for potential filtering later via schema
    validated = context.get("_validated_params") # noqa
    
    tasks = task_manager.get_pending_tasks()
    reminders = [t for t in tasks if t.task_type == "reminder"]
    
    if not reminders:
        return ActionResult.ok(
            "You don't have any pending reminders.",
            {"reminders": []},
            "list_reminders"
        )
    
    lines = []
    for r in reminders:
        trigger = datetime.fromisoformat(r.trigger_time)
        delta = trigger - datetime.now()
        if delta.total_seconds() > 0:
            mins = int(delta.total_seconds() // 60)
            time_str = f"in {mins} min" if mins < 60 else f"in {mins // 60}h {mins % 60}m"
        else:
            time_str = "due now"
        lines.append(f"- {r.content} ({time_str})")
    
    return ActionResult.ok(
        f"Your reminders:\n" + "\n".join(lines),
        {"reminders": [r.to_dict() for r in reminders]},
        "list_reminders"
    )


def handle_cancel_reminder(text: str, context: Dict[str, Any]) -> ActionResult:
    """Cancel a reminder."""
    task_manager = get_task_manager()
    
    # Get pending reminders
    tasks = task_manager.get_pending_tasks()
    reminders = [t for t in tasks if t.task_type == "reminder"]
    
    if not reminders:
        return ActionResult.ok("You don't have any reminders to cancel.", capability="cancel_reminder")
    
    target = None
    validated = context.get("_validated_params")
    if validated and isinstance(validated, CancelReminderSchema):
        target = validated.target.lower()
    
    if not target:
        if "all" in text.lower(): target = "all"
    
    # Cancel all or specific?
    if target == "all":
        for r in reminders:
            task_manager.cancel_task(r.id)
        return ActionResult.ok(f"Cancelled {len(reminders)} reminders.", capability="cancel_reminder")
    
    # Cancel the most recent one (simple fallback for now, ideally ID based)
    # The Schema asks for 'target' which should be ID or 'last'.
    # But user won't know ID. So we usually cancel 'last' or 'matching content'.
    # Simplified logic: if target is not 'all', try to match content or just pop last.
    
    # If target looks like content, find it
    if target and target != "last":
        for r in reminders:
            if target in r.content.lower():
                task_manager.cancel_task(r.id)
                return ActionResult.ok(f"Cancelled reminder: '{r.content}'", capability="cancel_reminder")
    
    # Default: Cancel last
    target_task = reminders[0] # List is sorted by time? get_pending_tasks usually is.
    task_manager.cancel_task(target_task.id)
    return ActionResult.ok(
        f"Cancelled reminder: '{target_task.content}'",
        capability="cancel_reminder"
    )


# ============================================================================
# TASK STATUS CAPABILITIES
# ============================================================================

def handle_task_status(text: str, context: Dict[str, Any]) -> ActionResult:
    """Get status of tasks and reminders."""
    task_manager = get_task_manager()
    stats = task_manager.get_stats()
    
    pending = stats.get("pending", 0)
    completed = stats.get("completed", 0)
    
    upcoming = task_manager.get_upcoming_tasks(hours=24)
    
    parts = []
    parts.append(f"Pending tasks: {pending}")
    parts.append(f"Completed today: {completed}")
    
    if upcoming:
        parts.append(f"\nUpcoming ({len(upcoming)}):")
        for t in upcoming[:3]:
            parts.append(f"  - {t.content}")
    
    return ActionResult.ok(
        "\n".join(parts),
        {"stats": stats, "upcoming": len(upcoming)},
        "task_status"
    )


# ============================================================================
# TODO TASKS
# ============================================================================

def handle_add_task(text: str, context: Dict[str, Any]) -> ActionResult:
    """Add a todo task."""
    task_manager = get_task_manager()
    content = None

    validated = context.get("_validated_params")
    if validated and isinstance(validated, AddTaskSchema):
        content = validated.content

    if not content:
        quote_match = re.search(r'"([^"]+)"|\'([^\']+)\'', text)
        if quote_match:
            content = (quote_match.group(1) or quote_match.group(2) or "").strip()
        else:
            cleaned = text
            prefixes = [
                "add to my todo list", "add to my tasks", "add to my task list",
                "add task", "new task", "create task", "todo item", "todo", "to-do", "add ",
            ]
            for prefix in prefixes:
                if cleaned.lower().startswith(prefix):
                    cleaned = cleaned[len(prefix):].strip()
                    break
            content = cleaned.strip().strip(".")
            # Remove trailing "to my tasks/todo list"
            content = re.sub(r"\s+to my (tasks|todo list)\s*$", "", content, flags=re.IGNORECASE).strip()

    if not content:
        return ActionResult.fail("What should I add to your tasks?", "add_task")

    task = task_manager.add_task(content)
    return ActionResult.ok(
        f"Added task: {content}",
        {"task_id": task.id, "content": content},
        "add_task",
    )


def handle_list_tasks(_text: str, _context: Dict[str, Any]) -> ActionResult:
    """List pending todo tasks."""
    task_manager = get_task_manager()
    tasks = task_manager.list_tasks(limit=50)
    if not tasks:
        return ActionResult.ok("You don't have any pending tasks.", {"tasks": []}, "list_tasks")

    # Keep output readable by collapsing duplicate task titles.
    grouped: Dict[str, Dict[str, Any]] = {}
    for t in tasks:
        key = (t.content or "").strip().lower()
        if not key:
            continue
        bucket = grouped.get(key)
        if not bucket:
            grouped[key] = {"label": (t.content or "").strip(), "count": 1}
        else:
            bucket["count"] += 1

    lines = ["Your tasks:"]
    shown = 0
    for item in grouped.values():
        if shown >= 20:
            break
        label = str(item["label"])
        count = int(item["count"])
        if count > 1:
            lines.append(f"- {label} (x{count})")
        else:
            lines.append(f"- {label}")
        shown += 1

    return ActionResult.ok("\n".join(lines), {"tasks": [t.to_dict() for t in tasks]}, "list_tasks")


def handle_complete_task(text: str, context: Dict[str, Any]) -> ActionResult:
    """Mark a task as complete."""
    task_manager = get_task_manager()
    target = None
    
    validated = context.get("_validated_params")
    if validated and isinstance(validated, CompleteTaskSchema):
        target = validated.target.lower()
    
    if not target:
        # Extract target from text - look for quoted content or key patterns
        quote_match = re.search(r'"([^"]+)"|\'([^\']+)\'', text)
        if quote_match:
            target = (quote_match.group(1) or quote_match.group(2) or "").strip().lower()
        else:
            # Try to extract after common prefixes
            text_lower = text.lower()
            for pattern in ["mark ", "complete ", "done with ", "finish ", "finished "]:
                if pattern in text_lower:
                    idx = text_lower.index(pattern) + len(pattern)
                    target = text_lower[idx:].strip().rstrip(".")
                    # Remove trailing "as done/complete"
                    target = re.sub(r"\s+(as\s+)?(done|complete|completed|finished)\s*$", "", target).strip()
                    break
    
    if not target:
        return ActionResult.fail("What task would you like to mark as complete?", "complete_task")
    
    # Find matching task
    tasks = task_manager.list_tasks(limit=100)
    if not tasks:
        return ActionResult.ok("You don't have any tasks to complete.", capability="complete_task")
    
    # Match by content
    matched = None
    for t in tasks:
        if target in t.content.lower() or t.content.lower() in target:
            matched = t
            break
    
    if not matched and target == "last":
        matched = tasks[0] if tasks else None
    
    if not matched:
        return ActionResult.fail(f"Couldn't find a task matching '{target}'.", "complete_task")
    
    # Complete the task
    task_manager.complete_task(matched.id)
    return ActionResult.ok(
        f"Marked task as complete: {matched.content}",
        {"task_id": matched.id, "content": matched.content},
        "complete_task"
    )


def handle_timer(text: str, context: Dict[str, Any]) -> ActionResult:
    """Set a timer (uses reminder system)."""
    task_manager = get_task_manager()

    delay = parse_time_expression(text)
    content = extract_timer_content(text)

    trigger_time = datetime.now() + delay
    task = task_manager.add_reminder(f"Timer: {content}", trigger_time, metadata={"timer": True})

    if delay.total_seconds() < 3600:
        time_display = f"{int(delay.total_seconds() // 60)} minutes"
    else:
        hours = delay.total_seconds() / 3600
        time_display = f"{hours:.1f} hours"

    return ActionResult.ok(
        f"Timer set for {time_display}: {content}",
        {"task_id": task.id, "trigger_time": trigger_time.isoformat()},
        "timer",
    )


# ============================================================================
# ASSISTANT STATE CAPABILITY
# ============================================================================

def handle_status(text: str, context: Dict[str, Any]) -> ActionResult:
    """Report the assistant's current state."""
    from ..core.state import get_state_manager, AssistantState
    from ..brain.memory.preferences import get_preference_manager
    from ..brain.memory.tiered_memory import get_memory_store
    
    state_manager = get_state_manager()
    pref_manager = get_preference_manager()
    memory = get_memory_store()
    task_manager = get_task_manager()
    
    state = state_manager.get_state()
    prefs = pref_manager.preferences
    mem_stats = memory.get_stats()
    task_stats = task_manager.get_stats()
    
    parts = []
    parts.append(f"**Status**: {state.assistant_state.value}")
    
    if prefs.user_name:
        parts.append(f"**User**: {prefs.user_name}")
    
    # Memory stats
    total_mem = sum(mem_stats.values())
    parts.append(f"**Memories**: {total_mem}")
    
    # Pending tasks
    pending = task_stats.get("pending", 0)
    parts.append(f"**Pending reminders**: {pending}")
    
    return ActionResult.ok(
        "\n".join(parts),
        {"state": state.assistant_state.value, "memories": total_mem, "tasks": pending},
        "status"
    )


# ============================================================================
# REGISTRY INITIALIZATION
# ============================================================================

def register_task_capabilities() -> None:
    """Register all task management capabilities."""
    registry = get_registry()
    
    # Set Reminder
    registry.register(Capability(
        name="set_reminder",
        triggers=["remind me", "set a reminder", "reminder in", "remind me in"],
        handler=handle_set_reminder,
        requires_confirmation=False,
        description="set a reminder",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=["Remind me in 10 minutes to take a break", "Set a reminder for 2 hours"],
        schema=SetReminderSchema
    ))
    
    # List Reminders
    registry.register(Capability(
        name="list_reminders",
        triggers=["my reminders", "list reminders", "show reminders", "pending reminders", "next reminder", "upcoming reminder"],
        handler=handle_list_reminders,
        requires_confirmation=False,
        description="list pending reminders",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=["Show my reminders", "What reminders do I have?"],
        schema=ListRemindersSchema
    ))
    
    # Cancel Reminder
    registry.register(Capability(
        name="cancel_reminder",
        triggers=["cancel reminder", "delete reminder", "remove reminder", "cancel all reminders", 
                  "clear reminder", "clear reminders", "clear all reminders", "clear all my reminders"],
        handler=handle_cancel_reminder,
        requires_confirmation=False,
        description="cancel a reminder",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=["Cancel my reminder", "Cancel all reminders"],
        schema=CancelReminderSchema
    ))
    
    # Task Status
    registry.register(Capability(
        name="task_status",
        triggers=["task status", "pending tasks", "task summary"],
        handler=handle_task_status,
        requires_confirmation=False,
        description="show task status",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=["Task status", "What tasks do I have?"],
        schema=TaskStatusSchema
    ))

    # Add Task
    registry.register(Capability(
        name="add_task",
        triggers=[
            "add task", "new task", "create task", "add to my tasks", "add to my todo list", "todo item",
            r"add\s+.+\s+to my todo list", r"add\s+.+\s+to my tasks"
        ],
        handler=handle_add_task,
        requires_confirmation=False,
        description="add a task to the todo list",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=["Add buy groceries to my tasks", "Add 'Review PRs' to my todo list"],
        schema=AddTaskSchema,
    ))

    # List Tasks
    registry.register(Capability(
        name="list_tasks",
        triggers=["my tasks", "list tasks", "todo list", "show tasks", "show my tasks"],
        handler=handle_list_tasks,
        requires_confirmation=False,
        description="list pending tasks",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=["List my tasks", "Show my todo list"],
        schema=ListTasksSchema,
    ))

    # Complete Task
    registry.register(Capability(
        name="complete_task",
        triggers=["mark as done", "mark as complete", "complete task", "finish task", 
                  "done with", "finished", "mark done", "task done", "check off"],
        handler=handle_complete_task,
        requires_confirmation=False,
        description="mark a task as complete",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=["Mark 'Review PRs' as done", "Complete the groceries task"],
        schema=CompleteTaskSchema,
    ))

    # Timer (alias of reminder)
    registry.register(Capability(
        name="timer",
        triggers=["set a timer", "timer", "countdown", "count down", "alarm", "wake me up"],
        handler=handle_timer,
        requires_confirmation=False,
        description="set a timer",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=["Set a timer for 10 minutes", "Timer for pasta for 12 mins"],
    ))
    
    # Assistant Status (also registered in help_capabilities; avoid duplicate registration)
    if registry.get("status") is None:
        registry.register(Capability(
            name="status",
            triggers=["status", "your status", "how are you", "system status"],
            handler=handle_status,
            requires_confirmation=False,
            description="report assistant status",
            capability_type=CapabilityType.SYSTEM,
            examples=["Status", "How are you?"],
            schema=AssistantStatusSchema
        ))
    
class DeleteTaskSchema(BaseModel):
    target: str = Field(..., description="Task content to delete, or 'all', or 'last'.")


# ... (Skipping to handler implementation)

def handle_delete_task(text: str, context: Dict[str, Any]) -> ActionResult:
    """Delete a task permanently (from ToDo or Schedule)."""
    task_manager = get_task_manager()
    # Lazy import to avoid circular dependency
    from ..core.scheduler import get_scheduler
    scheduler = get_scheduler()
    
    target = None
    
    validated = context.get("_validated_params")
    if validated and isinstance(validated, DeleteTaskSchema):
        target = validated.target.lower()
    
    if not target:
        # Extract target from text
        quote_match = re.search(r'"([^"]+)"|\'([^\']+)\'', text)
        if quote_match:
            target = (quote_match.group(1) or quote_match.group(2) or "").strip().lower()
        else:
            text_lower = text.lower()
            if "all" in text_lower:
                target = "all"
            elif "last" in text_lower:
                target = "last"
            else:
                # Try to extract after 'delete task'
                for pattern in ["delete task ", "remove task ", "delete ", "cancel "]:
                    if pattern in text_lower:
                        idx = text_lower.index(pattern) + len(pattern)
                        target = text_lower[idx:].strip().rstrip(".")
                        # Remove trailing garbage
                        target = re.sub(r"\s+(task|schedule|scheduler|job)\s*$", "", target).strip()
                        break
    
    if not target:
        return ActionResult.fail("What task would you like to delete?", "delete_task")
    
    deleted_items = []
    
    # === 1. DELETE FROM TASK LIST ===
    todo_tasks = task_manager.list_tasks(limit=100)
    
    if target == "all":
        # Delete all ToDo tasks
        for t in todo_tasks:
            if task_manager.delete_task(t.id):
                deleted_items.append(f"ToDo: {t.content}")
        
        # Delete all Scheduled Tasks
        scheduled_tasks = scheduler.list_tasks()
        for st in scheduled_tasks:
            if scheduler.cancel(st.id):
                deleted_items.append(f"Schedule: {st.name}")
                
        if not deleted_items:
            return ActionResult.ok("No tasks found to delete.", capability="delete_task")
        return ActionResult.ok(f"Deleted {len(deleted_items)} items.", capability="delete_task")

    # === 2. SMART SEARCH & DELETE ===
    
    # Search ToDo List
    todo_match = None
    for t in todo_tasks:
        if target in t.content.lower() or t.content.lower() in target:
            todo_match = t
            break
            
    # Search Scheduler
    schedule_match = None
    scheduled_tasks = scheduler.list_tasks()
    for st in scheduled_tasks:
        if target in st.name.lower() or st.name.lower() in target:
            schedule_match = st
            break

    # Action
    if todo_match:
        if task_manager.delete_task(todo_match.id):
            deleted_items.append(f"ToDo: {todo_match.content}")
            
    if schedule_match:
        if scheduler.cancel(schedule_match.id):
            deleted_items.append(f"Schedule: {schedule_match.name}")
            
    if not deleted_items:
        # Fallback: check "last"
        if target == "last" and todo_tasks:
             if task_manager.delete_task(todo_tasks[0].id):
                 return ActionResult.ok(f"Deleted last task: {todo_tasks[0].content}", capability="delete_task")
                 
        return ActionResult.fail(f"Couldn't find any task or schedule matching '{target}'.", "delete_task")

    return ActionResult.ok(
        f"Deleted: {', '.join(deleted_items)}",
        {"deleted": deleted_items},
        "delete_task"
    )

def handle_job_search(text: str, context: Dict[str, Any]) -> ActionResult:
    """Search for jobs using the JobSearcher automation."""
    from ..automation.job_search import JobSearcher
    
    searcher = JobSearcher()
    
    query = None
    location = None
    platform = "linkedin"
    
    validated = context.get("_validated_params")
    if validated and isinstance(validated, JobSearchSchema):
        query = validated.query
        location = validated.location
        platform = validated.platform
    
    if not query:
        # Fallback to manual parsing if schema validation didn't happen
        parsed_role, parsed_loc = JobSearcher.parse_job_query(text)
        query = parsed_role
        location = location or parsed_loc
    
    if not query:
        return ActionResult.fail("What kind of jobs are you looking for?", "job_search")
    
    success = searcher.search(query=query, location=location, platform=platform)
    
    if success:
        loc_str = f" in {location}" if location else ""
        return ActionResult.ok(
            f"Searching for {query} jobs{loc_str} on {platform}.",
            {"query": query, "location": location, "platform": platform},
            "job_search"
        )
    else:
        return ActionResult.fail("I failed to open the job search.", "job_search")


# ... (Skipping to registration)

    # Delete Task
    registry.register(Capability(
        name="delete_task",
        triggers=["delete task", "remove task", "clear tasks", "delete all my tasks", "remove all tasks"],
        handler=handle_delete_task,
        requires_confirmation=True, # Safety first!
        description="delete a task permanently",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=["Delete 'Buy milk'", "Delete all tasks"],
        schema=DeleteTaskSchema,
    ))

    # Job Search
    registry.register(Capability(
        name="job_search",
        triggers=["find jobs", "search for jobs", "find roles", "job search", "look for jobs"],
        handler=handle_job_search,
        requires_confirmation=False,
        description="search for jobs online",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=["Find me Python jobs in Atlanta", "Search for 'Software Engineer' roles on Indeed"],
        schema=JobSearchSchema,
    ))

    logger.info("Registered task capabilities")

