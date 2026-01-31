"""
Deep Search capability for Chintu AI Assistant.
Performs comprehensive multi-source research and generates reports.
"""

import logging
import asyncio
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor

from ..core.capabilities import Capability, CapabilityType, ActionResult

logger = logging.getLogger(__name__)


def _search_source(source: str, query: str, max_results: int = 3) -> List[Dict[str, str]]:
    """Search a single source and return results."""
    try:
        from ..search.web_search import get_search_engine
        engine = get_search_engine()
        
        if source == "web":
            results = engine.search(query, max_results=max_results)
        elif source == "news":
            results = engine.search_news(query, max_results=max_results)
        else:
            # Add source to query for more specific results
            results = engine.search(f"{query} {source}", max_results=max_results)
        
        return [
            {"title": r.title, "snippet": r.snippet, "url": r.url, "source": source}
            for r in results
        ]
    except Exception as e:
        logger.warning(f"Search failed for {source}: {e}")
        return []


def deep_search(query: str, sources: List[str] = None) -> str:
    """
    Perform deep search across multiple sources.
    
    Args:
        query: Research query
        sources: List of sources to search (default: web, news, reddit)
        
    Returns:
        Formatted research report
    """
    if sources is None:
        sources = ["web", "news", "reddit", "forum"]
    
    all_results = []
    
    # Search sources in parallel
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(_search_source, source, query, 3): source
            for source in sources
        }
        
        for future in futures:
            try:
                results = future.result(timeout=10)
                all_results.extend(results)
            except Exception as e:
                logger.warning(f"Source search failed: {e}")
    
    if not all_results:
        return f"No results found for '{query}'."
    
    # Format as research report
    lines = [
        f"# Research Report: {query}\n",
        f"Searched {len(sources)} sources, found {len(all_results)} results.\n",
        "---\n"
    ]
    
    # Group by source
    by_source = {}
    for r in all_results:
        src = r.get("source", "web")
        if src not in by_source:
            by_source[src] = []
        by_source[src].append(r)
    
    for source, results in by_source.items():
        lines.append(f"\n## From {source.title()}\n")
        for i, r in enumerate(results, 1):
            lines.append(f"**{i}. {r['title']}**")
            lines.append(f"   {r['snippet']}")
            if r['url']:
                lines.append(f"   [Source]({r['url']})")
            lines.append("")
    
    return "\n".join(lines)


def handle_deep_search(text: str, context: Dict[str, Any]) -> ActionResult:
    """
    Handle deep research requests.
    
    Examples:
        "Research the pros and cons of electric cars"
        "Deep search best programming languages 2026"
        "Research and summarize machine learning trends"
    """
    # Extract research query
    query = text.lower().strip()
    prefixes = [
        "research ", "deep search ", "research and summarize ",
        "comprehensive search ", "investigate ", "analyze "
    ]
    
    research_query = query
    for prefix in prefixes:
        if query.startswith(prefix):
            research_query = query[len(prefix):].strip()
            break
    
    if not research_query or len(research_query) < 3:
        return ActionResult.fail(
            "What would you like me to research?",
            "deep_search"
        )
    
    try:
        # Use new Verified Researcher
        from ..research.verified_research import VerifiedResearcher
        researcher = VerifiedResearcher()
        result = researcher.research(research_query, deep=True)
        
        return ActionResult.ok(
            result["report"],
            {"query": research_query, "sources": len(result["sources"])},
            "deep_search"
        )
        
    except Exception as e:
        logger.error(f"Deep search failed: {e}")
        return ActionResult.fail(
            f"Research failed: {e}",
            "deep_search"
        )


def register_deep_search_capability(registry) -> None:
    """Register deep search capability."""
    
    registry.register(Capability(
        name="deep_search",
        triggers=[
            "research ", "deep search", "comprehensive search",
            "investigate", "research and summarize", "analyze and report",
            "verify", "fact check", "source check", "find sources for"
        ],
        handler=handle_deep_search,
        requires_confirmation=False,
        description="perform deep multi-source research",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=[
            "Research the pros and cons of electric cars",
            "Deep search best laptops 2026",
            "Research machine learning trends"
        ]
    ))
    
    logger.info("Registered deep search capability")
