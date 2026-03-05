"""
Calendar Capabilities
---------------------
Voice commands for Google Calendar integration.
"""

import logging
import re
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from pydantic import BaseModel, Field

from chintu_backend.core.capabilities import Capability, CapabilityType, ActionResult, get_registry
from chintu_backend.integrations.google_calendar import get_calendar
from chintu_backend.tasks.task_manager import get_task_manager

logger = logging.getLogger(__name__)


_MEETING_KEYWORDS = (
    "meeting",
    "appointment",
    "dentist",
    "doctor",
    "interview",
    "standup",
    "sync",
    "call",
    "event",
)

_NON_MEETING_HINTS = (
    "buy ",
    "grocer",
    "timer",
    "todo",
    "task",
    "remind me",
)


def _is_meeting_like_task(task: Any) -> bool:
    """Best-effort classifier for meeting/event entries in local fallback mode."""
    try:
        metadata = getattr(task, "metadata", {}) or {}
    except Exception:
        metadata = {}

    source = str(metadata.get("source", "")).strip().lower()
    kind = str(metadata.get("kind", "")).strip().lower()
    if source in {"calendar_event", "calendar"} or kind in {"meeting", "appointment", "event"}:
        return True

    content = str(getattr(task, "content", "") or "").strip().lower()
    if not content:
        return False
    if any(token in content for token in _NON_MEETING_HINTS):
        return False
    return any(token in content for token in _MEETING_KEYWORDS)

# ============================================================================
# SCHEMAS
# ============================================================================

class SetupCalendarSchema(BaseModel):
    pass

class ListCalendarSchema(BaseModel):
    limit: int = Field(5, description="Number of events to list.")

class AddEventSchema(BaseModel):
    title: str = Field(..., description="Title of the event/reminder.")
    start_time: str = Field(..., description="Start time (e.g., '2023-10-27 10:00', 'tomorrow at 9am').")

def handle_setup_calendar(text: str, context: Dict[str, Any] = None) -> ActionResult:
    """Authenticate with Google Calendar."""
    from chintu_backend.integrations.oauth_onboarding import connect_google_calendar

    context = context or {}
    credentials_path = None
    if isinstance(context.get("_extracted_params"), dict):
        credentials_path = context["_extracted_params"].get("credentials_path")
    result = connect_google_calendar(
        credentials_path=str(credentials_path) if credentials_path else None,
        write_access=None,
        force_reauth=False,
    )
    if bool(result.get("ok")):
        return ActionResult.ok(
            str(result.get("message") or "Google Calendar connected."),
            {"receipt_path": result.get("receipt_path"), "scopes": result.get("scopes")},
            "setup_calendar",
        )
    return ActionResult.fail(str(result.get("message") or "Calendar setup failed."), "setup_calendar")

def handle_list_calendar(text: str, context: Dict[str, Any] = None) -> ActionResult:
    """List upcoming events."""
    calendar = get_calendar()
    limit = 5
    text_lower = (text or "").lower()
    wants_next_meeting = any(
        k in text_lower for k in ("next meeting", "next appointment", "time is my next meeting")
    )
    
    validated = context.get("_validated_params")
    if validated and isinstance(validated, ListCalendarSchema):
        limit = validated.limit
    
    if not calendar.is_authenticated:
        # Fallback to local tasks
        tm = get_task_manager()
        tasks = tm.get_pending_tasks()
        if not tasks:
            return ActionResult.fail("No upcoming local reminders found. Say 'setup calendar' to link Google Calendar.")

        normalized = []
        for t in tasks:
            dt = None
            try:
                if getattr(t, "trigger_time", None):
                    dt = datetime.fromisoformat(t.trigger_time)
            except Exception:
                dt = None
            normalized.append((t, dt))

        # Prefer tasks that have explicit scheduled time for calendar-like queries.
        timed = [item for item in normalized if item[1] is not None]
        selected = (timed or normalized)[:limit]

        if wants_next_meeting:
            timed_meetings = [(task, dt) for task, dt in timed if _is_meeting_like_task(task)]
            first = timed_meetings[0] if timed_meetings else None
            if first is not None:
                task, dt = first
                if dt is not None:
                    time_str = dt.strftime("%I:%M %p, %b %d")
                    return ActionResult.ok(
                        f"Your next meeting is '{task.content}' at {time_str}.",
                        {"next": task.to_dict()},
                    )
                return ActionResult.ok(
                    f"Your next meeting is '{task.content}'.",
                    {"next": task.to_dict()},
                )
            return ActionResult.ok(
                "I could not find your next scheduled meeting in the local calendar yet. "
                "You can say 'schedule a meeting at 3pm tomorrow'."
            )

        lines = ["Here are your upcoming local reminders:"]
        for task, dt in selected:
            if dt is not None:
                lines.append(f"- {task.content} at {dt.strftime('%I:%M %p, %b %d')}")
            else:
                lines.append(f"- {task.content}")
        return ActionResult.ok("\n".join(lines).strip(), {"tasks": [t.to_dict() for t, _ in selected]})
        
    events = calendar.get_upcoming_events(max_results=limit)
    if wants_next_meeting:
        if events:
            first = events[0]
            title = str(first.get("title") or "Untitled event")
            start = str(first.get("start") or "")
            pretty = calendar._format_time(start) if start else "an unknown time"
            return ActionResult.ok(
                f"Your next meeting is '{title}' at {pretty}.",
                {"next": first, "events": events},
            )
        return ActionResult.ok("You have no upcoming events for your next meeting.", {"events": []})

    response = calendar.format_events_for_voice(events)
    return ActionResult.ok(response, {"events": events})

