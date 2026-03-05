"""Regression tests for waiting-input resume flow in login capability."""

from chintu_backend.security import login_capabilities as lc


def test_login_to_resume_waiting_input_acknowledges_manual_completion():
    result = lc.handle_login_to(
        "done, I logged in",
        {
            "_resume_waiting_input": True,
            "_waiting_input_meta": {"site": "youtube"},
        },
    )
    assert result.success is True
    assert result.capability_name == "login_to"
    assert "manual login step complete" in result.message.lower()
    assert (result.data or {}).get("site") == "youtube"
