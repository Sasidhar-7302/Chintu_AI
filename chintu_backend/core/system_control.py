"""System control arbitration to serialize OS-level actions."""

from __future__ import annotations

import time
import threading
from contextlib import contextmanager
from typing import Dict, Optional

from chintu_backend.core.config import get_config
from chintu_backend.core.state import get_state_manager

SYSTEM_CONTROL_SIDE_EFFECTS = {
    "window_control",
    "mouse_keyboard_action",
    "open_application",
    "close_application",
    "open_browser",
    "browser_action",
    "capture_screen",
    "system_shutdown",
    "modify_clipboard",
    "modify_notes",
    "modify_preferences",
    "create_task",
}


class SystemControlArbiter:
    """Serialize system control actions to avoid conflicting OS operations."""

    def __init__(self):
        self._lock = threading.Lock()
        self._active_action: Optional[str] = None
        self._active_since: Optional[float] = None

    def acquire(self, action: str, timeout: Optional[float] = None) -> bool:
        config = get_config()
        timeout = timeout if timeout is not None else float(config.system_control_lock_timeout_seconds)
        acquired = self._lock.acquire(timeout=timeout)
        if acquired:
            self._active_action = action
            self._active_since = time.time()
            try:
                get_state_manager().update_feature("system_control", status="active", error=None)
            except Exception:
                pass
        return acquired

    def release(self) -> None:
        if not self._lock.locked():
            return
        try:
            self._lock.release()
        finally:
            self._active_action = None
            self._active_since = None
            try:
                get_state_manager().update_feature("system_control", status="inactive")
            except Exception:
                pass

    def status(self) -> Dict[str, object]:
        return {
            "active": self._lock.locked(),
            "action": self._active_action,
            "since": self._active_since,
        }

    @contextmanager
    def guard(self, action: str, timeout: Optional[float] = None):
        acquired = self.acquire(action, timeout=timeout)
        try:
            yield acquired
        finally:
            if acquired:
                self.release()


_arbiter: Optional[SystemControlArbiter] = None


def get_system_control_arbiter() -> SystemControlArbiter:
    global _arbiter
    if _arbiter is None:
        _arbiter = SystemControlArbiter()
    return _arbiter