def handle_add_event(text: str, context: Dict[str, Any] = None) -> ActionResult:
    """Add an event to the calendar."""
    calendar = get_calendar()
    
    title = None
    start_time_str = None
    start_time = None
    
    validated = context.get("_validated_params")
    if validated and isinstance(validated, AddEventSchema):
        title = validated.title
        start_time_str = validated.start_time
        
        # Parse strict time from schema if possible, or pass to local parser
        try:
             from chintu_backend.tasks.task_capabilities import parse_time_expression
             delay = parse_time_expression(start_time_str)
             start_time = datetime.now() + delay
        except Exception:
             # If parsing fails, default to 1 hour from now
             start_time = datetime.now() + timedelta(hours=1)
    
    if not title:
        # Legacy Extraction if schema didn't provide title
        try:
            from chintu_backend.tasks.task_capabilities import parse_time_expression
            delay = parse_time_expression(text)
            start_time = datetime.now() + delay
        except Exception:
            if start_time is None:
                start_time = datetime.now() + timedelta(hours=1)
            
        # Extract Title: Simple extraction based on prefixes
        title = text
        for prefix in ["add to calendar", "schedule meeting", "remind me to", "create event", "create an event for"]:
            start_idx = text.lower().find(prefix)
            if start_idx != -1:
                 prefix_len = len(prefix)
                 title = text[start_idx + prefix_len:].strip()
                 break
        if not title:
            title = "New Event"
    
    # Ensure start_time is set
    if start_time is None:
        start_time = datetime.now() + timedelta(hours=1)

    # If Google Calendar is not connected, use Local Reminders
    if not calendar.is_authenticated:
        try:
            tm = get_task_manager()
            tm.add_reminder(
                title,
                start_time,
                metadata={"source": "calendar_event", "kind": "meeting"},
            )
            time_str = start_time.strftime("%I:%M %p on %A")
            return ActionResult.ok(f"Added local reminder: '{title}' for {time_str} (Google Calendar not connected).")
        except Exception as e:
            return ActionResult.fail(f"Failed to add local reminder: {e}")
            
    event = calendar.create_event(title=title, start=start_time)
    
    if event:
        time_str = start_time.strftime("%I:%M %p on %A")
        return ActionResult.ok(f"Added event '{event['title']}' for {time_str}.")
    else:
        return ActionResult.fail("Failed to create event.")

def register_calendar_capabilities() -> None:
    """Register calendar capabilities."""
    registry = get_registry()
    
    registry.register(Capability(
        name="setup_calendar",
        triggers=["setup calendar", "connect google calendar", "link calendar", "setup google cal"],
        handler=handle_setup_calendar,
        description="Setup Google Calendar connection",
        capability_type=CapabilityType.SYSTEM,
        schema=SetupCalendarSchema
    ))
    
    # Fixed: Added triggers for meeting queries like "when is my next meeting"
    registry.register(Capability(
        name="list_calendar",
        triggers=["my schedule", "calendar events", "whats on my calendar", "show calendar", 
                  "list events", "my calendar", "next meeting", "when is my meeting",
                  "time of my meeting", "my next appointment", "upcoming events"],
        handler=handle_list_calendar,
        description="List upcoming calendar events",
        capability_type=CapabilityType.PRODUCTIVITY,
        schema=ListCalendarSchema
    ))
    
    # Fixed: Added triggers for dentist/doctor appointments to catch these before open_app
    registry.register(Capability(
        name="add_calendar_event",
        triggers=["add to calendar", "schedule meeting", "schedule a", "schedule an", 
                  "book", "appointment", "new event", "create event", "create an event",
                  "dentist", "doctor visit", "at 3pm tomorrow", "at 2pm tomorrow"],
        handler=handle_add_event,
        description="Add an event to the calendar",
        capability_type=CapabilityType.PRODUCTIVITY,
        schema=AddEventSchema
    ))
