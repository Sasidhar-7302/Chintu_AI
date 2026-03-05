from __future__ import annotations

from pathlib import Path

from chintu_backend.core.action_dispatcher import ActionDispatcher
from chintu_backend.core.capabilities import ActionResult, Capability, CapabilityRegistry, CapabilityType


def test_dispatcher_adds_structured_evidence_log(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.md"
    artifact.write_text("ok", encoding="utf-8")

    registry = CapabilityRegistry()

    def _handler(_text, _context):
        return ActionResult.ok(
            "done",
            {"report_path": str(artifact)},
            "artifact_cap",
        )

    registry.register(
        Capability(
            name="artifact_cap",
            triggers=["artifact"],
            handler=_handler,
            capability_type=CapabilityType.SYSTEM,
        )
    )
    dispatcher = ActionDispatcher(registry=registry, llm_client=None)
    result = dispatcher.dispatch("artifact", context={"_confirmed": True})

    assert result.success is True
    assert isinstance(result.data, dict)
    rows = result.data.get("evidence_log")
    assert isinstance(rows, list) and rows
    first = rows[0]
    assert first.get("what_changed")
    assert first.get("where") == str(artifact)
    assert first.get("proof") == "path_exists"
