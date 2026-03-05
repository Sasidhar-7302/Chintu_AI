"""Phase 4.5 replay harness for idea-to-project build execution."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from chintu_backend.automation.content_studio import execute_app_builder_build, generate_app_builder_docs


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_stamp() -> str:
    return _utc_now().strftime("%Y%m%d_%H%M%S")


def run_replay(out_dir: Path, idea: str) -> Dict[str, Any]:
    docs = generate_app_builder_docs(idea=idea, output_dir=out_dir / "phase45_projects", context={})
    project_dir = Path(docs["dir"])

    command_log: List[Dict[str, Any]] = []

    def fake_runner(command, cwd, timeout_seconds):
        row = {
            "command": list(command),
            "cwd": str(cwd),
            "timeout_seconds": int(timeout_seconds),
            "return_code": 0,
            "stdout_preview": "ok",
            "stderr_preview": "",
        }
        command_log.append(row)
        return row

    build = execute_app_builder_build(
        project_dir,
        install_deps=True,
        run_tests=True,
        runner=fake_runner,
    )
    checkpoints = build.get("checkpoints") if isinstance(build.get("checkpoints"), list) else []
    passed = sum(1 for row in checkpoints if str(row.get("status")) == "passed")
    total = len(checkpoints)
    pass_gate = bool(build.get("success")) and total > 0 and passed == total
    return {
        "timestamp_utc": _utc_now().isoformat().replace("+00:00", "Z"),
        "idea": idea,
        "project_dir": str(project_dir),
        "artifacts": docs,
        "build": build,
        "summary": {
            "checkpoints_total": total,
            "checkpoints_passed": passed,
            "pass_gate": pass_gate,
        },
        "command_log_count": len(command_log),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay Phase 4.5 project builder workflow.")
    parser.add_argument("--out-dir", default="generated_reports")
    parser.add_argument("--idea", default="AI-first personal finance copilot")
    args = parser.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    report = run_replay(out_dir, args.idea)
    out_path = out_dir / f"phase45_project_builder_replay_{_utc_stamp()}.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    print(f"Wrote: {out_path}")
    print(json.dumps(report["summary"], indent=2))
    return 0 if bool(report["summary"]["pass_gate"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())

