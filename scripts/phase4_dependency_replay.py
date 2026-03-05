"""Phase 4 replay harness for missing-dependency recovery."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from chintu_backend.core.dependency_bootstrap import DependencyBootstrapAgent, EnvironmentSnapshot


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_stamp() -> str:
    return _utc_now().strftime("%Y%m%d_%H%M%S")


def run_replay(out_dir: Path) -> Dict[str, Any]:
    receipts_dir = out_dir / "phase4_dependency_receipts"
    cfg = SimpleNamespace(
        dependency_bootstrap_receipts_dir=receipts_dir,
        dependency_bootstrap_allow_global_installs=True,
        dependency_bootstrap_prefer_user_installs=True,
    )

    command_log: List[Dict[str, Any]] = []

    def runner(command, cwd, timeout_seconds):
        entry = {
            "command": list(command),
            "cwd": str(cwd),
            "timeout_seconds": int(timeout_seconds),
            "return_code": 0,
        }
        command_log.append(entry)
        return 0, "ok", ""

    agent = DependencyBootstrapAgent(config=cfg, runner=runner)
    env = EnvironmentSnapshot(
        python_executable=str(Path(sys.executable).resolve()),
        in_venv=False,
        venv_path="",
        cwd=str(REPO_ROOT),
        binaries={
            "python": str(Path(sys.executable).resolve()),
            "npm": "npm",
            "cargo": "cargo",
            "winget": "winget",
        },
    )

    replay_cases = [
        "ModuleNotFoundError: No module named 'pandas'",
        "ModuleNotFoundError: No module named 'yaml'",
        "ModuleNotFoundError: No module named 'PIL'",
        "ImportError: No module named 'bs4'",
        "ModuleNotFoundError: No module named 'numpy'",
        "ModuleNotFoundError: No module named 'sklearn'",
        "ModuleNotFoundError: No module named 'dotenv'",
        "ModuleNotFoundError: No module named 'requests'",
        "ModuleNotFoundError: No module named 'pytest'",
        "ModuleNotFoundError: No module named 'fastapi'",
    ]

    rows: List[Dict[str, Any]] = []
    recovered = 0
    for message in replay_cases:
        plan = agent.plan_from_failure(message, context={"capability_name": "replay_case"}, environment=env)
        if not plan:
            rows.append({"message": message, "planned": False, "recovered": False})
            continue
        result = agent.execute_plan(plan, environment=env, context={"capability_name": "replay_case"})
        ok = bool(result.success)
        if ok:
            recovered += 1
        rows.append(
            {
                "message": message,
                "planned": True,
                "dependency_name": plan.dependency_name,
                "requires_confirmation": bool(plan.requires_confirmation),
                "recovered": ok,
                "receipt_path": result.receipt_path,
            }
        )

    total = len(replay_cases)
    recovery_rate = (recovered / total) if total else 0.0
    return {
        "timestamp_utc": _utc_now().isoformat().replace("+00:00", "Z"),
        "total_cases": total,
        "recovered_cases": recovered,
        "recovery_rate": round(recovery_rate, 3),
        "pass_gate": recovery_rate >= 0.90,
        "cases": rows,
        "command_log_count": len(command_log),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay missing-dependency failures for Phase 4 gate.")
    parser.add_argument("--out-dir", default="generated_reports")
    args = parser.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    report = run_replay(out_dir)
    out_path = out_dir / f"phase4_dependency_replay_{_utc_stamp()}.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    print(f"Wrote: {out_path}")
    print(json.dumps({"recovery_rate": report["recovery_rate"], "pass_gate": report["pass_gate"]}, indent=2))
    return 0 if bool(report["pass_gate"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())

