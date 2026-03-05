"""Minimal Jira Cloud client for task creation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests

from chintu_backend.core.config import get_config


@dataclass(frozen=True)
class JiraIssueResult:
    ok: bool
    key: str = ""
    url: str = ""
    error: str = ""


def _adf_paragraph(text: str) -> Dict[str, Any]:
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": str(text or "").strip()[:4000]}],
            }
        ],
    }


def get_jira_runtime_config() -> Tuple[bool, Dict[str, str], str]:
    cfg = get_config()
    base_url = str(getattr(cfg, "jira_base_url", "") or "").strip().rstrip("/")
    email = str(getattr(cfg, "jira_email", "") or "").strip()
    token = str(getattr(cfg, "jira_api_token", "") or "").strip()
    project_key = str(getattr(cfg, "jira_project_key", "") or "").strip()
    issue_type = str(getattr(cfg, "jira_issue_type", "Task") or "Task").strip() or "Task"
    if not base_url or not email or not token or not project_key:
        return (
            False,
            {},
            "Missing Jira configuration. Set CHINTU_JIRA_BASE_URL, CHINTU_JIRA_EMAIL, CHINTU_JIRA_API_TOKEN, CHINTU_JIRA_PROJECT_KEY.",
        )
    return (
        True,
        {
            "base_url": base_url,
            "email": email,
            "token": token,
            "project_key": project_key,
            "issue_type": issue_type,
        },
        "",
    )


def create_issue(
    *,
    summary: str,
    description: str,
    labels: Optional[List[str]] = None,
    issue_type: Optional[str] = None,
    timeout_seconds: int = 25,
) -> JiraIssueResult:
    ok, cfg, err = get_jira_runtime_config()
    if not ok:
        return JiraIssueResult(ok=False, error=err)

    payload = {
        "fields": {
            "project": {"key": cfg["project_key"]},
            "summary": str(summary or "").strip()[:255] or "Chintu Task",
            "description": _adf_paragraph(description or ""),
            "issuetype": {"name": str(issue_type or cfg["issue_type"] or "Task")},
        }
    }
    clean_labels = [str(x).strip() for x in (labels or []) if str(x).strip()]
    if clean_labels:
        payload["fields"]["labels"] = clean_labels[:10]

    try:
        resp = requests.post(
            f"{cfg['base_url']}/rest/api/3/issue",
            auth=(cfg["email"], cfg["token"]),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            json=payload,
            timeout=max(5, int(timeout_seconds)),
        )
    except Exception as exc:  # noqa: BLE001
        return JiraIssueResult(ok=False, error=f"Jira request failed: {exc}")

    if resp.status_code >= 300:
        msg = f"Jira API returned {resp.status_code}"
        try:
            detail = (resp.json() or {}).get("errorMessages") or ""
            if detail:
                msg = f"{msg}: {detail}"
        except Exception:
            pass
        return JiraIssueResult(ok=False, error=msg)

    data = resp.json() if resp.content else {}
    key = str(data.get("key") or "").strip()
    browse_url = f"{cfg['base_url']}/browse/{key}" if key else ""
    return JiraIssueResult(ok=True, key=key, url=browse_url)

