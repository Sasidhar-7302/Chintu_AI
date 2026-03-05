"""Deterministic finance read-only workflow pack executor."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run(portfolio_name: str, output_root: Path) -> dict:
    safe_name = "".join(ch for ch in (portfolio_name or "default_portfolio") if ch.isalnum() or ch in ("-", "_", " ")).strip()
    safe_name = safe_name or "default_portfolio"
    run_dir = output_root / safe_name.replace(" ", "_")
    run_dir.mkdir(parents=True, exist_ok=True)

    summary_path = run_dir / "finance_summary.md"
    checklist_path = run_dir / "manual_checklist.md"

    summary_path.write_text(
        "\n".join(
            [
                f"# Finance Read-Only Summary: {safe_name}",
                "",
                "- Scope: read-only analysis (no trades, no payments).",
                "- Position concentration check: pending operator input.",
                "- Risk note: rebalance only via manual broker actions.",
                "",
                "## Suggested Review",
                "1. Confirm allocation drift from target.",
                "2. Review downside protection plan.",
                "3. Validate liquidity needs for next 90 days.",
            ]
        ),
        encoding="utf-8",
    )
    checklist_path.write_text(
        "\n".join(
            [
                f"# Manual Execution Checklist: {safe_name}",
                "",
                "- [ ] Verify current holdings from broker statement",
                "- [ ] Confirm no unauthorized orders",
                "- [ ] Apply manual rebalance if needed",
                "- [ ] Record evidence receipt in finance log",
            ]
        ),
        encoding="utf-8",
    )

    return {
        "pack": "finance_readonly",
        "portfolio_name": safe_name,
        "timestamp_utc": _utc_now(),
        "output_dir": str(run_dir),
        "artifacts": [str(summary_path), str(checklist_path)],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Finance read-only workflow pack.")
    parser.add_argument("--portfolio", default="core_portfolio")
    parser.add_argument("--out", default="generated_reports/workflow_packs/finance_readonly")
    args = parser.parse_args()

    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    report = run(args.portfolio, out_root)
    print(json.dumps(report, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

