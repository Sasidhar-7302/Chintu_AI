"""Persist non-secret integration settings under ~/.chintu.

Secrets (passwords/API keys) must go into IdentityVault; this store only keeps
non-sensitive configuration like hosts and usernames so integrations survive
restarts without committing secrets to the repo.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def _default_store_path() -> Path:
    return Path.home() / ".chintu" / "integrations.json"


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def load_integrations(path: Optional[Path] = None) -> Dict[str, Any]:
    p = Path(path) if path else _default_store_path()
    if not p.exists():
        return {}
    try:
        raw = p.read_text(encoding="utf-8")
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load integrations store (%s): %s", p, exc)
        return {}


def save_integrations(data: Dict[str, Any], path: Optional[Path] = None) -> Tuple[bool, str]:
    p = Path(path) if path else _default_store_path()
    try:
        _atomic_write_json(p, data or {})
        return True, f"Saved integrations config to {p}"
    except Exception as exc:  # noqa: BLE001
        return False, f"Failed to save integrations config: {exc}"


@dataclass(frozen=True)
class EmailImapConfig:
    host: str
    port: int = 993
    user: str = ""
    folder: str = "INBOX"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "host": self.host,
            "port": int(self.port),
            "user": self.user,
            "folder": self.folder,
        }


@dataclass(frozen=True)
class JiraConfig:
    base_url: str
    email: str
    project_key: str
    issue_type: str = "Task"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "base_url": self.base_url,
            "email": self.email,
            "project_key": self.project_key,
            "issue_type": self.issue_type or "Task",
        }


def get_email_imap_config(data: Dict[str, Any]) -> Optional[EmailImapConfig]:
    raw = data.get("email_imap")
    if not isinstance(raw, dict):
        return None
    host = str(raw.get("host") or "").strip()
    if not host:
        return None
    try:
        port = int(raw.get("port") or 993)
    except Exception:
        port = 993
    user = str(raw.get("user") or "").strip()
    folder = str(raw.get("folder") or "INBOX").strip() or "INBOX"
    return EmailImapConfig(host=host, port=port, user=user, folder=folder)


def upsert_email_imap_config(
    config: EmailImapConfig,
    *,
    path: Optional[Path] = None,
) -> Tuple[bool, str]:
    data = load_integrations(path)
    data["email_imap"] = config.to_dict()
    return save_integrations(data, path)


def get_jira_config(data: Dict[str, Any]) -> Optional[JiraConfig]:
    raw = data.get("jira")
    if not isinstance(raw, dict):
        return None
    base_url = str(raw.get("base_url") or "").strip().rstrip("/")
    email = str(raw.get("email") or "").strip()
    project_key = str(raw.get("project_key") or "").strip()
    issue_type = str(raw.get("issue_type") or "Task").strip() or "Task"
    if not base_url or not email or not project_key:
        return None
    return JiraConfig(
        base_url=base_url,
        email=email,
        project_key=project_key,
        issue_type=issue_type,
    )


def upsert_jira_config(
    config: JiraConfig,
    *,
    path: Optional[Path] = None,
) -> Tuple[bool, str]:
    data = load_integrations(path)
    data["jira"] = config.to_dict()
    return save_integrations(data, path)
