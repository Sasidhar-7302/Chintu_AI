"""
Search module for Chintu AI Assistant.
Provides web search and deep research capabilities.
"""

from .web_search import WebSearchEngine, search_web, search_news
from .search_capabilities import register_search_capabilities
from .deep_search import deep_search, register_deep_search_capability

__all__ = [
    "WebSearchEngine",
    "search_web",
    "search_news",
    "deep_search",
    "register_search_capabilities",
    "register_deep_search_capability",
]
