from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from chintu_backend.core.task_history import get_task_history_manager


def main() -> int:
    parser = argparse.ArgumentParser(description="Export Phase 5 training datasets from task dossiers.")
    parser.add_argument("--limit", type=int, default=500, help="Max dossiers to include in export.")
    parser.add_argument(
        "--reindex-runs",
        action="store_true",
        help="Rebuild dossiers from existing run events before export.",
    )
    args = parser.parse_args()

    manager = get_task_history_manager()
    if args.reindex_runs:
        reindex_report = manager.reindex_existing_runs(limit=0)
        print("Reindex:", json.dumps(reindex_report, indent=2))

    export = manager.export_training_bundle(limit=max(1, int(args.limit)))
    print("Export:", json.dumps(export, indent=2))

    manifest = Path(export.get("manifest_path") or "")
    if manifest.exists():
        print(f"Manifest written to: {manifest}")
        return 0
    print("Export failed: manifest not created.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
