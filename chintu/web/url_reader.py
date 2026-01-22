"""
URL Reader for Chintu AI Assistant.

Fetches and extracts readable content from web pages.
Uses readability-lxml for intelligent content extraction.
"""

import logging
import re
from typing import Optional, Dict, Any, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# HTTP requests
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    logger.warning("requests not installed")

# HTML parsing
try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False
    logger.warning("beautifulsoup4 not installed")

# Readability for smart extraction
try:
    from readability import Document as ReadabilityDocument
    HAS_READABILITY = True
except ImportError:
    HAS_READABILITY = False


class URLReader:
    """
    Reads and extracts content from web pages.
    
    Uses multiple strategies:
    1. Readability (best for articles)
    2. BeautifulSoup (fallback)
    3. Raw text (last resort)
    """
    
    # User agent to avoid blocks
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    
    # Timeout for requests
    TIMEOUT = 10
    
    def __init__(self, llm_client=None):
        """
        Initialize URL reader.
        
        Args:
            llm_client: Optional LLM for summarization
        """
        self.llm = llm_client
        self._cache: Dict[str, Tuple[str, Dict]] = {}
        
    @property
    def is_available(self) -> bool:
        """Check if URL reading is available."""
        return HAS_REQUESTS and HAS_BS4
    
    def fetch(self, url: str) -> Tuple[str, Dict[str, Any]]:
        """
        Fetch and extract content from a URL.
        
        Args:
            url: URL to fetch
            
        Returns:
            Tuple of (text_content, metadata)
        """
        if not HAS_REQUESTS:
            raise ImportError("requests is not installed")
            
        # Check cache
        if url in self._cache:
            logger.debug(f"Returning cached content for: {url}")
            return self._cache[url]
        
        # Fetch page
        try:
            response = requests.get(
                url,
                headers={"User-Agent": self.USER_AGENT},
                timeout=self.TIMEOUT,
                allow_redirects=True,
            )
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Failed to fetch {url}: {e}")
            raise RuntimeError(f"Could not access the page: {e}")
        
        html = response.text
        content_type = response.headers.get("Content-Type", "")
        
        # Build metadata
        metadata = {
            "url": url,
            "domain": urlparse(url).netloc,
            "status_code": response.status_code,
            "content_type": content_type,
        }
        
        # Extract content
        if "text/html" in content_type:
            text, title = self._extract_html(html)
            metadata["title"] = title
        else:
            # Plain text or other
            text = html
            metadata["title"] = urlparse(url).path.split("/")[-1] or "Untitled"
        
        metadata["char_count"] = len(text)
        metadata["word_count"] = len(text.split())
        
        # Cache result
        self._cache[url] = (text, metadata)
        
        logger.info(f"Fetched {url}: {metadata['word_count']} words")
        return text, metadata
    
    def _extract_html(self, html: str) -> Tuple[str, str]:
        """
        Extract readable content from HTML.
        
        Returns:
            Tuple of (text, title)
        """
        title = "Untitled"
        
        # Try readability first (best for articles)
        if HAS_READABILITY:
            try:
                doc = ReadabilityDocument(html)
                title = doc.title() or "Untitled"
                summary_html = doc.summary()
                
                # Clean extracted HTML
                if HAS_BS4:
                    soup = BeautifulSoup(summary_html, "html.parser")
                    text = soup.get_text(separator="\n", strip=True)
                else:
                    # Basic HTML stripping
                    text = re.sub(r'<[^>]+>', ' ', summary_html)
                    text = re.sub(r'\s+', ' ', text).strip()
                
                if len(text) > 100:  # Good extraction
                    return text, title
            except Exception as e:
                logger.debug(f"Readability failed: {e}")
        
        # Fallback to BeautifulSoup
        if HAS_BS4:
            soup = BeautifulSoup(html, "html.parser")
            
            # Get title
            title_tag = soup.find("title")
            if title_tag:
                title = title_tag.get_text(strip=True)
            
            # Remove script, style, nav, footer, etc.
            for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'iframe', 'noscript']):
                tag.decompose()
            
            # Try to find main content
            main = soup.find('main') or soup.find('article') or soup.find(class_=re.compile(r'content|article|post'))
            if main:
                text = main.get_text(separator="\n", strip=True)
            else:
                # Fallback to body
                body = soup.find('body')
                text = body.get_text(separator="\n", strip=True) if body else soup.get_text(separator="\n", strip=True)
            
            # Clean up excessive whitespace
            text = re.sub(r'\n{3,}', '\n\n', text)
            
            return text, title
        
        # Last resort: basic regex
        title_match = re.search(r'<title[^>]*>([^<]+)</title>', html, re.IGNORECASE)
        if title_match:
            title = title_match.group(1).strip()
        
        text = re.sub(r'<[^>]+>', ' ', html)
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text, title
    
    def summarize(self, text: str, max_length: int = 500) -> str:
        """
        Summarize web page content using LLM.
        
        Args:
            text: Page content
            max_length: Max summary length
            
        Returns:
            Summary text
        """
        if not self.llm:
            # No LLM - return first portion
            if len(text) <= max_length:
                return text
            return text[:max_length] + "..."
        
        prompt = f"""Summarize this web page content concisely. 
Focus on the main points. Keep it under {max_length} characters.

CONTENT:
{text[:8000]}

SUMMARY:"""

        try:
            return self.llm.generate(prompt).strip()
        except Exception as e:
            logger.warning(f"LLM summarization failed: {e}")
            return text[:max_length] + "..." if len(text) > max_length else text
    
    def clear_cache(self):
        """Clear URL cache."""
        self._cache.clear()


# Global instance
_reader: Optional[URLReader] = None


def get_url_reader(llm_client=None) -> URLReader:
    """Get or create the global URL reader."""
    global _reader
    if _reader is None:
        _reader = URLReader(llm_client)
    elif llm_client and not _reader.llm:
        _reader.llm = llm_client
    return _reader


def fetch_url(url: str) -> Tuple[str, Dict[str, Any]]:
    """Convenience function to fetch a URL."""
    return get_url_reader().fetch(url)
