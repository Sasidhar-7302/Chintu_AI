"""Generate Phase 13 dashboard projects (reliability, content, finance)."""

from __future__ import annotations

import json
from pathlib import Path

from chintu_backend.reporting.dashboard_studio import get_dashboard_studio


def _ensure_sample_finance_csv(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(
            "symbol,market_value,pnl\nBTC,12000,850\nETH,6000,220\nNVDA,4500,410\n",
            encoding="utf-8",
        )
    return path


def main() -> None:
    studio = get_dashboard_studio()
    finance_csv = _ensure_sample_finance_csv(Path("generated_reports") / "sample_portfolio.csv")

    results = [
        studio.build_dashboard("reliability", name="Chintu Reliability Dashboard").to_dict(),
        studio.build_dashboard("content", name="Chintu Content Pipeline Dashboard").to_dict(),
        studio.build_dashboard("finance", name="Chintu Portfolio Dashboard", finance_csv_path=finance_csv).to_dict(),
    ]
    out = Path("generated_reports") / "phase13_dashboards.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"dashboards": results}, indent=2, ensure_ascii=True), encoding="utf-8")
    print(f"Generated {len(results)} dashboard projects.")
    print(f"Report: {out}")
    for row in results:
        print(f"- {row['kind']}: {row['project_dir']}")


if __name__ == "__main__":
    main()

