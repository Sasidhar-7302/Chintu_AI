"""News reliability + freshness policy helpers.

Centralizes source trust scoring and recency filtering so daily briefings and
news search flows consistently prefer fresh, reputable sources.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence
from urllib.parse import urlparse


_TRUSTED_DOMAINS = {
    "apnews.com",
    "reuters.com",
    "bloomberg.com",
    "ft.com",
    "wsj.com",
    "cnbc.com",
    "marketwatch.com",
    "finance.yahoo.com",
    "investing.com",
    "sec.gov",
    "federalreserve.gov",
    "worldbank.org",
    "imf.org",
    "who.int",
    "nih.gov",
    "fda.gov",
    "cdc.gov",
    "nejm.org",
    "thelancet.com",
    "nature.com",
    "science.org",
    "statnews.com",
    "techcrunch.com",
    "theverge.com",
    "wired.com",
    "arstechnica.com",
    "venturebeat.com",
    "hackernews.com",
    "news.ycombinator.com",
    "openai.com",
    "anthropic.com",
    "googleblog.com",
    "blog.google",
    "microsoft.com",
    "meta.com",
    "nvidia.com",
    "huggingface.co",
    "ollama.com",
}

_CATEGORY_DOMAINS = {
    "tech": {
        "techcrunch.com",
        "theverge.com",
        "wired.com",
        "arstechnica.com",
        "venturebeat.com",
        "news.ycombinator.com",
        "openai.com",
        "anthropic.com",
        "huggingface.co",
        "nvidia.com",
    },
    "finance": {
        "reuters.com",
        "bloomberg.com",
        "ft.com",
        "wsj.com",
        "cnbc.com",
        "marketwatch.com",
        "finance.yahoo.com",
        "sec.gov",
        "federalreserve.gov",
    },
    "healthcare": {
        "who.int",
        "nih.gov",
        "fda.gov",
        "cdc.gov",
        "nejm.org",
        "thelancet.com",
        "nature.com",
        "science.org",
        "statnews.com",
        "reuters.com",
    },
}

_NOISY_SOCIAL_DOMAINS = {
    "x.com",
    "twitter.com",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "reddit.com",
    "youtube.com",
}

_TRUSTED_SOURCE_TOKENS = (
    "reuters",
    "associated press",
    "ap news",
    "bloomberg",
    "financial times",
    "wall street journal",
    "cnbc",
    "nature",
    "science",
    "who",
    "nih",
    "fda",
    "cdc",
)

_CATEGORY_KEYWORDS = {
    "tech": {
        "tech",
        "technology",
        "ai",
        "model",
        "models",
        "llm",
        "software",
        "chip",
        "gpu",
        "cloud",
        "developer",
        "robotics",
        "open source",
    },
    "finance": {
        "finance",
        "financial",
        "stock",
        "stocks",
        "market",
        "markets",
        "fed",
        "rates",
        "interest rate",
        "inflation",
        "earnings",
        "invest",
        "investment",
        "portfolio",
        "crypto",
        "bond",
    },
    "healthcare": {
        "health",
        "healthcare",
        "medical",
        "medicine",
        "biotech",
        "pharma",
        "fda",
        "cdc",
        "nih",
        "clinical",
        "trial",
        "vaccine",
        "hospital",
    },
}


def normalize_domain(value: str) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    try:
        host = str(urlparse(raw).netloc or "").strip().lower()
    except Exception:
        host = ""
    if not host:
        return str(value or "").strip().lower()
    if ":" in host:
        host = host.split(":", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    return host


def domain_matches(host: str, expected: str) -> bool:
    left = normalize_domain(host)
    right = normalize_domain(expected)
    if not left or not right:
        return False
    return left == right or left.endswith("." + right) or right.endswith("." + left)


def extract_domain(url: str, source: str = "") -> str:
    dom = normalize_domain(url)
    if dom:
        return dom
    source_dom = normalize_domain(source)
    if source_dom and "." in source_dom:
        return source_dom
    return ""


def parse_published_at(value: str) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None

    # Relative DDG styles: "2h ago", "3 days ago", "15m ago".
    rel = re.match(r"^\s*(\d+)\s*([smhdw])(?:\s*ago)?\s*$", raw.lower())
    if rel:
        amount = int(rel.group(1))
        unit = rel.group(2)
        now = datetime.now(timezone.utc)
        if unit == "s":
            return now - timedelta(seconds=amount)
        if unit == "m":
            return now - timedelta(minutes=amount)
        if unit == "h":
            return now - timedelta(hours=amount)
        if unit == "d":
            return now - timedelta(days=amount)
        if unit == "w":
            return now - timedelta(days=amount * 7)

    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        pass

    try:
        return parsedate_to_datetime(raw).astimezone(timezone.utc)
    except Exception:
        return None


def reliability_score(
    *,
    domain: str,
    source: str = "",
    category: str = "general",
    extra_trusted_domains: Optional[Sequence[str]] = None,
) -> float:
    dom = normalize_domain(domain)
    source_l = str(source or "").strip().lower()
    cat = str(category or "general").strip().lower()
    trusted = set(_TRUSTED_DOMAINS)
    category_trusted = set(_CATEGORY_DOMAINS.get(cat, set()))

    for row in list(extra_trusted_domains or []):
        clean = normalize_domain(str(row or ""))
        if clean:
            trusted.add(clean)

    if dom and any(domain_matches(dom, noisy) for noisy in _NOISY_SOCIAL_DOMAINS):
        return 0.05
    if dom and any(domain_matches(dom, row) for row in category_trusted):
        return 0.98
    if dom and any(domain_matches(dom, row) for row in trusted):
        return 0.9
    if dom.endswith(".gov") or dom.endswith(".edu"):
        return 0.86

    for token in _TRUSTED_SOURCE_TOKENS:
        if token in source_l:
            return 0.82

    if dom:
        return 0.42
    return 0.36


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", str(title or "").strip().lower())


def _compute_freshness_label(published_dt: Optional[datetime]) -> str:
    if not published_dt:
        return "recent"
    delta = datetime.now(timezone.utc) - published_dt
    hours = max(int(delta.total_seconds() // 3600), 0)
    if hours < 1:
        return "<1h"
    if hours < 24:
        return f"{hours}h"
    return f"{max(1, hours // 24)}d"


def _category_relevance_score(category: str, title: str, snippet: str) -> float:
    cat = str(category or "").strip().lower()
    keywords = _CATEGORY_KEYWORDS.get(cat)
    if not keywords:
        return 1.0
    text = f"{title} {snippet}".lower()
    word_tokens = set(re.findall(r"[a-z0-9]+", text))
    if cat == "healthcare":
        finance_tokens = ("stock", "stocks", "dow", "nasdaq", "s&p", "market", "futures", "earnings", "investor")
        medical_tokens = (
            "health",
            "healthcare",
            "medical",
            "medicine",
            "biotech",
            "pharma",
            "fda",
            "cdc",
            "nih",
            "clinical",
            "trial",
            "vaccine",
            "hospital",
            "disease",
        )
        if any(tok in text for tok in finance_tokens) and not any(tok in text for tok in medical_tokens):
            return 0.0
    hits = 0
    for token in keywords:
        if " " in token:
            if token in text:
                hits += 1
            continue
        if token in word_tokens:
            hits += 1
    if hits <= 0:
        return 0.0
    return min(1.0, hits / 3.0)


def rank_news_results(
    rows: Sequence[Any],
    *,
    category: str = "general",
    limit: int = 8,
    max_age_hours: int = 48,
    min_reliability: float = 0.58,
    fallback_min_reliability: float = 0.35,
    extra_trusted_domains: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    """Rank and filter news rows to prefer reputable and fresh sources.

    The function is intentionally resilient: if strict filtering would return
    too few items, it falls back to lower-confidence rows while still excluding
    clearly stale items when publish time is known.
    """

    prepared: List[Dict[str, Any]] = []
    seen_titles: set[str] = set()
    for row in rows or []:
        title = str(getattr(row, "title", "") or (row.get("title") if isinstance(row, dict) else "") or "").strip()
        if not title:
            continue
        title_key = _normalize_title(title)
        if not title_key or title_key in seen_titles:
            continue
        seen_titles.add(title_key)

        url = str(getattr(row, "url", "") or (row.get("url") if isinstance(row, dict) else "") or "").strip()
        snippet = str(getattr(row, "snippet", "") or (row.get("snippet") if isinstance(row, dict) else "") or "").strip()
        source = str(getattr(row, "source", "") or (row.get("source") if isinstance(row, dict) else "") or "").strip()
        published_raw = str(
            getattr(row, "published_at", "")
            or getattr(row, "date", "")
            or (row.get("published_at") if isinstance(row, dict) else "")
            or (row.get("date") if isinstance(row, dict) else "")
            or ""
        ).strip()
        published_dt = parse_published_at(published_raw)
        age_hours: Optional[float] = None
        if published_dt is not None:
            age_hours = max(0.0, (datetime.now(timezone.utc) - published_dt).total_seconds() / 3600.0)
            if age_hours > float(max_age_hours):
                continue

        domain = extract_domain(url, source)
        rel = reliability_score(
            domain=domain,
            source=source,
            category=category,
            extra_trusted_domains=extra_trusted_domains,
        )
        relevance = _category_relevance_score(category, title, snippet)

        freshness_bonus = 0.0
        if age_hours is None:
            freshness_bonus = -0.03
        elif age_hours <= 6:
            freshness_bonus = 0.2
        elif age_hours <= 24:
            freshness_bonus = 0.12
        elif age_hours <= max_age_hours:
            freshness_bonus = 0.04

        relevance_adjust = (0.18 * relevance) - (0.12 if relevance <= 0.0 else 0.0)
        quality = max(0.0, min(1.2, rel + freshness_bonus + relevance_adjust))
        prepared.append(
            {
                "title": title,
                "snippet": snippet,
                "url": url,
                "source": domain or source or "news",
                "domain": domain,
                "published_at": published_dt.isoformat().replace("+00:00", "Z") if published_dt else "",
                "freshness_label": _compute_freshness_label(published_dt),
                "reliability_score": round(float(rel), 4),
                "relevance_score": round(float(relevance), 4),
                "quality_score": round(float(quality), 4),
                "_age_hours": age_hours,
            }
        )

    if not prepared:
        return []

    strict = [
        row
        for row in prepared
        if float(row["reliability_score"]) >= float(min_reliability) and float(row["relevance_score"]) >= 0.2
    ]
    fallback = [
        row
        for row in prepared
        if float(row["reliability_score"]) >= float(fallback_min_reliability) and float(row["relevance_score"]) >= 0.05
    ]
    if strict:
        pool = strict
    elif fallback:
        pool = fallback
    else:
        if str(category or "").strip().lower() in {"tech", "finance", "healthcare"}:
            return []
        pool = prepared

    pool.sort(
        key=lambda row: (
            float(row.get("quality_score") or 0.0),
            float(row.get("reliability_score") or 0.0),
            -1.0 * float(row.get("_age_hours") or 10_000.0) if row.get("_age_hours") is not None else -10_000.0,
        ),
        reverse=True,
    )

    selected: List[Dict[str, Any]] = []
    for row in pool:
        clean = dict(row)
        clean.pop("_age_hours", None)
        selected.append(clean)
        if len(selected) >= max(1, int(limit)):
            break
    return selected


def trusted_domains() -> set[str]:
    return set(_TRUSTED_DOMAINS)
