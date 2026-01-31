"""
Task Capabilities for Chintu Assistant.
Handlers for reminders, task management, and status queries.
"""

import re
import logging
from datetime import datetime, timedelta
from typing import Dict, Any

from ..core.capabilities import (
    Capability, CapabilityType, ActionResult, get_registry
)
from .task_manager import get_task_manager, TaskStatus

logger = logging.getLogger(__name__)


def parse_time_expression(text: str) -> timedelta:
    """Parse time expressions like '5 minutes' or absolute times like '6pm'."""
    text_lower = text.lower()
    
    # 1. Check for relative time FIRST (to avoid misinterpreting "in 10 minutes" as "at 10:00")
    total = timedelta()
    
    # Hours
    hour_match = re.search(r'(\d+)\s*hours?', text_lower)
    if hour_match:
        total += timedelta(hours=int(hour_match.group(1)))
    
    # Minutes
    min_match = re.search(r'(\d+)\s*min(?:ute)?s?', text_lower)
    if min_match:
        total += timedelta(minutes=int(min_match.group(1)))
    
    # Seconds
    sec_match = re.search(r'(\d+)\s*sec(?:ond)?s?', text_lower)
    if sec_match:
        total += timedelta(seconds=int(sec_match.group(1)))
    
    if total > timedelta():
        return total

    # 2. Check for absolute time (e.g., "6pm", "at 18:00", "at 5:30")
    # Require either 'at/for', 'am/pm', or a colon to count as absolute time
    abs_time_match = re.search(r'(?:at|for)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?|(\d{1,2}):(\d{2})\s*(am|pm)?|(\d{1,2})\s*(am|pm)', text_lower)
    if abs_time_match:
        # Group handling (multiple patterns in one regex)
        groups = abs_time_match.groups()
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
            
        if meridiem == 'pm' and hour < 12:
            hour += 12
        elif meridiem == 'am' and hour == 12:
            hour = 0
            
        now = datetime.now()
        target_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        
        # If time has passed today (or is very close), assume tomorrow
        if target_time <= now + timedelta(minutes=1):
            target_time += timedelta(days=1)
            
        return target_time - now
    
    return timedelta(minutes=5)  # Default 5 min


def extract_reminder_content(text: str) -> str:
    """Extract the reminder content from user text."""
    # Remove trigger phrases
    patterns = [
        r'remind me (?:to|about|that)\s+',
        r'set a reminder (?:to|for|about)\s+',
        r'remind me in \d+\s*(?:hours?|minutes?|seconds?)\s*(?:to|about|that)?\s*',
        r'in \d+\s*(?:hours?|minutes?|seconds?)\s*remind me (?:to|about)?\s*',
    ]
    
    result = text
    for pattern in patterns:
        result = re.sub(pattern, '', result, flags=re.IGNORECASE)
    
    return result.strip().strip('.')


# ============================================================================
# REMINDER CAPABILITIES
# ============================================================================

def handle_set_reminder(text: str, context: Dict[str, Any]) -> ActionResult:
    """Set a reminder for the user."""
    task_manager = get_task_manager()
    text_lower = text.lower()
    
    # Parse delay time
    delay = parse_time_expression(text)
    
    # Extract reminder content
    content = extract_reminder_content(text)
    
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
        time_str = f"{int(delay.total_seconds() // 60)} minutes"
    else:
        hours = delay.total_seconds() / 3600
        time_str = f"{hours:.1f} hours"
    
    return ActionResult.ok(
        f"I'll remind you in {time_str}: '{content}'",
        {"task_id": task.id, "trigger_time": trigger_time.isoformat()},
        "set_reminder"
    )


def handle_list_reminders(text: str, context: Dict[str, Any]) -> ActionResult:
    """List pending reminders."""
    task_manager = get_task_manager()
    
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
        lines.append(f"• {r.content} ({time_str})")
    
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
    
    # Cancel all or specific?
    if "all" in text.lower():
        for r in reminders:
            task_manager.cancel_task(r.id)
        return ActionResult.ok(f"Cancelled {len(reminders)} reminders.", capability="cancel_reminder")
    
    # Cancel the most recent one
    task_manager.cancel_task(reminders[0].id)
    return ActionResult.ok(
        f"Cancelled reminder: '{reminders[0].content}'",
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
            parts.append(f"  • {t.content}")
    
    return ActionResult.ok(
        "\n".join(parts),
        {"stats": stats, "upcoming": len(upcoming)},
        "task_status"
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
        examples=["Remind me in 10 minutes to take a break", "Set a reminder for 2 hours"]
    ))
    
    # List Reminders
    registry.register(Capability(
        name="list_reminders",
        triggers=["my reminders", "list reminders", "show reminders", "pending reminders"],
        handler=handle_list_reminders,
        requires_confirmation=False,
        description="list pending reminders",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=["Show my reminders", "What reminders do I have?"]
    ))
    
    # Cancel Reminder
    registry.register(Capability(
        name="cancel_reminder",
        triggers=["cancel reminder", "delete reminder", "remove reminder", "cancel all reminders"],
        handler=handle_cancel_reminder,
        requires_confirmation=False,
        description="cancel a reminder",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=["Cancel my reminder", "Cancel all reminders"]
    ))
    
    # Task Status
    registry.register(Capability(
        name="task_status",
        triggers=["task status", "my tasks", "pending tasks"],
        handler=handle_task_status,
        requires_confirmation=False,
        description="show task status",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=["Task status", "What tasks do I have?"]
    ))
    
    # Assistant Status
    registry.register(Capability(
        name="status",
        triggers=["status", "your status", "how are you", "system status"],
        handler=handle_status,
        requires_confirmation=False,
        description="report assistant status",
        capability_type=CapabilityType.SYSTEM,
        examples=["Status", "How are you?"]
    ))
    
    logger.info("Registered task capabilities")
