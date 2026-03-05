"""Phase 9 continuous benchmarking and governance gate."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from chintu_backend.core.config import get_config
from chintu_backend.reporting.governance import BenchmarkGovernance


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _run_script(path: Path) -> dict:
    command = [sys.executable, str(path)]
    proc = subprocess.run(command, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=1800, check=False)
    return {
        "command": command,
        "return_code": int(proc.returncode),
        "stdout_preview": (proc.stdout or "")[-2000:],
        "stderr_preview": (proc.stderr or "")[-2000:],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Phase 9 governance gate.")
    parser.add_argument("--out-dir", default="generated_reports", help="Directory to write gate report.")
    parser.add_argument(
        "--run-nightly-benchmarks",
        action="store_true",
        help="Run 9-task and 50-task benchmarks before evaluating governance gate.",
    )
    parser.add_argument(
        "--emit-monthly-review",
        action="store_true",
        help="Generate monthly governance review markdown after gate run.",
    )
    args = parser.parse_args()

    command_log = []
    if args.run_nightly_benchmarks:
        nightly_scripts = [
            REPO_ROOT / "scripts" / "validate_9_tasks.py",
            REPO_ROOT / "scripts" / "chintu_50_realistic_benchmark.py",
            REPO_ROOT / "scripts" / "phase8_security_doctor.py",
            REPO_ROOT / "scripts" / "phase85_social_replay.py",
        ]
        for script_path in nightly_scripts:
            if not script_path.exists():
                command_log.append(
                    {
                        "command": [sys.executable, str(script_path)],
                        "return_code": 127,
                        "stderr_preview": "missing script",
                        "stdout_preview": "",
                    }
                )
                continue
            command_log.append(_run_script(script_path))

    cfg = get_config()
    governance_enabled = bool(getattr(cfg, "phase9_governance_enabled", True))
    gate = None
    if governance_enabled:
        governance = BenchmarkGovernance(config=cfg)
        gate = governance.run_gate()

    monthly_review = None
    if args.emit_monthly_review and governance_enabled:
        monthly_review = governance.generate_monthly_review()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"phase9_governance_gate_{_stamp()}.json"
    payload = {
        "phase": "phase9",
        "timestamp_utc": (gate or {}).get("timestamp_utc"),
        "governance_enabled": governance_enabled,
        "governance": gate or {},
        "nightly_commands": command_log,
        "monthly_review": monthly_review or {},
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    summary = {
        "ok": bool((gate or {}).get("summary", {}).get("ok", governance_enabled is False)),
        "critical_alerts": int((gate or {}).get("summary", {}).get("critical_alerts", 0)),
        "warning_alerts": int((gate or {}).get("summary", {}).get("warning_alerts", 0)),
        "aggregate_pass_rate": (gate or {}).get("summary", {}).get("aggregate_pass_rate", 0.0),
        "governance_enabled": governance_enabled,
    }
    print(f"Wrote: {out_path}")
    print(json.dumps(summary, indent=2, ensure_ascii=True))

    if not governance_enabled:
        return 0

    fail_on_critical = bool(getattr(cfg, "phase9_fail_on_critical_alerts", True))
    if fail_on_critical and summary["critical_alerts"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
