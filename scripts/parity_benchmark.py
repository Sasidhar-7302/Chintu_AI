"""
Capability parity benchmark (Chintu-only).

Goal:
- Use a reference coding tool profile (fs/runtime/sessions/web/memory/image).
- Give Chintu equivalent tasks and verify completion with deterministic evidence.

This is intentionally non-destructive:
- all file writes/moves happen inside a sandbox directory under generated_reports/
- no deletions
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


def _utc_now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


@dataclass
class BenchCase:
    name: str
    text: str
    expected_capability: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)
    auto_confirm: bool = False
    timeout_s: float = 120.0
    verify: Optional[Callable[[Dict[str, Any]], Tuple[bool, str]]] = None


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def _read_text(path_str: str) -> str:
    try:
        p = Path(path_str)
        if p.exists():
            return p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        pass
    return ""


def _wait_for_terminal_or_pending(run_mgr: Any, run_id: str, timeout_s: float) -> Dict[str, Any]:
    deadline = time.monotonic() + max(5.0, float(timeout_s or 0.0))
    last: Dict[str, Any] = {}
    while time.monotonic() < deadline:
        snap = run_mgr.snapshot(limit=200)
        runs = snap.get("runs") if isinstance(snap, dict) else None
        if isinstance(runs, list):
            for r in runs:
                if isinstance(r, dict) and r.get("id") == run_id:
                    last = dict(r)
                    status = str(r.get("status") or "")
                    if status in {
                        "completed",
                        "failed",
                        "cancelled",
                        "timed_out",
                        "waiting_approval",
                        "waiting_input",
                    }:
                        return last
        time.sleep(0.2)
    return last


def _make_sandbox(root: Path) -> Path:
    sandbox = root / "bench_sandbox"
    sandbox.mkdir(parents=True, exist_ok=True)
    # Seed for list/read tests
    seed = sandbox / "seed.txt"
    if not seed.exists():
        seed.write_text("seed", encoding="utf-8", errors="ignore")
    return sandbox


def _contains_link(text: str) -> bool:
    lowered = (text or "").lower()
    return ("http://" in lowered) or ("https://" in lowered) or ("[source]" in lowered)


def _verify_web_fetch_example(result: Dict[str, Any]) -> Tuple[bool, str]:
    preview = str(result.get("response_preview") or "").lower()
    if "x.com" in preview or "twitter.com" in preview or "opening x " in preview:
        return False, "response routed to x/twitter instead of example.com"
    if "example.com" in preview or "example domain" in preview:
        return True, "response references example.com"
    return False, "missing explicit example.com evidence"


def _coerce_pass_rate(summary: Dict[str, Any]) -> float:
    try:
        if "pass_rate" in summary and summary.get("pass_rate") is not None:
            return float(summary.get("pass_rate") or 0.0)
        passed = float(summary.get("passed") or summary.get("pass") or 0.0)
        total = float(summary.get("total") or 0.0)
        return (passed / total) if total > 0 else 0.0
    except Exception:
        return 0.0


def _extract_baseline_summary(payload: Dict[str, Any]) -> Dict[str, Any]:
    summary = payload.get("summary") if isinstance(payload, dict) else {}
    if isinstance(summary, dict) and summary:
        return dict(summary)
    # fallback shape
    results = payload.get("results") if isinstance(payload, dict) else []
    if isinstance(results, list):
        total = len(results)
        passed = sum(
            1
            for row in results
            if str(row.get("verdict") or row.get("status") or "").upper() in {"PASS", "COMPLETED"}
            or bool(row.get("ok"))
        )
        return {"total": total, "passed": passed, "pass_rate": (passed / total) if total else 0.0}
    return {"total": 0, "passed": 0, "pass_rate": 0.0}


def _build_case_compare(chintu_results: List[Dict[str, Any]], baseline_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    baseline_results = baseline_payload.get("results") if isinstance(baseline_payload, dict) else []
    if not isinstance(baseline_results, list):
        return []
    base_map: Dict[str, Dict[str, Any]] = {}
    for row in baseline_results:
        if not isinstance(row, dict):
            continue
        key = str(row.get("case") or row.get("name") or row.get("task") or "").strip().lower()
        if key:
            base_map[key] = row
    rows: List[Dict[str, Any]] = []
    for row in chintu_results:
        key = str(row.get("case") or "").strip().lower()
        if not key:
            continue
        base = base_map.get(key)
        if not base:
            continue
        chintu_ok = bool(row.get("ok"))
        baseline_ok = bool(base.get("ok")) or str(base.get("verdict") or base.get("status") or "").upper() in {"PASS", "COMPLETED"}
        rows.append(
            {
                "case": row.get("case"),
                "chintu_ok": chintu_ok,
                "baseline_ok": baseline_ok,
                "delta": int(chintu_ok) - int(baseline_ok),
            }
        )
    return rows


def run_parity_benchmark(
    out_dir: Path,
    mode: str = "safe",
    allow_live_browser: bool = False,
    baseline_report: Optional[Dict[str, Any]] = None,
    baseline_label: str = "reference",
) -> Dict[str, Any]:
    from chintu_backend.core.command_handler import CommandHandler
    from chintu_backend.core.run_manager import get_run_manager

    run_mgr = get_run_manager()
    handler = CommandHandler(mock_mode=(mode == "dry_run"))

    stamp = _utc_now_stamp()
    run_root = out_dir / f"parity_benchmark_{stamp}"
    sandbox = _make_sandbox(run_root)

    file_path = sandbox / "hello_parity.txt"
    file_content = "Hello from Chintu (parity suite)."

    def _verify_written_file(_r: Dict[str, Any]) -> Tuple[bool, str]:
        p = Path(str(file_path))
        if not p.exists():
            return False, f"missing file: {p}"
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:
            return False, f"read failed: {exc}"
        if txt != file_content:
            return False, "content mismatch"
        return True, "file exists and content matches"

    cases: List[BenchCase] = [
        # fs (write/read/list)
        BenchCase(
            name="fs_write_file",
            text=f"Write file {file_path} with content: {file_content}",
            expected_capability="write_file",
            context={"_extracted_params": {"path": str(file_path), "content": file_content}},
            verify=_verify_written_file,
            timeout_s=60.0,
        ),
        BenchCase(
            name="fs_read_file",
            text=f"Read file {file_path}",
            expected_capability="read_file",
            context={"_extracted_params": {"filename": str(file_path)}},
            verify=lambda r: (file_content in (r.get("response_preview") or ""), "response contains written content"),
            timeout_s=60.0,
        ),
        BenchCase(
            name="fs_list_files",
            text=f"List files in {sandbox}",
            expected_capability="list_files",
            context={"_extracted_params": {"directory": str(sandbox)}},
            verify=lambda r: (
                ("seed.txt" in (r.get("response_preview") or ""))
                and ("hello_parity.txt" in (r.get("response_preview") or "")),
                "response contains expected filenames",
            ),
            timeout_s=60.0,
        ),
        # runtime (exec with approvals)
        BenchCase(
            name="runtime_terminal_exec",
            text='Run command: python -c "print(6*7)"',
            expected_capability="terminal_exec",
            context={"_extracted_params": {"command": 'python -c "print(6*7)"', "cwd": str(sandbox)}},
            auto_confirm=True,
            verify=lambda r: ("42" in (r.get("response_preview") or ""), "output contains 42"),
            timeout_s=120.0,
        ),
        # web (search/fetch)
        BenchCase(
            name="web_search",
            text="Search for coding tools list",
            expected_capability="web_search",
            verify=lambda r: (_contains_link(r.get("response_preview") or ""), "response includes a link/source"),
            timeout_s=120.0,
        ),
        # memory
        BenchCase(
            name="memory_write",
            text="Remember my dog's name is Buddy",
            expected_capability="remember_fact",
            timeout_s=60.0,
        ),
        BenchCase(
            name="memory_read",
            text="What is my dog's name?",
            expected_capability="recall_facts",
            verify=lambda r: ("buddy" in (r.get("response_preview") or "").lower(), "response contains Buddy"),
            timeout_s=60.0,
        ),
        # image
        BenchCase(
            name="image_screenshot",
            text="Take a screenshot",
            expected_capability="screenshot",
            timeout_s=120.0,
            verify=lambda r: (True, "verified by core path_exists check if present"),
        ),
    ]

    if allow_live_browser:
        cases.insert(
            5,
            BenchCase(
                name="web_fetch",
                text="Read http://example.com",
                expected_capability="open_url",
                verify=_verify_web_fetch_example,
                timeout_s=120.0,
            ),
        )

    results: List[Dict[str, Any]] = []
    session_id = f"parity_benchmark:{stamp}"
    started = time.perf_counter()

    for case in cases:
        ctx: Dict[str, Any] = {"session_id": session_id, "workspace_dir": str(_REPO_ROOT)}
        ctx["_keep_extracted_params"] = True
        ctx.update(case.context or {})

        t0 = time.perf_counter()
        response = handler.handle(case.text, source="benchmark", context=ctx)
        latency_s = time.perf_counter() - t0

        run_id = str(ctx.get("_run_id") or "").strip()
        run_summary: Dict[str, Any] = {}
        receipt_path = ""

        if run_id:
            run_summary = _wait_for_terminal_or_pending(run_mgr, run_id, timeout_s=case.timeout_s)
            receipt_path = str(run_summary.get("receipt_path") or "").strip()

        if case.auto_confirm and run_id:
            status = str(run_summary.get("status") or "")
            if status == "waiting_approval":
                confirm_ctx = {"session_id": session_id, "workspace_dir": str(_REPO_ROOT)}
                confirm_response = handler.handle("yes", source="benchmark", context=confirm_ctx)
                if confirm_response:
                    response = (response or "") + "\n" + str(confirm_response)
                run_summary = _wait_for_terminal_or_pending(run_mgr, run_id, timeout_s=case.timeout_s)
                receipt_path = str(run_summary.get("receipt_path") or "").strip()

        last_capability = ""
        try:
            last_capability = str(handler.state_manager.state.last_capability or "")
        except Exception:
            last_capability = ""

        status = str(run_summary.get("status") or "")
        ok = bool(run_id) and status == "completed"
        if case.expected_capability and case.expected_capability != last_capability:
            ok = False

        verify_ok = None
        verify_detail = ""
        if case.verify:
            try:
                verify_ok, verify_detail = case.verify(
                    {
                        "case": case.name,
                        "response_preview": (response or "")[:2000],
                        "run_id": run_id,
                        "status": status,
                        "receipt_path": receipt_path,
                    }
                )
                ok = ok and bool(verify_ok)
            except Exception as exc:
                verify_ok = False
                verify_detail = f"verify exception: {exc}"
                ok = False

        results.append(
            {
                "case": case.name,
                "text": case.text,
                "expected_capability": case.expected_capability,
                "actual_capability": last_capability,
                "run_id": run_id,
                "status": status,
                "latency_s": round(latency_s, 3),
                "receipt_path": receipt_path,
                "verify_ok": verify_ok,
                "verify_detail": verify_detail,
                "ok": bool(ok),
                "response_preview": (response or "")[:500],
            }
        )

    elapsed_s = time.perf_counter() - started
    passed = sum(1 for r in results if r.get("ok"))
    total = len(results)
    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "mode": mode,
        "session_id": session_id,
        "sandbox_dir": str(sandbox),
        "summary": {
            "total": total,
            "passed": passed,
            "pass_rate": round((passed / total) if total else 0.0, 3),
            "elapsed_s": round(elapsed_s, 2),
            "avg_latency_s": round(sum(float(r.get("latency_s") or 0.0) for r in results) / total, 3) if total else 0.0,
        },
        "browser_actions_enabled": bool(allow_live_browser),
        "results": results,
        "reference_profile": {
            "docs": [
                "https://docs.example.com/tools",
                "https://docs.example.com/exec-approvals",
            ],
            "profile": "coding",
            "tool_groups": ["fs", "runtime", "sessions", "web", "browser", "memory", "image"],
        },
    }
    if isinstance(baseline_report, dict) and baseline_report:
        base_summary = _extract_baseline_summary(baseline_report)
        chintu_summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
        base_pass_rate = _coerce_pass_rate(base_summary)
        chintu_pass_rate = _coerce_pass_rate(chintu_summary)
        case_compare = _build_case_compare(results, baseline_report)
        report["baseline_compare"] = {
            "label": str(baseline_label or "reference"),
            "baseline_summary": base_summary,
            "chintu_summary": chintu_summary,
            "pass_rate_delta": round(chintu_pass_rate - base_pass_rate, 3),
            "case_compare": case_compare,
        }
    return report


def _render_md(report: Dict[str, Any]) -> str:
    summary = report.get("summary") if isinstance(report, dict) else {}
    results = report.get("results") if isinstance(report, dict) else []
    ref = report.get("reference_profile") if isinstance(report, dict) else {}

    lines: List[str] = []
    lines.append("# Capability Parity Benchmark (Chintu)")
    lines.append("")
    lines.append(f"- timestamp_utc: {report.get('timestamp_utc', '')}")
    lines.append(f"- mode: {report.get('mode', '')}")
    lines.append(f"- browser_actions_enabled: {report.get('browser_actions_enabled', False)}")
    lines.append(f"- session_id: {report.get('session_id', '')}")
    lines.append(f"- sandbox_dir: {report.get('sandbox_dir', '')}")
    if isinstance(ref, dict):
        lines.append(f"- reference_profile: {ref.get('profile', '')}")
        lines.append(f"- reference_tool_groups: {', '.join(ref.get('tool_groups') or [])}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- total: {summary.get('total')}")
    lines.append(f"- passed: {summary.get('passed')}")
    lines.append(f"- pass_rate: {summary.get('pass_rate')}")
    lines.append(f"- elapsed_s: {summary.get('elapsed_s')}")
    lines.append(f"- avg_latency_s: {summary.get('avg_latency_s')}")
    lines.append("")
    lines.append("## Results")
    lines.append("")
    lines.append("| Case | Status | Expected | Actual | Verify | Latency(s) | Run | |")
    lines.append("|---|---|---|---|---|---:|---|---|")
    if isinstance(results, list):
        for r in results:
            if not isinstance(r, dict):
                continue
            ok = "PASS" if r.get("ok") else "FAIL"
            verify = r.get("verify_ok")
            lines.append(
                "| {case} | {ok} ({status}) | {exp} | {act} | {verify} | {lat} | {run_id} |".format(
                    case=str(r.get("case") or ""),
                    ok=ok,
                    status=str(r.get("status") or ""),
                    exp=str(r.get("expected_capability") or ""),
                    act=str(r.get("actual_capability") or ""),
                    verify=str(verify),
                    lat=str(r.get("latency_s") or ""),
                    run_id=str(r.get("run_id") or ""),
                )
            )
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- This suite is intentionally non-destructive and writes only under the sandbox directory.")
    lines.append("- Each request produces a run receipt under `~/.chintu/runs/<run_id>/receipt.md`.")
    base = report.get("baseline_compare") if isinstance(report, dict) else None
    if isinstance(base, dict):
        lines.append(f"- Baseline comparison enabled: {base.get('label')}")
    lines.append("")
    if isinstance(base, dict):
        lines.append("## Baseline Compare")
        lines.append("")
        lines.append(f"- baseline_label: {base.get('label')}")
        lines.append(f"- pass_rate_delta: {base.get('pass_rate_delta')}")
        lines.append("")
        rows = base.get("case_compare") if isinstance(base.get("case_compare"), list) else []
        if rows:
            lines.append("| Case | Chintu | Baseline | Delta |")
            lines.append("|---|---|---|---:|")
            for row in rows:
                if not isinstance(row, dict):
                    continue
                lines.append(
                    "| {case} | {ch} | {ba} | {de} |".format(
                        case=str(row.get("case") or ""),
                        ch="PASS" if row.get("chintu_ok") else "FAIL",
                        ba="PASS" if row.get("baseline_ok") else "FAIL",
                        de=int(row.get("delta") or 0),
                    )
                )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run capability parity benchmark suite against Chintu.")
    parser.add_argument("--mode", choices=["safe", "dry_run"], default="safe")
    parser.add_argument("--out-dir", default="generated_reports")
    parser.add_argument(
        "--allow-live-browser",
        action="store_true",
        help="Include web_fetch benchmark that can open a real browser tab (disabled by default).",
    )
    parser.add_argument(
        "--baseline-json",
        default="",
        help="Optional baseline report JSON (e.g., external framework run) for side-by-side compare.",
    )
    parser.add_argument(
        "--baseline-label",
        default="reference",
        help="Label used in output when baseline-json is supplied.",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir).expanduser().resolve()
    stamp = _utc_now_stamp()

    baseline_payload: Optional[Dict[str, Any]] = None
    baseline_json = str(args.baseline_json or "").strip()
    if baseline_json:
        baseline_path = Path(baseline_json).expanduser().resolve()
        if baseline_path.exists():
            try:
                baseline_payload = json.loads(baseline_path.read_text(encoding="utf-8", errors="ignore"))
            except Exception as exc:
                print(f"Warning: failed to read baseline JSON ({baseline_path}): {exc}")

    report = run_parity_benchmark(
        out_dir=out_dir,
        mode=args.mode,
        allow_live_browser=bool(args.allow_live_browser),
        baseline_report=baseline_payload,
        baseline_label=str(args.baseline_label or "reference"),
    )
    json_path = out_dir / f"parity_benchmark_{stamp}.json"
    md_path = out_dir / f"parity_benchmark_{stamp}.md"
    _write_json(json_path, report)
    md_path.write_text(_render_md(report), encoding="utf-8")
    print(f"Wrote: {json_path}")
    print(f"Wrote: {md_path}")
    print(f"pass_rate: {report.get('summary', {}).get('pass_rate')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
