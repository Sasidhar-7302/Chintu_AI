"""Future gesture action mappings (not wired)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from chintu_backend.vision.gesture_recognition import GestureType, GestureResult


@dataclass
class GestureAction:
    command: str
    gesture: GestureType


class GestureActionRouter:
    """
    Placeholder for gesture -> command mapping.
    Not connected to runtime until explicitly enabled.
    """

    def __init__(self, cooldown_seconds: float = 2.0):
        self.cooldown_seconds = cooldown_seconds
        self._last_action_at = 0.0

    def get_action(self, result: GestureResult) -> Optional[GestureAction]:
        now = time.monotonic()
        if now - self._last_action_at < self.cooldown_seconds:
            return None
        self._last_action_at = now

        gesture = result.gesture
        if gesture == GestureType.THUMBS_UP:
            return GestureAction(command="confirm", gesture=gesture)
        if gesture == GestureType.THUMBS_DOWN:
            return GestureAction(command="cancel", gesture=gesture)
        if gesture == GestureType.FIST:
            return GestureAction(command="stop_speaking", gesture=gesture)
        if gesture == GestureType.PEACE:
            return GestureAction(command="scroll down", gesture=gesture)
        if gesture == GestureType.POINTING:
            return GestureAction(command="scroll up", gesture=gesture)
        if gesture == GestureType.OK:
            return GestureAction(command="list windows", gesture=gesture)
        return None

