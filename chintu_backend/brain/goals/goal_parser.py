"""
Natural Language Goal Parser for Chintu v5.1

Parses natural language goal descriptions into structured Goal objects.

Examples:
    "Read me news every morning at 9 AM"
    "Monitor my website https://example.com every hour and tell me if it's down"
    "Remind me to exercise every day at 6 PM"
    "Track my app metrics and send me a weekly report on Mondays"
"""

import re
import logging
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timedelta

from .goal_manager import GoalType, RecurrencePattern

logger = logging.getLogger(__name__)


def parse_goal_from_text(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse a natural language goal description into goal parameters.
    
    Args:
        text: Natural language description like "read me news every morning at 9am"
        
    Returns:
        Dict with goal parameters or None if parsing fails
    """
    text_lower = text.lower().strip()
    
    # Extract time
    schedule_time = _extract_time(text_lower)
    
    # Determine recurrence pattern
    recurrence, schedule_days = _extract_recurrence(text_lower)
    
    # Determine goal type
    goal_type = _determine_goal_type(text_lower)
    
    # Extract the action command (what to do)
    action_command = _extract_action(text)
    
    # Extract name (first few words or generate from action)
    name = _generate_name(text, action_command)
    
    return {
        "name": name,
        "action_command": action_command,
        "goal_type": goal_type,
        "recurrence": recurrence,
        "schedule_time": schedule_time,
        "schedule_days": schedule_days,
        "description": text,
    }


def _extract_time(text: str) -> str:
    """Extract time from text, default to 09:00."""
    # Match patterns like "9am", "9:30 am", "21:00", "9 in the morning"
    
    # Pattern: HH:MM AM/PM or HH AM/PM
    time_match = re.search(r'(\d{1,2}):?(\d{2})?\s*(am|pm|a\.m\.|p\.m\.)?', text)
    
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2)) if time_match.group(2) else 0
        am_pm = time_match.group(3)
        
        if am_pm and ('pm' in am_pm or 'p.m.' in am_pm) and hour < 12:
            hour += 12
        elif am_pm and ('am' in am_pm or 'a.m.' in am_pm) and hour == 12:
            hour = 0
        
        return f"{hour:02d}:{minute:02d}"
    
    # Time of day keywords
    if "morning" in text:
        return "09:00"
    elif "afternoon" in text:
        return "14:00"
    elif "evening" in text:
        return "18:00"
    elif "night" in text:
        return "21:00"
    elif "noon" in text or "midday" in text:
        return "12:00"
    
    return "09:00"  # Default


def _extract_recurrence(text: str) -> Tuple[Optional[RecurrencePattern], Optional[list]]:
    """Extract recurrence pattern and days from text."""
    
    # Check for interval patterns first
    interval_match = re.search(r'every\s+(\d+)\s*(hour|minute)', text)
    if interval_match:
        return RecurrencePattern.HOURLY, None
    
    if "every hour" in text or "hourly" in text:
        return RecurrencePattern.HOURLY, None
    
    # Daily patterns
    daily_patterns = ["every day", "daily", "every morning", "every evening", "every night"]
    if any(p in text for p in daily_patterns):
        return RecurrencePattern.DAILY, None
    
    # Weekly patterns
    days_of_week = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    found_days = [day for day in days_of_week if day in text]
    
    if found_days or "every week" in text or "weekly" in text:
        return RecurrencePattern.WEEKLY, found_days if found_days else ["monday"]
    
    # Monthly patterns
    if "every month" in text or "monthly" in text:
        return RecurrencePattern.MONTHLY, None
    
    # No recurrence found - one-time
    return None, None


def _determine_goal_type(text: str) -> GoalType:
    """Determine the goal type from text."""
    
    # Monitoring keywords
    monitor_keywords = ["monitor", "watch", "track", "check", "health check", "status"]
    if any(kw in text for kw in monitor_keywords):
        return GoalType.MONITORING
    
    # Habit keywords
    habit_keywords = ["habit", "exercise", "workout", "meditate", "practice"]
    if any(kw in text for kw in habit_keywords):
        return GoalType.HABIT
    
    # Project keywords
    project_keywords = ["project", "build", "create", "develop", "research"]
    if any(kw in text for kw in project_keywords):
        return GoalType.PROJECT
    
    # Check for recurrence indicators
    recurring_keywords = ["every", "daily", "weekly", "monthly", "hourly"]
    if any(kw in text for kw in recurring_keywords):
        return GoalType.RECURRING
    
    return GoalType.ONE_TIME


def _extract_action(text: str) -> str:
    """Extract the action command from the goal text."""
    # Remove scheduling phrases to get the core action
    scheduling_phrases = [
        r"every\s+(day|morning|evening|night|hour|week|month|monday|tuesday|wednesday|thursday|friday|saturday|sunday)",
        r"at\s+\d{1,2}(:\d{2})?\s*(am|pm|a\.m\.|p\.m\.)?",
        r"daily|weekly|monthly|hourly",
        r"remind me to",
        r"please",
    ]
    
    action = text
    for phrase in scheduling_phrases:
        action = re.sub(phrase, "", action, flags=re.IGNORECASE)
    
    # Clean up extra spaces
    action = re.sub(r'\s+', ' ', action).strip()
    
    return action if action else text


def _generate_name(text: str, action: str) -> str:
    """Generate a short name for the goal."""
    # Take first 5 words of action, capitalize
    words = action.split()[:5]
    name = " ".join(words).title()
    
    # Limit length
    if len(name) > 50:
        name = name[:47] + "..."
    
    return name

