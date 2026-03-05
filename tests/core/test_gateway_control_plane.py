from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from chintu_backend.interfaces.gateway.control_plane import (
    build_control_plane_snapshot,
    build_run_board,
)


class _Dispatcher:
    def get_pending_confirmation(self):
        return {
            "pending": True,
            "capability": "tool::write_file",
            "message": "Need approval",
            "confirmation_type": "action",
        }


class _Router:
    def __init__(self):
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self.arbiter_telemetry = _TelemetryStore(
            [
                {
                    "event": "provider_attempt",
                    "ts": now,
                    "payload": {"provider": "local", "success": True, "latency_ms": 120.0},
                },
                {
                    "event": "provider_attempt",
                    "ts": now,
                    "payload": {"provider": "local", "success": False, "latency_ms": 210.0},
                },
            ]
        )

    def get_provider_health(self):
        return {"local": {"ok": True}}

    def get_arbiter_telemetry_summary(self, hours=24, limit=1200):
        return {"events": 1, "hours": hours, "limit": limit}


class _TelemetryStore:
    def __init__(self, rows):
        self._rows = list(rows or [])

    def read_recent(self, limit=300):
        return self._rows[-max(1, int(limit)) :]


class _Policy:
    def get_tool_policy(self, channel, user_id):
        return {"allow": ["tool::write_file"], "deny": []}


def _write_run_events(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    events = (
        '{"step":{"evidence":[{"kind":"url","value":"https://example.com","summary":"example"}]}}\n'
        '{"event":{"artifacts":["C:/tmp/output.txt"]}}\n'
    )
    (run_dir / "events.jsonl").write_text(events, encoding="utf-8")


def test_build_run_board_extracts_artifacts_and_counts(tmp_path):
    run_id = "run-001"
    run_dir = tmp_path / run_id
    _write_run_events(run_dir)
    receipt_path = str(run_dir / "receipt.md")
    (run_dir / "receipt.md").write_text("# receipt", encoding="utf-8")

    run_summary = {
        "pending_confirmation_run_id": run_id,
        "pending_input_run_id": "",
        "lanes": {"waiting_approval": [run_id]},
        "runs": [
            {
                "id": run_id,
                "session_id": "s1",
                "source": "gateway",
                "status": "waiting_approval",
                "outcome_label": "",
                "created_at": "2026-03-03T00:00:00Z",
                "receipt_path": receipt_path,
            }
        ],
    }

    payload = build_run_board(run_summary=run_summary, runs_root=tmp_path, limit_runs=10)
    assert payload["counts"]["waiting_approval"] == 1
    assert payload["counts"]["total"] == 1
    assert payload["runs"][0]["is_waiting_approval"] is True
    artifact_kinds = {item["kind"] for item in payload["runs"][0]["artifact_links"]}
    assert "receipt" in artifact_kinds
    assert "events" in artifact_kinds
    assert "url" in artifact_kinds or "artifact" in artifact_kinds


def test_build_control_plane_snapshot_contains_required_sections(tmp_path):
    run_id = "run-002"
    _write_run_events(tmp_path / run_id)
    run_summary = {
        "pending_confirmation_run_id": run_id,
        "pending_input_run_id": "",
        "lanes": {"waiting_approval": [run_id]},
        "runs": [
            {
                "id": run_id,
                "session_id": "s2",
                "source": "gateway",
                "status": "waiting_approval",
                "created_at": "2026-03-03T00:00:00Z",
                "receipt_path": str((tmp_path / run_id / "receipt.md")),
            }
        ],
    }
    (tmp_path / run_id / "receipt.md").write_text("# receipt", encoding="utf-8")

    handler = SimpleNamespace(action_dispatcher=_Dispatcher(), router=_Router())
    payload = build_control_plane_snapshot(
        command_handler=handler,
        run_summary=run_summary,
        session={"channel": "telegram", "user_id": "42"},
        channel_policy=_Policy(),
        runs_root=tmp_path,
        limit_runs=10,
        limit_approvals=10,
    )

    assert "run_board" in payload
    assert "approvals_ledger" in payload
    assert "telemetry" in payload
    assert "artifact_viewer" in payload
    assert payload["approvals_ledger"]["pending_count"] >= 1
    pending = payload["approvals_ledger"]["pending"]
    assert any(item.get("kind") == "action" for item in pending)
    assert isinstance(payload["artifact_viewer"]["recent"], list)
    trends = ((payload.get("telemetry") or {}).get("provider_trends") or {}).get("providers") or {}
    assert "local" in trends
    local = trends["local"]
    assert isinstance(local.get("points"), list)
    assert isinstance(local.get("success_rate_series"), list)
