"""Generate Phase 9 monthly governance review artifact."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from chintu_backend.core.config import get_config
from chintu_backend.reporting.governance import BenchmarkGovernance


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate monthly governance review from Phase 9 history.")
    parser.add_argument("--month", default="", help="Month in YYYY-MM format. Defaults to current UTC month.")
    args = parser.parse_args()

    cfg = get_config()
    governance = BenchmarkGovernance(config=cfg)
    result = governance.generate_monthly_review(month=args.month or None)
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0 if bool(result.get("success")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
