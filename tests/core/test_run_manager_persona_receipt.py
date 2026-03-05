from __future__ import annotations

from pathlib import Path

from chintu_backend.core.run_manager import RunManager


def test_record_persona_selection_writes_receipt_section(tmp_path):
    mgr = RunManager()
    mgr._runs_dir = tmp_path
    run = mgr.create_run(session_id="s-persona", source="test", user_text="help with code")
    assert mgr.acquire_run_turn(run.id, timeout_s=0.1) is True

    mgr.record_persona_selection(
        run.id,
        persona="coding",
        requested="coding",
        reason="keyword_intent_match",
        provider="local",
        adapter_path="",
        adapter_ready=True,
        fallback_to_default=False,
        routing_tags=["code", "engineering"],
    )
    mgr.mark_completed(run.id, message="done")

    record = mgr._runs[run.id]  # noqa: SLF001
    receipt_path = str(record.meta.get("receipt_path") or "").strip()
    assert receipt_path
    receipt = Path(receipt_path).read_text(encoding="utf-8")
    assert "## Personas" in receipt
    assert "persona: coding" in receipt
