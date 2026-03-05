"""
Search capability handlers for Chintu AI Assistant.
Provides voice commands for web search, news search, and research.
"""

import re
import logging
import json
import datetime
from typing import Dict, Any
from pathlib import Path
from pydantic import BaseModel, Field

from ..core.capabilities import Capability, CapabilityType, ActionResult
from chintu_backend.brain.memory.hybrid_memory import HybridMemoryManager

logger = logging.getLogger(__name__)

# ============================================================================
# SCHEMAS
# ============================================================================

class WebSearchSchema(BaseModel):
    query: str = Field(..., description="The query to search for.")

class NewsSearchSchema(BaseModel):
    topic: str = Field(..., description="The topic to find news about.")

class QuickAnswerSchema(BaseModel):
    question: str = Field(..., description="The factual question to answer.")


def _extract_requested_top_n(text: str, default: int = 3, min_value: int = 1, max_value: int = 10) -> int:
    match = re.search(r"\btop\s+(\d{1,2})\b", str(text or "").lower())
    if match:
        try:
            value = int(match.group(1))
            return max(min_value, min(value, max_value))
        except Exception:
            pass
    return max(min_value, min(default, max_value))


def _extract_hn_topic(text: str) -> str:
    lower = str(text or "").lower()
    match = re.search(r"\btop\s+\d+\s+(.+?)\s+news\s+headlines?\s+from\s+hacker\s+news\b", lower)
    if match:
        topic = match.group(1).strip()
        if topic:
            return topic
    return "ai"


def _fetch_hacker_news_headlines(topic: str, limit: int = 3) -> list[dict[str, str]]:
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
    seen_titles = set()
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        title = str(hit.get("title") or hit.get("story_title") or "").strip()
        if not title:
            continue
        key = title.lower().strip()
        if key in seen_titles:
            continue
        seen_titles.add(key)
        url = str(hit.get("url") or hit.get("story_url") or "").strip()
        if not url:
            object_id = str(hit.get("objectID") or "").strip()
            url = f"https://news.ycombinator.com/item?id={object_id}" if object_id else "https://news.ycombinator.com/"
        rows.append({"title": title, "url": url})
        if len(rows) >= int(limit):
            break
    return rows


def _cached_news_headlines(topic: str, limit: int = 3) -> list[dict[str, str]]:
    cache_path = Path.home() / ".chintu" / "daily_briefing_cache.json"
    if not cache_path.exists():
        return []
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    items = payload.get("items") if isinstance(payload, dict) else []
    if not isinstance(items, list):
        return []

    topic_low = str(topic or "ai").strip().lower()
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        blob = " ".join(
            [
                title.lower(),
                str(item.get("summary") or "").lower(),
                str(item.get("category") or "").lower(),
            ]
        )
        if topic_low and topic_low not in blob and topic_low != "ai":
            continue
        key = title.lower()
        if key in seen:
            continue
        seen.add(key)
        rows.append({"title": title, "url": str(item.get("url") or "").strip()})
        if len(rows) >= int(limit):
            break
    return rows


def _clean_query(text: str) -> str:
    """Clean a natural language search query."""
    text = text.lower().strip()
    
    # 1. Remove standard prefixes
    prefixes = [
        "search google for ", "search google ", "search the web for ", "web search for ", 
        "web search ", "find information about ", "find info about ", "look for ", 
        "look up ", "search for ", "search ", "find ", "google ",
        "can you search for ", "can you find ", "please search for "
    ]
    for prefix in prefixes:
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            break
            
    # 2. Remove filler phrases identifying user intent or politeness
    fillers = [
        "can you ", "could you ", "please ", "i need ", "i want ", "give me ", "show me ", "tell me ",
        "find me ", "suggest me ", "recommend me ", "what are ", "list ", 
        "i am looking for ", "i'm looking for ", "help me find ",
        "planning on ", "planning to ", "trying to ", "want to "
    ]
    
    # We remove these from the START generally, or replace them if they are in the middle?
    # Simple replace approach for noise phrases
    for filler in fillers:
        text = text.replace(filler, "")
        
    # 3. Remove context fluff
    fluff = [
        " for my pc", " for my computer", " suitable options", " suitable", " compatible for", 
        " basically", " actually", " probably", " kind of", " sort of"
    ]
    for f in fluff:
        text = text.replace(f, " ")
        
    # 4. Cleanup
    text = text.replace("  ", " ").strip().rstrip("?.!")
    
    return text

def search_web(query: str, max_results: int = 5):
    """Wrapper for web search to allow tests to patch this module."""
    from .web_search import get_search_engine
    engine = get_search_engine()
    raw_results = engine.search(query, max_results=max_results)
    formatted = engine.format_results(raw_results, query)
    return raw_results, formatted


