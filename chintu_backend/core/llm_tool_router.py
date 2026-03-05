"""LLM tool router (local-first).

Uses the local LLM to choose the best capability and parameters when
rule-based triggers are ambiguous or missing.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

from .config import get_config
from .capabilities import CapabilityRegistry, Capability

logger = logging.getLogger(__name__)


@dataclass
class ToolRoute:
    capability: str
    parameters: Dict[str, Any]
    confidence: float
    needs_clarification: bool = False
    clarify_question: str = ""


@dataclass
class DecomposedStep:
    text: str
    thought: str


class LLMToolRouter:
    """Local-first router that asks the LLM to pick a capability."""

    def __init__(self, registry: CapabilityRegistry, llm_client=None, config=None):
        self.registry = registry
        self.config = config or get_config()
        self.llm = llm_client
        if not self.llm:
            try:
                from ..brain.llm.ollama_client import OllamaClient

                self.llm = OllamaClient()
            except Exception:
                self.llm = None

    def select(self, text: str, context: Optional[Dict[str, Any]] = None) -> Optional[ToolRoute]:
        """Return a ToolRoute or None if routing is not confident."""
        if not getattr(self.config, "llm_tool_routing_enabled", True):
            return None
        if not text:
            return None
        if not self.llm or not hasattr(self.llm, "generate"):
            return None

        candidates = self._get_candidates(text, context or {})
        if not candidates:
            return None

        prompt = self._build_prompt(text, candidates)
        try:
            response = self.llm.generate(prompt)
        except Exception as exc:
            logger.warning("LLM tool routing failed: %s", exc)
            return None

        payload = self._parse_json(response)
        if not payload:
            return None
        if not isinstance(payload, dict):
            return None

        capability = str(payload.get("capability", "")).strip()
        if not capability or capability.lower() == "none":
            return None

        capability = capability.strip()
        if capability not in self.registry._capabilities:
            return None

        confidence = self._coerce_confidence(payload.get("confidence"))
        min_conf = float(getattr(self.config, "llm_tool_routing_confidence_threshold", 0.55))
        if confidence < min_conf:
            return None

        parameters = payload.get("parameters") or {}
        if not isinstance(parameters, dict):
            parameters = {}

        needs_clarification = bool(payload.get("needs_clarification"))
        clarify_question = str(payload.get("clarify_question") or "").strip()

        return ToolRoute(
            capability=capability,
            parameters=parameters,
            confidence=confidence,
            needs_clarification=needs_clarification,
            clarify_question=clarify_question,
        )

    def decompose(self, text: str) -> List[DecomposedStep]:
        """Split a compound command into individual steps."""
        if not text:
            return []
            
        prompt = f"""
        Analyze this user request for an AI assistant. 
        If it contains multiple independent actions, split them into a list.
        If it is a single action, return a list with one item.
        
        Example: "Check the weather and set a timer for 5 minutes" 
        -> 
        [
          {{"text": "Check the weather", "thought": "Querying weather info"}},
          {{"text": "set a timer for 5 minutes", "thought": "Setting system timer"}}
        ]
        
        Request: "{text}"
        
        Return ONLY valid JSON list of objects with "text" and "thought" keys.
        """
        
        try:
            response = self.llm.generate(prompt)
            payload = self._parse_json(response)
            if isinstance(payload, list):
                steps = []
                for item in payload:
                    if isinstance(item, dict) and "text" in item:
                        steps.append(DecomposedStep(
                            text=item["text"],
                            thought=item.get("thought", "")
                        ))
                return steps
        except Exception as e:
            logger.warning(f"Failed to decompose command: {e}")
            
        return [DecomposedStep(text=text, thought="Single action fallback")]

    def _get_candidates(self, text: str, context: Dict[str, Any]) -> List[Capability]:
        text_lower = text.lower()
        tokens = [t for t in re.split(r"\\W+", text_lower) if len(t) >= 3]
        agent_policy = context.get("_agent_policy")

        scored: List[Tuple[float, Capability]] = []
        for cap in self.registry._capabilities.values():
            if agent_policy and hasattr(agent_policy, "allows"):
                try:
                    if not agent_policy.allows(cap.name):
                        continue
                except Exception:
                    pass

            score = 0.0
            try:
                score = cap.get_match_score(text)
            except Exception:
                score = 0.0

            name = cap.name.lower()
            desc = (cap.description or "").lower()
            examples = " ".join(cap.examples or []).lower()

            for token in tokens:
                if token in name:
                    score += 0.12
                if token in desc:
                    score += 0.06
                if token in examples:
                    score += 0.04

            if score > 0:
                scored.append((score, cap))

        if scored:
            scored.sort(key=lambda x: x[0], reverse=True)
            max_candidates = int(getattr(self.config, "llm_tool_routing_max_candidates", 12))
            return [cap for _, cap in scored[:max_candidates]]

        # Fallback to a core set when nothing matches.
        fallback_names = [
            "conversation",
            "open_app",
            "open_url",
            "web_search",
            "news_search",
            "weather",
            "remember",
            "recall",
            "add_task",
            "list_tasks",
            "set_reminder",
            "timer",
            "screen_control",
            "window_control",
            "volume",
            "screenshot",
        ]
        fallback = []
        for name in fallback_names:
            cap = self.registry.get(name)
            if cap:
                fallback.append(cap)
        return fallback

    def _build_prompt(self, text: str, candidates: List[Capability]) -> str:
        lines = []
        max_fields = int(getattr(self.config, "llm_tool_routing_max_schema_fields", 6))
        
        # Add core autonomous capabilities explicitly if not present
        core_caps = ["code_interpreter", "autonomous_swarm", "deep_researcher", "conversation"]
        
        # Merge candidates with core caps
        final_candidates = list(candidates)
        existing_names = set(c.name for c in candidates)
        
        for name in core_caps:
            if name not in existing_names:
                cap = self.registry.get(name)
                if cap:
                    final_candidates.append(cap)

        for cap in final_candidates:
            schema_hint = self._schema_hint(cap, max_fields)
            examples = ", ".join(cap.examples[:2]) if cap.examples else ""
            desc = cap.description or ""
            entry = f"- {cap.name}: {desc}"
            if examples:
                entry += f" (examples: {examples})"
            if schema_hint:
                entry += f" (params: {schema_hint})"
            lines.append(entry.strip())

        catalog = "\n".join(lines)
        return (
            "You are Chintu, the Executive Brain of an autonomous Windows agent. "
            "You have FULL control and must decide the best course of action.\n\n"
            "CRITICAL INSTRUCTIONS:\n"
            "1. MATH/LOGIC/DATES: You MUST use 'code_interpreter' for math, logic, and DATE calculations. Do not simulate math or guess dates.\n"
            "   - E.g. 'Calculate fib 100' -> code_interpreter\n"
            "   - E.g. 'What day is Oct 1 2026' -> code_interpreter\n"
            "   - E.g. 'Sort these files' -> code_interpreter\n"
            "2. COMPLEX PLANS: Use 'autonomous_swarm' for multi-step goals (apps, trips).\n"
            "3. RESEARCH: Use 'deep_researcher' for detailed inquiry.\n"
            "4. UNKNOWN TASKS: Default to 'conversation' unless the user explicitly asks to create/learn a new skill.\n"
            "5. SKILL CREATION: Use 'skill_propose' ONLY for explicit requests like 'propose skill', 'create skill', or 'learn skill'.\n"
            "6. CHAT: Use 'conversation' for greetings, Q&A, explanations, brainstorming, and creative writing.\n"
            "7. UI: Use 'window_control' or 'screen_control' for app interaction.\n\n"
            "Return ONLY valid JSON:\n"
            '{"capability": "name", "parameters": {}, "confidence": 1.0, '
            '"needs_clarification": false, "clarify_question": ""}\n\n'
            f"Available Capabilities:\n{catalog}\n\n"
            f"User Goal: {text}\n"
        )

    def _schema_hint(self, cap: Capability, max_fields: int) -> str:
        schema = cap.schema
        if not schema:
            return ""
        try:
            schema_json = schema.model_json_schema() if hasattr(schema, "model_json_schema") else schema.schema()
        except Exception:
            return ""
        props = schema_json.get("properties", {}) if isinstance(schema_json, dict) else {}
        if not props:
            return ""
        fields = list(props.keys())[:max_fields]
        return ", ".join(fields)

    def _parse_json(self, text: str) -> Optional[Union[Dict[str, Any], List[Any]]]:
        if not text:
            return None
        snippet = text.strip()
        if snippet.startswith("```"):
            parts = snippet.split("```")
            snippet = parts[1] if len(parts) > 1 else snippet
            if "\n" in snippet:
                first_line, _, rest = snippet.partition("\n")
                # Handle fenced blocks like ```json
                if first_line.strip().lower() in {"json", "yaml", "yml"}:
                    snippet = rest
            if "```" in snippet:
                snippet = snippet.split("```", 1)[0]

        obj_start = snippet.find("{")
        arr_start = snippet.find("[")
        starts = [idx for idx in (obj_start, arr_start) if idx >= 0]
        if not starts:
            return None
        start = min(starts)
        open_char = snippet[start]
        close_char = "}" if open_char == "{" else "]"

        depth = 0
        end = None
        for i in range(start, len(snippet)):
            if snippet[i] == open_char:
                depth += 1
            elif snippet[i] == close_char:
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end is None:
            return None
        try:
            return json.loads(snippet[start:end])
        except Exception:
            return None

    def _coerce_confidence(self, value: Any) -> float:
        try:
            conf = float(value)
        except Exception:
            conf = 0.0
        if conf < 0:
            conf = 0.0
        if conf > 1:
            conf = 1.0
        return conf
