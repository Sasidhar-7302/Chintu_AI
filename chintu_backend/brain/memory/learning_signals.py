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
                ))
                
        # 4. Content Feedback (News/Topics)
        # "That news was boring", "I like tech news", "Not interested in politics"
        content_patterns = [
            (r"(?:that|this) (?:news|story|article) (?:is|was) (?:boring|irrelevant|bad|useless)", "negative_content"),
            (r"not interested in ([\w\s]+)", "negative_topic"),
            (r"stop showing (?:me )?([\w\s]+)", "negative_topic"),
            (r"(?:that|this) (?:news|story|article) (?:is|was) (?:good|interesting|great|useful)", "positive_content"),
            (r"i (?:like|love|want) ([\w\s]+) (?:news|updates)", "positive_topic"),
            (r"more ([\w\s]+) (?:news|updates)", "positive_topic"),
        ]
        
        for pattern, signal_type in content_patterns:
            match = re.search(pattern, text)
            if match:
                content_val = match.group(1).strip() if match.re.groups > 0 else "last_topic"
                
                if signal_type == "negative_content":
                    signals.append(LearningSignal(
                        signal_type="feedback",
                        content="User disliked the last content.",
                        confidence=0.8,
                        proposed_action={"type": "negative_content_feedback", "value": "last_content"}
                    ))
                elif signal_type == "negative_topic":
                    signals.append(LearningSignal(
                        signal_type="preference",
                        content=f"User not interested in: {content_val}",
                        confidence=0.9,
                        proposed_action={"type": "negative_topic_preference", "value": content_val}
                    ))
                elif signal_type == "positive_content":
                    signals.append(LearningSignal(
                        signal_type="feedback",
                        content="User liked the last content.",
                        confidence=0.8,
                        proposed_action={"type": "positive_content_feedback", "value": "last_content"}
                    ))
                elif signal_type == "positive_topic":
                    signals.append(LearningSignal(
                        signal_type="preference",
                        content=f"User interested in: {content_val}",
                        confidence=0.9,
                        proposed_action={"type": "positive_topic_preference", "value": content_val}
                    ))

        # 5. Correction Detection ("No, that's wrong", "I didn't say that") - NEW for True AI
        correction_patterns = [
            r"no,? that'?s (wrong|incorrect|not right)",
            r"i didn'?t say that",
            r"you (got|understood) that wrong",
            r"stop (doing|saying) that",
            r"that'?s not (what i meant|true|correct)"
        ]
        
        for pattern in correction_patterns:
            if re.search(pattern, text):
                # High confidence for explicit corrections
                signals.append(LearningSignal(
                    signal_type="correction",
                    content="User corrected the previous action/statement.",
                    confidence=0.95,
                    proposed_action={"type": "learned_lesson", "value": "User correction received"}
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
