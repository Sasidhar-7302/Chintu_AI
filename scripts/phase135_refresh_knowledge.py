"""Run Phase 13.5 knowledge updater refresh and print a digest preview."""

from __future__ import annotations

import json
from pathlib import Path

from chintu_backend.brain.knowledge.knowledge_updater import get_knowledge_updater


def main() -> None:
    updater = get_knowledge_updater()
    refresh = updater.ingest_daily_updates(categories=["tech", "finance", "healthcare"], include_model_releases=True)
    digest = updater.build_daily_digest(total=20, categories=["tech", "finance", "healthcare"])

    out = Path("generated_reports") / "phase135_knowledge_refresh.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"refresh": refresh, "digest_preview": digest.get("items", [])[:10]}, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    print("Knowledge updater refresh complete.")
    print(f"- ingested_count: {refresh.get('ingested_count', 0)}")
    print(f"- digest_id: {digest.get('digest_id', '')}")
    print(f"- report: {out}")


if __name__ == "__main__":
    main()

