"""Record and optionally version-control code changes made by Chintu."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

from chintu_backend.core.config import get_config


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class ChangeRecord:
    request_id: str
    file_path: str
    issue: str
    applied: bool
    diff: str
    created_at: str
    commit_sha: str = ""


def record_change(request_id: str, file_path: str, issue: str, diff: str, applied: bool) -> Optional[Path]:
    config = get_config()
    if not getattr(config, "coding_agent_change_log_enabled", True):
        return None

    base_dir = Path(getattr(config, "coding_agent_change_log_dir", config.data_dir / "changes"))
    base_dir.mkdir(parents=True, exist_ok=True)

    slug = Path(file_path).name.replace(" ", "_")
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    patch_path = base_dir / f"{ts}_{slug}.patch"
    meta_path = base_dir / f"{ts}_{slug}.json"

    patch_path.write_text(diff or "", encoding="utf-8")
    record = ChangeRecord(
        request_id=request_id,
        file_path=file_path,
        issue=issue or "",
        applied=applied,
        diff=diff or "",
        created_at=_utc_now(),
    )
    meta_path.write_text(json.dumps(record.__dict__, indent=2), encoding="utf-8")
    return patch_path


def list_changes(limit: int = 50) -> list[dict]:
    config = get_config()
    base_dir = Path(getattr(config, "coding_agent_change_log_dir", config.data_dir / "changes"))
    if not base_dir.exists():
        return []
    entries = []
    for meta in sorted(base_dir.glob("*.json"), reverse=True):
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
            data["id"] = meta.stem
            entries.append(data)
        except Exception:
            continue
    return entries[:limit]


def commit_change(change_id: str, message: Optional[str] = None) -> Tuple[bool, str]:
    config = get_config()
    base_dir = Path(getattr(config, "coding_agent_change_log_dir", config.data_dir / "changes"))
    meta_path = base_dir / f"{change_id}.json"
    if not meta_path.exists():
        return False, "change record not found"
    record = json.loads(meta_path.read_text(encoding="utf-8"))
    file_path = record.get("file_path")
    if not file_path:
        return False, "missing file path"
    commit_msg = message or f"chintu: {Path(file_path).name} update"
    committed, info = maybe_git_commit(file_path, commit_msg)
    if committed:
        record["commit_sha"] = info
        meta_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return committed, info


def rollback_change(change_id: str) -> Tuple[bool, str]:
    config = get_config()
    base_dir = Path(getattr(config, "coding_agent_change_log_dir", config.data_dir / "changes"))
    meta_path = base_dir / f"{change_id}.json"
    patch_path = base_dir / f"{change_id}.patch"
    if not meta_path.exists() or not patch_path.exists():
        return False, "change record not found"
    try:
        result = subprocess.run(
            ["git", "apply", "-R", str(patch_path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return False, (result.stderr or "git apply failed").strip()
    except Exception as exc:
        return False, f"rollback failed: {exc}"
    return True, "rollback applied"


def maybe_git_commit(file_path: str, message: str) -> Tuple[bool, str]:
    config = get_config()
    if not getattr(config, "coding_agent_auto_commit", False):
        return False, "auto-commit disabled"

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0 or "true" not in (result.stdout or "").lower():
            return False, "not a git repository"
    except Exception as exc:
        return False, f"git unavailable: {exc}"

    try:
        subprocess.run(["git", "add", file_path], check=False, timeout=5)
        commit = subprocess.run(
            ["git", "commit", "-m", message],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if commit.returncode != 0:
            stderr = (commit.stderr or "").strip()
            return False, stderr or "git commit failed"
        sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5)
        return True, (sha.stdout or "").strip()
    except Exception as exc:
        return False, f"git commit failed: {exc}"
