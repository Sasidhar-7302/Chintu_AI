"""
Default Rules for Proactivity Engine.
"""

from typing import Dict, Any
from .rules import Rule

def battery_low_condition(signals: Dict[str, Any]) -> bool:
    """Condition: Battery < 20% and not plugged in."""
    battery = signals.get("battery_percent", 100)
    plugged = signals.get("is_plugged_in", True)
    return battery < 20 and not plugged

def work_start_condition(signals: Dict[str, Any]) -> bool:
    """Condition: Weekday at 9 AM."""
    hour = signals.get("hour", 0)
    minute = signals.get("minute", 0)
    is_weekday = signals.get("is_weekday", False)
    
    # Trigger between 9:00 and 9:05
    return is_weekday and hour == 9 and 0 <= minute <= 5

def get_default_rules():
    """Return a list of predefined safe rules."""
    return [
        Rule(
            id="battery_saver",
            name="Battery Saver Suggestion",
            condition=battery_low_condition,
            suggestion_text="Battery is low (below 20%). Should I close background apps to save power?",
            priority=8,
            cooldown_seconds=1800  # 30 mins
        ),
        Rule(
            id="morning_routine",
            name="Morning Work Routine",
            condition=work_start_condition,
            suggestion_text="Good morning! It's 9 AM. Shall I open your work applications?",
            priority=5,
            cooldown_seconds=3600 * 12 # 12 hours (once per day)
        )
    ]
