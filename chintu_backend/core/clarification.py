"""
Clarification System for Chintu AI Assistant.

Handles ambiguous user input by:
- Detecting unclear commands
- Asking targeted clarification questions
- Tracking pending clarifications
- Providing helpful suggestions
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Callable
from enum import Enum

logger = logging.getLogger(__name__)


class ClarificationType(Enum):
    """Types of clarification needed."""
    MISSING_TARGET = "missing_target"      # "open" -> open what?
    AMBIGUOUS_ACTION = "ambiguous_action"  # Could mean multiple things
    INCOMPLETE_INFO = "incomplete_info"    # Need more details
    CONFIRMATION = "confirmation"          # Verify understanding
    CHOICE = "choice"                      # Multiple options available


@dataclass
class ClarificationRequest:
    """A pending clarification request."""
    type: ClarificationType
    question: str
    original_text: str
    options: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    callback: Optional[Callable[[str], Any]] = None


class ClarificationManager:
    """
    Manages clarification requests and responses.
    
    Tracks when the assistant needs more information and
    handles the follow-up conversation.
    """
    
    def __init__(self):
        self._pending: Optional[ClarificationRequest] = None
        self._history: List[ClarificationRequest] = []
        
        # Patterns that indicate incomplete commands
        self._incomplete_patterns = [
            (r"^(open|launch|start|run)\s*$", "What would you like me to open?"),
            (r"^(search|find|look for)\s*$", "What would you like me to search for?"),
            (r"^(play|show|display)\s*$", "What would you like me to play?"),
            (r"^(send|write|create)\s*$", "What would you like me to create?"),
            (r"^(close|stop|end)\s*$", "What would you like me to close?"),
            (r"^(set|change|update)\s*$", "What would you like me to change?"),
            (r"^(tell me|what is|what's)\s*$", "What would you like to know?"),
            (r"^(remind me|remember)\s*$", "What should I remind you about?"),
            (r"^(schedule|plan)\s*$", "What would you like me to schedule?"),
        ]
        
        # Very short/vague inputs
        self._vague_patterns = [
            (r"^(do it|go|okay|yes|no|maybe|sure|fine)$", None),  # Context-dependent
            (r"^(help|what|how|why|when|where|who)$", "Could you be more specific?"),
            (r"^(this|that|it|them|those)$", "I'm not sure what you're referring to. Could you clarify?"),
        ]
    
    def check_needs_clarification(self, text: str) -> Optional[ClarificationRequest]:
        """
        Check if user input needs clarification.
        
        Args:
            text: User's input text
            
        Returns:
            ClarificationRequest if clarification needed, None otherwise
        """
        text_lower = text.lower().strip()
        
        # Check for incomplete commands
        for pattern, question in self._incomplete_patterns:
            if re.match(pattern, text_lower, re.IGNORECASE):
                return ClarificationRequest(
                    type=ClarificationType.MISSING_TARGET,
                    question=question,
                    original_text=text,
                )
        
        # Check for vague inputs
        for pattern, question in self._vague_patterns:
            if re.match(pattern, text_lower, re.IGNORECASE):
                if question:
                    return ClarificationRequest(
                        type=ClarificationType.INCOMPLETE_INFO,
                        question=question,
                        original_text=text,
                    )
        
        # Check for very short input (1-2 words that aren't greetings)
        words = text_lower.split()
        greetings = {"hi", "hello", "hey", "bye", "goodbye", "thanks", "thank"}
        if len(words) <= 2 and not any(w in greetings for w in words):
            # Check if it's a question word alone
            question_words = {"what", "how", "why", "when", "where", "who", "which"}
            if len(words) == 1 and words[0] in question_words:
                return ClarificationRequest(
                    type=ClarificationType.INCOMPLETE_INFO,
                    question=f"What would you like to know about?",
                    original_text=text,
                )
        
        return None
    
    def set_pending(self, request: ClarificationRequest) -> None:
        """Set a pending clarification request."""
        self._pending = request
        self._history.append(request)
        logger.info(f"Clarification pending: {request.type.value} - {request.question}")
    
    def has_pending(self) -> bool:
        """Check if there's a pending clarification."""
        return self._pending is not None
    
    def get_pending(self) -> Optional[ClarificationRequest]:
        """Get the pending clarification request."""
        return self._pending
    
    def resolve_pending(self, response: str) -> Optional[str]:
        """
        Resolve pending clarification with user's response.
        
        Returns:
            Combined command (original + clarification) or None
        """
        if not self._pending:
            return None
        
        original = self._pending.original_text
        self._pending = None
        
        # Combine original command with clarification
        # e.g., "open" + "chrome" -> "open chrome"
        combined = f"{original} {response}".strip()
        logger.info(f"Clarification resolved: '{original}' + '{response}' = '{combined}'")
        return combined
    
    def clear_pending(self) -> None:
        """Clear any pending clarification."""
        self._pending = None


# Global instance
_clarification_manager: Optional[ClarificationManager] = None


def get_clarification_manager() -> ClarificationManager:
    """Get or create the global clarification manager."""
    global _clarification_manager
    if _clarification_manager is None:
        _clarification_manager = ClarificationManager()
    return _clarification_manager

