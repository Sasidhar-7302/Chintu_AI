from __future__ import annotations

from pathlib import Path

from chintu_backend.core.run_manager import RunManager


def test_record_escalation_persists_and_writes_receipt_section(tmp_path):
    mgr = RunManager()
    mgr._runs_dir = tmp_path
    run = mgr.create_run(session_id="s-escalation", source="test", user_text="analyze this")
    assert mgr.acquire_run_turn(run.id, timeout_s=0.1) is True

    artifact_path = mgr.write_artifact(run.id, "escalation_test.json", "{}")
    mgr.record_escalation(
        run.id,
        reason_code="context_overflow_risk",
        provider="groq",
        mode="conversation",
        inputs={"user_text": "masked"},
        returned_solution={"provider": "groq", "response": "ok"},
        artifacts=[artifact_path or ""],
    )
    mgr.mark_completed(run.id, message="done")

    record = mgr._runs[run.id]  # noqa: SLF001 - targeted state assertion for receipt contract.
    escalations = record.meta.get("escalations")
    assert isinstance(escalations, list)
    assert len(escalations) == 1
    assert escalations[0]["reason_code"] == "context_overflow_risk"

    receipt_path = str(record.meta.get("receipt_path") or "").strip()
    assert receipt_path
    receipt = Path(receipt_path).read_text(encoding="utf-8")
    assert "## Escalations" in receipt
    assert "reason_code: context_overflow_risk" in receipt
