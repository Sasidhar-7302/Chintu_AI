"""Browser-as-model fallback using Playwright CDP connection."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from chintu_backend.core.config import get_config

logger = logging.getLogger(__name__)

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except Exception:
    PLAYWRIGHT_AVAILABLE = False


@dataclass
class BrowserFallbackResult:
    response_text: str
    source_url: str


class BrowserFallbackAgent:
    """Drive an authenticated browser session to fetch higher-intelligence answers."""

    def __init__(
        self,
        cdp_url: Optional[str] = None,
        target_url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ):
        config = get_config()
        self.cdp_url = cdp_url or config.browser_cdp_url
        self.target_url = target_url or config.browser_fallback_url
        self.timeout_seconds = timeout_seconds or config.browser_fallback_timeout_seconds

    @property
    def is_available(self) -> bool:
        return PLAYWRIGHT_AVAILABLE

    def ask(self, prompt: str) -> BrowserFallbackResult:
        if not self.is_available:
            raise RuntimeError(
                "Playwright is not available. Install with: pip install playwright && playwright install chromium"
            )
        if not prompt:
            raise ValueError("prompt is required")

        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(self.cdp_url)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(self.timeout_seconds * 1000)
            page.goto(self.target_url)

            input_box = page.query_selector("textarea")
            if not input_box:
                input_box = page.query_selector("[contenteditable='true']")
            if not input_box:
                raise RuntimeError("Could not locate a prompt input on the page.")

            input_box.fill(prompt)
            input_box.press("Enter")

            response_text = self._wait_for_response(page)
            return BrowserFallbackResult(response_text=response_text, source_url=page.url)

    def _wait_for_response(self, page) -> str:
        selectors = [
            "div[data-message-author-role='assistant']",
            "div.markdown",
        ]
        for selector in selectors:
            try:
                page.wait_for_selector(selector)
                elements = page.query_selector_all(selector)
                if elements:
                    text = elements[-1].inner_text().strip()
                    if text:
                        return text
            except Exception:
                continue
        raise RuntimeError("No assistant response detected on the page.")

    def health_check(self) -> tuple[bool, str]:
        """
        Check if browser fallback is available and working.

        Returns:
            Tuple of (is_healthy, message)
        """
        if not PLAYWRIGHT_AVAILABLE:
            return False, "Playwright not installed. Run: pip install playwright && playwright install chromium"

        def _run_check():
            try:
                with sync_playwright() as p:
                    browser = p.chromium.connect_over_cdp(self.cdp_url)
                    if browser.contexts:
                        return True, f"Browser connected via CDP at {self.cdp_url}"
                    return True, "Browser connected but no contexts available"
            except Exception as e:
                return False, (
                    f"Cannot connect to browser: {e}. "
                    "Start Chrome with: chrome.exe --remote-debugging-port=9222"
                )

        # ALWAYS use timeout to prevent blocking startup indefinitely
        try:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_run_check)
                try:
                    return future.result(timeout=min(self.timeout_seconds, 5.0))  # Max 5s for health check
                except concurrent.futures.TimeoutError:
                    return False, f"Browser health check timed out after {min(self.timeout_seconds, 5.0)}s"
        except Exception as e:
            return False, f"Browser health check failed: {e}"

    def ask_with_retry(self, prompt: str, max_retries: int = 2) -> BrowserFallbackResult:
        """
        Ask with automatic retry on failure.

        Args:
            prompt: The question to ask
            max_retries: Maximum retry attempts

        Returns:
            BrowserFallbackResult with response
        """
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                return self.ask(prompt)
            except Exception as e:
                last_error = e
                logger.warning(f"Browser fallback attempt {attempt + 1} failed: {e}")
                if attempt < max_retries:
                    import time
                    time.sleep(1)  # Brief pause before retry

        raise RuntimeError(f"Browser fallback failed after {max_retries + 1} attempts: {last_error}")


def get_browser_fallback() -> BrowserFallbackAgent:
    """Get a browser fallback agent instance."""
    return BrowserFallbackAgent()
