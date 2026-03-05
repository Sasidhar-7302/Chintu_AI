from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _load_workflows_benchmark_module():
    root = Path(__file__).resolve().parents[2]
    target = root / "scripts" / "chintu_workflows_benchmark.py"
    spec = importlib.util.spec_from_file_location("chintu_workflows_benchmark_module", target)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


def test_startup_task_script_contains_scheduler_registration() -> None:
    root = Path(__file__).resolve().parents[2]
    script_path = root / "scripts" / "install_chintu_startup_task.ps1"
    assert script_path.exists()
    text = script_path.read_text(encoding="utf-8", errors="ignore")
    assert "Register-ScheduledTask" in text
    assert "New-ScheduledTaskTrigger" in text
    assert "AtLogOn" in text


def test_workflows_benchmark_dry_run_has_all_cases() -> None:
    module = _load_workflows_benchmark_module()
    report = module.run_workflows_benchmark(live=False)  # type: ignore[attr-defined]
    summary = report.get("summary") or {}
    assert int(summary.get("total", 0)) >= 4
    assert int(summary.get("failed", 0)) == 0
    assert str(report.get("mode")) == "dry_run"


def test_workflows_evidence_log_shape(tmp_path: Path) -> None:
    module = _load_workflows_benchmark_module()
    temp_artifact = tmp_path / "phase6_evidence_shape_test.md"
    temp_artifact.write_text("ok", encoding="utf-8")
    payload = {"report_path": str(temp_artifact), "schedule": {"task_id": "task123"}}
    rows = module._evidence_from_payload("workflow_schedule_health_check", payload)  # type: ignore[attr-defined]  # noqa: SLF001
    assert len(rows) >= 2
    for row in rows:
        assert set(row.keys()) == {"what_changed", "where", "proof"}
        assert row["what_changed"]
        assert row["where"]
        assert row["proof"]


def test_weekly_dashboard_aggregates_recent_reports(tmp_path: Path) -> None:
    module = _load_workflows_benchmark_module()

    recent_a = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "summary": {"pass_rate": 1.0},
        "results": [{"case": "workflow_web_summarize", "ok": True, "latency_s": 1.2}],
    }
    recent_b = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "summary": {"pass_rate": 0.75},
        "results": [{"case": "workflow_web_summarize", "ok": False, "latency_s": 1.8}],
    }
    old = {
        "timestamp_utc": (datetime.now(timezone.utc) - timedelta(days=14)).isoformat().replace("+00:00", "Z"),
        "summary": {"pass_rate": 0.0},
        "results": [{"case": "workflow_web_summarize", "ok": False, "latency_s": 2.2}],
    }

    (tmp_path / "chintu_workflows_benchmark_a.json").write_text(json.dumps(recent_a), encoding="utf-8")
    (tmp_path / "chintu_workflows_benchmark_b.json").write_text(json.dumps(recent_b), encoding="utf-8")
    (tmp_path / "chintu_workflows_benchmark_old.json").write_text(json.dumps(old), encoding="utf-8")

    dashboard = module.build_weekly_dashboard(tmp_path)  # type: ignore[attr-defined]
    payload = dashboard.get("payload") or {}
    summary = payload.get("summary") or {}
    cases = payload.get("cases") or {}
    web_summary = cases.get("workflow_web_summarize") or {}

    assert int(summary.get("runs", 0)) == 2
    assert float(summary.get("avg_pass_rate", 0.0)) > 0.8
    assert int(web_summary.get("total_runs", 0)) == 2
    assert int(web_summary.get("passed_runs", 0)) == 1
