from __future__ import annotations

from chintu_backend.core.command_handler import CommandHandler


def _handler() -> CommandHandler:
    return CommandHandler.__new__(CommandHandler)


def test_canonical_escalation_reason_prefers_budget_code():
    handler = _handler()
    code = handler._canonical_escalation_reason_code(  # noqa: SLF001
        {
            "provider_attempts": [
                {"reason": "budget_blocked", "error": ""},
            ],
            "routing_outcomes": [],
        }
    )
    assert code == "verifier_fail_budget_exhausted"


def test_canonical_escalation_reason_detects_timeout_or_oom():
    handler = _handler()
    code = handler._canonical_escalation_reason_code(  # noqa: SLF001
        {
            "provider_attempts": [],
            "routing_outcomes": [
                {"reason": "final_fallback", "error": "CUDA out of memory while generating"},
            ],
        }
    )
    assert code == "local_model_timeout_or_oom"
