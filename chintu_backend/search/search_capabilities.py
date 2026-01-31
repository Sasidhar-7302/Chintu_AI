"""
Search capability handlers for Chintu AI Assistant.
Provides voice commands for web search, news search, and research.
"""

import re
import logging
from typing import Dict, Any

from ..core.capabilities import Capability, CapabilityType, ActionResult

logger = logging.getLogger(__name__)


def handle_web_search(text: str, context: Dict[str, Any]) -> ActionResult:
    """
    Handle web search requests.
    
    Examples:
        "Search for Python tutorials"
        "Look up best laptops 2026"
        "Find information about machine learning"
    """
    from .web_search import search_web
    
    # Extract search query by removing command prefixes
    query = text.lower().strip()
    prefixes = [
        "search for ", "search ", "look up ", "find information about ",
        "find info about ", "find ", "google ", "look for ", "search the web for ",
        "web search for ", "web search "
    ]
    
    for prefix in prefixes:
        if query.startswith(prefix):
            query = query[len(prefix):].strip()
            break
    
    # Remove trailing punctuation
    query = query.rstrip("?.!")
    
    if not query or len(query) < 2:
        return ActionResult.fail(
            "What would you like me to search for?",
            "web_search"
        )
    
    try:
        results = search_web(query, max_results=5)
        
        if "No results found" in results:
            return ActionResult.ok(
                f"I couldn't find any results for '{query}'. Try a different search term.",
                {"query": query, "results": 0},
                "web_search"
            )
        
        return ActionResult.ok(
            results,
            {"query": query, "results": 5},
            "web_search"
        )
        
    except Exception as e:
        logger.error(f"Web search failed: {e}")
        return ActionResult.fail(
            f"Search failed: {e}. Make sure duckduckgo-search is installed.",
            "web_search"
        )


def handle_news_search(text: str, context: Dict[str, Any]) -> ActionResult:
    """
    Handle news search requests.
    
    Examples:
        "What's the latest news about AI?"
        "News about Tesla"
        "Recent news on climate change"
    """
    from .web_search import search_news
    
    # Extract news query
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
        results = search_news(query, max_results=5)
        
        if "No results found" in results:
            return ActionResult.ok(
                f"I couldn't find any news about '{query}'.",
                {"query": query, "results": 0},
                "news_search"
            )
        
        # Format as news results
        results = results.replace("**Search Results", "**Latest News")
        
        return ActionResult.ok(
            results,
            {"query": query, "results": 5},
            "news_search"
        )
        
    except Exception as e:
        logger.error(f"News search failed: {e}")
        return ActionResult.fail(
            f"News search failed: {e}",
            "news_search"
        )


def handle_quick_answer(text: str, context: Dict[str, Any]) -> ActionResult:
    """
    Handle quick factual questions by searching and summarizing.
    
    Examples:
        "What is the capital of France?"
        "How tall is the Eiffel Tower?"
        "Who invented the telephone?"
    """
    from .web_search import get_search_engine
    
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
            "search for", "search ", "look up", "google", "find information",
            "web search", "look for", "search the web"
        ],
        handler=handle_web_search,
        requires_confirmation=False,
        description="search the web for information",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=[
            "Search for Python tutorials",
            "Look up best restaurants near me",
            "Google machine learning basics"
        ]
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
        ]
    ))
    
    # Register deep search
    from .deep_search import register_deep_search_capability
    register_deep_search_capability(registry)
    
    logger.info("Registered search capabilities")

