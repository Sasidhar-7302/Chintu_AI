"""Deterministic Build-an-App workflow pack executor."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run(project: str, output_root: Path) -> dict:
    safe_project = "".join(ch for ch in project if ch.isalnum() or ch in ("-", "_")).strip() or "sample_app"
    root = output_root / safe_project
    root.mkdir(parents=True, exist_ok=True)

    prd_path = root / "PRD.md"
    arch_path = root / "ARCHITECTURE.md"
    tasks_path = root / "MILESTONES.md"

    prd_path.write_text(
        "\n".join(
            [
                f"# {safe_project} Product Requirements",
                "",
                "- Problem statement:",
                "- Target users:",
                "- Core features:",
                "- Success metrics:",
            ]
        ),
        encoding="utf-8",
    )
    arch_path.write_text(
        "\n".join(
            [
                f"# {safe_project} Architecture",
                "",
                "- Runtime: local-first single-process",
                "- Planner/Executor/Verifier loop",
                "- Evidence receipt contract",
                "- Risk gates and approvals",
            ]
        ),
        encoding="utf-8",
    )
    tasks_path.write_text(
        "\n".join(
            [
                f"# {safe_project} Milestones",
                "",
                "1. Scaffold project and baseline tests",
                "2. Implement core APIs and persistence",
                "3. Integrate UI and operator controls",
                "4. Run E2E + performance + chaos checks",
            ]
        ),
        encoding="utf-8",
    )

    report = {
        "pack": "build_app",
        "project": safe_project,
        "timestamp_utc": _utc_now(),
        "output_dir": str(root),
        "artifacts": [str(prd_path), str(arch_path), str(tasks_path)],
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Build-an-App workflow pack.")
    parser.add_argument("--project", default="sample_app")
    parser.add_argument("--out", default="generated_reports/workflow_packs/build_app")
    args = parser.parse_args()

    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    report = run(args.project, out_root)
    print(json.dumps(report, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

