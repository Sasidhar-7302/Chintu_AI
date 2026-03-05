"""Phase 18 UI vNext gate: validates operator UI contracts and widget tests."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


REPO_ROOT = Path(__file__).resolve().parents[1]
UI_ROOT = REPO_ROOT / "chintu_ui"
OUTPUT_DIR = REPO_ROOT / "generated_reports"


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _check_dashboard_tabs() -> Dict[str, Any]:
    path = UI_ROOT / "lib" / "widgets" / "dashboard_panel.dart"
    if not path.exists():
        return {"ok": False, "error": f"missing_file:{path}"}
    text = path.read_text(encoding="utf-8", errors="ignore")
    required = ["Tab(text: 'Models')", "Tab(text: 'Identity')", "_modelsTab(", "_identityTab("]
    missing = [token for token in required if token not in text]
    return {"ok": len(missing) == 0, "missing_tokens": missing}


def _check_ws_test_mode() -> Dict[str, Any]:
    path = UI_ROOT / "lib" / "services" / "websocket_service.dart"
    if not path.exists():
        return {"ok": False, "error": f"missing_file:{path}"}
    text = path.read_text(encoding="utf-8", errors="ignore")
    required = ["WebSocketService({bool autoConnect = true})", "if (autoConnect) {", "connect();"]
    missing = [token for token in required if token not in text]
    return {"ok": len(missing) == 0, "missing_tokens": missing}


def _run_flutter_widget_tests() -> Dict[str, Any]:
    if not UI_ROOT.exists():
        return {"ok": False, "error": f"missing_ui_root:{UI_ROOT}"}

    if sys.platform.startswith("win"):
        cmd = ["cmd", "/c", "flutter", "test", "--concurrency=1", "test/widget_test.dart"]
    else:
        flutter_bin = shutil.which("flutter")
        cmd = [flutter_bin, "test", "--concurrency=1", "test/widget_test.dart"] if flutter_bin else [
            "flutter",
            "test",
            "--concurrency=1",
            "test/widget_test.dart",
        ]

    crash_codes = {3221226505, 3221225477, -1073740791, -1073741819}
    attempt = 0
    proc = None
    while True:
        attempt += 1
        proc = subprocess.run(
            cmd,
            cwd=str(UI_ROOT),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if int(proc.returncode) == 0:
            break
        if attempt >= 2 or int(proc.returncode) not in crash_codes:
            break

    stdout = str(proc.stdout or "").strip()
    stderr = str(proc.stderr or "").strip()
    ok = int(proc.returncode) == 0
    tail_lines = (stdout + ("\n" + stderr if stderr else "")).splitlines()[-20:]
    return {
        "ok": ok,
        "command": " ".join(cmd),
        "attempts": attempt,
        "returncode": int(proc.returncode),
        "output_tail": tail_lines,
    }


def run_phase18_gate(*, run_flutter_tests: bool = True) -> Dict[str, Any]:
    tabs = _check_dashboard_tabs()
    ws_test_mode = _check_ws_test_mode()
    flutter = (
        _run_flutter_widget_tests()
        if run_flutter_tests
        else {
            "ok": True,
            "skipped": True,
            "command": "flutter test test/widget_test.dart",
            "reason": "skipped by flag",
            "output_tail": [],
        }
    )

    gates = {
        "dashboard_models_identity_tabs": bool(tabs.get("ok")),
        "websocket_test_mode": bool(ws_test_mode.get("ok")),
        "flutter_widget_tests": bool(flutter.get("ok")),
    }
    overall_ok = all(bool(v) for v in gates.values())
    return {
        "phase": "phase18",
        "timestamp_utc": _utc_iso(),
        "gates": gates,
        "overall_ok": overall_ok,
        "checks": {
            "dashboard_tabs": tabs,
            "ws_test_mode": ws_test_mode,
            "flutter": flutter,
        },
    }


def _render_md(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# Phase 18 UI vNext Gate")
    lines.append("")
    lines.append(f"- Timestamp (UTC): `{report.get('timestamp_utc', '')}`")
    lines.append(f"- Overall gate pass: `{report.get('overall_ok')}`")
    lines.append("")
    lines.append("## Gate Summary")
    for key, value in (report.get("gates") or {}).items():
        lines.append(f"- {key}: `{value}`")
    lines.append("")
    checks = report.get("checks") if isinstance(report, dict) else {}
    flutter = (checks or {}).get("flutter") if isinstance(checks, dict) else {}
    if isinstance(flutter, dict):
        lines.append("## Flutter Widget Test")
        lines.append(f"- command: `{flutter.get('command', '')}`")
        lines.append(f"- returncode: `{flutter.get('returncode', '')}`")
        if flutter.get("skipped"):
            lines.append("- skipped: `True`")
        tail = flutter.get("output_tail") if isinstance(flutter.get("output_tail"), list) else []
        if tail:
            lines.append("- output tail:")
            for row in tail:
                lines.append(f"  - {row}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Phase 18 UI vNext gate.")
    parser.add_argument("--skip-flutter-tests", action="store_true", help="Skip flutter widget test execution.")
    args = parser.parse_args()

    report = run_phase18_gate(run_flutter_tests=not bool(args.skip_flutter_tests))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _utc_stamp()
    json_path = OUTPUT_DIR / f"phase18_ui_vnext_gate_{stamp}.json"
    md_path = OUTPUT_DIR / f"phase18_ui_vnext_gate_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    md_path.write_text(_render_md(report), encoding="utf-8")
    print(f"Wrote: {json_path}")
    print(f"Wrote: {md_path}")
    return 0 if bool(report.get("overall_ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