def handle_web_search(text: str, context: Dict[str, Any]) -> ActionResult:
    """Handle web search requests."""
    from chintu_backend.brain.learning.learning_engine import get_learning_engine
    
    query = None
    validated = context.get("_validated_params")
    if validated and isinstance(validated, WebSearchSchema):
        query = validated.query
    
    if not query:
        # Extract search query (Legacy)
        query = _clean_query(text)
    
    # Shopping / Price Optimization
    shopping_triggers = ["buy", "price", "cost", "cheap", "best", "deal", "purchase", "shopping"]
    text_lower = text.lower()
    if any(trigger in text_lower for trigger in shopping_triggers):
        if "price" not in query and "buy" not in query:
             # Append keywords to guide duckduckgo to shopping results
             query += " price review buy"
    
    if not query or len(query) < 2:
        return ActionResult.fail(
            "What would you like me to search for?",
            "web_search"
        )
    
    try:
        search_result = search_web(query, max_results=5)
        if isinstance(search_result, tuple):
            raw_results, results = search_result
        else:
            raw_results, results = [], str(search_result)
        
        if not raw_results or "No results found" in results:
            return ActionResult.ok(
                f"I couldn't find any results for '{query}'. Try a different search term.",
                {"query": query, "results": 0},
                "web_search"
            )
        
        # ADAPTIVE LEARNING: Store result in memory
        try:
            mem = HybridMemoryManager()
            mem.save_interaction(
                "assistant",
                f"Research result for '{query}': {results[:500]}...",
                meta={"tags": ["learned", "web_search"]}
            )
        except Exception as e:
            logger.warning(f"Failed to learn from web search: {e}")

        # Continuous learning log for fine-tuning dataset
        try:
            sources = [r.url for r in raw_results if r.url]
            get_learning_engine().record_web_learning(query, results, sources=sources)
        except Exception as e:
            logger.warning(f"Failed to learn from web search: {e}")

        urls = [r.url for r in raw_results if getattr(r, "url", None)]
        first_url = urls[0] if urls else ""
        return ActionResult.ok(
            results,
            {
                "query": query,
                "results": len(raw_results),
                "urls": urls[:10],
                # Provide one URL for deterministic verification.
                "url": first_url,
            },
            "web_search"
        )
        
    except Exception as e:
        logger.error(f"Web search failed: {e}")
        return ActionResult.fail(
            f"Search failed: {e}. Make sure duckduckgo-search is installed.",
            "web_search"
        )


def handle_news_search(text: str, context: Dict[str, Any]) -> ActionResult:
    """Handle news search requests."""
    from .web_search import get_search_engine
    from .news_quality import rank_news_results
    from chintu_backend.brain.memory.preferences import get_preference_manager
    from chintu_backend.core.config import get_config
    
    query = None
    validated = context.get("_validated_params")
    if validated and isinstance(validated, NewsSearchSchema):
        query = validated.topic
        
    if not query:
        # Extract news query (Legacy)
        query = text.lower().strip()
        prefixes = [
            "what's the latest news about ", "what is the latest news about ",
            "latest news about ", "latest news on ", "news about ", "news on ",
            "recent news about ", "recent news on ", "news ", "headlines about ",
            "headlines on ", "headlines "
        ]
        
        for prefix in prefixes:
            if query.startswith(prefix):
                query = query[len(prefix):].strip()
                break
        
        query = query.rstrip("?.!")
    
    if not query or len(query) < 2:
        return ActionResult.fail(
            "What news topic would you like me to search for?",
            "news_search"
        )

    try:
        pref_manager = get_preference_manager()
        hide_urls = bool(getattr(pref_manager.preferences, "news_hide_urls", True))
        text_lower = str(text or "").lower()
        top_n = _extract_requested_top_n(text, default=3)
        headlines_only = "headline" in text_lower
        no_links = hide_urls or ("no links" in text_lower) or ("headlines only" in text_lower) or ("read only headlines" in text_lower)

        if "hacker news" in text_lower and headlines_only:
            topic = _extract_hn_topic(text)
            rows = _fetch_hacker_news_headlines(topic=topic, limit=top_n)
            if not rows:
                rows = _cached_news_headlines(topic=topic, limit=top_n)
            if not rows:
                return ActionResult.ok(
                    "I could not fetch live Hacker News headlines right now. "
                    "Check your internet/DNS and say retry Hacker News headlines.",
                    {"query": query, "results": 0, "offline_blocked": True},
                    "news_search",
                )
            lines = [f"Top {len(rows)} {topic.upper()} headlines from Hacker News today:"]
            lines.extend([f"{idx}. {row['title']}" for idx, row in enumerate(rows, start=1)])
            lines.append("")
            lines.append("Want details on any headline? Reply with a number like #1.")
            return ActionResult.ok(
                "\n".join(lines).strip(),
                {
                    "query": query,
                    "results": len(rows),
                    "urls": [row["url"] for row in rows],
                    "url": str((rows[0] or {}).get("url") or "").strip() if rows else "",
                },
                "news_search",
            )

        engine = get_search_engine()
        max_results = top_n if headlines_only else 5
        raw_rows = engine.search_news(query, max_results=max(8, max_results * 3), timelimit="d")
        cfg = get_config()
        rows_ranked = rank_news_results(
            raw_rows,
            category="general",
            limit=max_results,
            max_age_hours=int(getattr(cfg, "knowledge_news_max_age_hours", 48) or 48),
            min_reliability=float(getattr(cfg, "knowledge_news_min_reliability", 0.58) or 0.58),
            fallback_min_reliability=float(
                getattr(cfg, "knowledge_news_fallback_min_reliability", 0.35) or 0.35
            ),
            extra_trusted_domains=list(getattr(cfg, "knowledge_news_extra_trusted_domains", []) or []),
        )
        rows = rows_ranked[:max_results]
        if not rows:
            return ActionResult.ok(
                f"I couldn't find any news about '{query}'.",
                {"query": query, "results": 0},
                "news_search",
            )

        if headlines_only:
            selected = rows[:top_n]
            lines = [f"Top {len(selected)} headlines for '{query}':"]
            for idx, row in enumerate(selected, start=1):
                lines.append(f"{idx}. {str(row.get('title') or '').strip()}")
            lines.append("")
            lines.append("Want details on any headline? Reply with a number like #1.")
            response = "\n".join(lines).strip()
        else:
            lines = [f"Latest News for '{query}':", ""]
            for idx, row in enumerate(rows, start=1):
                title = str(row.get("title") or "").strip()
                snippet = str(row.get("snippet") or "").strip()
                lines.append(f"{idx}. {title}")
                if snippet:
                    lines.append(f"   {snippet}")
                if not no_links:
                    url = str(row.get("url") or "").strip()
                    if url:
                        lines.append(f"   {url}")
                lines.append("")
            response = "\n".join(lines).strip()

        return ActionResult.ok(
            response,
            {"query": query, "results": len(rows), "urls": [str((r or {}).get("url") or "") for r in rows]},
            "news_search",
        )

    except Exception as e:
        logger.error(f"News search failed: {e}")
        return ActionResult.fail(
            f"News search failed: {e}",
            "news_search"
        )


