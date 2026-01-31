"""Notion skill CLI (search)."""
from __future__ import annotations

import json
import os
import sys
from typing import Any

import requests

NOTION_VERSION = "2022-06-28"


def _search(query: str, token: str) -> str:
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {"query": query, "page_size": 5}
    resp = requests.post("https://api.notion.com/v1/search", headers=headers, json=payload, timeout=12)
    if resp.status_code >= 400:
        raise RuntimeError(f"Notion API error {resp.status_code}: {resp.text}")
    data = resp.json()
    results = data.get("results", [])
    if not results:
        return "No Notion results found."
    lines = []
    for item in results:
        title = "Untitled"
        if item.get("object") == "page":
            props = item.get("properties", {})
            # Try common title property
            for prop in props.values():
                if prop.get("type") == "title" and prop.get("title"):
                    title = "".join(t.get("plain_text", "") for t in prop.get("title", [])) or title
                    break
        lines.append(f"- {title} ({item.get('id', '')})")
    return "Notion search results:
" + "
".join(lines)


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python -m chintu_backend.skills.tools.notion <query>")
        return 0
    query = " ".join(sys.argv[1:]).strip()
    token = os.getenv("NOTION_TOKEN")
    if not token:
        print("Missing NOTION_TOKEN. Set it in .env to enable Notion search.")
        return 0
    try:
        print(_search(query, token))
        return 0
    except Exception as exc:
        print(f"Notion search failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
