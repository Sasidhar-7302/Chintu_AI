"""Behavior policy module for human-like responses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any, Optional

from .emotion_signals import EmotionSignal
from .mental_model import MentalModel


@dataclass
class BehaviorPlan:
    persona: str
    tone: str
    brevity: str
    empathy: str
    directness: str
    persistence: str
    risk_posture: str
    ask_clarify: bool
    response_strategy: str

    def to_context(self) -> str:
        return (
            f"persona={self.persona}; tone={self.tone}; brevity={self.brevity}; "
            f"empathy={self.empathy}; directness={self.directness}; persistence={self.persistence}; "
            f"risk={self.risk_posture}; clarify={self.ask_clarify}; strategy={self.response_strategy}"
        )


class BehaviorPolicy:
    """Builds behavior plans from preferences, mental model, and emotion signals."""

    def __init__(self, config=None):
        self.config = config

    def build_plan(
        self,
        emotion: EmotionSignal,
        preferences: Dict[str, Any],
        mental_model: Optional[MentalModel] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> BehaviorPlan:
        context = context or {}
        mental_model = mental_model or MentalModel()

        # Persona / role
        persona = preferences.get("behavior_role") or mental_model.role or "cofounder"
        if persona not in ("cofounder", "manager", "assistant", "buddy", "advisor"):
            persona = "cofounder"

        # Tone & brevity
        comm = mental_model.communication or {}
        response_style = preferences.get("response_style") or comm.get("brevity", "balanced")
        tone = preferences.get("tone_style") or comm.get("tone", "warm")
        brevity = response_style

        if emotion.urgency in ("high", "medium"):
            brevity = "concise"
        if preferences.get("busy_mode"):
            brevity = "concise"
        if emotion.frustration in ("high", "medium"):
            tone = "calm"

        # Empathy level
        empathy = preferences.get("empathy_level") or comm.get("empathy", "medium")
        if preferences.get("low_empathy"):
            empathy = "low"
        if emotion.sentiment == "negative" and empathy != "low":
            empathy = "medium" if empathy == "high" else empathy

        # Directness
        directness = preferences.get("directness") or comm.get("directness", "high")
        if emotion.confusion in ("high", "medium"):
            directness = "high"

        # Persistence & risk posture
        persistence = preferences.get("persistence") or mental_model.persistence or "high"
        risk_posture = preferences.get("risk_posture") or mental_model.risk_posture or "balanced"
        if preferences.get("confirmation_required"):
            risk_posture = "cautious"

        # Clarify when confidence low or confusion high
        ask_clarify = emotion.confusion in ("high", "medium") or emotion.confidence < 0.45

        # Response strategy
        response_strategy = "entrepreneurial" if preferences.get("entrepreneurial_mode", True) else "standard"
        if persona == "cofounder":
            response_strategy = "product-leader"
        if persona in ("manager", "advisor"):
            response_strategy = "structured"
        if emotion.urgency == "high":
            response_strategy = "action-first"

        return BehaviorPlan(
            persona=persona,
            tone=tone,
            brevity=brevity,
            empathy=empathy,
            directness=directness,
            persistence=persistence,
            risk_posture=risk_posture,
            ask_clarify=ask_clarify,
            response_strategy=response_strategy,
        )
