"""Helper utilities for morning briefing generation and feedback learning."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from chintu_backend.core.config import get_config


def fetch_hn_top_stories(limit: int = 10) -> List[Dict[str, str]]:
    """Fetch Hacker News top stories (no API key)."""
    import requests

    limit = max(1, min(int(limit), 15))
    base = "https://hacker-news.firebaseio.com/v0"
    ids_resp = requests.get(f"{base}/topstories.json", timeout=10)
    ids_resp.raise_for_status()
    ids = ids_resp.json() or []

    stories: List[Dict[str, str]] = []
    for item_id in ids[:limit]:
        try:
            item_resp = requests.get(f"{base}/item/{int(item_id)}.json", timeout=10)
            item_resp.raise_for_status()
            item = item_resp.json() or {}
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            url = str(item.get("url") or "").strip() or f"https://news.ycombinator.com/item?id={int(item_id)}"
            stories.append({"title": title, "url": url})
        except Exception:
            continue

    return stories


def normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").strip().lower())


def allocate_category_counts(weights: Dict[str, float], total: int, min_per: int = 3) -> Dict[str, int]:
    if not weights:
        return {}
    total = max(int(total), len(weights))
    safe_weights = {k: max(float(v), 0.0) for k, v in weights.items()}
    weight_sum = sum(safe_weights.values()) or float(len(safe_weights))
    counts = {k: max(min_per, int(round((safe_weights[k] / weight_sum) * total))) for k in safe_weights}

    current = sum(counts.values())
    keys = list(counts.keys())
    idx = 0
    while current != total and keys:
        key = keys[idx % len(keys)]
        if current > total and counts[key] > min_per:
            counts[key] -= 1
            current -= 1
        elif current < total:
            counts[key] += 1
            current += 1
        idx += 1
        if idx > 500:
            break
    return counts


def build_news_queries(category: str) -> List[str]:
    base = category.replace("_", " ").strip()
    return [
        f"latest {base} innovations",
        f"{base} breakthroughs today",
        f"{base} major update",
        f"{base} news today",
    ]


def fetch_category_headlines(engine, category: str, target: int) -> List[Dict[str, str]]:
    from chintu_backend.search.news_quality import rank_news_results

    items: List[Dict[str, str]] = []
    seen = set()
    cfg = get_config()
    max_age_hours = int(getattr(cfg, "knowledge_news_max_age_hours", 48) or 48)
    min_reliability = float(getattr(cfg, "knowledge_news_min_reliability", 0.58) or 0.58)
    fallback_min_reliability = float(getattr(cfg, "knowledge_news_fallback_min_reliability", 0.35) or 0.35)
    extra_trusted_domains = list(getattr(cfg, "knowledge_news_extra_trusted_domains", []) or [])
    for query in build_news_queries(category):
        rows = engine.search_news(query, max_results=max(10, target * 3), timelimit="d")
        ranked = rank_news_results(
            rows,
            category=category,
            limit=max(6, target * 2),
            max_age_hours=max_age_hours,
            min_reliability=min_reliability,
            fallback_min_reliability=fallback_min_reliability,
            extra_trusted_domains=extra_trusted_domains,
        )
        for row in ranked:
            title = str(row.get("title") or "").strip()
            if not title:
                continue
            key = normalize_title(title)
            if key in seen:
                continue
            seen.add(key)
            items.append(
                {
                    "title": title,
                    "url": str(row.get("url") or "").strip(),
                    "category": category,
                    "source": str(row.get("source") or "").strip(),
                    "freshness_label": str(row.get("freshness_label") or "").strip(),
                }
            )
            if len(items) >= target:
                break
        if len(items) >= target:
            break
    return items


def fetch_daily_headlines(categories: List[str], weights: Dict[str, float], total: int) -> List[Dict[str, str]]:
    from chintu_backend.search.web_search import get_search_engine

    engine = get_search_engine()
    if not engine.is_available:
        return []

    counts = allocate_category_counts(weights, total, min_per=3)
    headlines: List[Dict[str, str]] = []
    seen = set()

    for category in categories:
        target = counts.get(category, max(3, total // max(len(categories), 1)))
        category_items = fetch_category_headlines(engine, category, target)
        for item in category_items:
            key = normalize_title(item.get("title", ""))
            if key in seen:
                continue
            seen.add(key)
            headlines.append(item)

    if len(headlines) < total:
        fallback_items = fetch_category_headlines(engine, "technology", total - len(headlines))
        for item in fallback_items:
            key = normalize_title(item.get("title", ""))
            if key in seen:
                continue
            seen.add(key)
            headlines.append(item)

    return headlines[:total]


def nudge_news_category_weight(category: str, delta: float = 0.15) -> None:
    try:
        from chintu_backend.brain.memory.preferences import get_preference_manager

        pref_manager = get_preference_manager()
        weights = dict(getattr(pref_manager.preferences, "news_category_weights", {}) or {})
        cat = str(category or "").strip().lower()
        if not cat:
            return
        current = float(weights.get(cat, 1.0))
        weights[cat] = max(0.1, min(current + float(delta), 6.0))
        pref_manager.update(news_category_weights=weights)
    except Exception:
        return


def news_feedback_profile_path() -> Path:
    return Path.home() / ".chintu" / "news_feedback_profile.json"


def load_news_feedback_profile() -> Dict[str, Any]:
    path = news_feedback_profile_path()
    if not path.exists():
        return {
            "liked_categories": {},
            "disliked_categories": {},
            "liked_sources": {},
            "disliked_sources": {},
            "liked_keywords": {},
            "disliked_keywords": {},
            "updated_at": "",
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload.setdefault("liked_categories", {})
            payload.setdefault("disliked_categories", {})
            payload.setdefault("liked_sources", {})
            payload.setdefault("disliked_sources", {})
            payload.setdefault("liked_keywords", {})
            payload.setdefault("disliked_keywords", {})
            payload.setdefault("updated_at", "")
            return payload
    except Exception:
        pass
    return {
        "liked_categories": {},
        "disliked_categories": {},
        "liked_sources": {},
        "disliked_sources": {},
        "liked_keywords": {},
        "disliked_keywords": {},
        "updated_at": "",
    }


def save_news_feedback_profile(profile: Dict[str, Any]) -> None:
    try:
        from datetime import datetime, timezone

        path = news_feedback_profile_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(profile or {})
        payload["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    except Exception:
        return


def tokenize_news_title(title: str) -> List[str]:
    stop = {
        "the",
        "and",
        "with",
        "from",
        "for",
        "this",
        "that",
        "into",
        "over",
        "after",
        "before",
        "today",
        "update",
        "latest",
        "new",
    }
    tokens = re.findall(r"[a-z0-9]{4,}", str(title or "").lower())
    return [token for token in tokens if token not in stop][:6]


def inc_profile_counter(bucket: Dict[str, Any], key: str, delta: int = 1) -> None:
    clean = str(key or "").strip().lower()
    if not clean:
        return
    current = int(bucket.get(clean, 0) or 0)
    bucket[clean] = max(0, current + int(delta))


def learn_news_preference(item: Dict[str, Any], *, positive: bool, explicit: bool = False) -> Dict[str, Any]:
    """Learn user preference from a consumed/liked/disliked news item."""
    category = str(item.get("category") or "news").strip().lower()
    source = str(item.get("source") or "").strip().lower()
    title = str(item.get("title") or "").strip()

    delta = 0.22 if explicit else 0.08
    nudge_news_category_weight(category, delta=delta if positive else -delta)

    profile = load_news_feedback_profile()
    cat_bucket = "liked_categories" if positive else "disliked_categories"
    src_bucket = "liked_sources" if positive else "disliked_sources"
    kw_bucket = "liked_keywords" if positive else "disliked_keywords"
    inc_profile_counter(profile.setdefault(cat_bucket, {}), category, 1)
    if source:
        inc_profile_counter(profile.setdefault(src_bucket, {}), source, 1)
    for token in tokenize_news_title(title):
        inc_profile_counter(profile.setdefault(kw_bucket, {}), token, 1)
    save_news_feedback_profile(profile)

    return {
        "category": category,
        "source": source,
        "title": title,
        "explicit": bool(explicit),
        "positive": bool(positive),
    }


def extract_feedback_sentiment(text: str) -> Optional[bool]:
    low = str(text or "").lower()
    positive_markers = (
        "i like",
        "liked",
        "love this",
        "more like this",
        "prefer this",
        "good one",
    )
    negative_markers = (
        "i dislike",
        "didn't like",
        "do not like",
        "not interested",
        "less like this",
        "don't show this",
        "skip this",
        "bad one",
    )
    if any(marker in low for marker in positive_markers):
        return True
    if any(marker in low for marker in negative_markers):
        return False
    return None


def apply_category_feedback_from_text(text: str) -> Optional[Dict[str, Any]]:
    low = str(text or "").lower()
    from chintu_backend.brain.memory.preferences import get_preference_manager

    categories = ("tech", "finance", "healthcare")
    deltas: Dict[str, float] = {}
    for cat in categories:
        if f"more {cat}" in low:
            deltas[cat] = deltas.get(cat, 0.0) + 0.2
        if f"less {cat}" in low:
            deltas[cat] = deltas.get(cat, 0.0) - 0.2
    if not deltas:
        return None

    pref_manager = get_preference_manager()
    weights = dict(getattr(pref_manager.preferences, "news_category_weights", {}) or {})
    for cat in categories:
        weights.setdefault(cat, 1.0)
    for cat, delta in deltas.items():
        weights[cat] = max(0.1, min(float(weights.get(cat, 1.0)) + float(delta), 6.0))
    pref_manager.update(news_category_weights=weights)
    return {"weights": weights, "deltas": deltas}


def extract_headline_number(text: str) -> Optional[int]:
    match = re.search(r"(?:#|number\s+)?(\d{1,3})", str(text or "").lower())
    if not match:
        return None
    try:
        value = int(match.group(1))
    except Exception:
        return None
    return value if value > 0 else None


def save_cached_morning_briefing_items(items: List[Dict[str, Any]]) -> None:
    """Persist briefing items so 'read more about #N' survives process/session gaps."""
    try:
        from datetime import datetime, timezone

        cache_path = Path.home() / ".chintu" / "daily_briefing_cache.json"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload_items: List[Dict[str, Any]] = []
        for row in list(items or []):
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or "").strip()
            if not title:
                continue
            payload_items.append(
                {
                    "title": title,
                    "category": str(row.get("category") or "news").strip(),
                    "source": str(row.get("source") or "").strip(),
                    "url": str(row.get("url") or "").strip(),
                    "digest_id": str(row.get("digest_id") or "").strip(),
                }
            )
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "items": payload_items,
        }
        cache_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    except Exception:
        return


def render_morning_briefing_feedback_ui(items: List[Dict[str, Any]]) -> None:
    """Render a lightweight desktop feedback card for briefing personalization."""
    if not items:
        return
    try:
        from chintu_backend.interfaces.ui.a2ui import (
            A2UIAction,
            A2UIComponent,
            A2UIView,
            get_a2ui_service,
        )

        max_items = min(len(items), 20)
        options: List[Dict[str, str]] = []
        for idx in range(1, max_items + 1):
            row = items[idx - 1] if idx - 1 < len(items) else {}
            title = str(row.get("title") or f"Headline #{idx}").strip()
            if len(title) > 80:
                title = f"{title[:77].rstrip()}..."
            options.append({"label": f"#{idx} - {title}", "value": str(idx)})

        form_id = "news.feedback.form"
        view_id = "news:briefing:feedback"
        view = A2UIView(
            id=view_id,
            kind="assistant_feedback",
            title="Briefing Feedback",
            description="Choose a headline and mark like or dislike. Optional archive saves full text for liked items.",
            components=[
                A2UIComponent(
                    type="form",
                    id=form_id,
                    data={
                        "title": "Feedback",
                        "fields": [
                            {
                                "name": "headline_number",
                                "label": "Headline",
                                "type": "select",
                                "default": "1",
                                "options": options,
                            },
                            {
                                "name": "sentiment",
                                "label": "Feedback",
                                "type": "select",
                                "default": "like",
                                "options": [
                                    {"label": "Like", "value": "like"},
                                    {"label": "Not Interested", "value": "dislike"},
                                ],
                            },
                            {
                                "name": "archive_full_article",
                                "label": "Archive full article text for liked item",
                                "type": "checkbox",
                                "default": False,
                            },
                        ],
                    },
                )
            ],
            actions=[
                A2UIAction(
                    id="news.feedback.submit",
                    label="Save Feedback",
                    style="primary",
                    action_type="submit",
                    form_id=form_id,
                ),
                A2UIAction(
                    id=f"a2ui.dismiss:{view_id}",
                    label="Later",
                    style="secondary",
                    action_type="dismiss",
                ),
            ],
            meta={"category": "news_feedback", "count": max_items},
        )
        get_a2ui_service().render_view(view)
    except Exception:
        return


def archive_news_item_if_needed(item: Dict[str, Any], *, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Archive full article content for liked headlines when enabled or requested."""
    cfg = get_config()
    if not bool(getattr(cfg, "knowledge_archive_enabled", True)):
        return {"ok": False, "reason": "archive_disabled"}
    ctx = context if isinstance(context, dict) else {}
    explicit_archive = bool(ctx.get("archive_full_article") or ctx.get("archive") or ctx.get("save_full_article"))
    if not explicit_archive and not bool(getattr(cfg, "knowledge_archive_on_like", True)):
        return {"ok": False, "reason": "archive_not_requested"}
    include_html = bool(explicit_archive and bool(getattr(cfg, "knowledge_archive_include_html", False)))
    try:
        from chintu_backend.brain.knowledge.knowledge_updater import get_knowledge_updater

        updater = get_knowledge_updater()
        return updater.archive_item_content(
            dict(item or {}),
            reason="liked",
            include_html=include_html,
            force_refresh=False,
        )
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def load_cached_morning_briefing_items(max_age_hours: int = 168) -> List[Dict[str, Any]]:
    """Load recent daily-briefing items from the shared disk cache."""
    cache_path = Path.home() / ".chintu" / "daily_briefing_cache.json"
    if not cache_path.exists():
        return []

    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    if not isinstance(payload, dict):
        return []

    generated_at = str(payload.get("generated_at") or "").strip()
    if generated_at:
        try:
            from datetime import datetime, timezone

            generated_dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
            age_hours = (datetime.now(timezone.utc) - generated_dt).total_seconds() / 3600.0
            if age_hours > float(max_age_hours):
                return []
        except Exception:
            pass

    rows = payload.get("items")
    if not isinstance(rows, list):
        return []

    items: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        items.append(
            {
                "title": title,
                "category": str(row.get("category") or "news").strip(),
                "source": str(row.get("source") or "").strip(),
                "url": str(row.get("url") or "").strip(),
            }
        )
    return items


def bootstrap_morning_briefing_items(total: int = 20) -> List[Dict[str, Any]]:
    """Best-effort fallback when no in-session briefing context exists."""
    try:
        from chintu_backend.brain.memory.preferences import get_preference_manager
        from chintu_backend.brain.knowledge.knowledge_updater import get_knowledge_updater

        prefs = get_preference_manager().preferences
        categories = list(getattr(prefs, "news_categories", []) or []) or ["tech", "finance", "healthcare"]
        weights = dict(getattr(prefs, "news_category_weights", {}) or {})
        updater = get_knowledge_updater()
        digest = updater.build_daily_digest(total=int(total), categories=categories, weights=weights)
        digest_id = str(digest.get("digest_id") or "").strip()
        items: List[Dict[str, Any]] = []
        for item in list(digest.get("items") or []):
            row = dict(item)
            if digest_id:
                row["digest_id"] = digest_id
            items.append(row)
        return items
    except Exception:
        return []

