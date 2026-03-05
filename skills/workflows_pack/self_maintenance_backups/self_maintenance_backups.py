from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from chintu_backend.core.config import get_config
from chintu_backend.core.scheduler import get_scheduler


EXCLUDE_DIR_NAMES = {
    "backups",
    "repo_index",
    "airllm_cache",
    "models",
    "__pycache__",
    ".pytest_cache",
    ".tmp",
}
MAX_FILE_BYTES = 100 * 1024 * 1024


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _collect_targets() -> List[Path]:
    cfg = get_config()
    targets = [Path(cfg.data_dir)]
    markdown_dir = Path(getattr(cfg, "memory_markdown_dir", cfg.data_dir / "brain_md"))
    if markdown_dir not in targets:
        targets.append(markdown_dir)
    existing: List[Path] = []
    for target in targets:
        if target.exists():
            existing.append(target)
    return existing


def _zip_targets(output_zip: Path, targets: List[Path]) -> Dict[str, Any]:
    files_added = 0
    files_skipped = 0
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for target in targets:
            for item in target.rglob("*"):
                if not item.is_file():
                    continue
                if any(part in EXCLUDE_DIR_NAMES for part in item.parts):
                    files_skipped += 1
                    continue
                if item.resolve() == output_zip.resolve():
                    continue
                try:
                    if int(item.stat().st_size) > MAX_FILE_BYTES:
                        files_skipped += 1
                        continue
                except Exception:
                    files_skipped += 1
                    continue
                arcname = f"{target.name}/{item.relative_to(target).as_posix()}"
                zf.write(item, arcname=arcname)
                files_added += 1
    size_bytes = int(output_zip.stat().st_size) if output_zip.exists() else 0
    return {"files_added": files_added, "files_skipped": files_skipped, "size_bytes": size_bytes}


def _apply_retention(backup_dir: Path, keep_latest: int = 4) -> List[str]:
    quarantine = Path.home() / ".chintu" / "verify_delete" / "backups"
    quarantine.mkdir(parents=True, exist_ok=True)
    archives = sorted(backup_dir.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    moved: List[str] = []
    for old in archives[keep_latest:]:
        destination = quarantine / old.name
        if destination.exists():
            destination = quarantine / f"{old.stem}_{_safe_stamp()}{old.suffix}"
        old.replace(destination)
        moved.append(str(destination))
    return moved


def ensure_weekly_schedule() -> Dict[str, Any]:
    scheduler = get_scheduler()
    workflow_text = "run self maintenance backups"
    for task in scheduler.list_tasks():
        if str(getattr(task, "workflow", "")).strip().lower() == workflow_text:
            return {"scheduled": True, "created": False, "task_id": str(getattr(task, "id", ""))}
    task = scheduler.schedule(
        name="Self-maintenance backups",
        workflow=workflow_text,
        schedule_type="weekly",
        schedule_time="03:00",
        schedule_day="sunday",
    )
    return {"scheduled": True, "created": True, "task_id": str(task.id)}


def run(request_text: str) -> Dict[str, Any]:
    cfg = get_config()
    backup_dir = Path(cfg.data_dir) / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    low = str(request_text or "").lower()
    wants_schedule = any(token in low for token in ["set up", "setup", "schedule", "weekly"])
    run_now = "schedule only" not in low

    result: Dict[str, Any] = {
        "workflow": "self_maintenance_backups",
        "requested_schedule": bool(wants_schedule),
        "requested_run_now": bool(run_now),
        "timestamp_utc": _utc_now(),
    }
    if wants_schedule:
        result["schedule"] = ensure_weekly_schedule()

    if run_now:
        archive_path = backup_dir / f"chintu_backup_{_safe_stamp()}.zip"
        targets = _collect_targets()
        zip_stats = _zip_targets(archive_path, targets)
        moved = _apply_retention(backup_dir, keep_latest=4)

        report_path = backup_dir / f"backup_report_{_safe_stamp()}.md"
        lines = [
            "# Self-maintenance Backup Report",
            "",
            f"- Timestamp UTC: {_utc_now()}",
            f"- Archive: {archive_path}",
            f"- Files added: {zip_stats.get('files_added', 0)}",
            f"- Files skipped by policy: {zip_stats.get('files_skipped', 0)}",
            f"- Archive size: {zip_stats.get('size_bytes', 0)} bytes",
            "",
            "## Targets",
        ]
        for target in targets:
            lines.append(f"- {target}")
        lines.append("")
        lines.append("## Retention / Quarantine Moves")
        if moved:
            for path in moved:
                lines.append(f"- Moved old backup to: {path}")
        else:
            lines.append("- No old backups moved.")
        lines.append("")
        report_path.write_text("\n".join(lines), encoding="utf-8")

        result.update(
            {
                "archive_path": str(archive_path),
                "report_path": str(report_path),
                "targets": [str(path) for path in targets],
                "retention_quarantined": moved,
                "files_added": int(zip_stats.get("files_added", 0)),
                "files_skipped": int(zip_stats.get("files_skipped", 0)),
            }
        )

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Self-maintenance backup workflow.")
    parser.add_argument("--request", default="")
    args = parser.parse_args()
    print(json.dumps(run(args.request), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
