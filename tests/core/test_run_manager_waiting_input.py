"""Regression tests for waiting-input run lifecycle helpers."""

from chintu_backend.core.run_manager import RunManager


def test_waiting_input_state_tracks_pending_run_and_context():
    mgr = RunManager()
    run = mgr.create_run(session_id="s1", source="test", user_text="login to youtube")
    assert mgr.acquire_run_turn(run.id, timeout_s=0.1) is True

    mgr.mark_waiting_input(
        run.id,
        prompt="Please complete login manually.",
        capability="login_to",
        meta={"site": "youtube", "url": "https://accounts.google.com", "ignored": "x"},
    )

    assert mgr.pending_input_run_id() == run.id
    ctx = mgr.get_waiting_input_context(run.id)
    assert ctx.get("capability") == "login_to"
    assert ctx.get("meta", {}).get("site") == "youtube"
    assert "ignored" not in (ctx.get("meta") or {})


def test_clear_waiting_input_resumes_run_and_terminal_state_clears_pending_id():
    mgr = RunManager()
    run = mgr.create_run(session_id="s2", source="test", user_text="login to youtube")
    assert mgr.acquire_run_turn(run.id, timeout_s=0.1) is True

    mgr.mark_waiting_input(run.id, prompt="waiting", capability="login_to")
    assert mgr.pending_input_run_id() == run.id

    mgr.clear_waiting_input(run.id)
    snap = mgr.snapshot(limit=5)
    status = next(r for r in snap["runs"] if r["id"] == run.id)["status"]
    assert status == "running"

    mgr.mark_completed(run.id, message="done")
    assert mgr.pending_input_run_id() is None
