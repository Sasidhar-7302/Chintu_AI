"""Phase 28 Telegram control-plane gate (remote ops safety + telemetry contract)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
OUTPUT_DIR = REPO_ROOT / "generated_reports"

from chintu_backend.interfaces.gateway.server import GatewayServer


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class _DispatcherStub:
    def get_pending_confirmation(self) -> Dict[str, Any]:
        return {
            "pending": True,
            "capability": "tool::write_file",
            "message": "Need approval",
            "confirmation_type": "action",
        }

    def confirm_pending(self, context: Dict[str, Any] | None = None) -> SimpleNamespace:
        return SimpleNamespace(success=True, message="confirmed", context=context or {})

    def cancel_pending(self) -> bool:
        return True


class _ChannelPolicyStub:
    def is_allowed(self, channel: str, user_id: Any) -> bool:
        return str(user_id) == "1001"

    def get_tool_policy(self, channel: str, user_id: Any) -> Dict[str, Any]:
        return {"allow": ["tool::write_file"], "deny": []}

    def set_tool_policy(self, channel: str, allow=None, deny=None, user_id=None) -> Dict[str, Any]:
        return {
            "channel": channel,
            "user_id": user_id,
            "allow": list(allow or []),
            "deny": list(deny or []),
        }


class _TelemetryStore:
    def __init__(self, rows: List[Dict[str, Any]]):
        self._rows = list(rows or [])

    def read_recent(self, limit: int = 300) -> List[Dict[str, Any]]:
        return self._rows[-max(1, int(limit)) :]


class _RouterStub:
    def __init__(self) -> None:
        now = _utc_iso()
        self.arbiter_telemetry = _TelemetryStore(
            [
                {"event": "provider_attempt", "ts": now, "payload": {"provider": "local", "success": True, "latency_ms": 120.0}},
                {"event": "provider_attempt", "ts": now, "payload": {"provider": "cloud", "success": True, "latency_ms": 380.0}},
            ]
        )

    def get_provider_health(self) -> Dict[str, Any]:
        return {"local": {"available": True}, "cloud": {"available": True}}

    def get_arbiter_telemetry_summary(self, hours: int = 24, limit: int = 1200) -> Dict[str, Any]:
        return {"events": 2, "hours": hours, "limit": limit}


def _write_run_artifacts(root: Path, run_id: str) -> Path:
    run_dir = root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    receipt = run_dir / "receipt.md"
    receipt.write_text("# receipt\nrun completed", encoding="utf-8")
    (run_dir / "events.jsonl").write_text(
        '{"step":{"evidence":[{"kind":"url","value":"https://example.com","summary":"example"}]}}\n',
        encoding="utf-8",
    )
    return receipt


def run_phase28_gate() -> Dict[str, Any]:
    runs_root = REPO_ROOT / "generated_reports" / "phase28_control_plane_runs"
    runs_root.mkdir(parents=True, exist_ok=True)
    run_id = "phase28-run-1"
    receipt_path = _write_run_artifacts(runs_root, run_id)

    server = GatewayServer.__new__(GatewayServer)
    server.command_handler = SimpleNamespace(action_dispatcher=_DispatcherStub(), router=_RouterStub())
    server._channel_policy = _ChannelPolicyStub()
    server._config = SimpleNamespace(
        gateway_version="1.0.0",
        gateway_audit_history_limit=100,
        gateway_ops_rate_limit_per_minute=60,
        gateway_ops_approval_rate_limit_per_minute=30,
        gateway_approval_payload_ttl_seconds=300,
        telegram_approval_signing_secret="ops-secret",
        telegram_require_signed_approvals=True,
        telegram_allowed_user_id=1001,
        gateway_auth_token="gw-token",
        memory_receipts_dir=runs_root,
        data_dir=REPO_ROOT / "data",
    )
    server.auth_token = "gw-token"
    server._ops_rate_buckets = {}
    server._sessions = {}

    import chintu_backend.core.run_manager as run_manager_module

    class _RunManagerStub:
        def snapshot(self, limit: int = 30) -> Dict[str, Any]:
            return {"runs": [{"id": run_id, "receipt_path": str(receipt_path)}]}

        def cancel_run(self, rid: str, reason: str = "") -> bool:
            return rid == run_id

    original_get_rm = run_manager_module.get_run_manager
    run_manager_module.get_run_manager = lambda: _RunManagerStub()  # type: ignore[assignment]
    try:
        # Control-plane snapshot + signed approval payload contract.
        snapshot = server._build_control_plane_snapshot(  # noqa: SLF001
            session={"session_id": "s1", "channel": "telegram", "user_id": "1001", "is_local": False},
            limit_runs=20,
            limit_approvals=20,
        )
        required_sections = all(key in snapshot for key in ("run_board", "approvals_ledger", "telemetry", "artifact_viewer"))
        signed = server._attach_signed_approval_payloads(snapshot, ttl_s=180)  # noqa: SLF001
        pending = ((signed.get("approvals_ledger") or {}).get("pending") or [])
        has_signed_payload = bool(
            pending
            and isinstance(pending[0], dict)
            and isinstance(pending[0].get("approval_payload"), dict)
            and str(pending[0].get("approval_signature") or "").strip()
        )

        # Remote approval resolution must require and accept valid signatures.
        approval_ok = False
        if has_signed_payload:
            item = pending[0]
            payload = item.get("approval_payload") if isinstance(item, dict) else {}
            signature = str(item.get("approval_signature") or "") if isinstance(item, dict) else ""
            resolved = server._resolve_approval_request(  # noqa: SLF001
                params={
                    "kind": "action",
                    "decision": "allow_once",
                    "approval_payload": payload,
                    "approval_signature": signature,
                },
                session={"is_local": False, "channel": "telegram", "user_id": "1001"},
            )
            approval_ok = bool(resolved.get("ok"))

        # Run control contract: read receipt and cancel.
        receipt_result = server._resolve_run_control_request(  # noqa: SLF001
            params={"action": "receipt", "run_id": run_id},
            session={"is_local": True},
        )
        cancel_result = server._resolve_run_control_request(  # noqa: SLF001
            params={"action": "cancel", "run_id": run_id},
            session={"is_local": True},
        )
    finally:
        run_manager_module.get_run_manager = original_get_rm  # type: ignore[assignment]

    run_receipt_ok = bool(receipt_result.get("ok")) and "run completed" in str(receipt_result.get("receipt_text") or "")
    run_cancel_ok = bool(cancel_result.get("ok"))

    checks = {
        "control_plane_sections": required_sections,
        "signed_approval_payloads": has_signed_payload,
        "remote_approval_resolution": approval_ok,
        "run_receipt_access": run_receipt_ok,
        "run_cancel_action": run_cancel_ok,
    }
    overall_ok = all(bool(v) for v in checks.values())

    return {
        "phase": "phase28",
        "timestamp_utc": _utc_iso(),
        "checks": checks,
        "overall_ok": overall_ok,
        "snapshot_counts": ((snapshot.get("run_board") or {}).get("counts") or {}),
    }


def _render_md(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# Phase 28 Telegram Control-Plane Gate")
    lines.append("")
    lines.append(f"- Timestamp (UTC): `{report.get('timestamp_utc', '')}`")
    lines.append(f"- Overall gate pass: `{report.get('overall_ok')}`")
    lines.append("")
    lines.append("## Checks")
    checks = report.get("checks") if isinstance(report, dict) else {}
    for key, value in (checks or {}).items():
        lines.append(f"- {key}: `{value}`")
    lines.append("")
    counts = report.get("snapshot_counts") or {}
    lines.append("## Snapshot Counts")
    for key, value in counts.items():
        lines.append(f"- {key}: `{value}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    report = run_phase28_gate()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _utc_stamp()
    json_path = OUTPUT_DIR / f"phase28_telegram_control_plane_gate_{stamp}.json"
    md_path = OUTPUT_DIR / f"phase28_telegram_control_plane_gate_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    md_path.write_text(_render_md(report), encoding="utf-8")
    print(f"Wrote: {json_path}")
    print(f"Wrote: {md_path}")
    return 0 if bool(report.get("overall_ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
