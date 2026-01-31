"""Router agent for intent classification in the swarm."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .model_manager import ModelManager

logger = logging.getLogger(__name__)


class RouterIntent(str, Enum):
    CHAT = "CHAT"
    PLAN = "PLAN"
    CODE = "CODE"
    RESEARCH = "RESEARCH"
    COMPLEX = "COMPLEX"


@dataclass
class RouterDecision:
    intent: RouterIntent
    complexity_score: float
    reason: str


class RouterAgent:
    """Classify user intent using a small local model or heuristics."""

    SYSTEM_PROMPT = (
        "You are a routing model. Classify the user's request into one intent.\n"
        "Return ONLY valid JSON with keys: intent, complexity_score, reason.\n"
        "intent must be one of: CHAT, PLAN, CODE, RESEARCH, COMPLEX.\n"
        "complexity_score is a float between 0 and 1.\n"
    )

    def __init__(self, model_manager: Optional[ModelManager], model_name: str):
        self.model_manager = model_manager
        self.model_name = model_name

    def route(self, text: str) -> RouterDecision:
        if not text:
            return RouterDecision(RouterIntent.CHAT, 0.1, "empty input")

        if not self.model_manager:
            return self._fallback_route(text)

        try:
            content, _raw = self.model_manager.chat(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
            )
            decision = self._parse_response(content)
            if decision:
                return decision
        except Exception as exc:
            logger.warning("Router model failed, using fallback: %s", exc)

        return self._fallback_route(text)

    def _parse_response(self, content: str) -> Optional[RouterDecision]:
        if not content:
            return None

        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not match:
            return None

        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

        intent_raw = str(data.get("intent", "")).upper()
        reason = str(data.get("reason", "")).strip() or "router classification"
        try:
            intent = RouterIntent(intent_raw)
        except ValueError:
            return None

        score = data.get("complexity_score", 0.5)
        try:
            score = float(score)
        except (TypeError, ValueError):
            score = 0.5
        score = min(max(score, 0.0), 1.0)

        return RouterDecision(intent=intent, complexity_score=score, reason=reason)

    def _fallback_route(self, text: str) -> RouterDecision:
        text_lower = text.lower()

        if any(keyword in text_lower for keyword in ["plan", "roadmap", "phase", "milestone", "steps"]):
            return RouterDecision(RouterIntent.PLAN, 0.6, "planning keywords")

        if any(keyword in text_lower for keyword in ["code", "debug", "error", "stack trace", "function"]):
            return RouterDecision(RouterIntent.CODE, 0.7, "coding keywords")

        if any(keyword in text_lower for keyword in ["research", "compare", "analyze", "explain", "summarize"]):
            return RouterDecision(RouterIntent.RESEARCH, 0.7, "research keywords")

        if len(text.split()) > 80 or any(keyword in text_lower for keyword in ["medical", "legal", "finance"]):
            return RouterDecision(RouterIntent.COMPLEX, 0.9, "complexity heuristic")

        return RouterDecision(RouterIntent.CHAT, 0.3, "default fallback")
