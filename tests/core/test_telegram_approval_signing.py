from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from chintu_backend.channels.telegram import TelegramGateway


def _gateway(*, secret: str, require_signed: bool) -> TelegramGateway:
    gw = TelegramGateway.__new__(TelegramGateway)
    gw.config = SimpleNamespace(
        telegram_approval_signing_secret=secret,
        telegram_bot_token="",
        telegram_require_signed_approvals=require_signed,
    )
    return gw


def test_signed_orchestrator_callback_round_trip():
    gw = _gateway(secret="test-secret", require_signed=True)
    payload = gw._build_orchestrator_callback_data(step_id="step-123", approve=True)  # noqa: SLF001
    assert payload.startswith("orchv1:a:step-123:")

    parsed = gw._parse_orchestrator_callback_data(payload)  # noqa: SLF001
    assert parsed == ("step-123", True, "")


def test_signed_orchestrator_callback_rejects_tamper():
    gw = _gateway(secret="test-secret", require_signed=True)
    payload = gw._build_orchestrator_callback_data(step_id="step-123", approve=False)  # noqa: SLF001
    tampered = payload[:-1] + ("0" if payload[-1] != "0" else "1")

    parsed = gw._parse_orchestrator_callback_data(tampered)  # noqa: SLF001
    assert parsed is not None
    assert parsed[2] == "Approval payload signature check failed."


def test_legacy_callbacks_blocked_when_signed_required():
    gw = _gateway(secret="test-secret", require_signed=True)
    parsed = gw._parse_orchestrator_callback_data("orch:approve:step-123")  # noqa: SLF001
    assert parsed is not None
    assert parsed[2] == "Unsigned approval payloads are disabled."


def test_legacy_callbacks_allowed_when_not_required():
    gw = _gateway(secret="", require_signed=False)
    parsed = gw._parse_orchestrator_callback_data("orch:reject:step-123")  # noqa: SLF001
    assert parsed == ("step-123", False, "")


def test_build_mini_app_url_includes_signed_owner_gate_payload():
    gw = TelegramGateway.__new__(TelegramGateway)
    gw.config = SimpleNamespace(
        telegram_approval_signing_secret="miniapp-secret",
        telegram_bot_token="",
        telegram_require_signed_approvals=True,
        telegram_mini_app_url="https://example.com/ops/mini-app",
        telegram_mini_app_token_ttl_seconds=900,
        gateway_auth_token="gateway-token",
    )
    update = SimpleNamespace(effective_user=SimpleNamespace(id=777))

    url = gw._build_mini_app_url(update)  # noqa: SLF001
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert parsed.path == "/ops/mini-app"
    assert query.get("uid", [""])[0] == "777"
    assert query.get("sig", [""])[0]
    assert query.get("exp", [""])[0]
    assert query.get("token", [""])[0] == "gateway-token"
