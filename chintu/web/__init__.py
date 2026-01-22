"""Web module for live search and URL reading."""

from .live_search import (
    LiveSearch,
    get_live_search,
    web_search,
)
from .url_reader import (
    URLReader,
    get_url_reader,
    fetch_url,
)

__all__ = [
    'LiveSearch',
    'get_live_search',
    'web_search',
    'URLReader', 
    'get_url_reader',
    'fetch_url',
]
