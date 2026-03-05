"""Generate llmfit-style local model-fit report for Chintu."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from chintu_backend.core.model_fit import collect_model_fit_snapshot, write_model_fit_reports


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Chintu model fit report.")
    parser.add_argument(
        "--out",
        default=str(REPO_ROOT / "generated_reports"),
        help="Output directory for JSON + Markdown reports.",
    )
    parser.add_argument(
        "--max-show-models",
        type=int,
        default=6,
        help="Maximum models to inspect with `ollama show`.",
    )
    args = parser.parse_args()

    snapshot = collect_model_fit_snapshot(max_show_models=max(1, int(args.max_show_models)))
    out_dir = Path(str(args.out))
    json_path, md_path = write_model_fit_reports(snapshot, out_dir)

    payload = {
        "ok": True,
        "json_report": str(json_path),
        "markdown_report": str(md_path),
        "mismatches": list(snapshot.get("fit", {}).get("mismatches", []) or []),
        "recommended": dict(snapshot.get("fit", {}).get("recommended", {}) or {}),
    }
    print(json.dumps(payload, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
