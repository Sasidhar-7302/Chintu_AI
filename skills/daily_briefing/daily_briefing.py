from __future__ import annotations

import datetime as dt
from difflib import SequenceMatcher
import json
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote_plus

import requests


REQUEST_TIMEOUT = 15
MAX_HEADLINES = 20
MAX_NEWS_AGE_HOURS = 48
CACHE_PATH = Path.home() / ".chintu" / "daily_briefing_cache.json"
PROFILE_PATH = Path.home() / ".chintu" / "daily_briefing_interest.json"

CATEGORY_QUERIES = {
    "tech": [
        "AI innovation OR semiconductor OR robotics OR developer tools when:1d",
        "technology breakthrough startup funding when:1d",
    ],
    "finance": [
        "markets OR fintech OR investment OR earnings when:1d",
        "economy inflation rate cut jobs report when:1d",
    ],
    "healthcare": [
        "healthcare innovation OR biotech OR medtech OR clinical trial when:1d",
        "FDA approval OR medical breakthrough OR health policy when:1d",
    ],
}

CATEGORY_QUOTAS = {
    "tech": 8,
    "finance": 6,
    "healthcare": 6,
}


@dataclass
class NewsItem:
    title: str
    source: str
    url: str
    published_iso: str
    category: str
    rank_score: float
    digest_id: str = ""


def _to_ascii(value: str) -> str:
    return str(value or "").encode("ascii", errors="ignore").decode("ascii")


def _clean_source_label(value: str) -> str:
    source = _to_ascii(value).strip()
    if not source:
        return "Unknown source"
    # RSS sources occasionally include URLs or duplicate site labels.
    source = re.sub(r"https?://\S+", "", source, flags=re.IGNORECASE)
    source = re.sub(r"\bwww\.[^\s]+", "", source, flags=re.IGNORECASE)
    source = re.sub(r"\s+", " ", source).strip(" -|")
    return source or "Unknown source"


