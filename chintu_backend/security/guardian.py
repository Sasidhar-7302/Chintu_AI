"""Guardian utilities for high-risk actions."""

from __future__ import annotations

from typing import Callable, Dict

from chintu_backend.core.capabilities import ActionResult


def require_confirmation(reason: str, capability_name: str) -> Callable:
    """Decorator that forces confirmation for high-risk actions."""

    def decorator(func: Callable[[str, Dict], ActionResult]) -> Callable[[str, Dict], ActionResult]:
        def wrapper(text: str, context: Dict) -> ActionResult:
            if context.get("_confirmed"):
                return func(text, context)

            def pending():
                updated = dict(context)
                updated["_confirmed"] = True
                return func(text, updated)

            return ActionResult.confirm(reason, pending, capability_name)

        return wrapper

    return decorator
