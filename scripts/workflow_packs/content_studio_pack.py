"""Deterministic content-studio workflow pack executor."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_token(value: str, fallback: str) -> str:
    token = "".join(ch for ch in (value or "") if ch.isalnum() or ch in ("-", "_", " ")).strip()
    return token or fallback


def run(topic: str, platform: str, output_root: Path) -> dict:
    safe_topic = _safe_token(topic, "content_topic")
    safe_platform = _safe_token(platform, "youtube")
    run_dir = output_root / safe_topic.replace(" ", "_")
    run_dir.mkdir(parents=True, exist_ok=True)

    script_path = run_dir / "script.md"
    captions_path = run_dir / "captions.txt"
    thumbnail_path = run_dir / "thumbnail_brief.md"
    staging_path = run_dir / "staging_checklist.md"

    script_path.write_text(
        "\n".join(
            [
                f"# {safe_platform.title()} Script: {safe_topic}",
                "",
                "Hook:",
                "- Open with the core problem in one sentence.",
                "",
                "Body:",
                "1. Explain why the problem matters now.",
                "2. Show one tactical framework.",
                "3. Give one concrete action the audience can take today.",
                "",
                "Close:",
                "- Summarize in one line and ask for one measurable follow-up.",
            ]
        ),
        encoding="utf-8",
    )
    captions_path.write_text(
        "\n".join(
            [
                f"{safe_topic} explained in 60 seconds.",
                "Actionable playbook, no fluff.",
                "Comment with your biggest blocker and I will break it down.",
            ]
        ),
        encoding="utf-8",
    )
    thumbnail_path.write_text(
        "\n".join(
            [
                f"# Thumbnail Brief ({safe_platform})",
                "",
                f"- Primary text: {safe_topic.upper()}",
                "- Contrast: dark background + teal accent stroke",
                "- Visual cue: one focused subject with directional arrow to outcome metric",
                "- Keep copy <= 4 words",
            ]
        ),
        encoding="utf-8",
    )
    staging_path.write_text(
        "\n".join(
            [
                f"# Staging Checklist ({safe_platform})",
                "",
                "- [ ] Script reviewed for claims and sourcing",
                "- [ ] Captions reviewed for length and clarity",
                "- [ ] Thumbnail brief validated with style guide",
                "- [ ] Final publish action remains approval-gated",
            ]
        ),
        encoding="utf-8",
    )

    return {
        "pack": "content_studio",
        "topic": safe_topic,
        "platform": safe_platform,
        "timestamp_utc": _utc_now(),
        "output_dir": str(run_dir),
        "artifacts": [str(script_path), str(captions_path), str(thumbnail_path), str(staging_path)],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Content Studio workflow pack.")
    parser.add_argument("--topic", default="local-first autonomous cofounder")
    parser.add_argument("--platform", default="youtube")
    parser.add_argument("--out", default="generated_reports/workflow_packs/content_studio")
    args = parser.parse_args()

    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    report = run(args.topic, args.platform, out_root)
    print(json.dumps(report, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

