"""Deterministic Research+Decision workflow pack executor."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run(topic: str, output_root: Path) -> dict:
    safe_topic = (topic or "general_topic").strip().replace("/", "_").replace("\\", "_")
    topic_key = "".join(ch for ch in safe_topic if ch.isalnum() or ch in ("-", "_", " ")).strip() or "general_topic"
    run_dir = output_root / topic_key.replace(" ", "_")
    run_dir.mkdir(parents=True, exist_ok=True)

    research_path = run_dir / "research.md"
    decision_path = run_dir / "decision.md"
    followup_path = run_dir / "followup_plan.md"

    research_path.write_text(
        "\n".join(
            [
                f"# Research Brief: {topic_key}",
                "",
                "## Inputs",
                "- Source set A (local notes)",
                "- Source set B (recent telemetry)",
                "",
                "## Synthesis",
                "- Key trend 1",
                "- Key trend 2",
                "- Risk signal",
            ]
        ),
        encoding="utf-8",
    )
    decision_path.write_text(
        "\n".join(
            [
                f"# Decision Memo: {topic_key}",
                "",
                "Recommendation: proceed with pilot scope.",
                "",
                "Pros:",
                "- Fast validation cycle",
                "- Low dependency risk",
                "",
                "Cons:",
                "- Requires weekly operator review",
            ]
        ),
        encoding="utf-8",
    )
    followup_path.write_text(
        "\n".join(
            [
                f"# Follow-up Plan: {topic_key}",
                "",
                "1. Define pilot success criteria",
                "2. Run benchmark pack for one week",
                "3. Review evidence artifacts and decide rollout",
            ]
        ),
        encoding="utf-8",
    )

    return {
        "pack": "research_decision",
        "topic": topic_key,
        "timestamp_utc": _utc_now(),
        "output_dir": str(run_dir),
        "artifacts": [str(research_path), str(decision_path), str(followup_path)],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Research+Decision workflow pack.")
    parser.add_argument("--topic", default="local-first autonomy roadmap")
    parser.add_argument("--out", default="generated_reports/workflow_packs/research_decision")
    args = parser.parse_args()

    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    report = run(args.topic, out_root)
    print(json.dumps(report, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

