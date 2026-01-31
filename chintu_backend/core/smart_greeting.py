"""Smart Greeting System - Time-aware, personalized greetings.

Generates intelligent greetings based on:
- Time of day
- Previous conversations
- User preferences
"""

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


def get_time_of_day() -> str:
    """Get current time of day."""
    hour = datetime.now().hour
    if 5 <= hour < 12:
        return "morning"
    elif 12 <= hour < 17:
        return "afternoon"
    elif 17 <= hour < 21:
        return "evening"
    else:
        return "night"


def get_smart_greeting(user_name: str = None) -> str:
    """Generate a smart, personalized greeting.
    
    Args:
        user_name: Optional user name for personalization
        
    Returns:
        A warm, context-aware greeting
    """
    time_of_day = get_time_of_day()
    hour = datetime.now().hour
    
    # Time-based greetings
    greetings = {
        "morning": [
            "Good morning! Hope you're having a great start to your day!",
            "Morning! Ready to help you tackle the day!",
            "Good morning! What can I do for you today?",
        ],
        "afternoon": [
            "Good afternoon! How can I help you?",
            "Hey there! Hope your afternoon is going well!",
            "Good afternoon! What's on your mind?",
        ],
        "evening": [
            "Good evening! How can I help?",
            "Hey! Hope you had a productive day. What can I do for you?",
            "Good evening! Ready to assist!",
        ],
        "night": [
            "Hey! Burning the midnight oil? How can I help?",
            "Hi there! Working late? Let me help you out!",
            "Hey! I'm here whenever you need me!",
        ]
    }
    
    # Pick greeting based on current minute (for variety)
    options = greetings.get(time_of_day, greetings["afternoon"])
    idx = datetime.now().minute % len(options)
    greeting = options[idx]
    
    # Personalize if we have the name
    if user_name:
        # Insert name naturally
        if "!" in greeting:
            parts = greeting.split("!", 1)
            greeting = f"{parts[0]}, {user_name}!{parts[1]}" if len(parts) > 1 else f"{parts[0]}, {user_name}!"
    
    return greeting


def get_returning_greeting(last_seen: datetime = None, user_name: str = None) -> str:
    """Generate greeting for returning user.
    
    Args:
        last_seen: When user was last active
        user_name: Optional user name
    """
    if last_seen:
        hours_gone = (datetime.now() - last_seen).total_seconds() / 3600
        
        if hours_gone < 1:
            return "Welcome back! That was quick!"
        elif hours_gone < 8:
            return "Hey, welcome back! What can I help you with?"
        elif hours_gone < 24:
            return get_smart_greeting(user_name)
        else:
            days = int(hours_gone / 24)
            return f"Hey! Great to see you again! How can I help?"
    
    return get_smart_greeting(user_name)


def get_quick_acknowledgment() -> str:
    """Get a quick acknowledgment for wake word detection."""
    options = [
        "Yes?",
        "Hey!",
        "I'm here!",
        "Listening!",
        "What's up?",
        "Yes, I'm listening!",
    ]
    idx = datetime.now().second % len(options)
    return options[idx]