def handle_quick_answer(text: str, context: Dict[str, Any]) -> ActionResult:
    """Handle quick factual questions by searching and summarizing."""
    from .web_search import get_search_engine
    from chintu_backend.brain.learning.learning_engine import get_learning_engine
    
    query = None
    validated = context.get("_validated_params")
    if validated and isinstance(validated, QuickAnswerSchema):
        query = validated.question
        
    if not query:
        query = text.strip().rstrip("?.!")
    
    try:
        engine = get_search_engine()
        results = engine.search(query, max_results=3)
        
        if not results:
            return ActionResult.fail(
                f"I couldn't find an answer for that.",
                "quick_answer"
            )
        
        # Combine top snippets for a quick answer
        answer = results[0].snippet
        source = results[0].url
        
        response = f"{answer}\n\n*Source: {source}*"
        
        # ADAPTIVE LEARNING: Store fact
        try:
            mem = HybridMemoryManager()
            mem.save_interaction("assistant", f"Fact: {query} -> {answer}", meta={"tags": ["learned", "quick_answer"]})
        except Exception as e:
            logger.warning(f"Failed to learn quick answer: {e}")

        # Continuous learning log for fine-tuning dataset
        try:
            get_learning_engine().record_web_learning(query, answer, sources=[source] if source else [])
        except Exception as e:
            logger.warning(f"Failed to log quick answer for learning: {e}")
        
        return ActionResult.ok(
            response,
            {"query": query, "source": source},
            "quick_answer"
        )
        
    except Exception as e:
        logger.error(f"Quick answer failed: {e}")
        return ActionResult.fail(
            f"I couldn't find an answer: {e}",
            "quick_answer"
        )


def register_search_capabilities(registry) -> None:
    """Register all search-related capabilities."""
    
    # Web Search
    registry.register(Capability(
        name="web_search",
        triggers=[
            "search for",
            "search ",
            "look up",
            "google",
            "find information",
            "find info about",
            "web search",
            "look for",
            "search the web",
            "search online",
            "search the internet",
            "what is the latest on",
            "what's the latest on",
            "latest on",
        ],
        handler=handle_web_search,
        requires_confirmation=False,
        description="search the web for information",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=[
            "Search for Python tutorials",
            "Look up best restaurants near me",
            "Google machine learning basics"
        ],
        schema=WebSearchSchema
    ))
    
    # News Search
    registry.register(Capability(
        name="news_search",
        triggers=[
            "latest news", "news about", "news on", "headlines",
            "recent news", "what's the news"
        ],
        handler=handle_news_search,
        requires_confirmation=False,
        description="search for latest news",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=[
            "Latest news about AI",
            "What's the news on Tesla?",
            "Headlines about technology"
        ],
        schema=NewsSearchSchema
    ))
    
    # Register deep search
    from .deep_search import register_deep_search_capability
    register_deep_search_capability(registry)
    
    logger.info("Registered search capabilities")
