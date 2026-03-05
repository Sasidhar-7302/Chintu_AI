from __future__ import annotations

import time
from types import SimpleNamespace

from chintu_backend.interfaces.gateway.server import GatewayServer


class _DispatcherStub:
    def __init__(self):
        self.confirm_called = False

    def get_pending_confirmation(self):
        return {
            "pending": True,
            "capability": "tool::write_file",
            "message": "Need approval",
            "confirmation_type": "action",
        }

    def confirm_pending(self, context=None):
        self.confirm_called = True
        return SimpleNamespace(success=True, message="ok")

    def cancel_pending(self):
        return True


def _make_server():
    server = GatewayServer.__new__(GatewayServer)
    server.command_handler = SimpleNamespace(action_dispatcher=_DispatcherStub())
    server._channel_policy = SimpleNamespace()
    server._config = SimpleNamespace(
        telegram_approval_signing_secret="ops-secret",
        gateway_auth_token="gw-token",
        telegram_require_signed_approvals=True,
        telegram_allowed_user_id=1001,
    )
    server.auth_token = "gw-token"
    return server


def test_owner_gate_signature_round_trip():
    server = _make_server()
    exp = int(time.time()) + 300
    sig = server._sign_owner_gate_signature("1001", exp)  # noqa: SLF001
    assert sig
    assert server._verify_owner_gate_signature("1001", exp, sig) is True  # noqa: SLF001


def test_http_owner_allowed_for_remote_request_with_valid_signature():
    server = _make_server()
    exp = int(time.time()) + 300
    sig = server._sign_owner_gate_signature("1001", exp)  # noqa: SLF001
    request = SimpleNamespace(
        client=SimpleNamespace(host="8.8.8.8"),
        query_params={"uid": "1001", "exp": str(exp), "sig": sig},
        headers={},
    )
    assert server._http_owner_allowed(request) is True  # noqa: SLF001


def test_attach_signed_approval_payloads_adds_payload_and_signature():
    server = _make_server()
    control_plane = {
        "approvals_ledger": {
            "pending": [
                {
                    "id": "dispatcher_pending",
                    "kind": "action",
                    "capability": "tool::write_file",
                    "run_id": "run-1",
                }
            ]
        }
    }
    updated = server._attach_signed_approval_payloads(control_plane, ttl_s=180)  # noqa: SLF001
    pending = updated["approvals_ledger"]["pending"][0]
    assert isinstance(pending.get("approval_payload"), dict)
    assert str(pending.get("approval_signature") or "").strip()


def test_remote_approval_requires_valid_signed_payload():
    server = _make_server()
    remote_session = {"is_local": False, "channel": "telegram", "user_id": "1001"}

    missing = server._resolve_approval_request(  # noqa: SLF001
        params={"kind": "action", "decision": "allow_once"},
        session=remote_session,
    )
    assert missing["ok"] is False

    now_ts = int(time.time())
    payload = {
        "kind": "action",
        "id": "dispatcher_pending",
        "step_id": "",
        "capability": "tool::write_file",
        "run_id": "run-1",
        "issued_at": now_ts,
        "expires_at": now_ts + 120,
    }
    sig = server._sign_json_payload(payload)  # noqa: SLF001
    ok = server._resolve_approval_request(  # noqa: SLF001
        params={
            "kind": "action",
            "decision": "allow_once",
            "approval_payload": payload,
            "approval_signature": sig,
        },
        session=remote_session,
    )
    assert ok["ok"] is True
