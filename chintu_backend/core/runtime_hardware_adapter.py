"""Runtime hardware adaptation for long-lived assistant sessions.

Detects hardware topology changes (GPU add/remove/upgrade) and reapplies
hardware tuning without requiring a full restart.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, Optional

from .config import get_config

logger = logging.getLogger(__name__)


class RuntimeHardwareAdapter:
    """Periodically refresh hardware signature and re-tune runtime config."""

    def __init__(
        self,
        config=None,
        optimizer=None,
        state_manager=None,
        now_fn=None,
        on_applied: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self.config = config or get_config()
        if optimizer is None:
            from .hardware_optimizer import get_hardware_optimizer

            optimizer = get_hardware_optimizer()
        self.optimizer = optimizer
        self.state_manager = state_manager
        self._now_fn = now_fn or time.time
        self._on_applied = on_applied
        self._last_check_ts = 0.0
        self._last_signature = {}

    def maybe_refresh(self, *, force: bool = False) -> Optional[Dict[str, Any]]:
        if not bool(getattr(self.config, "hardware_adapt_runtime_enabled", True)):
            return None

        now = float(self._now_fn())
        interval = float(getattr(self.config, "hardware_adapt_check_interval_seconds", 120.0) or 120.0)
        if not force and self._last_check_ts and (now - self._last_check_ts) < max(1.0, interval):
            return None
        self._last_check_ts = now

        refresh = self.optimizer.refresh_hardware()
        current = dict(refresh.get("current") or {})
        previous = dict(refresh.get("previous") or {})
        changed = bool(refresh.get("changed"))

        if not self._last_signature:
            self._last_signature = current
            return {
                "checked": True,
                "changed": changed,
                "applied": False,
                "current": current,
                "previous": previous,
                "optimizations": {},
            }

        if not changed and current == self._last_signature:
            return {
                "checked": True,
                "changed": False,
                "applied": False,
                "current": current,
                "previous": previous,
                "optimizations": {},
            }

        self._last_signature = current
        optimizations = self.optimizer.optimize_config(self.config)
        payload = {
            "checked": True,
            "changed": True,
            "applied": True,
            "current": current,
            "previous": previous,
            "optimizations": dict(optimizations or {}),
        }

        logger.info("Runtime hardware adaptation applied: %s", payload)
        self._emit_state_update(payload)
        self._emit_callback(payload)
        return payload

    def _emit_state_update(self, payload: Dict[str, Any]) -> None:
        if not self.state_manager:
            return
        try:
            profile = str((payload.get("current") or {}).get("hardware_profile") or "")
            gpu_count = int((payload.get("current") or {}).get("gpu_count") or 0)
            self.state_manager.update_feature("hardware_optimizer", enabled=True, status="active", error=None)
            self.state_manager.log_activity(
                f"Hardware profile updated to {profile} (GPUs: {gpu_count}). Runtime tuning reapplied."
            )
        except Exception:
            return

    def _emit_callback(self, payload: Dict[str, Any]) -> None:
        callback = self._on_applied
        if not callback:
            return
        try:
            callback(payload)
        except Exception as exc:
            logger.warning("Runtime hardware adaptation callback failed: %s", exc)
