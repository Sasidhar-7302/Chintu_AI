"""
Tests for the Action Interceptor (Human-in-the-loop) module.
"""
import asyncio
from unittest.mock import AsyncMock
from chintu_backend.core.action_interceptor import get_action_interceptor, ActionInterceptor

def _run(coro):
    return asyncio.run(coro)

def test_action_interceptor_approval():
    async def _impl():
        interceptor = ActionInterceptor()
        interceptor.event_bus = AsyncMock()

        task = asyncio.create_task(interceptor.request_approval("delete_file", {"path": "/important.txt"}))
        await asyncio.sleep(0.05)

        assert interceptor.event_bus.publish.called
        assert len(interceptor.pending_actions) == 1
        action_id = next(iter(interceptor.pending_actions.keys()))

        assert interceptor.resolve_action(action_id, approved=True) is True

        assert await task is True
        assert len(interceptor.pending_actions) == 0

    _run(_impl())

def test_action_interceptor_rejection():
    async def _impl():
        interceptor = ActionInterceptor()
        interceptor.event_bus = AsyncMock()

        task = asyncio.create_task(interceptor.request_approval("send_payment", {"amount": 500}))
        await asyncio.sleep(0.05)

        action_id = next(iter(interceptor.pending_actions.keys()))
        interceptor.resolve_action(action_id, approved=False)

        assert await task is False

    _run(_impl())

def test_action_interceptor_invalid_resolve():
    """Test resolving an unknown action."""
    interceptor = ActionInterceptor()
    assert interceptor.resolve_action("unknown_id", True) is False
