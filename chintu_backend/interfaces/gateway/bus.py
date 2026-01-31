"""Simple async event bus for the gateway layer."""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List


class GatewayEventBus:
    def __init__(self):
        self._subs: Dict[str, List[Callable[[Dict[str, Any]], Awaitable[None]]]] = {}

    def subscribe(self, event_type: str, handler: Callable[[Dict[str, Any]], Awaitable[None]]):
        self._subs.setdefault(event_type, []).append(handler)

    async def publish(self, event_type: str, payload: Dict[str, Any]):
        handlers = self._subs.get(event_type, [])
        for handler in handlers:
            await handler(payload)

    async def publish_safe(self, event_type: str, payload: Dict[str, Any]):
        handlers = self._subs.get(event_type, [])
        for handler in handlers:
            try:
                await handler(payload)
            except Exception:
                # Best-effort bus; swallow to avoid cascading failures.
                await asyncio.sleep(0)
