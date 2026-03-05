"""Regression tests for sandbox CSV task routing in ActionDispatcher."""

from chintu_backend.core.action_dispatcher import ActionDispatcher
from chintu_backend.core.capabilities import ActionResult, Capability, CapabilityRegistry, CapabilityType


def _dummy_handler(_text, _context):
    return ActionResult.ok("dummy", capability="sandbox_data_task")


def test_sandbox_data_requests_bypass_compound_decomposition(monkeypatch):
    registry = CapabilityRegistry()
    registry.register(
        Capability(
            name="sandbox_data_task",
            triggers=["sandbox", "csv", "clean null values", "matplotlib trend chart"],
            handler=_dummy_handler,
            requires_confirmation=False,
            capability_type=CapabilityType.AUTOMATION,
        )
    )
    dispatcher = ActionDispatcher(registry, llm_client=None)

    calls = {"forced": 0}

    def _fake_execute_with_loop_guard(capability, text, context):
        assert capability.name == "sandbox_data_task"
        calls["forced"] += 1
        return ActionResult.ok(f"handled: {text[:20]}", capability="sandbox_data_task")

    def _fail_decompose(_text):
        raise AssertionError("decompose() should not be called for sandbox_data_task prompts")

    monkeypatch.setattr(dispatcher, "_execute_with_loop_guard", _fake_execute_with_loop_guard)
    monkeypatch.setattr(dispatcher.tool_router, "decompose", _fail_decompose)

    prompt = (
        "I have a messy dataset called sales_2025.csv in my Downloads. "
        "Write a Python script to clean the null values, generate a matplotlib trend chart, "
        "and save the chart to my Desktop. Do not run the code on my main OS - execute it in the sandbox."
    )

    result = dispatcher.dispatch(prompt, {})

    assert result.success is True
    assert result.capability_name == "sandbox_data_task"
    assert calls["forced"] == 1


def test_sandbox_data_alias_analyze_csv_in_sandbox(monkeypatch):
    registry = CapabilityRegistry()
    registry.register(
        Capability(
            name="sandbox_data_task",
            triggers=["analyze csv in sandbox"],
            handler=_dummy_handler,
            requires_confirmation=False,
            capability_type=CapabilityType.AUTOMATION,
        )
    )
    dispatcher = ActionDispatcher(registry, llm_client=None)

    calls = {"forced": 0}

    def _fake_execute_with_loop_guard(capability, text, context):
        assert capability.name == "sandbox_data_task"
        calls["forced"] += 1
        return ActionResult.ok(text, capability="sandbox_data_task")

    def _fail_decompose(_text):
        raise AssertionError("decompose() should not be called for sandbox_data_task alias prompts")

    monkeypatch.setattr(dispatcher, "_execute_with_loop_guard", _fake_execute_with_loop_guard)
    monkeypatch.setattr(dispatcher.tool_router, "decompose", _fail_decompose)

    prompt = "Analyze sales_2025.csv in sandbox"
    result = dispatcher.dispatch(prompt, {})

    assert result.success is True
    assert result.capability_name == "sandbox_data_task"
    assert calls["forced"] == 1
