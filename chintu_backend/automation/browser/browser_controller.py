"""
Browser Controller for Chintu AI Assistant.
Provides browser automation using Playwright with async support.
"""

import asyncio
import logging
import re
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime
import threading

logger = logging.getLogger(__name__)

# Screenshot save directory
SCREENSHOT_DIR = Path.home() / ".chintu" / "screenshots"


@dataclass
class PageInfo:
    """Information about the current page."""
    url: str
    title: str
    text_preview: str
    links_count: int


class BrowserController:
    """
    Controls a Chromium browser via Playwright.
    Runs in headless mode by default but can show UI.
    """
    
    def __init__(self, headless: bool = True):
        """
        Initialize browser controller.
        
        Args:
            headless: Run in headless mode (no visible window)
        """
        self._headless = headless
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._available = False
        self._lock = threading.Lock()
        
        # Create screenshot directory
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        
        self._check_availability()
    
    def _check_availability(self):
        """Check if Playwright is available."""
        try:
            from playwright.sync_api import sync_playwright
            self._available = True
            logger.info("Playwright browser automation available")
        except ImportError:
            logger.warning("Playwright not installed. Run: pip install playwright && playwright install chromium")
            self._available = False
    
    @property
    def is_available(self) -> bool:
        return self._available
    
    @property
    def is_open(self) -> bool:
        return self._page is not None
    
    def _ensure_browser(self):
        """Ensure browser is started."""
        if not self._available:
            raise RuntimeError("Playwright not available")
        
        with self._lock:
            if self._browser is None:
                from playwright.sync_api import sync_playwright
                self._playwright = sync_playwright().start()
                self._browser = self._playwright.chromium.launch(
                    headless=self._headless,
                    args=['--disable-blink-features=AutomationControlled']
                )
                self._context = self._browser.new_context(
                    viewport={'width': 1280, 'height': 720},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                )
                self._page = self._context.new_page()
                logger.info("Browser started")
    
    def open_url(self, url: str, wait_for: str = "load") -> PageInfo:
        """
        Navigate to a URL.
        
        Args:
            url: URL to open (auto-adds https:// if missing)
            wait_for: Wait strategy ('load', 'domcontentloaded', 'networkidle')
            
        Returns:
            PageInfo with title and text preview
        """
        self._ensure_browser()
        
        # Auto-add protocol
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        try:
            self._page.goto(url, wait_until=wait_for, timeout=30000)
            
            # Get page info
            title = self._page.title() or "Untitled"
            text = self._page.inner_text('body')[:500] if self._page.query_selector('body') else ""
            links = len(self._page.query_selector_all('a'))
            
            logger.info(f"Opened: {url} - {title}")
            
            return PageInfo(
                url=self._page.url,
                title=title,
                text_preview=text[:200],
                links_count=links
            )
            
        except Exception as e:
            logger.error(f"Failed to open URL: {e}")
            raise
    
    def search_google(self, query: str) -> PageInfo:
        """
        Search Google for a query.
        
        Args:
            query: Search query
            
        Returns:
            PageInfo with search results page
        """
        self._ensure_browser()
        
        # Go to Google
        self._page.goto('https://www.google.com', wait_until='networkidle')
        
        # Accept cookies if present
        try:
            accept_btn = self._page.query_selector('button:has-text("Accept")')
            if accept_btn:
                accept_btn.click()
        except Exception as e:
            logger.debug(f"Cookie accept failed: {e}")
        
        # Type search query
        search_input = self._page.query_selector('textarea[name="q"], input[name="q"]')
        if search_input:
            search_input.fill(query)
            search_input.press('Enter')
            self._page.wait_for_load_state('networkidle')
        
        return PageInfo(
            url=self._page.url,
            title=self._page.title(),
            text_preview=self._extract_search_results(),
            links_count=len(self._page.query_selector_all('a'))
        )
    
    def _extract_search_results(self) -> str:
        """Extract search results from Google page."""
        try:
            results = []
            # Get search result divs
            result_elements = self._page.query_selector_all('div.g')[:5]
            
            for i, elem in enumerate(result_elements, 1):
                try:
                    title_el = elem.query_selector('h3')
                    snippet_el = elem.query_selector('div[data-sncf], span[class*="st"]')
                    
                    title = title_el.inner_text() if title_el else "No title"
                    snippet = snippet_el.inner_text()[:150] if snippet_el else ""
                    
                    results.append(f"{i}. {title}: {snippet}")
                except Exception as e:
                    logger.debug(f"Result parse failed: {e}")
                    continue
            
            return "\n".join(results) if results else "Search results loaded"
        except Exception as e:
            return f"Results loaded (extraction failed: {e})"
    
    def take_screenshot(self, filename: Optional[str] = None) -> str:
        """
        Take a screenshot of the current page.
        
        Args:
            filename: Optional filename (auto-generated if not provided)
            
        Returns:
            Path to saved screenshot
        """
        self._ensure_browser()
        
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"screenshot_{timestamp}.png"
        
        filepath = SCREENSHOT_DIR / filename
        self._page.screenshot(path=str(filepath), full_page=False)
        
        logger.info(f"Screenshot saved: {filepath}")
        return str(filepath)
    
    def get_page_content(self, max_length: int = 3000) -> str:
        """
        Get the text content of the current page.
        
        Args:
            max_length: Maximum characters to return
            
        Returns:
            Page text content
        """
        self._ensure_browser()
        
        if not self._page.url or self._page.url == 'about:blank':
            return "No page is currently open."
        
        try:
            # Get main content
            text = self._page.inner_text('body')
            
            # Clean up whitespace
            text = re.sub(r'\n\s*\n', '\n\n', text)
            text = re.sub(r' +', ' ', text)
            
            if len(text) > max_length:
                text = text[:max_length] + f"\n\n... [Truncated - {len(text)} total characters]"
            
            return text
            
        except Exception as e:
            return f"Failed to get page content: {e}"
    
    def get_page_info(self) -> Optional[PageInfo]:
        """Get information about the current page."""
        if not self.is_open:
            return None
        
        try:
            return PageInfo(
                url=self._page.url,
                title=self._page.title() or "Untitled",
                text_preview=self._page.inner_text('body')[:200] if self._page.query_selector('body') else "",
                links_count=len(self._page.query_selector_all('a'))
            )
        except Exception as e:
            logger.warning(f"Failed to get page info: {e}")
            return None
    
    def click_link(self, text: str) -> bool:
        """
        Click a link containing the given text.
        
        Args:
            text: Text to search for in links
            
        Returns:
            True if link was clicked
        """
        self._ensure_browser()
        
        try:
            # Find link with matching text (case insensitive)
            link = self._page.query_selector(f'a:has-text("{text}")')
            if link:
                link.click()
                self._page.wait_for_load_state('networkidle')
                logger.info(f"Clicked link: {text}")
                return True
            else:
                logger.warning(f"No link found with text: {text}")
                return False
        except Exception as e:
            logger.error(f"Failed to click link: {e}")
            return False
    
    def fill_input(self, selector_or_label: str, value: str) -> bool:
        """
        Fill an input field.
        
        Args:
            selector_or_label: CSS selector or label text
            value: Value to fill
            
        Returns:
            True if successful
        """
        self._ensure_browser()
        
        try:
            # Try as CSS selector first
            element = self._page.query_selector(selector_or_label)
            
            # If not found, try finding by label
            if not element:
                label = self._page.query_selector(f'label:has-text("{selector_or_label}")')
                if label:
                    for_id = label.get_attribute('for')
                    if for_id:
                        element = self._page.query_selector(f'#{for_id}')
            
            # Try by placeholder
            if not element:
                element = self._page.query_selector(f'input[placeholder*="{selector_or_label}" i]')
            
            if element:
                element.fill(value)
                logger.info(f"Filled input: {selector_or_label}")
                return True
            else:
                logger.warning(f"No input found: {selector_or_label}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to fill input: {e}")
            return False
    
    def close(self):
        """Close the browser."""
        with self._lock:
            if self._browser:
                try:
                    self._browser.close()
                except Exception as e:
                    logger.warning(f"Failed to close browser: {e}")
                self._browser = None
                self._context = None
                self._page = None
            
            if self._playwright:
                try:
                    self._playwright.stop()
                except Exception as e:
                    logger.warning(f"Failed to stop playwright: {e}")
                self._playwright = None
        
        logger.info("Browser closed")
    
    def __del__(self):
        self.close()


# Global instance
_browser_controller: Optional[BrowserController] = None


def get_browser_controller(headless: bool = True) -> BrowserController:
    """Get the global browser controller instance."""
    global _browser_controller
    if _browser_controller is None:
        _browser_controller = BrowserController(headless=headless)
    return _browser_controller
