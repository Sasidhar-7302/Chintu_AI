"""Phase 7 self-healing planner, fallback graph, and stuck-plan watchdog."""

from __future__ import annotations

import hashlib
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock
from typing import Deque, Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class RecoveryPlan:
    """Ordered recovery actions for a failed step."""

    failure_type: str
    actions: Tuple[str, ...]
    alternatives: Tuple[str, ...]
    reason: str = ""


class ToolFallbackGraph:
    """Static, safety-first fallback edges for reliable tool execution."""

    DEFAULT_GRAPH: Dict[str, Tuple[str, ...]] = {
        # Web/research family.
        "browse_url": ("page_content", "open_browser", "live_search", "web_search"),
        "page_content": ("browse_url", "open_browser", "live_search", "web_search"),
        "web_search": ("live_search", "browser_search", "open_browser"),
        "live_search": ("web_search", "browser_search", "open_browser"),
        "browser_search": ("web_search", "live_search", "open_browser"),
        "deep_research": ("live_search", "web_search"),
        "agentic_research": ("deep_research", "live_search", "web_search"),
        "skill::price-compare": ("live_search", "web_search"),
        # Browser action family (read-only fallbacks first).
        "click_link": ("page_content", "browser_snapshot_refs", "open_browser"),
        "open_url": ("open_browser", "browse_url", "page_content"),
        "open_browser": ("browse_url", "page_content"),
        # File/read family.
        "read_file": ("list_files",),
        "list_files": ("read_file",),
    }

    def __init__(self, custom_graph: Optional[Dict[str, Sequence[str]]] = None):
        merged: Dict[str, Tuple[str, ...]] = dict(self.DEFAULT_GRAPH)
        if isinstance(custom_graph, dict):
            for key, values in custom_graph.items():
                merged[str(key)] = tuple(str(v) for v in (values or []) if str(v).strip())
        self._graph = merged

    def alternatives(self, capability_name: str) -> Tuple[str, ...]:
        cap = str(capability_name or "").strip()
        if not cap:
            return tuple()
        direct = self._graph.get(cap, tuple())
        if direct:
            return direct
        # Skill family fallback: keep category fallback generic.
        if cap.startswith("skill::"):
            return ("live_search", "web_search")
        return tuple()


@dataclass(frozen=True)
class _FailureRecord:
    signature: str
    ts: float


class PlanWatchdog:
    """Detects repeated identical failures and asks dispatcher to break loops gracefully."""

    def __init__(self, repeat_threshold: int = 3, window_seconds: float = 180.0):
        self.repeat_threshold = max(2, int(repeat_threshold))
        self.window_seconds = max(10.0, float(window_seconds))
        self._lock = Lock()
        self._history: Dict[str, Deque[_FailureRecord]] = defaultdict(lambda: deque(maxlen=32))

    @staticmethod
    def _hash(payload: str) -> str:
        return hashlib.sha256(str(payload or "").encode("utf-8", errors="ignore")).hexdigest()

    def _signature(self, capability_name: str, failure_type: str, message: str) -> str:
        body = f"{str(capability_name or '').strip().lower()}::{str(failure_type or '').strip().lower()}::{str(message or '').strip().lower()[:500]}"
        return self._hash(body)

    def register_failure(
        self,
        *,
        run_key: str,
        capability_name: str,
        failure_type: str,
        message: str,
    ) -> Dict[str, object]:
        """Register a failure and return loop status."""
        key = str(run_key or "global")
        now = time.time()
        signature = self._signature(capability_name, failure_type, message)
        with self._lock:
            history = self._history[key]
            history.append(_FailureRecord(signature=signature, ts=now))
            recent = [row for row in history if (now - row.ts) <= self.window_seconds]
            repeat = 0
            for row in reversed(recent):
                if row.signature != signature:
                    break
                repeat += 1
            blocked = repeat >= self.repeat_threshold
            return {
                "blocked": blocked,
                "repeat_count": repeat,
                "threshold": self.repeat_threshold,
                "window_seconds": self.window_seconds,
                "signature": signature,
            }


class FailureAwareRetryPlanner:
    """Computes failure-type-specific recovery plans."""

    _TRANSIENT_FAILURES = {"timeout", "verification_failed", "execution_failed", "unknown"}

    def __init__(self, fallback_graph: ToolFallbackGraph):
        self.fallback_graph = fallback_graph

    def build_plan(
        self,
        *,
        capability_name: str,
        failure_type: str,
        attempt: int,
        max_attempts: int,
        allow_cloud_fallback: bool,
        local_alternatives: Optional[Sequence[str]] = None,
        watchdog_blocked: bool = False,
    ) -> RecoveryPlan:
        cap = str(capability_name or "").strip()
        ftype = str(failure_type or "unknown").strip().lower() or "unknown"
        alternatives = tuple(str(item) for item in (local_alternatives or self.fallback_graph.alternatives(cap)) if str(item).strip())

        if watchdog_blocked:
            return RecoveryPlan(
                failure_type=ftype,
                actions=tuple(),
                alternatives=alternatives,
                reason="watchdog_blocked",
            )

        if attempt >= max(1, int(max_attempts)):
            return RecoveryPlan(
                failure_type=ftype,
                actions=tuple(),
                alternatives=alternatives,
                reason="max_attempts_reached",
            )

        if ftype in {"blocked_by_policy", "cancelled", "missing_dependency"}:
            return RecoveryPlan(
                failure_type=ftype,
                actions=tuple(),
                alternatives=alternatives,
                reason="not_retryable",
            )

        actions: List[str] = []
        if ftype == "timeout":
            actions.extend(["retry_same", "fallback_local", "fallback_cloud"])
        elif ftype == "verification_failed":
            actions.extend(["retry_same", "fallback_local", "fallback_cloud"])
        elif ftype in {"execution_failed", "unknown"}:
            actions.extend(["fallback_local", "retry_same", "fallback_cloud"])
        else:
            actions.extend(["retry_same", "fallback_local", "fallback_cloud"])

        # After first failed recovery attempt, prioritize alternatives over same-step retries.
        if int(attempt) > 0 and "retry_same" in actions and "fallback_local" in actions:
            actions = [item for item in actions if item != "retry_same"] + ["retry_same"]

        if not alternatives:
            actions = [item for item in actions if item != "fallback_local"]
        if not allow_cloud_fallback:
            actions = [item for item in actions if item != "fallback_cloud"]

        # Deduplicate while preserving order.
        ordered: List[str] = []
        for item in actions:
            if item not in ordered:
                ordered.append(item)

        reason = "transient_failure" if ftype in self._TRANSIENT_FAILURES else "planned_recovery"
        return RecoveryPlan(
            failure_type=ftype,
            actions=tuple(ordered),
            alternatives=alternatives,
            reason=reason,
        )
