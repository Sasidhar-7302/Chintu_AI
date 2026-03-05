"""Notion integration helpers (search).

CLI usage (via skill packs):
    python -m chintu_backend.integrations.notion "my query"

Environment:
    - NOTION_TOKEN
"""

from __future__ import annotations

import os
import sys
from typing import Any, Optional

import requests


NOTION_VERSION = "2022-06-28"


def search(query: str, token: str, *, page_size: int = 5, timeout_s: float = 12.0) -> str:
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {"query": query, "page_size": page_size}
    resp = requests.post(
        "https://api.notion.com/v1/search",
        headers=headers,
        json=payload,
        timeout=timeout_s,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Notion API error {resp.status_code}: {resp.text}")
    data = resp.json()
    results = data.get("results", [])
    if not results:
        return "No Notion results found."

    lines: list[str] = []
    for item in results:
        title = "Untitled"
        if item.get("object") == "page":
            props = item.get("properties", {})
            for prop in props.values():
                if prop.get("type") == "title" and prop.get("title"):
                    title = "".join(t.get("plain_text", "") for t in prop.get("title", [])) or title
                    break
        lines.append(f"- {title} ({item.get('id', '')})")
    return "Notion search results:\n" + "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        print("Usage: python -m chintu_backend.integrations.notion <query>")
        return 0
    query = " ".join(argv).strip()
    token = os.getenv("NOTION_TOKEN")
    if not token:
        print("Missing NOTION_TOKEN. Set it in .env to enable Notion search.")
        return 0
    try:
        print(search(query, token))
        return 0
    except Exception as exc:
        print(f"Notion search failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