def _clean_headline_title(title: str, source: str = "") -> str:
    cleaned = _to_ascii(title).strip()
    if not cleaned:
        return ""
    source_clean = _clean_source_label(source)
    if source_clean:
        cleaned = re.sub(
            rf"\s*-\s*{re.escape(source_clean)}\s*$",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
    cleaned = re.sub(r"\s*-\s*[A-Za-z0-9.-]+\.(?:com|org|net|io|ai)\s*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -")
    return cleaned


def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _resolve_gcalcli_command() -> List[str]:
    """Resolve gcalcli command even when Scripts/ isn't on PATH."""
    gcal_bin = shutil.which("gcalcli")
    if gcal_bin:
        return [gcal_bin]

    candidates = [
        Path(sys.executable).resolve().with_name("gcalcli.exe"),
        Path(sys.executable).resolve().with_name("gcalcli"),
        Path.cwd() / "venv" / "Scripts" / "gcalcli.exe",
        Path.cwd() / "venv" / "bin" / "gcalcli",
    ]
    for candidate in candidates:
        if candidate.exists():
            return [str(candidate)]

    # Final fallback when the package exists but launcher is not on PATH.
    try:
        import importlib.util

        if importlib.util.find_spec("gcalcli"):
            return [sys.executable, "-m", "gcalcli"]
    except Exception:
        pass

    return []


def _fetch_calendar_events_native() -> Optional[str]:
    """Prefer Chintu's built-in Google Calendar integration when available."""
    try:
        from chintu_backend.integrations.google_calendar import get_calendar

        calendar = get_calendar()
        if calendar.is_authenticated:
            events = calendar.get_todays_events()
            return calendar.format_events_for_voice(events)
        if calendar.is_configured:
            return "Calendar linked. Run 'setup calendar' once to finish authentication."
        return "Calendar not connected. Run 'setup calendar' to link your Google account."
    except Exception:
        return None
    return None


def fetch_calendar_events() -> str:
    native = _fetch_calendar_events_native()
    if native:
        return native

    gcal_cmd = _resolve_gcalcli_command()
    if not gcal_cmd:
        return "Calendar not connected. Run 'setup calendar' to link your Google account."

    today = dt.datetime.now().strftime("%Y-%m-%d")
    try:
        result = subprocess.run(
            [*gcal_cmd, "agenda", today, today],
            capture_output=True,
            text=True,
            check=True,
        )
        output = (result.stdout or "").strip()
        return output if output else "No events scheduled for today."
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        detail_l = detail.lower()
        if "eof when reading a line" in detail_l or "client_id" in detail_l:
            return (
                "Calendar needs one-time setup. "
                "Run setup calendar, then complete Google login."
            )
        return f"Calendar check failed: {detail or 'unknown error'}"
    except Exception as exc:
        return f"Calendar check failed: {exc}"


def _parse_pub_date(value: str) -> Optional[dt.datetime]:
    if not value:
        return None
    try:
        parsed_iso = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed_iso.tzinfo is None:
            parsed_iso = parsed_iso.replace(tzinfo=dt.timezone.utc)
        return parsed_iso.astimezone(dt.timezone.utc)
    except Exception:
        pass
    try:
        parsed = parsedate_to_datetime(value)
        return parsed.astimezone(dt.timezone.utc)
    except Exception:
        return None


def _format_age(published: dt.datetime) -> str:
    delta = _now_utc() - published
    hours = int(max(0.0, delta.total_seconds()) // 3600)
    if hours < 1:
        return "just now"
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


def _score_headline(title: str, category: str, published: Optional[dt.datetime], interest: Dict[str, float]) -> float:
    title_l = title.lower()
    base = 1.0
    keywords = {
        "breakthrough": 0.35,
        "launch": 0.25,
        "funding": 0.2,
        "approval": 0.2,
        "record": 0.15,
        "open source": 0.15,
        "policy": 0.1,
    }
    for kw, boost in keywords.items():
        if kw in title_l:
            base += boost

    if published:
        age_hours = max(0.0, (_now_utc() - published).total_seconds() / 3600.0)
        base += max(0.0, 1.2 - min(age_hours, 36.0) / 30.0)

    base += float(interest.get(category, 1.0))
    return round(base, 4)


def _google_news_feed(query: str) -> str:
    encoded = quote_plus(query)
    return f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"


def _fetch_google_news(query: str, category: str, interest: Dict[str, float], limit: int = 15) -> List[NewsItem]:
    url = _google_news_feed(query)
    headers = {"User-Agent": "Chintu/1.0 (+daily-briefing)"}
    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except Exception:
        return []

    items: List[NewsItem] = []
    try:
        root = ET.fromstring(response.text)
    except Exception:
        return []

    max_age = dt.timedelta(hours=MAX_NEWS_AGE_HOURS)
    for node in root.findall("./channel/item"):
        if len(items) >= limit:
            break
        title = (node.findtext("title") or "").strip()
        source = (node.findtext("source") or "Unknown source").strip()
        link = (node.findtext("link") or "").strip()
        published = _parse_pub_date(node.findtext("pubDate") or "")
        if not title or not link or not published:
            continue
        if (_now_utc() - published) > max_age:
            continue
        source_clean = _clean_source_label(source)
        title_clean = _clean_headline_title(title, source_clean)
        if not title_clean:
            continue
        items.append(
            NewsItem(
                title=title_clean,
                source=source_clean,
                url=link,
                published_iso=published.isoformat(),
                category=category,
                rank_score=_score_headline(title, category, published, interest),
            )
        )
    return items


def _fetch_hn_ai(interest: Dict[str, float], limit: int = 8) -> List[NewsItem]:
    url = "https://hn.algolia.com/api/v1/search?query=AI&tags=story&hitsPerPage=30"
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return []

    items: List[NewsItem] = []
    max_age = dt.timedelta(hours=MAX_NEWS_AGE_HOURS)
    hits = payload.get("hits") or []
    for story in hits:
        if len(items) >= limit:
            break
        title = (story.get("title") or story.get("story_title") or "").strip()
        if not title:
            continue
        source = (story.get("author") or "Hacker News").strip() or "Hacker News"
        story_url = (story.get("url") or story.get("story_url") or "https://news.ycombinator.com").strip()
        created_at = story.get("created_at") or ""
        published = None
        try:
            published = dt.datetime.fromisoformat(created_at.replace("Z", "+00:00")).astimezone(dt.timezone.utc)
        except Exception:
            published = None
        if not published:
            continue
        if (_now_utc() - published) > max_age:
            continue
        source_clean = _clean_source_label(source)
        title_clean = _clean_headline_title(title, source_clean)
        if not title_clean:
            continue
        items.append(
            NewsItem(
                title=title_clean,
                source=source_clean,
                url=story_url,
                published_iso=published.isoformat(),
                category="tech",
                rank_score=_score_headline(title, "tech", published, interest) + 0.15,
            )
        )
    return items


def _dedupe(items: List[NewsItem]) -> List[NewsItem]:
    unique: List[NewsItem] = []
    normalized_titles: List[str] = []
    for item in sorted(items, key=lambda x: x.rank_score, reverse=True):
        key = re.sub(r"[^a-z0-9]+", " ", item.title.lower()).strip()
        duplicate = False
        for existing in normalized_titles:
            if key == existing:
                duplicate = True
                break
            if SequenceMatcher(a=key, b=existing).ratio() >= 0.94:
                duplicate = True
                break
        if duplicate:
            continue
        normalized_titles.append(key)
        unique.append(item)
    return unique


def _pick_headlines(items: List[NewsItem], total: int = MAX_HEADLINES) -> List[NewsItem]:
    by_category: Dict[str, List[NewsItem]] = {"tech": [], "finance": [], "healthcare": []}
    for item in sorted(items, key=lambda x: x.rank_score, reverse=True):
        if item.category in by_category:
            by_category[item.category].append(item)

    selected: List[NewsItem] = []
    for category, quota in CATEGORY_QUOTAS.items():
        selected.extend(by_category.get(category, [])[:quota])

    if len(selected) < total:
        selected_ids = {id(item) for item in selected}
        extras = [item for item in sorted(items, key=lambda x: x.rank_score, reverse=True) if id(item) not in selected_ids]
        selected.extend(extras[: total - len(selected)])

    selected = sorted(selected[:total], key=lambda x: x.rank_score, reverse=True)
    return selected


def _load_interest_profile() -> Dict[str, float]:
    if not PROFILE_PATH.exists():
        return {"tech": 1.0, "finance": 1.0, "healthcare": 1.0}
    try:
        payload = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return {
                "tech": float(payload.get("tech", 1.0)),
                "finance": float(payload.get("finance", 1.0)),
                "healthcare": float(payload.get("healthcare", 1.0)),
            }
    except Exception:
        pass
    return {"tech": 1.0, "finance": 1.0, "healthcare": 1.0}


def _save_interest_profile(profile: Dict[str, float]) -> None:
    _ensure_parent(PROFILE_PATH)
    PROFILE_PATH.write_text(json.dumps(profile, indent=2, ensure_ascii=True), encoding="utf-8")


def _save_cache(items: List[NewsItem]) -> None:
    _ensure_parent(CACHE_PATH)
    payload = {
        "generated_at": _now_utc().isoformat(),
        "items": [asdict(item) for item in items],
    }
    CACHE_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def _load_cache() -> List[NewsItem]:
    if not CACHE_PATH.exists():
        return []
    try:
        payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        items = payload.get("items") if isinstance(payload, dict) else []
        result: List[NewsItem] = []
        for row in items if isinstance(items, list) else []:
            if not isinstance(row, dict):
                continue
            result.append(
                NewsItem(
                    title=str(row.get("title") or ""),
                    source=str(row.get("source") or "Unknown source"),
                    url=str(row.get("url") or ""),
                    published_iso=str(row.get("published_iso") or ""),
                    category=str(row.get("category") or "tech"),
                    rank_score=float(row.get("rank_score") or 1.0),
                    digest_id=str(row.get("digest_id") or ""),
                )
            )
        return result
    except Exception:
        return []


def _extract_detail_query(request_text: str) -> str:
    lowered = request_text.lower()
    markers = ["read more about", "detail about", "details on", "more on"]
    for marker in markers:
        if marker in lowered:
            idx = lowered.find(marker) + len(marker)
            return request_text[idx:].strip()
    return ""


def _resolve_detail_target(detail_query: str, cached: List[NewsItem]) -> Optional[NewsItem]:
    if not detail_query or not cached:
        return None
    m = re.search(r"\d+", detail_query)
    if m:
        idx = int(m.group(0))
        if 1 <= idx <= len(cached):
            return cached[idx - 1]
    dq = detail_query.lower()
    for item in cached:
        if dq and dq in item.title.lower():
            return item
    return None


def _fetch_article_text(url: str, max_chars: int = 3600) -> str:
    headers = {"User-Agent": "Chintu/1.0 (+daily-briefing)"}
    candidates = [
        f"https://r.jina.ai/http://{url.replace('https://', '').replace('http://', '')}",
        url,
    ]
    for candidate in candidates:
        try:
            response = requests.get(candidate, headers=headers, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            text = response.text
            text = re.sub(r"\[(?:Image|Video)[^\]]*\]\([^)]*\)", " ", text)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                return text[:max_chars]
        except Exception:
            continue
    return ""


def _resolve_article_url(item: NewsItem) -> str:
    url = item.url
    if "news.google.com/" not in url:
        return url
    try:
        from ddgs import DDGS

        query = f"{item.title} {item.source}".strip()
        results = DDGS().text(query, max_results=5)
        for row in results if isinstance(results, list) else []:
            if not isinstance(row, dict):
                continue
            href = str(row.get("href") or "").strip()
            if not href or "news.google.com/" in href:
                continue
            return href
    except Exception:
        return url
    return url


def _summarize_article(text: str) -> List[str]:
    if not text:
        return []
    sentences = re.split(r"(?<=[.!?])\s+", text)
    cleaned = []
    for sentence in sentences:
        s = sentence.strip()
        s = _to_ascii(s)
        if len(s) < 50:
            continue
        if s.lower().startswith("title:") or s.lower().startswith("url source:"):
            continue
        cleaned.append(s)
        if len(cleaned) >= 4:
            break
    return cleaned


def _render_briefing(calendar: str, headlines: List[NewsItem], interest: Dict[str, float]) -> str:
    lines = ["=== Daily Briefing ===", "", "[Calendar]", calendar.strip() or "No calendar updates.", "", "[Top 20 Headlines]"]

    if not headlines:
        lines.append("No fresh headlines found in the last 48 hours.")
        return "\n".join(lines)

    for idx, item in enumerate(headlines, start=1):
        title = item.title.strip()
        if len(title) > 95:
            title = f"{title[:92].rstrip()}..."
        lines.append(f"{idx:02d}. [{item.category.title()}] {title}")

    lines.extend(
        [
            "",
            "I only listed headlines here. If you want details, say:",
            "- read more about #<number>",
            "- read more about <headline keywords>",
            "",
            (
                "Interest weights (auto-adapting): "
                f"Tech={interest.get('tech', 1.0):.2f}, "
                f"Finance={interest.get('finance', 1.0):.2f}, "
                f"Healthcare={interest.get('healthcare', 1.0):.2f}"
            ),
        ]
    )
    return "\n".join(lines)


def _render_detail(item: NewsItem, bullets: List[str]) -> str:
    lines = [
        "=== Daily Briefing Detail ===",
        f"Headline: {item.title}",
        f"Category: {_to_ascii(item.category.title())}",
        f"Source: {_to_ascii(item.source)}",
        "",
    ]
    if not bullets:
        lines.append("I could not extract enough detail from this source right now.")
        lines.append("Try another headline from the list.")
        return "\n".join(lines)

    lines.append("What matters:")
    for bullet in bullets:
        lines.append(f"- {_to_ascii(bullet)}")
    lines.append("")
    lines.append("Say 'daily briefing' anytime for a fresh 20-headline digest.")
    return "\n".join(lines)


def _build_from_knowledge_updater(interest: Dict[str, float]) -> List[NewsItem]:
    try:
        from chintu_backend.brain.knowledge.knowledge_updater import get_knowledge_updater

        updater = get_knowledge_updater()
        digest = updater.build_daily_digest(
            total=MAX_HEADLINES,
            categories=["tech", "finance", "healthcare"],
            weights=interest,
        )
        digest_id = str(digest.get("digest_id") or "").strip()
        rows = list(digest.get("items") or [])
        out: List[NewsItem] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            title = _clean_headline_title(str(row.get("title") or ""), str(row.get("source") or ""))
            if not title:
                continue
            category = str(row.get("category") or "tech").strip().lower()
            if category not in {"tech", "finance", "healthcare"}:
                category = "tech"
            source = _clean_source_label(str(row.get("source") or ""))
            published_iso = str(row.get("published_at") or "").strip()
            published = _parse_pub_date(published_iso) if published_iso else None
            score = _score_headline(title, category, published, interest)
            out.append(
                NewsItem(
                    title=title,
                    source=source,
                    url=str(row.get("url") or "").strip(),
                    published_iso=published_iso,
                    category=category,
                    rank_score=score,
                    digest_id=digest_id,
                )
            )
        return out
    except Exception:
        return []


def build_fresh_briefing() -> tuple[str, List[NewsItem], Dict[str, float]]:
    interest = _load_interest_profile()
    calendar = fetch_calendar_events()
    all_items: List[NewsItem] = _build_from_knowledge_updater(interest)

    if all_items:
        selected = _pick_headlines(_dedupe(all_items), total=MAX_HEADLINES)
        _save_cache(selected)
        return calendar, selected, interest

    all_items = []

    for category, queries in CATEGORY_QUERIES.items():
        for query in queries:
            all_items.extend(_fetch_google_news(query=query, category=category, interest=interest, limit=14))

    all_items.extend(_fetch_hn_ai(interest=interest, limit=8))
    all_items = _dedupe(all_items)
    selected = _pick_headlines(all_items, total=MAX_HEADLINES)
    _save_cache(selected)

    return calendar, selected, interest


def main() -> None:
    request_text = " ".join(sys.argv[1:]).strip()
    detail_query = _extract_detail_query(request_text)
    cached = _load_cache()

    if detail_query and cached:
        target = _resolve_detail_target(detail_query, cached)
        if not target:
            print("I could not map that detail request to a headline number or title.")
            print("Try: read more about #3")
            return
        if target.digest_id:
            try:
                from chintu_backend.brain.knowledge.knowledge_updater import get_knowledge_updater

                updater = get_knowledge_updater()
                idx = cached.index(target) + 1
                expanded = updater.expand_digest_item(target.digest_id, idx)
                if bool(expanded.get("ok")):
                    summary = str(expanded.get("summary") or "").strip()
                    bullets = _summarize_article(summary) or [summary] if summary else []
                    print(_render_detail(target, bullets[:4]))
                    return
            except Exception:
                pass
        resolved_url = _resolve_article_url(target)
        article_text = _fetch_article_text(resolved_url)
        if not article_text and resolved_url != target.url:
            article_text = _fetch_article_text(target.url)
        bullets = _summarize_article(article_text)
        profile = _load_interest_profile()
        profile[target.category] = min(3.0, float(profile.get(target.category, 1.0)) + 0.15)
        _save_interest_profile(profile)
        print(_render_detail(target, bullets))
        return

    calendar, selected, interest = build_fresh_briefing()
    print(_render_briefing(calendar, selected, interest))


if __name__ == "__main__":
    main()
