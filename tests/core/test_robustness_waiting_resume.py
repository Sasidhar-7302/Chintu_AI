"""Regression tests for waiting-input resume handling in robustness middleware."""

from types import SimpleNamespace

from chintu_backend.core.command_parser import CommandIntent
from chintu_backend.core.robustness import RobustnessMiddleware


def _install_like_parse_result():
    return SimpleNamespace(
        intent=CommandIntent.INSTALL,
        clarification_needed=True,
        clarification_question="What package or app should I install?",
        target=None,
        parameters={},
    )


def test_resume_waiting_input_skips_install_clarification(monkeypatch):
    middleware = RobustnessMiddleware()
    monkeypatch.setattr(middleware.context_manager, "has_pending_requests", lambda session_id=None: False)
    monkeypatch.setattr(middleware.command_parser, "parse", lambda *args, **kwargs: _install_like_parse_result())

    response = middleware.pre_process(
        "done, continue channel setup",
        context={"_resume_waiting_input": True},
    )

    assert response.success is True
    assert response.needs_followup is False
    assert response.followup_prompt is None
    assert response.message == ""


def test_normal_install_still_asks_for_package(monkeypatch):
    middleware = RobustnessMiddleware()
    monkeypatch.setattr(middleware.context_manager, "has_pending_requests", lambda session_id=None: False)
    monkeypatch.setattr(middleware.command_parser, "parse", lambda *args, **kwargs: _install_like_parse_result())

    response = middleware.pre_process("setup this app", context={})

    assert response.success is True
    assert response.needs_followup is True
    assert "what package or app should i install" in str(response.followup_prompt or "").lower()
