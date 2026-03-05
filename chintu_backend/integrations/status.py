"""Integration status snapshots for UI dashboards and diagnostics."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

from chintu_backend.core.config import get_config
from chintu_backend.integrations.google_calendar import HAS_GOOGLE_API, GoogleCalendar, get_calendar
from chintu_backend.integrations.integration_store import load_integrations


def _mask_email(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if "@" not in raw:
        return raw[:1] + "***" if len(raw) > 1 else "***"
    local, domain = raw.split("@", 1)
    local = local.strip()
    domain = domain.strip()
    if not local:
        return f"***@{domain}" if domain else "***"
    if len(local) <= 2:
        masked_local = local[:1] + "*"
    else:
        masked_local = local[:1] + ("*" * (len(local) - 2)) + local[-1]
    return f"{masked_local}@{domain}"


def _calendar_token_valid(calendar: GoogleCalendar) -> bool:
    """Best-effort token validity check without refreshing."""
    if not HAS_GOOGLE_API:
        return False
    try:
        token_path = Path(str(calendar.token_path or "")).expanduser()
        if token_path.exists():
            from google.oauth2.credentials import Credentials

            creds = Credentials.from_authorized_user_file(
                str(token_path),
                list(getattr(calendar, "scopes", []) or []),
            )
            return bool(creds and creds.valid)
        return bool(calendar.is_authenticated)
    except Exception:
        return False


def get_integrations_snapshot() -> Dict[str, Any]:
    config = get_config()
    store = load_integrations()
    calendar_store = store.get("google_calendar") if isinstance(store, dict) else {}
    if not isinstance(calendar_store, dict):
        calendar_store = {}

    # Google Calendar
    cal = get_calendar()
    credentials_path = Path(str(getattr(cal, "credentials_path", "")) or "").expanduser()
    token_path = Path(str(getattr(cal, "token_path", "")) or "").expanduser()
    calendar_snapshot = {
        "available": bool(HAS_GOOGLE_API),
        "configured": bool(HAS_GOOGLE_API and credentials_path.exists()),
        "credentials_path": str(credentials_path) if str(credentials_path) else "",
        "token_present": bool(HAS_GOOGLE_API and token_path.exists()),
        "token_path": str(token_path) if str(token_path) else "",
        "token_valid": _calendar_token_valid(cal),
        "scopes": [str(x) for x in (calendar_store.get("scopes") or getattr(cal, "scopes", [])) if str(x)],
        "write_access": bool(calendar_store.get("write_access", False)),
        "connected_at": str(calendar_store.get("connected_at") or ""),
        "token_in_vault": bool(calendar_store.get("token_in_vault", False)),
    }

    # Email (IMAP)
    host = str(getattr(config, "email_imap_host", "") or "").strip()
    user = str(getattr(config, "email_imap_user", "") or "").strip()
    password = str(getattr(config, "email_imap_password", "") or "").strip()
    folder = str(getattr(config, "email_imap_folder", "INBOX") or "INBOX").strip() or "INBOX"
    try:
        port = int(getattr(config, "email_imap_port", 993) or 993)
    except Exception:
        port = 993

    email_snapshot = {
        "enabled": bool(getattr(config, "email_reader_enabled", True)),
        "configured": bool(host and user and password),
        "host": host,
        "port": port,
        "user_masked": _mask_email(user),
        "folder": folder,
        "password_set": bool(password),
    }

    # Jira
    jira_base = str(getattr(config, "jira_base_url", "") or "").strip().rstrip("/")
    jira_email = str(getattr(config, "jira_email", "") or "").strip()
    jira_project = str(getattr(config, "jira_project_key", "") or "").strip()
    jira_issue_type = str(getattr(config, "jira_issue_type", "Task") or "Task").strip() or "Task"
    jira_token = str(getattr(config, "jira_api_token", "") or "").strip()
    jira_snapshot = {
        "enabled": bool(getattr(config, "jira_enabled", True)),
        "configured": bool(jira_base and jira_email and jira_project and jira_token),
        "base_url": jira_base,
        "email_masked": _mask_email(jira_email),
        "project_key": jira_project,
        "issue_type": jira_issue_type,
        "api_token_set": bool(jira_token),
    }

    # Provider keys (bools only)
    providers = {
        "ollama": {
            "host": str(getattr(config, "ollama_host", "") or ""),
            "model": str(getattr(config, "ollama_model", "") or ""),
        },
        "nvidia": {"api_key_set": bool(str(getattr(config, "nvidia_api_key", "") or "").strip())},
        "groq": {"api_key_set": bool(str(getattr(config, "groq_api_key", "") or "").strip())},
        "gemini": {"api_key_set": bool(str(getattr(config, "google_ai_key", "") or "").strip())},
        "deepseek": {"api_key_set": bool(str(getattr(config, "deepseek_api_key", "") or "").strip())},
    }

    return {
        "google_calendar": calendar_snapshot,
        "email_imap": email_snapshot,
        "jira": jira_snapshot,
        "providers": providers,
    }


def apply_env_from_integrations_file(path: Optional[Path] = None) -> None:
    """Load non-secret integration settings into env vars (best-effort).

    Used at startup so pydantic settings can pick them up.
    """
    from chintu_backend.integrations.integration_store import (
        load_integrations,
        get_email_imap_config,
        get_jira_config,
    )

    data = load_integrations(path)
    email_cfg = get_email_imap_config(data) if isinstance(data, dict) else None
    jira_cfg = get_jira_config(data) if isinstance(data, dict) else None
    if email_cfg:
        os.environ.setdefault("CHINTU_EMAIL_IMAP_HOST", str(email_cfg.host))
        os.environ.setdefault("CHINTU_EMAIL_IMAP_PORT", str(int(email_cfg.port)))
        if email_cfg.user:
            os.environ.setdefault("CHINTU_EMAIL_IMAP_USER", str(email_cfg.user))
        if email_cfg.folder:
            os.environ.setdefault("CHINTU_EMAIL_IMAP_FOLDER", str(email_cfg.folder))
    if jira_cfg:
        os.environ.setdefault("CHINTU_JIRA_BASE_URL", str(jira_cfg.base_url))
        os.environ.setdefault("CHINTU_JIRA_EMAIL", str(jira_cfg.email))
        os.environ.setdefault("CHINTU_JIRA_PROJECT_KEY", str(jira_cfg.project_key))
        os.environ.setdefault("CHINTU_JIRA_ISSUE_TYPE", str(jira_cfg.issue_type))
