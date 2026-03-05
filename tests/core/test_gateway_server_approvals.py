from __future__ import annotations

from types import SimpleNamespace

from chintu_backend.interfaces.gateway.server import GatewayServer


class _ChannelPolicyStub:
    def __init__(self):
        self.set_calls = []

    def is_allowed(self, channel, user_id):
        return str(user_id) == "1001"

    def get_tool_policy(self, channel, user_id):
        return {"allow": [], "deny": []}

    def set_tool_policy(self, channel, allow=None, deny=None, user_id=None):
        self.set_calls.append(
            {
                "channel": channel,
                "user_id": user_id,
                "allow": list(allow or []),
                "deny": list(deny or []),
            }
        )


class _DispatcherStub:
    def __init__(self):
        self.cancel_called = False
        self.confirm_called = False
        self.confirm_context = {}

    def get_pending_confirmation(self):
        return {
            "pending": True,
            "capability": "tool::write_file",
            "message": "Need approval",
            "confirmation_type": "action",
        }

    def cancel_pending(self):
        self.cancel_called = True
        return True

    def confirm_pending(self, context=None):
        self.confirm_called = True
        self.confirm_context = dict(context or {})
        return SimpleNamespace(success=True, message="confirmed")


def _make_server(dispatcher=None, channel_policy=None, telegram_owner=0):
    server = GatewayServer.__new__(GatewayServer)
    server.command_handler = SimpleNamespace(action_dispatcher=dispatcher)
    server._channel_policy = channel_policy or _ChannelPolicyStub()
    server._config = SimpleNamespace(telegram_allowed_user_id=telegram_owner)
    return server


def test_session_owner_allowed_enforces_telegram_owner():
    server = _make_server(channel_policy=_ChannelPolicyStub(), telegram_owner=1001)
    assert server._session_owner_allowed({"is_local": True}) is True
    assert (
        server._session_owner_allowed({"is_local": False, "channel": "telegram", "user_id": "1001"})
        is True
    )
    assert (
        server._session_owner_allowed({"is_local": False, "channel": "telegram", "user_id": "9999"})
        is False
    )


def test_resolve_action_whitelist_adds_policy_and_confirms():
    dispatcher = _DispatcherStub()
    policy = _ChannelPolicyStub()
    server = _make_server(dispatcher=dispatcher, channel_policy=policy)

    result = server._resolve_approval_request(
        params={"kind": "action", "decision": "whitelist"},
        session={"is_local": True, "channel": "telegram", "user_id": "1001"},
    )

    assert result["ok"] is True
    assert result["decision"] == "whitelist"
    assert dispatcher.confirm_called is True
    assert len(policy.set_calls) == 1
    assert "tool::write_file" in policy.set_calls[0]["allow"]


def test_resolve_action_deny_cancels_pending():
    dispatcher = _DispatcherStub()
    server = _make_server(dispatcher=dispatcher, channel_policy=_ChannelPolicyStub())

    result = server._resolve_approval_request(
        params={"kind": "action", "decision": "deny"},
        session={"is_local": True, "channel": "telegram", "user_id": "1001"},
    )

    assert result["ok"] is True
    assert result["decision"] == "deny"
    assert dispatcher.cancel_called is True


def test_resolve_orchestrator_step_approval(monkeypatch):
    server = _make_server(dispatcher=_DispatcherStub(), channel_policy=_ChannelPolicyStub())

    class _Manager:
        def approve_step(self, step_id, approve):
            if step_id != "step-1":
                return None
            status = SimpleNamespace(value="approved" if approve else "rejected")
            return SimpleNamespace(status=status)

    monkeypatch.setattr(
        "chintu_backend.orchestrator.get_orchestrator_manager",
        lambda: _Manager(),
    )

    result = server._resolve_approval_request(
        params={"kind": "orchestrator_step", "decision": "allow_once", "step_id": "step-1"},
        session={"is_local": True, "channel": "telegram", "user_id": "1001"},
    )
    assert result["ok"] is True
    assert result["kind"] == "orchestrator_step"
    assert result["step_id"] == "step-1"
    assert result["status"] == "approved"


def test_resolve_run_control_receipt_reads_receipt(monkeypatch, tmp_path):
    server = _make_server(dispatcher=_DispatcherStub(), channel_policy=_ChannelPolicyStub())
    receipt = tmp_path / "receipt.md"
    receipt.write_text("# run receipt\ncompleted", encoding="utf-8")

    class _Manager:
        def snapshot(self, limit=30):
            return {"runs": [{"id": "run-1", "receipt_path": str(receipt)}]}

        def cancel_run(self, run_id, reason=""):
            return False

    monkeypatch.setattr("chintu_backend.core.run_manager.get_run_manager", lambda: _Manager())
    result = server._resolve_run_control_request(  # noqa: SLF001
        params={"action": "receipt", "run_id": "run-1"},
        session={"is_local": True},
    )
    assert result["ok"] is True
    assert result["run_id"] == "run-1"
    assert "completed" in result["receipt_text"]


def test_resolve_run_control_cancel_calls_manager(monkeypatch):
    server = _make_server(dispatcher=_DispatcherStub(), channel_policy=_ChannelPolicyStub())
    calls = {}

    class _Manager:
        def snapshot(self, limit=30):
            return {"runs": [{"id": "run-9", "receipt_path": ""}]}

        def cancel_run(self, run_id, reason=""):
            calls["run_id"] = run_id
            calls["reason"] = reason
            return True

    monkeypatch.setattr("chintu_backend.core.run_manager.get_run_manager", lambda: _Manager())
    result = server._resolve_run_control_request(  # noqa: SLF001
        params={"action": "cancel", "run_id": "run-9"},
        session={"is_local": True},
    )
    assert result["ok"] is True
    assert calls["run_id"] == "run-9"
