"""Tests for context-forced capability routing in ActionDispatcher."""

from chintu_backend.core.action_dispatcher import ActionDispatcher
from chintu_backend.core.capabilities import ActionResult, Capability, CapabilityRegistry, CapabilityType


def test_dispatch_respects_forced_capability_from_context():
    registry = CapabilityRegistry()
    seen = {"called": False}

    def _forced_handler(text, context):
        seen["called"] = True
        return ActionResult.ok(f"forced:{text}", capability="forced_cap")

    registry.register(
        Capability(
            name="forced_cap",
            triggers=["never-match-this"],
            handler=_forced_handler,
            capability_type=CapabilityType.SYSTEM,
        )
    )

    dispatcher = ActionDispatcher(registry=registry, llm_client=None)
    result = dispatcher.dispatch("done", context={"_forced_capability": "forced_cap"})
    if result.requires_confirmation:
        result = dispatcher.confirm_pending(context={"_run_id": ""})

    assert seen["called"] is True
    assert result.success is True
    assert result.capability_name == "forced_cap"
    assert "forced:done" in result.message
