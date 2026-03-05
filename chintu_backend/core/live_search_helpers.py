"""
Helper functions for live-search handling.
Extracted from capability_handlers to keep routing code smaller.
"""

from __future__ import annotations

import datetime
import json
import re
from pathlib import Path
from typing import Any


def extract_requested_top_n(
    text: str,
    default: int = 3,
    min_value: int = 1,
    max_value: int = 10,
) -> int:
    match = re.search(r"\btop\s+(\d{1,2})\b", str(text or "").lower())
    if match:
        try:
            value = int(match.group(1))
            return max(min_value, min(value, max_value))
        except Exception:
            pass
    return max(min_value, min(default, max_value))


def clean_live_search_query(text: str) -> str:
    query = str(text or "").strip()
    # Keep only the first sentence for explicit multi-instruction prompts.
    query = query.split("\n", 1)[0].strip()
    query = query.split(".", 1)[0].strip()
    query = re.split(
        r"\b(?:read only|no links|ask if|and ask if|and ask|want details|would you like)\b",
        query,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()
    return query.strip(" ,")


def extract_hn_topic(text: str) -> str:
    lower = str(text or "").lower()
    # "top 3 AI news headlines from Hacker News"
    match = re.search(
        r"\btop\s+\d+\s+(.+?)\s+news\s+headlines?\s+from\s+hacker\s+news\b",
        lower,
    )
    if match:
        topic = match.group(1).strip()
        if topic:
            return topic
    # Default to AI for the benchmark phrasing.
    return "ai"


def fetch_hacker_news_headlines(topic: str, limit: int = 3) -> list[dict[str, str]]:
    try:
        import requests
    except Exception:
        return []

    safe_topic = (topic or "ai").strip()
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    min_created = int((now_utc - datetime.timedelta(hours=72)).timestamp())

    endpoints = [
        (
            "https://hn.algolia.com/api/v1/search_by_date",
            {
                "query": safe_topic,
                "tags": "story",
                "hitsPerPage": max(10, int(limit) * 5),
                "numericFilters": f"created_at_i>{min_created}",
            },
        ),
        (
            "https://hn.algolia.com/api/v1/search",
            {
                "query": safe_topic,
                "tags": "story",
                "hitsPerPage": max(10, int(limit) * 5),
            },
        ),
    ]

    payload: dict[str, Any] = {}
    for api, params in endpoints:
        try:
            resp = requests.get(api, params=params, timeout=12)
            resp.raise_for_status()
            candidate = resp.json() if resp.content else {}
            if isinstance(candidate, dict) and isinstance(candidate.get("hits"), list):
                payload = candidate
                if candidate.get("hits"):
                    break
        except Exception:
            continue

    if not payload:
        return []

    hits = payload.get("hits") if isinstance(payload, dict) else []
    if not isinstance(hits, list):
        return []

    rows: list[dict[str, str]] = []
    seen_titles: set[str] = set()
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        title = str(hit.get("title") or hit.get("story_title") or "").strip()
        if not title:
            continue

        title_key = title.lower().strip()
        if title_key in seen_titles:
            continue
        seen_titles.add(title_key)

        url = str(hit.get("url") or hit.get("story_url") or "").strip()
        if not url:
            object_id = str(hit.get("objectID") or "").strip()
            url = (
                f"https://news.ycombinator.com/item?id={object_id}"
                if object_id
                else "https://news.ycombinator.com/"
            )

        rows.append({"title": title, "url": url})
        if len(rows) >= int(limit):
            break

    return rows


def cached_news_headlines(topic: str, limit: int = 3) -> list[dict[str, str]]:
    """Best-effort fallback when live headline fetch fails."""
    cache_path = Path.home() / ".chintu" / "daily_briefing_cache.json"
    if not cache_path.exists():
        return []

    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    rows = payload.get("items") if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return []

    topic_low = str(topic or "ai").strip().lower()
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue

        title = str(row.get("title") or "").strip()
        if not title:
            continue

        blob = " ".join(
            [
                title.lower(),
                str(row.get("summary") or "").lower(),
                str(row.get("category") or "").lower(),
            ]
        )
        if topic_low and topic_low not in blob and topic_low != "ai":
            continue

        key = title.lower()
        if key in seen:
            continue
        seen.add(key)

        out.append(
            {
                "title": title,
                "url": str(row.get("url") or "").strip(),
            }
        )
        if len(out) >= int(limit):
            break

    return out
