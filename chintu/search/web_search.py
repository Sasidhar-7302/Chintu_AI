"""
Web Search Engine for Chintu AI Assistant.
Provides web search functionality using DuckDuckGo (free, no API key needed).
"""

import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """A single search result."""
    title: str
    snippet: str
    url: str
    source: str = "web"


class WebSearchEngine:
    """
    Web search engine using DuckDuckGo.
    Falls back gracefully if search fails.
    """
    
    def __init__(self):
        self._ddgs = None
        self._available = False
        self._init_search()
    
    def _init_search(self):
        """Initialize DuckDuckGo search."""
        try:
            # Try new package name first (ddgs)
            from ddgs import DDGS
            self._ddgs_class = DDGS
            self._available = True
            logger.info("DuckDuckGo search initialized (ddgs package)")
        except ImportError:
            try:
                # Fallback to old package name
                from duckduckgo_search import DDGS
                self._ddgs_class = DDGS
                self._available = True
                logger.info("DuckDuckGo search initialized (duckduckgo_search package)")
            except ImportError:
                logger.warning("Web search not available. Run: pip install ddgs")
                self._available = False
    
    @property
    def is_available(self) -> bool:
        return self._available
    
    def search(self, query: str, max_results: int = 5, region: str = "us-en") -> List[SearchResult]:
        """
        Search the web for the given query.
        
        Args:
            query: Search query
            max_results: Maximum number of results (1-10)
            region: Region code for localized results
            
        Returns:
            List of SearchResult objects
        """
        if not self._available:
            logger.error("Search not available - duckduckgo_search not installed")
            return []
        
        try:
            with self._ddgs_class() as ddgs:
                results = list(ddgs.text(
                    query,
                    max_results=min(max_results, 10),
                    region=region
                ))
            
            search_results = []
            for r in results:
                search_results.append(SearchResult(
                    title=r.get("title", "No title"),
                    snippet=r.get("body", "")[:300],
                    url=r.get("href", ""),
                    source="duckduckgo"
                ))
            
            logger.info(f"Search for '{query}' returned {len(search_results)} results")
            return search_results
            
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []
    
    def search_news(self, query: str, max_results: int = 5) -> List[SearchResult]:
        """
        Search for news articles.
        
        Args:
            query: Search query
            max_results: Maximum number of results
            
        Returns:
            List of SearchResult objects
        """
        if not self._available:
            return []
        
        try:
            with self._ddgs_class() as ddgs:
                results = list(ddgs.news(
                    query,
                    max_results=min(max_results, 10)
                ))
            
            search_results = []
            for r in results:
                search_results.append(SearchResult(
                    title=r.get("title", "No title"),
                    snippet=r.get("body", "")[:300],
                    url=r.get("url", ""),
                    source="news"
                ))
            
            logger.info(f"News search for '{query}' returned {len(search_results)} results")
            return search_results
            
        except Exception as e:
            logger.error(f"News search failed: {e}")
            return []
    
    def search_images(self, query: str, max_results: int = 5) -> List[Dict[str, str]]:
        """
        Search for images.
        
        Args:
            query: Search query  
            max_results: Maximum number of results
            
        Returns:
            List of image dictionaries with url, title, source
        """
        if not self._available:
            return []
        
        try:
            with self._ddgs_class() as ddgs:
                results = list(ddgs.images(
                    query,
                    max_results=min(max_results, 10)
                ))
            
            return [
                {
                    "url": r.get("image", ""),
                    "title": r.get("title", ""),
                    "source": r.get("source", "")
                }
                for r in results
            ]
            
        except Exception as e:
            logger.error(f"Image search failed: {e}")
            return []
    
    def format_results(self, results: List[SearchResult], query: str) -> str:
        """
        Format search results as readable text.
        
        Args:
            results: List of SearchResult objects
            query: Original search query
            
        Returns:
            Formatted string with results
        """
        if not results:
            return f"No results found for '{query}'."
        
        lines = [f"**Search Results for '{query}':**\n"]
        
        for i, r in enumerate(results, 1):
            lines.append(f"**{i}. {r.title}**")
            lines.append(f"   {r.snippet}")
            if r.url:
                lines.append(f"   [Source]({r.url})")
            lines.append("")
        
        return "\n".join(lines)


# Global instance
_search_engine: Optional[WebSearchEngine] = None


def get_search_engine() -> WebSearchEngine:
    """Get the global search engine instance."""
    global _search_engine
    if _search_engine is None:
        _search_engine = WebSearchEngine()
    return _search_engine


def search_web(query: str, max_results: int = 5) -> str:
    """
    Convenience function to search the web.
    
    Args:
        query: Search query
        max_results: Maximum results to return
        
    Returns:
        Formatted search results string
    """
    engine = get_search_engine()
    results = engine.search(query, max_results=max_results)
    return engine.format_results(results, query)


def search_news(query: str, max_results: int = 5) -> str:
    """
    Convenience function to search news.
    
    Args:
        query: Search query
        max_results: Maximum results to return
        
    Returns:
        Formatted news results string
    """
    engine = get_search_engine()
    results = engine.search_news(query, max_results=max_results)
    return engine.format_results(results, query)
