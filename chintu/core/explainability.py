"""
Explainability System for Chintu Assistant.
Allows users to understand why actions were taken.
"""

import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime
from collections import deque

from ..core.capabilities import get_registry

logger = logging.getLogger(__name__)


@dataclass
class ActionRecord:
    """Record of an action taken by the assistant."""
    timestamp: str
    user_input: str
    capability_name: str
    action_description: str
    success: bool
    triggers_matched: List[str] = field(default_factory=list)
    response: str = ""


class ExplainabilityEngine:
    """
    Tracks and explains assistant actions.
    Builds trust by making the assistant's decisions transparent.
    """
    
    def __init__(self, max_history: int = 50):
        self._history: deque = deque(maxlen=max_history)
        self._last_action: Optional[ActionRecord] = None
    
    def record_action(
        self,
        user_input: str,
        capability_name: str,
        action_description: str,
        success: bool,
        triggers_matched: List[str] = None,
        response: str = ""
    ) -> ActionRecord:
        """Record an action for later explanation."""
        record = ActionRecord(
            timestamp=datetime.now().isoformat(),
            user_input=user_input,
            capability_name=capability_name,
            action_description=action_description,
            success=success,
            triggers_matched=triggers_matched or [],
            response=response
        )
        self._history.append(record)
        self._last_action = record
        return record
    
    def explain_last_action(self) -> str:
        """Explain why the last action was taken."""
        if not self._last_action:
            return "I haven't taken any actions yet."
        
        action = self._last_action
        registry = get_registry()
        
        # Get capability info
        cap = registry.get(action.capability_name)
        
        parts = []
        
        # What was done
        parts.append(f"You asked: \"{action.user_input}\"")
        
        # Why it was done
        if action.triggers_matched:
            triggers = ", ".join(f"'{t}'" for t in action.triggers_matched)
            parts.append(f"I detected {triggers} in your request.")
        
        if cap:
            parts.append(f"This triggered the {action.capability_name} capability, which {cap.description}.")
        else:
            parts.append(f"I used the {action.capability_name} capability.")
        
        # What happened
        if action.success:
            parts.append(f"The action was successful.")
        else:
            parts.append(f"The action encountered an issue.")
        
        return " ".join(parts)
    
    def explain_capability(self, capability_name: str) -> str:
        """Explain what a specific capability does."""
        registry = get_registry()
        cap = registry.get(capability_name)
        
        if not cap:
            return f"I don't have a capability called '{capability_name}'."
        
        parts = [
            f"**{cap.name}**: {cap.description}",
            f"Type: {cap.capability_type.value}",
            f"Triggers: {', '.join(cap.triggers[:5])}",
        ]
        
        if cap.examples:
            parts.append(f"Examples: {', '.join(cap.examples[:3])}")
        
        if cap.requires_confirmation:
            parts.append("Note: This action requires confirmation before executing.")
        
        return "\n".join(parts)
    
    def get_history(self, limit: int = 10) -> List[ActionRecord]:
        """Get recent action history."""
        return list(self._history)[-limit:]
    
    def get_capabilities_summary(self) -> str:
        """Get a SHORT summary of capabilities for TTS."""
        registry = get_registry()
        caps = registry.list_capabilities()
        count = len(caps)
        
        # Short, TTS-friendly response
        summary = f"""I can help with {count} different things:

**Apps & Web**: Open apps, websites, and search the web.
**Tasks & Reminders**: Set reminders, manage tasks, and schedule recurring workflows.
**Memory**: Remember things about you and recall them later.
**Browser**: Automate browser tasks, take screenshots, read pages.
**Files**: Read files, copy to clipboard, and more.

For the full list, say "help" or ask about a specific capability."""
        
        return summary


# Global instance
_explainability: Optional[ExplainabilityEngine] = None


def get_explainability() -> ExplainabilityEngine:
    """Get or create the global explainability engine."""
    global _explainability
    if _explainability is None:
        _explainability = ExplainabilityEngine()
    return _explainability
