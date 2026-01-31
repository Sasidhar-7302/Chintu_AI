"""
Live Web Search for Chintu AI Assistant.

Provides real-time web search using DuckDuckGo (no API key needed).
Following tool-first architecture: cheap search, LLM only for summarization.
"""

import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# DuckDuckGo search
try:
    from duckduckgo_search import DDGS
    HAS_DDGS = True
except ImportError:
    HAS_DDGS = False
    logger.warning("duckduckgo-search not installed - live search disabled")


class LiveSearch:
    """
    Real-time web search using DuckDuckGo.
    
    No API key required - uses DuckDuckGo's free search.
    Respects rate limits and caches results.
    """
    
    def __init__(self, max_results: int = 5):
        """
        Initialize live search.
        
        Args:
            max_results: Default number of results to return
        """
        self.max_results = max_results
        self._cache: Dict[str, List[Dict]] = {}
        
    @property
    def is_available(self) -> bool:
        """Check if search is available."""
        return HAS_DDGS
    
    def search(self, query: str, max_results: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Search the web for a query.
        
        Args:
            query: Search query
            max_results: Number of results (default: self.max_results)
            
        Returns:
            List of search results with title, url, body
        """
        if not HAS_DDGS:
            logger.warning("DuckDuckGo search not available")
            return []
            
        max_results = max_results or self.max_results
        
        # Check cache
        cache_key = f"{query}:{max_results}"
        if cache_key in self._cache:
            logger.debug(f"Returning cached results for: {query}")
            return self._cache[cache_key]
        
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))
                
            # Format results
            formatted = []
            for r in results:
                formatted.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", r.get("link", "")),
                    "snippet": r.get("body", r.get("snippet", "")),
                })
            
            # Cache results
            self._cache[cache_key] = formatted
            
            logger.info(f"Search '{query}': {len(formatted)} results")
            return formatted
            
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []
    
    def search_news(self, query: str, max_results: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Search for news articles.
        
        Args:
            query: Search query
            max_results: Number of results
            
        Returns:
            List of news results
        """
        if not HAS_DDGS:
            return []
            
        max_results = max_results or self.max_results
        
        try:
            with DDGS() as ddgs:
                results = list(ddgs.news(query, max_results=max_results))
                
            formatted = []
            for r in results:
                formatted.append({
                    "title": r.get("title", ""),
                    "url": r.get("url", r.get("link", "")),
                    "snippet": r.get("body", ""),
                    "date": r.get("date", ""),
                    "source": r.get("source", ""),
                })
            
            logger.info(f"News search '{query}': {len(formatted)} results")
            return formatted
            
        except Exception as e:
            logger.error(f"News search failed: {e}")
            return []
    
    def format_results(self, results: List[Dict], include_urls: bool = True) -> str:
        """
        Format search results for display/TTS.
        
        Args:
            results: List of search results
            include_urls: Whether to include URLs
            
        Returns:
            Formatted string
        """
        if not results:
            return "No results found."
            
        lines = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "No title")
            snippet = r.get("snippet", "")
            url = r.get("url", "")
            
            if include_urls:
                lines.append(f"{i}. {title}\n   {snippet}\n   Link: {url}")
            else:
                lines.append(f"{i}. {title}: {snippet}")
                
        return "\n\n".join(lines)
    
    def clear_cache(self):
        """Clear search cache."""
        self._cache.clear()


# Global instance
_search: Optional[LiveSearch] = None


def get_live_search() -> LiveSearch:
    """Get or create the global search instance."""
    global _search
    if _search is None:
        _search = LiveSearch()
    return _search


def web_search(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """Convenience function for web search."""
    return get_live_search().search(query, max_results)
