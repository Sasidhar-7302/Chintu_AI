"""CI quality gate runner for Chintu roadmap contracts."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
UI_ROOT = REPO_ROOT / "chintu_ui"
OUTPUT_DIR = REPO_ROOT / "generated_reports"


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _resolve_flutter_cmd() -> List[str]:
    if sys.platform.startswith("win"):
        return ["cmd", "/c", "flutter"]
    flutter_bin = shutil.which("flutter")
    if flutter_bin:
        return [flutter_bin]
    return ["flutter"]


def _run_command(
    *,
    cmd: Sequence[str],
    cwd: Path,
    name: str,
) -> Dict[str, Any]:
    proc = subprocess.run(
        list(cmd),
        cwd=str(cwd),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = str(proc.stdout or "")
    err = str(proc.stderr or "")
    tail = (out + ("\n" + err if err else "")).splitlines()[-30:]
    return {
        "name": name,
        "ok": int(proc.returncode) == 0,
        "returncode": int(proc.returncode),
        "command": " ".join(str(x) for x in cmd),
        "cwd": str(cwd),
        "output_tail": tail,
    }


def _run_flutter_command_with_retry(*, cmd: Sequence[str], cwd: Path, name: str) -> Dict[str, Any]:
    crash_codes = {3221226505, 3221225477, -1073740791, -1073741819}
    attempt = 0
    result: Dict[str, Any] = {}
    while True:
        attempt += 1
        result = _run_command(cmd=cmd, cwd=cwd, name=name)
        if bool(result.get("ok")):
            result["attempts"] = attempt
            return result
        code = int(result.get("returncode", 1) or 1)
        if attempt >= 2 or code not in crash_codes:
            result["attempts"] = attempt
            return result


def run_ci_quality_gate(*, run_flutter_tests: bool = True) -> Dict[str, Any]:
    steps: List[Dict[str, Any]] = []

    steps.append(
        _run_command(
            cmd=[sys.executable, "-m", "pytest", "-q", "tests/core"],
            cwd=REPO_ROOT,
            name="pytest_core",
        )
    )

    if run_flutter_tests:
        flutter = _resolve_flutter_cmd() + ["test", "--concurrency=1", "test/widget_test.dart"]
        steps.append(_run_flutter_command_with_retry(cmd=flutter, cwd=UI_ROOT, name="flutter_widget_tests"))
    else:
        steps.append(
            {
                "name": "flutter_widget_tests",
                "ok": True,
                "skipped": True,
                "returncode": 0,
                "command": "flutter test --concurrency=1 test/widget_test.dart",
                "cwd": str(UI_ROOT),
                "output_tail": ["skipped by flag"],
            }
        )

    steps.append(
        _run_command(
            cmd=[sys.executable, "-m", "chintu_backend.cli", "gates", "all", "--skip-flutter-tests"],
            cwd=REPO_ROOT,
            name="phase_gates_all",
        )
    )
    steps.append(
        _run_command(
            cmd=[sys.executable, "-m", "chintu_backend.cli", "gates", "preflight"],
            cwd=REPO_ROOT,
            name="deployment_preflight_gate",
        )
    )
    steps.append(
        _run_command(
            cmd=[sys.executable, "-m", "chintu_backend.cli", "gates", "release"],
            cwd=REPO_ROOT,
            name="release_readiness_gate",
        )
    )

    overall_ok = all(bool(step.get("ok")) for step in steps)
    return {
        "phase": "ci_quality_gate",
        "timestamp_utc": _utc_iso(),
        "overall_ok": overall_ok,
        "steps": steps,
    }


def _render_md(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# CI Quality Gate")
    lines.append("")
    lines.append(f"- Timestamp (UTC): `{report.get('timestamp_utc', '')}`")
    lines.append(f"- Overall pass: `{report.get('overall_ok')}`")
    lines.append("")
    for step in report.get("steps", []):
        lines.append(f"## {step.get('name', 'step')}")
        lines.append(f"- ok: `{step.get('ok')}`")
        lines.append(f"- returncode: `{step.get('returncode')}`")
        lines.append(f"- command: `{step.get('command', '')}`")
        if step.get("skipped"):
            lines.append("- skipped: `True`")
        tail = step.get("output_tail") if isinstance(step.get("output_tail"), list) else []
        if tail:
            lines.append("- output tail:")
            for row in tail:
                lines.append(f"  - {row}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run CI quality gate chain.")
    parser.add_argument("--skip-flutter-tests", action="store_true", help="Skip flutter widget tests")
    args = parser.parse_args()

    report = run_ci_quality_gate(run_flutter_tests=not bool(args.skip_flutter_tests))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _utc_stamp()
    json_path = OUTPUT_DIR / f"ci_quality_gate_{stamp}.json"
    md_path = OUTPUT_DIR / f"ci_quality_gate_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    md_path.write_text(_render_md(report), encoding="utf-8")
    print(f"Wrote: {json_path}")
    print(f"Wrote: {md_path}")
    return 0 if bool(report.get("overall_ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
