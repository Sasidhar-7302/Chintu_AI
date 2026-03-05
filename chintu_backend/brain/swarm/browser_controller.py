
"""
Browser Controller: Abstraction layer for Web Automation.
Currently wraps 'search_web' and 'read_url' (Level 1).
Designed to be swapped with Playwright/Selenium (Level 2) seamlessly.
"""
import logging
import time
from typing import List, Dict, Any, Optional
from chintu_backend.search.search_capabilities import handle_web_search
# Note: read_url logic might need to be imported or re-implemented if not exposed.
# For now, we will use a simple request wrapper if needed, or rely on search snippets.
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

class BrowserController:
    def __init__(self):
        self.session = requests.Session()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

    def search(self, query: str) -> List[Dict[str, str]]:
        """
        Perform a Google search (or equivalent) and return organic results.
        Returns: List of {title, link, snippet, price}
        """
        try:
            # reuse existing capability
            res = handle_web_search(query, {})
            # Parse ActionResult
            if hasattr(res, 'data') and res.data:
                 if isinstance(res.data, list):
                     return res.data # Assuming list of dicts
                 # If string, we might need to parse, but handle_web_search usually returns list for "search_web"
            return []
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []

    def navigate(self, url: str) -> str:
        """
        Visit a page and return its text content (and extracted price if possible).
        """
        try:
            resp = self.session.get(url, headers=self.headers, timeout=10)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.content, "html.parser")
            
            # Simple Text Extraction
            text = soup.get_text(separator=' ', strip=True)
            return text[:10000] # Limit context
        except Exception as e:
            logger.error(f"Nav failed {url}: {e}")
            return ""

    def extract_price(self, content: str) -> Optional[str]:
        # Simple heuristic or regex
        import re
        match = re.search(r'\$\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)', content)
        if match:
            return match.group(0)
        return None

    def click(self, selector: str):
        logger.info(f"Clicking {selector} (Simulated)")
        # In Playwright, this would actually click.
        pass
        
    def type(self, selector: str, text: str):
        logger.info(f"Typing '{text}' into {selector} (Simulated)")
        pass
