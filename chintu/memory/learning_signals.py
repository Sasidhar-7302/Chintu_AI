"""
Learning Signals System.
Detects user corrections and feedback to propose preference updates.
"""

import logging
import re
from typing import Dict, Optional, List, Any
from dataclasses import dataclass

from .preferences import get_preference_manager

logger = logging.getLogger(__name__)

@dataclass
class LearningSignal:
    signal_type: str  # "correction", "preference", "fact"
    content: str
    confidence: float
    proposed_action: Dict[str, Any]

class LearningSignalManager:
    """Detects learning opportunities from user messages."""
    
    def __init__(self):
        self.prefs = get_preference_manager()
    
    def analyze_feedback(self, user_text: str, last_assistant_action: Optional[str] = None) -> List[LearningSignal]:
        """Analyze user text for potential learning signals."""
        signals = []
        text = user_text.lower()
        
        # 1. Negative Preference Detection ("Don't do X")
        dont_patterns = [
            r"don'?t (ever )?use ([\w\s]+)",
            r"stop using ([\w\s]+)",
            r"never (use|do) ([\w\s]+)",
            r"avoid ([\w\s]+)"
        ]
        
        for pattern in dont_patterns:
            match = re.search(pattern, text)
            if match:
                target = match.group(2).strip()
                signals.append(LearningSignal(
                    signal_type="preference",
                    content=f"User wants to avoid: {target}",
                    confidence=0.85,
                    proposed_action={"type": "negative_preference", "value": target}
                ))

        # 2. Positive Preference Detection ("Use X instead", "I prefer X")
        do_patterns = [
            r"use ([\w\s]+) instead",
            r"i prefer ([\w\s]+)",
            r"always use ([\w\s]+)",
            r"make sure to ([\w\s]+)"
        ]
        
        for pattern in do_patterns:
            match = re.search(pattern, text)
            if match:
                target = match.group(1).strip()
                signals.append(LearningSignal(
                    signal_type="preference",
                    content=f"User prefers: {target}",
                    confidence=0.85,
                    proposed_action={"type": "positive_preference", "value": target}
                ))

        # 3. Response Style Corrections ("Be more concise")
        style_map = {
            "concise": "concise",
            "short": "concise",
            "brief": "concise",
            "detailed": "detailed",
            "long": "detailed",
            "elaborate": "detailed",
            "funny": "humorous",
            "humor": "humorous",
            "serious": "serious",
            "formal": "formal"
        }
        
        for key, style in style_map.items():
            if f"be {key}" in text or f"make it {key}" in text or f"keep it {key}" in text:
                signals.append(LearningSignal(
                    signal_type="preference",
                    content=f"User wants response style: {style}",
                    confidence=0.9,
                    proposed_action={"type": "update_style", "value": style}
                ))

        return signals

    def process_signal(self, signal: LearningSignal) -> str:
        """
        Process a signal and return a proposal string for the user.
        Actual update happens only after user confirmation (handled by CommandHandler).
        """
        if signal.proposed_action["type"] == "update_style":
            return f"I've noticed you prefer {signal.proposed_action['value']} responses. Should I save that as your default preference?"
            
        return f"I detected a preference: '{signal.content}'. Should I remember this for next time?"

# Global instance
_signal_manager = None

def get_signal_manager():
    global _signal_manager
    if not _signal_manager:
        _signal_manager = LearningSignalManager()
    return _signal_manager
