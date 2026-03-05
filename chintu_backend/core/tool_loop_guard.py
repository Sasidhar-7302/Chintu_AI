"""Loop detection guard for repeated capability calls."""

from __future__ import annotations

import hashlib
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock
from typing import Deque, Dict, Optional


@dataclass(frozen=True)
class LoopSignal:
    blocked: bool = False
    level: str = ""
    message: str = ""
    repeat_count: int = 0


@dataclass
class _CallRecord:
    signature: str
    success: bool
    result_hash: str
    timestamp: float


class ToolLoopGuard:
    """Detect repetitive no-progress loops per session."""

    def __init__(
        self,
        enabled: bool = True,
        history_size: int = 24,
        warning_threshold: int = 4,
        critical_threshold: int = 6,
        warning_cooldown_seconds: float = 12.0,
    ):
        self.enabled = bool(enabled)
        self.history_size = max(8, int(history_size))
        self.warning_threshold = max(2, int(warning_threshold))
        self.critical_threshold = max(self.warning_threshold + 1, int(critical_threshold))
        self.warning_cooldown_seconds = max(1.0, float(warning_cooldown_seconds))
        self._history: Dict[str, Deque[_CallRecord]] = defaultdict(
            lambda: deque(maxlen=self.history_size)
        )
        self._last_warning: Dict[str, float] = {}
        self._lock = Lock()

    @staticmethod
    def _normalize(text: str) -> str:
        cleaned = re.sub(r"\s+", " ", str(text or "").strip().lower())
        return cleaned[:500]

    def _signature(self, capability_name: str, text: str) -> str:
        payload = f"{str(capability_name or '').strip().lower()}::{self._normalize(text)}"
        return hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()

    @staticmethod
    def _hash_result(message: str) -> str:
        normalized = re.sub(r"\s+", " ", str(message or "").strip().lower())
        return hashlib.sha256(normalized.encode("utf-8", errors="ignore")).hexdigest()

    def detect(self, session_id: str, capability_name: str, text: str) -> LoopSignal:
        if not self.enabled:
            return LoopSignal()

        sid = str(session_id or "global")
        signature = self._signature(capability_name, text)

        with self._lock:
            history = self._history.get(sid)
            if not history:
                return LoopSignal()

            consecutive = 0
            stale_failures = 0
            stale_result_hash: Optional[str] = None
            for rec in reversed(history):
                if rec.signature != signature:
                    break
                consecutive += 1
                if not rec.success:
                    stale_failures += 1
                if stale_result_hash is None:
                    stale_result_hash = rec.result_hash
                elif stale_result_hash != rec.result_hash:
                    stale_result_hash = ""

            if consecutive >= self.critical_threshold:
                return LoopSignal(
                    blocked=True,
                    level="critical",
                    repeat_count=consecutive,
                    message=(
                        "Loop guard stopped repeated tool execution. "
                        f"'{capability_name}' repeated {consecutive} times with no progress."
                    ),
                )

            if stale_failures >= self.warning_threshold:
                return LoopSignal(
                    blocked=True,
                    level="critical",
                    repeat_count=stale_failures,
                    message=(
                        "Loop guard stopped repeated failing attempts. "
                        f"'{capability_name}' failed {stale_failures} times in a row."
                    ),
                )

            if consecutive >= self.warning_threshold:
                warn_key = f"{sid}:{signature}"
                now = time.time()
                last_warn = self._last_warning.get(warn_key, 0.0)
                if now - last_warn >= self.warning_cooldown_seconds:
                    self._last_warning[warn_key] = now
                    return LoopSignal(
                        blocked=False,
                        level="warning",
                        repeat_count=consecutive,
                        message=(
                            "Loop guard warning: this looks repetitive. "
                            f"'{capability_name}' repeated {consecutive} times."
                        ),
                    )

        return LoopSignal()

    def record(
        self,
        session_id: str,
        capability_name: str,
        text: str,
        success: bool,
        message: str,
    ) -> None:
        if not self.enabled:
            return

        sid = str(session_id or "global")
        signature = self._signature(capability_name, text)
        record = _CallRecord(
            signature=signature,
            success=bool(success),
            result_hash=self._hash_result(message),
            timestamp=time.time(),
        )

        with self._lock:
            history = self._history[sid]
            # If history size changed at runtime, keep it in sync.
            if history.maxlen != self.history_size:
                history = deque(history, maxlen=self.history_size)
                self._history[sid] = history
            history.append(record)


_LOOP_GUARD: Optional[ToolLoopGuard] = None


def get_tool_loop_guard(config=None) -> ToolLoopGuard:
    """Get singleton loop guard configured from app config."""
    global _LOOP_GUARD
    if _LOOP_GUARD is None:
        enabled = bool(getattr(config, "tool_loop_detection_enabled", True))
        history_size = int(getattr(config, "tool_loop_history_size", 24))
        warning_threshold = int(getattr(config, "tool_loop_warning_threshold", 4))
        critical_threshold = int(getattr(config, "tool_loop_critical_threshold", 6))
        warning_cooldown = float(getattr(config, "tool_loop_warning_cooldown_seconds", 12.0))
        _LOOP_GUARD = ToolLoopGuard(
            enabled=enabled,
            history_size=history_size,
            warning_threshold=warning_threshold,
            critical_threshold=critical_threshold,
            warning_cooldown_seconds=warning_cooldown,
        )
    return _LOOP_GUARD
