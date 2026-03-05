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
        # Avoid turning one-off creative directives (e.g. "make it funny")
        # into global preference changes when the user is asking for content.
        is_content_generation_request = (
            any(term in text for term in ("generate", "write", "create", "draft", "script"))
            and any(
                noun in text
                for noun in ("youtube", "short", "story", "blog", "caption", "post", "script")
            )
        )
        
        if not is_content_generation_request:
            for key, style in style_map.items():
                if f"be {key}" in text or f"make it {key}" in text or f"keep it {key}" in text:
                    action = None
                    if style in ("concise", "detailed", "balanced"):
                        action = {"type": "set_preference", "key": "response_style", "value": style}
                    elif style == "humorous":
                        action = {"type": "set_preference", "key": "use_humor", "value": True}
                    elif style == "serious":
                        action = {"type": "set_preference", "key": "use_humor", "value": False}
                    elif style == "formal":
                        action = {"type": "set_preference", "key": "tone_style", "value": "formal"}
                    signals.append(LearningSignal(
                        signal_type="preference",
                        content=f"User wants response style: {style}",
                        confidence=0.9,
                        proposed_action=action or {"type": "set_preference", "key": "response_style", "value": "balanced"}
                    ))

        # 3.1 Tone & Empathy
        if "more empathetic" in text or "be empathetic" in text or "empathy" in text:
            signals.append(LearningSignal(
                signal_type="preference",
                content="User wants more empathy",
                confidence=0.9,
                proposed_action={"type": "set_preference", "key": "empathy_level", "value": "high"}
            ))
        if "less empathetic" in text or "not so empathetic" in text or "less emotion" in text:
            signals.append(LearningSignal(
                signal_type="preference",
                content="User wants less empathy",
                confidence=0.9,
                proposed_action={"type": "set_preference", "key": "empathy_level", "value": "low"}
            ))
        if "be direct" in text or "more direct" in text or "be blunt" in text:
            signals.append(LearningSignal(
                signal_type="preference",
                content="User wants more direct responses",
                confidence=0.9,
                proposed_action={"type": "set_preference", "key": "directness", "value": "high"}
            ))
        if "be gentle" in text or "softer" in text:
            signals.append(LearningSignal(
                signal_type="preference",
                content="User wants gentler responses",
                confidence=0.9,
                proposed_action={"type": "set_preference", "key": "directness", "value": "low"}
            ))
        if "formal tone" in text or "professional tone" in text or "be formal" in text:
            signals.append(LearningSignal(
                signal_type="preference",
                content="User wants a formal tone",
                confidence=0.85,
                proposed_action={"type": "set_preference", "key": "tone_style", "value": "formal"}
            ))
        if "casual" in text or "warm tone" in text:
            signals.append(LearningSignal(
                signal_type="preference",
                content="User wants a casual tone",
                confidence=0.85,
                proposed_action={"type": "set_preference", "key": "tone_style", "value": "warm"}
            ))

        # 3.2 Busy mode
        if "i'm busy" in text or "im busy" in text or "busy mode" in text:
            signals.append(LearningSignal(
                signal_type="preference",
                content="User is busy and wants brief responses",
                confidence=0.85,
                proposed_action={"type": "set_preference", "key": "busy_mode", "value": True}
            ))
        if "not busy" in text or "exit busy mode" in text:
            signals.append(LearningSignal(
                signal_type="preference",
                content="User wants to exit busy mode",
                confidence=0.8,
                proposed_action={"type": "set_preference", "key": "busy_mode", "value": False}
            ))

        # 3.3 Role preferences - Require explicit role invocation to avoid false positives
        role_patterns = [
            (r"act (?:as|like) (?:a |an |my )?(\w+)", None),  # "act as my buddy"
            (r"be (?:my |a |an )?(\w+)", None),  # "be my advisor"
            (r"you are (?:my |a |an )?(\w+)", None),  # "you are my cofounder"
            (r"talk to me (?:like|as) (?:a |an |my )?(\w+)", None),  # "talk to me like a friend"
        ]
        role_map = {
            "cofounder": "cofounder", "co-founder": "cofounder",
            "manager": "manager", "assistant": "assistant",
            "buddy": "buddy", "friend": "buddy",
            "advisor": "advisor",
        }
        for pattern, _ in role_patterns:
            match = re.search(pattern, text)
            if match:
                role_word = match.group(1).lower()
                if role_word in role_map:
                    signals.append(LearningSignal(
                        signal_type="preference",
                        content=f"User wants role: {role_map[role_word]}",
                        confidence=0.8,
                        proposed_action={"type": "set_preference", "key": "behavior_role", "value": role_map[role_word]}
                    ))
                    break

        # 3.4 Entrepreneurial mode
        if "entrepreneur" in text or "entrepreneurial" in text or "think like a founder" in text:
            signals.append(LearningSignal(
                signal_type="preference",
                content="User wants entrepreneurial mode",
                confidence=0.8,
                proposed_action={"type": "set_preference", "key": "entrepreneurial_mode", "value": True}
            ))
        if "standard mode" in text:
            signals.append(LearningSignal(
                signal_type="preference",
                content="User wants standard mode",
                confidence=0.8,
                proposed_action={"type": "set_preference", "key": "entrepreneurial_mode", "value": False}
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
        action = signal.proposed_action or {}
        action_type = action.get("type")
        if action_type == "set_preference":
            key = action.get("key", "preference")
            value = action.get("value")
            return f"I can set {key} to '{value}'. Should I save this as your default?"
        if action_type == "update_style":
            return f"I've noticed you prefer {action.get('value')} responses. Should I save that as your default preference?"
        return f"I detected a preference: '{signal.content}'. Should I remember this for next time?"

# Global instance
_signal_manager = None

def get_signal_manager():
    global _signal_manager
    if not _signal_manager:
        _signal_manager = LearningSignalManager()
    return _signal_manager
