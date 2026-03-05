"""Phase 6 workflow benchmark with live artifact verification + weekly dashboard."""

from __future__ import annotations

import argparse
import importlib.util
import inspect
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Callable, Dict, List, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_module(script_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Failed to load module from {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


def _run_workflow_script(script_rel_path: str, *, request: str = "", url: str = "") -> Dict[str, Any]:
    script_path = REPO_ROOT / script_rel_path
    module = _load_module(script_path, f"workflow_benchmark_{script_path.stem}_{int(time.time() * 1000)}")
    run_fn = getattr(module, "run", None)
    if not callable(run_fn):
        raise RuntimeError(f"Missing run() in workflow script: {script_rel_path}")

    sig = inspect.signature(run_fn)
    kwargs: Dict[str, Any] = {}
    if "request_text" in sig.parameters:
        kwargs["request_text"] = request
    elif sig.parameters:
        first = next(iter(sig.parameters))
        kwargs[first] = request
    if "url" in sig.parameters:
        kwargs["url"] = url
    payload = run_fn(**kwargs) if kwargs else run_fn()
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected workflow payload type from {script_rel_path}: {type(payload)!r}")
    return payload


def _path_exists(path_value: Any) -> bool:
    value = str(path_value or "").strip()
    return bool(value and Path(value).exists())


def _read_text(path_value: Any) -> str:
    value = str(path_value or "").strip()
    if not value:
        return ""
    try:
        return Path(value).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _evidence_entry(*, what_changed: str, where: Any, proof: str) -> Dict[str, str]:
    return {
        "what_changed": str(what_changed or "").strip(),
        "where": str(where or "").strip(),
        "proof": str(proof or "").strip(),
    }


def _evidence_from_payload(case_name: str, payload: Dict[str, Any]) -> List[Dict[str, str]]:
    entries: List[Dict[str, str]] = []
    path_keys = ("report_path", "summary_path", "archive_path", "artifact_path", "path")
    for key in path_keys:
        value = payload.get(key)
        if not value:
            continue
        entries.append(
            _evidence_entry(
                what_changed=f"{case_name} wrote artifact",
                where=value,
                proof="path_exists" if _path_exists(value) else "reported_path",
            )
        )
    schedule = payload.get("schedule")
    if isinstance(schedule, dict) and schedule.get("task_id"):
        entries.append(
            _evidence_entry(
                what_changed=f"{case_name} scheduled recurring task",
                where=schedule.get("task_id"),
                proof="scheduler_task_id",
            )
        )
    # Deduplicate while preserving order.
    dedup: List[Dict[str, str]] = []
    seen = set()
    for row in entries:
        token = (row.get("what_changed"), row.get("where"), row.get("proof"))
        if token in seen:
            continue
        seen.add(token)
        dedup.append(row)
    return dedup


def _verify_health(payload: Dict[str, Any]) -> Tuple[bool, str]:
    schedule = payload.get("schedule") if isinstance(payload.get("schedule"), dict) else {}
    scheduled = bool(schedule.get("scheduled"))
    report_path = payload.get("report_path")
    if not _path_exists(report_path):
        return False, "missing health report artifact"
    body = _read_text(report_path)
    if "Background Health Check" not in body:
        return False, "health report format mismatch"
    if not scheduled:
        return False, "daily health task was not scheduled"
    return True, "health schedule + report verified"


def _verify_web_summary(payload: Dict[str, Any]) -> Tuple[bool, str]:
    summary_path = payload.get("summary_path")
    if not _path_exists(summary_path):
        return False, "missing web summary artifact"
    body = _read_text(summary_path)
    if "## Summary" not in body:
        return False, "web summary section missing"
    if "example.com" not in body.lower():
        return False, "summary does not reference source url"
    return True, "web summary artifact verified"


def _verify_backups(payload: Dict[str, Any]) -> Tuple[bool, str]:
    archive_path = payload.get("archive_path")
    report_path = payload.get("report_path")
    if not _path_exists(archive_path):
        return False, "missing backup archive"
    if not _path_exists(report_path):
        return False, "missing backup report"
    return True, "backup archive + report verified"


def _verify_email_triage(payload: Dict[str, Any]) -> Tuple[bool, str]:
    report_path = payload.get("report_path")
    if not _path_exists(report_path):
        return False, "missing email triage report"
    body = _read_text(report_path)
    if "Daily Email Triage Drafts" not in body:
        return False, "email triage report format mismatch"
    if "Draft" not in body:
        return False, "email draft block missing"
    return True, "email triage report verified"


@dataclass
class WorkflowCase:
    name: str
    runner: Callable[[], Dict[str, Any]]
    verifier: Callable[[Dict[str, Any]], Tuple[bool, str]]


def _default_cases() -> List[WorkflowCase]:
    return [
        WorkflowCase(
            name="workflow_schedule_health_check",
            runner=lambda: _run_workflow_script(
                "skills/workflows_pack/background_health_checks/background_health_checks.py",
                request="set up background health checks daily and run now",
            ),
            verifier=_verify_health,
        ),
        WorkflowCase(
            name="workflow_web_summarize",
            runner=lambda: _run_workflow_script(
                "skills/workflows_pack/web_summarize/web_summarize.py",
                request="/summarize https://example.com",
                url="https://example.com",
            ),
            verifier=_verify_web_summary,
        ),
        WorkflowCase(
            name="workflow_self_maintenance_backups",
            runner=lambda: _run_workflow_script(
                "skills/workflows_pack/self_maintenance_backups/self_maintenance_backups.py",
                request="run self maintenance backups now",
            ),
            verifier=_verify_backups,
        ),
        WorkflowCase(
            name="workflow_email_triage_daily",
            runner=lambda: _run_workflow_script(
                "skills/workflows_pack/email_triage_daily/email_triage_daily.py",
                request="run email triage daily now",
            ),
            verifier=_verify_email_triage,
        ),
    ]


def _windowed_reports(out_dir: Path, *, days: int = 7) -> List[Dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))
    reports: List[Dict[str, Any]] = []
    for path in sorted(out_dir.glob("chintu_workflows_benchmark_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        stamp = str(payload.get("timestamp_utc") or "").strip()
        try:
            dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except Exception:
            continue
        if dt < cutoff:
            continue
        if isinstance(payload, dict):
            reports.append(payload)
    return reports


def build_weekly_dashboard(out_dir: Path) -> Dict[str, Any]:
    reports = _windowed_reports(out_dir, days=7)
    per_case: Dict[str, Dict[str, Any]] = {}
    pass_rates: List[float] = []

    for payload in reports:
        summary = payload.get("summary") if isinstance(payload, dict) else {}
        if isinstance(summary, dict):
            pass_rates.append(float(summary.get("pass_rate", 0.0) or 0.0))
        rows = payload.get("results") if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("case") or "").strip()
            if not name:
                continue
            bucket = per_case.setdefault(name, {"total": 0, "passed": 0, "avg_latency_s": []})
            bucket["total"] += 1
            if bool(row.get("ok")):
                bucket["passed"] += 1
            bucket["avg_latency_s"].append(float(row.get("latency_s", 0.0) or 0.0))

    per_case_summary: Dict[str, Dict[str, Any]] = {}
    for name, bucket in per_case.items():
        total = int(bucket.get("total", 0) or 0)
        passed = int(bucket.get("passed", 0) or 0)
        latencies = list(bucket.get("avg_latency_s") or [])
        per_case_summary[name] = {
            "total_runs": total,
            "passed_runs": passed,
            "pass_rate": round((passed / total), 3) if total else 0.0,
            "avg_latency_s": round(mean(latencies), 3) if latencies else 0.0,
        }

    payload = {
        "timestamp_utc": _utc_iso(),
        "window_days": 7,
        "summary": {
            "runs": len(reports),
            "avg_pass_rate": round(mean(pass_rates), 3) if pass_rates else 0.0,
            "best_pass_rate": round(max(pass_rates), 3) if pass_rates else 0.0,
            "worst_pass_rate": round(min(pass_rates), 3) if pass_rates else 0.0,
        },
        "cases": per_case_summary,
    }

    stamp = _utc_stamp()
    json_path = out_dir / f"chintu_workflows_dashboard_weekly_{stamp}.json"
    md_path = out_dir / f"chintu_workflows_dashboard_weekly_{stamp}.md"
    latest_json = out_dir / "chintu_workflows_dashboard_weekly_latest.json"
    latest_md = out_dir / "chintu_workflows_dashboard_weekly_latest.md"

    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    md_path.write_text(_render_dashboard_md(payload), encoding="utf-8")
    latest_json.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    latest_md.write_text(_render_dashboard_md(payload), encoding="utf-8")
    return {
        "payload": payload,
        "json_path": str(json_path),
        "md_path": str(md_path),
        "latest_json_path": str(latest_json),
        "latest_md_path": str(latest_md),
    }


def run_workflows_benchmark(*, live: bool) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    started_all = time.perf_counter()
    for case in _default_cases():
        started = time.perf_counter()
        payload: Dict[str, Any] = {}
        ok = False
        note = ""
        error = ""
        if not live:
            note = "dry_run_skipped"
            ok = True
        else:
            try:
                payload = case.runner()
                ok, note = case.verifier(payload)
            except Exception as exc:
                ok = False
                note = "execution_error"
                error = str(exc)
        latency_s = round(time.perf_counter() - started, 3)
        evidence = _evidence_from_payload(case.name, payload) if live else []
        rows.append(
            {
                "case": case.name,
                "ok": bool(ok),
                "note": str(note),
                "error": str(error),
                "latency_s": latency_s,
                "mode": "live" if live else "dry_run",
                "result": payload,
                "evidence_log": evidence,
            }
        )

    passed = sum(1 for row in rows if row.get("ok"))
    total = len(rows)
    return {
        "timestamp_utc": _utc_iso(),
        "mode": "live" if live else "dry_run",
        "summary": {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": round((passed / total), 3) if total else 0.0,
            "elapsed_s": round(time.perf_counter() - started_all, 2),
            "avg_latency_s": round(mean(float(r.get("latency_s", 0.0) or 0.0) for r in rows), 3) if rows else 0.0,
        },
        "results": rows,
    }


def _render_md(report: Dict[str, Any]) -> str:
    summary = report.get("summary") if isinstance(report, dict) else {}
    rows = report.get("results") if isinstance(report, dict) else []
    lines: List[str] = []
    lines.append("# Chintu Workflows Benchmark")
    lines.append("")
    lines.append(f"- timestamp_utc: {report.get('timestamp_utc', '')}")
    lines.append(f"- mode: {report.get('mode', '')}")
    lines.append(f"- total: {summary.get('total', 0)}")
    lines.append(f"- passed: {summary.get('passed', 0)}")
    lines.append(f"- failed: {summary.get('failed', 0)}")
    lines.append(f"- pass_rate: {summary.get('pass_rate', 0.0)}")
    lines.append(f"- elapsed_s: {summary.get('elapsed_s', 0.0)}")
    lines.append("")
    lines.append("## Results")
    lines.append("")
    lines.append("| Case | OK | Note | Latency (s) | Evidence |")
    lines.append("|---|---|---|---:|---|")
    for row in rows if isinstance(rows, list) else []:
        evidence = row.get("evidence_log") if isinstance(row.get("evidence_log"), list) else []
        evidence_preview = "; ".join(
            f"{item.get('what_changed')} -> {item.get('where')} ({item.get('proof')})"
            for item in evidence[:2]
            if isinstance(item, dict)
        )
        lines.append(
            "| {case} | {ok} | {note} | {lat} | {ev} |".format(
                case=str(row.get("case") or "").replace("|", "\\|"),
                ok="PASS" if row.get("ok") else "FAIL",
                note=str(row.get("note") or "").replace("|", "\\|"),
                lat=row.get("latency_s", 0.0),
                ev=evidence_preview.replace("|", "\\|"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _render_dashboard_md(payload: Dict[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload, dict) else {}
    cases = payload.get("cases") if isinstance(payload, dict) else {}
    lines: List[str] = []
    lines.append("# Chintu Weekly Workflow Dashboard")
    lines.append("")
    lines.append(f"- timestamp_utc: {payload.get('timestamp_utc', '')}")
    lines.append(f"- window_days: {payload.get('window_days', 7)}")
    lines.append(f"- runs: {summary.get('runs', 0)}")
    lines.append(f"- avg_pass_rate: {summary.get('avg_pass_rate', 0.0)}")
    lines.append(f"- best_pass_rate: {summary.get('best_pass_rate', 0.0)}")
    lines.append(f"- worst_pass_rate: {summary.get('worst_pass_rate', 0.0)}")
    lines.append("")
    lines.append("## Per Case")
    lines.append("")
    lines.append("| Case | Runs | Passed | Pass Rate | Avg Latency (s) |")
    lines.append("|---|---:|---:|---:|---:|")
    if isinstance(cases, dict):
        for name, row in sorted(cases.items()):
            if not isinstance(row, dict):
                continue
            lines.append(
                "| {name} | {runs} | {passed} | {rate} | {lat} |".format(
                    name=str(name).replace("|", "\\|"),
                    runs=row.get("total_runs", 0),
                    passed=row.get("passed_runs", 0),
                    rate=row.get("pass_rate", 0.0),
                    lat=row.get("avg_latency_s", 0.0),
                )
            )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run workflow benchmark with artifact verification.")
    parser.add_argument("--live", action="store_true", help="Run real workflows (default is dry-run skip mode).")
    parser.add_argument("--out-dir", default=str(REPO_ROOT / "generated_reports"))
    args = parser.parse_args()

    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    report = run_workflows_benchmark(live=bool(args.live))
    stamp = _utc_stamp()
    json_path = out_dir / f"chintu_workflows_benchmark_{stamp}.json"
    md_path = out_dir / f"chintu_workflows_benchmark_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    md_path.write_text(_render_md(report), encoding="utf-8")

    dashboard = build_weekly_dashboard(out_dir)
    print(
        json.dumps(
            {
                "ok": bool((report.get("summary") or {}).get("failed", 1) == 0),
                "json_report": str(json_path),
                "markdown_report": str(md_path),
                "dashboard_json": dashboard.get("json_path"),
                "dashboard_markdown": dashboard.get("md_path"),
                "summary": report.get("summary", {}),
            },
            ensure_ascii=True,
        )
    )
    return 0 if int((report.get("summary") or {}).get("failed", 1) or 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
