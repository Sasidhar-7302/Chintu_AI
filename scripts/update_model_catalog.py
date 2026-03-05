"""Refresh Chintu's local model/tool catalog snapshot."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from chintu_backend.core.model_catalog import get_model_catalog_updater


def main() -> int:
    parser = argparse.ArgumentParser(description="Update local model/tool catalog.")
    parser.add_argument(
        "--fetch-releases",
        action="store_true",
        help="Fetch release feeds (network).",
    )
    parser.add_argument(
        "--no-memory",
        action="store_true",
        help="Do not save summary note into memory store.",
    )
    args = parser.parse_args()

    updater = get_model_catalog_updater()
    snapshot = updater.refresh(fetch_releases=bool(args.fetch_releases), write_memory=not bool(args.no_memory))
    print(json.dumps(
        {
            "generated_at_utc": snapshot.get("generated_at_utc"),
            "catalog_path": snapshot.get("catalog_path"),
            "local_models": len(snapshot.get("local_models", []) or []),
            "release_updates": len(snapshot.get("release_updates", []) or []),
        },
        indent=2,
        ensure_ascii=True,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

