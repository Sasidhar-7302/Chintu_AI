from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from chintu_backend.core.config import get_config


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run() -> Dict[str, Any]:
    cfg = get_config()
    vault_dir = Path(getattr(cfg, "memory_markdown_dir", cfg.data_dir / "brain_md"))
    vault_dir.mkdir(parents=True, exist_ok=True)

    out_dir = Path(getattr(cfg, "workflows_dir", cfg.data_dir / "workflows")) / "vault_sync"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"

    result: Dict[str, Any] = {
        "workflow": "sync_vault_now",
        "vault_dir": str(vault_dir),
        "timestamp_utc": _utc_now(),
    }

    try:
        from chintu_backend.brain.memory.markdown_sync import MarkdownMemorySync
        from chintu_backend.core.memory import MemoryManager

        manager = MemoryManager()
        sync = MarkdownMemorySync(manager)
        stats = sync.sync_once()
        result["sync_stats"] = stats
        lines = [
            "# Vault Sync Report",
            "",
            f"- Vault dir: {vault_dir}",
            f"- Synced files: {int(stats.get('synced', 0))}",
            f"- Skipped files: {int(stats.get('skipped', 0))}",
            f"- Generated UTC: {_utc_now()}",
            "",
        ]
    except Exception as exc:
        result["error"] = str(exc)
        lines = [
            "# Vault Sync Report",
            "",
            f"- Vault dir: {vault_dir}",
            f"- Sync failed: {exc}",
            f"- Generated UTC: {_utc_now()}",
            "",
        ]

    out_path.write_text("\n".join(lines), encoding="utf-8")
    result["report_path"] = str(out_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run markdown vault sync once.")
    parser.parse_args()
    print(json.dumps(run(), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
