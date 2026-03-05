"""Local arbiter for cloud escalation decisions.

The arbiter uses a local model to decide whether to keep execution local
or escalate to cloud, and which provider order to use.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import List, Optional

from .config import get_config

logger = logging.getLogger(__name__)


@dataclass
class ArbiterDecision:
    need_cloud: bool
    force_local: bool
    provider_order: List[str]
    confidence: float
    reason: str


class LocalArbiter:
    """Lightweight policy arbiter backed by local LLM."""

    _VALID_PROVIDERS = ("nvidia", "groq", "gemini", "deepseek")

    def __init__(self, llm_client=None):
        self.config = get_config()
        self.llm = llm_client

    def decide(
        self,
        text: str,
        *,
        intent: str,
        complexity: str,
        prefer_cloud: bool,
        provider_priority: Optional[List[str]] = None,
    ) -> ArbiterDecision:
        provider_priority = self._normalize_order(
            provider_priority
            or list(getattr(self.config, "routing_cloud_priority", []) or [])
            or ["nvidia", "groq", "gemini", "deepseek"]
        )
        heuristic = self._heuristic_decision(
            text=text,
            intent=intent,
            complexity=complexity,
            prefer_cloud=prefer_cloud,
            provider_priority=provider_priority,
        )

        if not getattr(self.config, "llm_arbiter_enabled", True):
            return heuristic
        if not self.llm or not hasattr(self.llm, "generate"):
            return heuristic

        prompt = self._build_prompt(
            text=text,
            intent=intent,
            complexity=complexity,
            prefer_cloud=prefer_cloud,
            provider_priority=provider_priority,
        )
        try:
            raw = self.llm.generate(prompt, system_prompt="Return strict JSON only.")
            parsed = self._parse_json(raw)
            if not parsed:
                return heuristic

            need_cloud = bool(parsed.get("need_cloud", heuristic.need_cloud))
            force_local = bool(parsed.get("force_local", heuristic.force_local))
            confidence = self._coerce_confidence(parsed.get("confidence"), default=0.5)
            reason = str(parsed.get("reason") or "").strip() or heuristic.reason
            provider_order = self._normalize_order(parsed.get("provider_order") or provider_priority)

            return ArbiterDecision(
                need_cloud=need_cloud,
                force_local=force_local,
                provider_order=provider_order or provider_priority,
                confidence=confidence,
                reason=reason,
            )
        except Exception as exc:
            logger.debug("LocalArbiter fallback to heuristic: %s", exc)
            return heuristic

    def _heuristic_decision(
        self,
        *,
        text: str,
        intent: str,
        complexity: str,
        prefer_cloud: bool,
        provider_priority: List[str],
    ) -> ArbiterDecision:
        lowered = (text or "").lower()
        sensitive_keywords = [
            "password",
            "passcode",
            "otp",
            "secret",
            "ssn",
            "credit card",
            "api key",
            "token",
            "private key",
        ]
        force_local = bool(getattr(self.config, "llm_arbiter_sensitive_local_only", True)) and any(
            kw in lowered for kw in sensitive_keywords
        )

        complex_intents = {"coding", "research", "reasoning", "draft_resume"}
        need_cloud = (
            complexity in {"complex", "complex_reasoning"}
            or intent.lower() in complex_intents
            or prefer_cloud
        )
        if force_local:
            need_cloud = False

        provider_order = list(provider_priority)
        if intent.lower() in {"research", "read_article"} and "gemini" in provider_order:
            provider_order.remove("gemini")
            provider_order.insert(0, "gemini")
        if intent.lower() in {"coding"} and "deepseek" in provider_order:
            provider_order.remove("deepseek")
            provider_order.insert(1 if provider_order and provider_order[0] == "nvidia" else 0, "deepseek")

        reason = "heuristic"
        if force_local:
            reason = "sensitive_content_local_only"
        elif need_cloud:
            reason = "task_complexity_requires_cloud"

        return ArbiterDecision(
            need_cloud=need_cloud,
            force_local=force_local,
            provider_order=provider_order,
            confidence=0.65,
            reason=reason,
        )

    def _build_prompt(
        self,
        *,
        text: str,
        intent: str,
        complexity: str,
        prefer_cloud: bool,
        provider_priority: List[str],
    ) -> str:
        return (
            "You are the local routing arbiter for Chintu.\n"
            "Decide whether this request should run on local model or cloud model.\n"
            "Never route sensitive credentials or secrets to cloud.\n\n"
            f"Intent: {intent}\n"
            f"Complexity: {complexity}\n"
            f"CurrentPreferCloud: {prefer_cloud}\n"
            f"CloudProviderPriority: {provider_priority}\n"
            f"UserRequest: {text}\n\n"
            "Return ONLY JSON with keys:\n"
            '{"need_cloud": bool, "force_local": bool, "provider_order": ["nvidia","groq","gemini","deepseek"], '
            '"confidence": 0.0, "reason": "short reason"}'
        )

    def _normalize_order(self, value) -> List[str]:
        if not isinstance(value, list):
            return ["nvidia", "groq", "gemini", "deepseek"]
        normalized: List[str] = []
        for item in value:
            name = str(item).strip().lower()
            if name in self._VALID_PROVIDERS and name not in normalized:
                normalized.append(name)
        if not normalized:
            return ["nvidia", "groq", "gemini", "deepseek"]
        return normalized

    def _parse_json(self, text: str) -> Optional[dict]:
        if not text:
            return None
        snippet = text.strip()
        if snippet.startswith("```"):
            parts = snippet.split("```")
            if len(parts) >= 2:
                snippet = parts[1]
        start = snippet.find("{")
        end = snippet.rfind("}")
        if start < 0 or end < 0 or end <= start:
            return None
        candidate = snippet[start : end + 1]
        try:
            return json.loads(candidate)
        except Exception:
            # Try to salvage with relaxed cleanup.
            candidate = re.sub(r"[\r\n\t]", " ", candidate)
            try:
                return json.loads(candidate)
            except Exception:
                return None

    def _coerce_confidence(self, value, default: float) -> float:
        try:
            confidence = float(value)
        except Exception:
            confidence = default
        if confidence < 0.0:
            return 0.0
        if confidence > 1.0:
            return 1.0
        return confidence

