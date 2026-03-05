"""Persona registry + lightweight intent routing for specialist overlays."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import get_config

logger = logging.getLogger(__name__)


@dataclass
class PersonaSpec:
    name: str
    adapter_path: str = ""
    playbook: str = ""
    routing_tags: List[str] = field(default_factory=list)
    enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "adapter_path": self.adapter_path,
            "playbook": self.playbook,
            "routing_tags": list(self.routing_tags or []),
            "enabled": bool(self.enabled),
        }


@dataclass
class PersonaSelection:
    name: str
    requested: str
    reason: str
    playbook: str
    adapter_path: str
    adapter_ready: bool
    fallback_to_default: bool
    score: float
    routing_tags: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "requested": self.requested,
            "reason": self.reason,
            "playbook": self.playbook,
            "adapter_path": self.adapter_path,
            "adapter_ready": bool(self.adapter_ready),
            "fallback_to_default": bool(self.fallback_to_default),
            "score": round(float(self.score), 3),
            "routing_tags": list(self.routing_tags or []),
        }


DEFAULT_PERSONA_SPECS: List[PersonaSpec] = [
    PersonaSpec(
        name="default",
        adapter_path="",
        playbook=(
            "Operate as a local-first autonomous cofounder. Prioritize evidence, safety policies, "
            "and concise execution updates."
        ),
        routing_tags=["general", "cofounder"],
        enabled=True,
    ),
    PersonaSpec(
        name="coding",
        adapter_path="",
        playbook=(
            "Act as a senior software architect. Prefer deterministic repro steps, diff-first plans, "
            "tests, and rollback-safe changes."
        ),
        routing_tags=["code", "software", "engineering"],
        enabled=True,
    ),
    PersonaSpec(
        name="finance",
        adapter_path="",
        playbook=(
            "Act as a finance analyst. Emphasize assumptions, scenarios, and risk disclosures; "
            "avoid unverified claims."
        ),
        routing_tags=["finance", "markets", "portfolio"],
        enabled=True,
    ),
    PersonaSpec(
        name="medical",
        adapter_path="",
        playbook=(
            "Act as a medical information assistant. Provide cautious, informational guidance, "
            "state uncertainty, and recommend licensed clinician follow-up for diagnosis/treatment."
        ),
        routing_tags=["medical", "health", "symptoms"],
        enabled=True,
    ),
]


class PersonaRegistry:
    """Loads persona specs and resolves lightweight persona routing decisions."""

    _FINANCE_KEYWORDS = (
        "stock",
        "stocks",
        "portfolio",
        "invest",
        "investment",
        "trading",
        "market",
        "markets",
        "dividend",
        "etf",
        "mutual fund",
        "asset allocation",
        "rebalance",
        "budget",
        "cashflow",
    )
    _MEDICAL_KEYWORDS = (
        "symptom",
        "symptoms",
        "diagnosis",
        "diagnose",
        "medicine",
        "medication",
        "side effect",
        "pain",
        "fever",
        "blood pressure",
        "doctor",
        "treatment",
        "clinic",
        "dose",
    )
    _CODING_KEYWORDS = (
        "code",
        "coding",
        "python",
        "javascript",
        "typescript",
        "sql",
        "bug",
        "debug",
        "refactor",
        "compile",
        "test",
        "pytest",
        "exception",
        "api",
        "backend",
        "frontend",
    )

    def __init__(
        self,
        *,
        registry_path: Optional[Path] = None,
        default_name: str = "default",
        specs: Optional[List[PersonaSpec]] = None,
        enabled: bool = True,
    ) -> None:
        self.default_name = str(default_name or "default").strip() or "default"
        self.enabled = bool(enabled)
        self.registry_path = Path(registry_path) if registry_path else None
        self._specs: Dict[str, PersonaSpec] = {}

        loaded = self._load_specs_from_disk(self.registry_path) if self.registry_path else None
        source_specs = loaded if loaded else (specs or DEFAULT_PERSONA_SPECS)
        for spec in source_specs:
            key = str(spec.name or "").strip().lower()
            if not key:
                continue
            self._specs[key] = spec
        if self.default_name not in self._specs:
            self._specs[self.default_name] = PersonaSpec(name=self.default_name, enabled=True)

    def _load_specs_from_disk(self, path: Optional[Path]) -> Optional[List[PersonaSpec]]:
        if not path or not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Persona registry parse failed (%s): %s", path, exc)
            return None
        rows = data.get("personas") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return None
        out: List[PersonaSpec] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "").strip().lower()
            if not name:
                continue
            out.append(
                PersonaSpec(
                    name=name,
                    adapter_path=str(row.get("adapter_path") or "").strip(),
                    playbook=str(row.get("playbook") or "").strip(),
                    routing_tags=[str(t).strip() for t in (row.get("routing_tags") or []) if str(t).strip()],
                    enabled=bool(row.get("enabled", True)),
                )
            )
        return out or None

    def list_specs(self) -> Dict[str, Dict[str, Any]]:
        return {name: spec.to_dict() for name, spec in self._specs.items()}

    def _score_keyword_hits(self, text_lower: str, keywords: tuple[str, ...]) -> float:
        score = 0.0
        for kw in keywords:
            token = str(kw or "").strip().lower()
            if token and token in text_lower:
                score += 1.0
        return score

    def _intent_boost(self, intent: str) -> Dict[str, float]:
        low_intent = str(intent or "").strip().lower()
        boosts: Dict[str, float] = {}
        if low_intent in {"coding", "cmd", "file_op"}:
            boosts["coding"] = boosts.get("coding", 0.0) + 2.5
        if low_intent in {"research", "question"}:
            boosts["finance"] = boosts.get("finance", 0.0) + 0.3
            boosts["medical"] = boosts.get("medical", 0.0) + 0.3
        return boosts

    def _adapter_ready(self, spec: PersonaSpec) -> bool:
        path = str(spec.adapter_path or "").strip()
        if not path:
            return True
        try:
            return Path(path).exists()
        except Exception:
            return False

    def select(self, *, text: str, intent: str = "") -> PersonaSelection:
        if not self.enabled:
            default = self._specs.get(self.default_name) or PersonaSpec(name=self.default_name, enabled=True)
            return PersonaSelection(
                name=default.name,
                requested=default.name,
                reason="persona_mode_disabled",
                playbook=default.playbook,
                adapter_path=default.adapter_path,
                adapter_ready=self._adapter_ready(default),
                fallback_to_default=False,
                score=0.0,
                routing_tags=list(default.routing_tags or []),
            )

        text_lower = str(text or "").lower()
        intent_boosts = self._intent_boost(intent)
        scores: Dict[str, float] = {
            "coding": self._score_keyword_hits(text_lower, self._CODING_KEYWORDS) + intent_boosts.get("coding", 0.0),
            "finance": self._score_keyword_hits(text_lower, self._FINANCE_KEYWORDS) + intent_boosts.get("finance", 0.0),
            "medical": self._score_keyword_hits(text_lower, self._MEDICAL_KEYWORDS) + intent_boosts.get("medical", 0.0),
        }

        requested = self.default_name
        best_score = 0.0
        for name, score in scores.items():
            if score > best_score:
                requested = name
                best_score = score

        requested_spec = self._specs.get(requested) or self._specs.get(self.default_name) or PersonaSpec(name=self.default_name)
        default_spec = self._specs.get(self.default_name) or PersonaSpec(name=self.default_name)
        requested_enabled = bool(getattr(requested_spec, "enabled", True))
        requested_adapter_ready = self._adapter_ready(requested_spec)

        # Safe fallback: disabled or missing adapter path rolls back to default persona.
        if requested != self.default_name and (not requested_enabled or not requested_adapter_ready):
            reason = "adapter_missing_or_persona_disabled"
            return PersonaSelection(
                name=default_spec.name,
                requested=requested_spec.name,
                reason=reason,
                playbook=default_spec.playbook,
                adapter_path=default_spec.adapter_path,
                adapter_ready=self._adapter_ready(default_spec),
                fallback_to_default=True,
                score=best_score,
                routing_tags=list(default_spec.routing_tags or []),
            )

        reason = "keyword_intent_match" if requested != self.default_name else "default_persona"
        return PersonaSelection(
            name=requested_spec.name,
            requested=requested_spec.name,
            reason=reason,
            playbook=requested_spec.playbook,
            adapter_path=requested_spec.adapter_path,
            adapter_ready=requested_adapter_ready,
            fallback_to_default=False,
            score=best_score,
            routing_tags=list(requested_spec.routing_tags or []),
        )


_registry: Optional[PersonaRegistry] = None


def get_persona_registry() -> PersonaRegistry:
    global _registry
    if _registry is None:
        cfg = get_config()
        _registry = PersonaRegistry(
            registry_path=getattr(cfg, "persona_registry_path", None),
            default_name=str(getattr(cfg, "persona_default_name", "default") or "default"),
            enabled=bool(getattr(cfg, "persona_mode_enabled", True)),
        )
    return _registry
