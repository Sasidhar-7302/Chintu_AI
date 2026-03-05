"""
Browser Controller for Chintu AI Assistant.
Provides browser automation using Playwright with async support.
"""

import asyncio
import logging
import re
import time
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
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
    
    def __init__(self, headless: bool = True, profile_name: Optional[str] = None):
        """
        Initialize browser controller.
        
        Args:
            headless: Run in headless mode (no visible window)
        """
        self._headless = headless
        self._profile_name = profile_name
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._available = False
        self._lock = threading.Lock()
        self._last_structured_dom = None
        
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

    @property
    def profile_name(self) -> Optional[str]:
        return self._profile_name
    
    def _ensure_browser(self):
        """Ensure browser is started."""
        if not self._available:
            raise RuntimeError("Playwright not available")

        with self._lock:
            # For persistent contexts, _browser is intentionally None. Use _context/_page as the "started" signal.
            if self._context is not None and self._page is not None:
                return

            from playwright.sync_api import sync_playwright
            from chintu_backend.core.config import get_config

            if self._playwright is None:
                self._playwright = sync_playwright().start()
                args = ['--disable-blink-features=AutomationControlled']
                viewport = {'width': 1280, 'height': 720}
                user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                if self._profile_name:
                    config = get_config()
                    profile_dir = Path(config.browser_profiles_dir) / self._profile_name
                    profile_dir.mkdir(parents=True, exist_ok=True)
                    launch_kwargs = {
                        "user_data_dir": str(profile_dir),
                        "headless": self._headless,
                        "args": args,
                        "viewport": viewport,
                        "user_agent": user_agent,
                    }
                    # If user points Chintu to native Chrome user-data, prefer Chrome channel.
                    # This improves compatibility with existing human-created Chrome profiles.
                    profiles_root = str(config.browser_profiles_dir or "").lower()
                    prefer_chrome_channel = "google\\chrome\\user data" in profiles_root
                    if prefer_chrome_channel:
                        try:
                            self._context = self._playwright.chromium.launch_persistent_context(
                                channel="chrome",
                                **launch_kwargs,
                            )
                        except Exception:
                            self._context = self._playwright.chromium.launch_persistent_context(
                                **launch_kwargs,
                            )
                    else:
                        self._context = self._playwright.chromium.launch_persistent_context(
                            **launch_kwargs,
                        )
                    pages = self._context.pages
                    self._page = pages[0] if pages else self._context.new_page()
                    self._browser = None
                else:
                    self._browser = self._playwright.chromium.launch(
                        headless=self._headless,
                        args=args
                    )
                    self._context = self._browser.new_context(
                        viewport=viewport,
                        user_agent=user_agent
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

    def get_page_html(self, max_chars: int = 400_000) -> str:
        """Return the current page HTML (best-effort).

        This is primarily used for deterministic parsers that need raw DOM, such as
        Deal Finder's Playwright fallback when Requests is blocked.
        """
        self._ensure_browser()

        if not self._page.url or self._page.url == "about:blank":
            return ""

        html = self._page.content()
        if not isinstance(html, str):
            return ""
        if max_chars and len(html) > int(max_chars):
            return html[: int(max_chars)]
        return html
    
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
            target_text = (text or "").strip()
            if not target_text:
                return False

            # Try common interactive elements first (fast-path).
            selectors = [
                f'a:has-text("{target_text}")',
                f'button:has-text("{target_text}")',
                f'[role=\"button\"]:has-text("{target_text}")',
                f'[role=\"link\"]:has-text("{target_text}")',
            ]
            for selector in selectors:
                try:
                    element = self._page.query_selector(selector)
                    if element:
                        element.click()
                        self._wait_with_timeout(timeout_ms=5000)
                        logger.info(f"Clicked element ({selector}): {target_text}")
                        self._last_structured_dom = None
                        return True
                except Exception:
                    continue

            # Structured DOM fallback: find best interactive ref by visible text and click it.
            ref = self._best_text_match_ref(target_text)
            if ref:
                acted = self.act_by_ref(ref, action="click", screenshot_after=False)
                if acted.get("success"):
                    return True

            logger.warning(f"No clickable element found with text: {target_text}")
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
                self.wait_for_selector(selector_or_label, timeout_ms=3500)
                logger.info(f"Filled input: {selector_or_label}")
                return True
            else:
                logger.warning(f"No input found: {selector_or_label}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to fill input: {e}")
            return False

    def click_text_force(self, target_text: str) -> bool:
        """Force-click a visible element by text/aria-label, including shadow DOM."""
        self._ensure_browser()
        text = str(target_text or "").strip()
        if not text:
            return False
        try:
            script = """
            (target) => {
              const want = String(target || '').toLowerCase().trim();
              if (!want) return false;
              const isVisible = (el) => {
                try {
                  const r = el.getBoundingClientRect();
                  const s = window.getComputedStyle(el);
                  return !!(r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none');
                } catch { return false; }
              };
              const walker = [];
              const pushChildren = (root) => {
                if (!root) return;
                const list = root.querySelectorAll ? root.querySelectorAll('*') : [];
                for (const el of list) walker.push(el);
              };
              pushChildren(document);
              for (let i = 0; i < walker.length; i++) {
                const el = walker[i];
                if (el && el.shadowRoot) pushChildren(el.shadowRoot);
              }
              const score = (el) => {
                const t = (el.innerText || '').toLowerCase().trim();
                const a = (el.getAttribute && (el.getAttribute('aria-label') || '') || '').toLowerCase().trim();
                let s = 0;
                if (t === want || a === want) s += 10;
                if (t.includes(want) || a.includes(want)) s += 5;
                if (el.tagName === 'BUTTON' || el.tagName === 'A') s += 2;
                if (el.getAttribute && el.getAttribute('role') === 'button') s += 2;
                return s;
              };
              let best = null;
              let bestScore = 0;
              for (const el of walker) {
                if (!el || !isVisible(el)) continue;
                const s = score(el);
                if (s > bestScore) { best = el; bestScore = s; }
              }
              if (!best) return false;
              best.scrollIntoView({block: 'center', inline: 'center'});
              best.click();
              return true;
            }
            """
            ok = bool(self._page.evaluate(script, text))
            if ok:
                try:
                    self._page.wait_for_load_state("domcontentloaded", timeout=8000)
                except Exception:
                    pass
                self._last_structured_dom = None
            return ok
        except Exception:
            return False

    def click_popup_button_exact(self, label: str) -> bool:
        """Click a visible popup/dialog button by exact label text."""
        self._ensure_browser()
        target = str(label or "").strip()
        if not target:
            return False
        try:
            script = """
            (label) => {
              const want = String(label || '').trim().toLowerCase();
              if (!want) return false;
              const norm = (s) => String(s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
              const isVisible = (el) => {
                try {
                  const r = el.getBoundingClientRect();
                  const s = window.getComputedStyle(el);
                  return !!(r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none');
                } catch { return false; }
              };
              const roots = [document];
              const all = [];
              for (let i = 0; i < roots.length; i++) {
                const root = roots[i];
                if (!root || !root.querySelectorAll) continue;
                const nodes = root.querySelectorAll('*');
                for (const node of nodes) {
                  all.push(node);
                  if (node.shadowRoot) roots.push(node.shadowRoot);
                }
              }
              const matches = [];
              for (const el of all) {
                if (!el || !isVisible(el)) continue;
                const tag = String(el.tagName || '').toLowerCase();
                const role = String(el.getAttribute?.('role') || '').toLowerCase();
                if (!(tag === 'button' || role === 'button')) continue;
                const text = norm(el.innerText || el.textContent || el.getAttribute?.('aria-label') || '');
                if (text !== want) continue;
                let score = 0;
                const inDialog = el.closest('ytd-channel-creation-dialog-renderer, [role=\"dialog\"], tp-yt-paper-dialog, ytd-popup-container');
                if (inDialog) score += 5;
                const r = el.getBoundingClientRect();
                score += Math.max(0, 2000 - Math.abs((window.innerHeight * 0.65) - (r.top + r.height / 2))) / 2000;
                matches.push({ el, score });
              }
              if (!matches.length) return false;
              matches.sort((a, b) => b.score - a.score);
              const targetEl = matches[0].el;
              targetEl.scrollIntoView({ block: 'center', inline: 'center' });
              targetEl.click();
              return true;
            }
            """
            ok = bool(self._page.evaluate(script, target))
            if ok:
                self._wait_with_timeout(timeout_ms=5000)
                self._last_structured_dom = None
            return ok
        except Exception:
            return False

    def wait_for_selector(self, selector: str, timeout_ms: int = 5000) -> bool:
        """Wait for selector visibility with a hard timeout."""
        self._ensure_browser()
        target = str(selector or "").strip()
        if not target:
            return False
        try:
            self._page.wait_for_selector(target, state="visible", timeout=max(500, int(timeout_ms)))
            return True
        except Exception:
            return False

    def wait_for_text(self, text: str, timeout_ms: int = 5000) -> bool:
        """Wait for text to appear with a hard timeout."""
        self._ensure_browser()
        token = str(text or "").strip()
        if not token:
            return False
        deadline = time.time() + (max(500, int(timeout_ms)) / 1000.0)
        while time.time() < deadline:
            try:
                body_text = self._page.inner_text("body")
                if token.lower() in str(body_text or "").lower():
                    return True
            except Exception:
                pass
            try:
                self._page.wait_for_timeout(150)
            except Exception:
                time.sleep(0.15)
        return False

    def wait_for_ref_visible(self, ref: str, timeout_ms: int = 5000) -> bool:
        """Wait for an element ref from current snapshot to be visible."""
        self._ensure_browser()
        target = str(ref or "").strip()
        if not target:
            return False
        if self._last_structured_dom is None:
            self.snapshot_structured()
        element = self._last_structured_dom.get_by_ref(target) if self._last_structured_dom else None
        if not element:
            return False
        selector = str(getattr(element, "selector", "") or "").strip()
        if selector and self.wait_for_selector(selector, timeout_ms=timeout_ms):
            return True
        try:
            locator = self._get_locator_for_dom_element(element)
            locator.wait_for(state="visible", timeout=max(500, int(timeout_ms)))
            return True
        except Exception:
            return False

    def _wait_with_timeout(self, timeout_ms: int = 5000, ref_hint: Optional[str] = None) -> bool:
        """SPA-safe post-action wait: bounded wait_for_load_state + optional ref wait."""
        self._ensure_browser()
        deadline = time.time() + (max(500, int(timeout_ms)) / 1000.0)
        ref_name = str(ref_hint or "").strip()
        while time.time() < deadline:
            try:
                self._page.wait_for_load_state("domcontentloaded", timeout=700)
            except Exception:
                pass
            if ref_name:
                if self.wait_for_ref_visible(ref_name, timeout_ms=700):
                    return True
            else:
                return True
            try:
                self._page.wait_for_timeout(120)
            except Exception:
                time.sleep(0.12)
        return False

    def fill_visible_textbox(self, value: str, hint: str = "") -> bool:
        """Fill first visible textbox/contenteditable, including shadow DOM."""
        self._ensure_browser()
        val = str(value or "")
        if not val:
            return False
        try:
            script = """
            ({value, hint}) => {
              const want = String(hint || '').toLowerCase().trim();
              const isVisible = (el) => {
                try {
                  const r = el.getBoundingClientRect();
                  const s = window.getComputedStyle(el);
                  return !!(r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none');
                } catch { return false; }
              };
              const all = [];
              const add = (root) => {
                if (!root || !root.querySelectorAll) return;
                for (const el of root.querySelectorAll('*')) all.push(el);
              };
              add(document);
              for (let i = 0; i < all.length; i++) {
                const el = all[i];
                if (el && el.shadowRoot) add(el.shadowRoot);
              }
              const candidates = [];
              for (const el of all) {
                if (!el || !isVisible(el)) continue;
                const tag = (el.tagName || '').toLowerCase();
                const role = (el.getAttribute && el.getAttribute('role') || '').toLowerCase();
                const isInput = tag === 'input' || tag === 'textarea' || role === 'textbox' || el.isContentEditable;
                if (!isInput) continue;
                const ph = (el.getAttribute && (el.getAttribute('placeholder') || '') || '').toLowerCase();
                const aria = (el.getAttribute && (el.getAttribute('aria-label') || '') || '').toLowerCase();
                let s = 1;
                if (want && (ph.includes(want) || aria.includes(want))) s += 5;
                candidates.push([s, el]);
              }
              candidates.sort((a,b)=>b[0]-a[0]);
              if (!candidates.length) return false;
              const el = candidates[0][1];
              el.focus();
              if (el.isContentEditable) {
                el.innerText = String(value || '');
              } else {
                el.value = String(value || '');
              }
              el.dispatchEvent(new Event('input', { bubbles: true }));
              el.dispatchEvent(new Event('change', { bubbles: true }));
              return true;
            }
            """
            return bool(self._page.evaluate(script, {"value": val, "hint": str(hint or "")}))
        except Exception:
            return False

    def google_sign_in(self, email: str, password: str, timeout_ms: int = 20000) -> Dict[str, Any]:
        """Best-effort Google sign-in in the current page/session.

        Keeps the same persistent browser context/profile so subsequent
        YouTube actions continue in one session.
        """
        self._ensure_browser()
        try:
            if "accounts.google.com" not in str(getattr(self._page, "url", "") or "").lower():
                self._page.goto(
                    "https://accounts.google.com/signin/v2/identifier?service=youtube",
                    wait_until="domcontentloaded",
                    timeout=timeout_ms,
                )

            # Email step
            self._page.wait_for_selector("input[type='email']", timeout=timeout_ms)
            self._page.fill("input[type='email']", str(email or "").strip())
            clicked_next = False
            for selector in ("#identifierNext", "#identifierNext button", "button:has-text('Next')"):
                try:
                    self._page.click(selector, timeout=3000)
                    clicked_next = True
                    break
                except Exception:
                    continue
            if not clicked_next:
                self._page.keyboard.press("Enter")

            # Password step
            self._page.wait_for_selector("input[type='password']", timeout=timeout_ms)
            self._page.fill("input[type='password']", str(password or "").strip())
            clicked_submit = False
            for selector in ("#passwordNext", "#passwordNext button", "button:has-text('Next')"):
                try:
                    self._page.click(selector, timeout=3000)
                    clicked_submit = True
                    break
                except Exception:
                    continue
            if not clicked_submit:
                self._page.keyboard.press("Enter")

            try:
                self._page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
            except Exception:
                pass
            try:
                self._page.wait_for_timeout(2000)
            except Exception:
                pass

            current_url = str(getattr(self._page, "url", "") or "")
            low = current_url.lower()
            needs_user_action = any(token in low for token in ("accounts.google.com", "challenge", "signin"))
            return {
                "success": True,
                "url": current_url,
                "needs_user_action": needs_user_action,
            }
        except Exception as exc:
            return {"success": False, "error": str(exc), "url": str(getattr(self._page, "url", "") or "")}

    # ------------------------------------------------------------------
    # Structured DOM snapshots + ref-based actions (reference-style)
    # ------------------------------------------------------------------
    def snapshot_structured(self):
        """Return a StructuredDOM snapshot with stable refs for interactive elements."""
        self._ensure_browser()

        from chintu_backend.tools.browser.structured_dom import DOMParser

        try:
            title = self._page.title() or "Untitled"
        except Exception:
            title = "Untitled"

        try:
            ax_tree = self._page.accessibility.snapshot()
        except Exception:
            ax_tree = None

        parser = DOMParser()
        try:
            if ax_tree:
                dom = parser.parse_from_playwright(ax_tree, url=self._page.url, title=title)
            else:
                html = self._page.content()
                dom = parser.parse_from_html(html, url=self._page.url, title=title)
        except Exception:
            # Never hard-fail: keep automation usable even if snapshots break.
            html = ""
            try:
                html = self._page.content()
            except Exception:
                html = ""
            dom = parser.parse_from_html(html, url=self._page.url, title=title)

        self._last_structured_dom = dom
        return dom

    def list_interactive_elements(self, max_elements: int = 60) -> Dict[str, Any]:
        """List interactive elements as lightweight dicts for LLM consumption."""
        dom = self.snapshot_structured()
        elems = [e.to_dict() for e in dom.get_interactive()][: max(1, int(max_elements))]
        return {
            "url": dom.url,
            "title": dom.title,
            "interactive_count": len(dom.get_interactive()),
            "elements": elems,
            "summary": dom.to_summary(max_elements=max(1, int(max_elements))),
        }

    def act_by_ref(
        self,
        ref: str,
        *,
        action: str = "click",
        value: Optional[str] = None,
        screenshot_after: bool = True,
    ) -> Dict[str, Any]:
        """Perform an action on an element by its ref from the last snapshot."""
        self._ensure_browser()

        ref = (ref or "").strip()
        action = (action or "click").strip().lower()
        if not ref:
            return {"success": False, "error": "ref is required"}

        if self._last_structured_dom is None:
            self.snapshot_structured()

        dom = self._last_structured_dom
        element = dom.get_by_ref(ref) if dom else None
        if not element:
            return {"success": False, "error": f"Unknown ref: {ref}"}

        try:
            locator = self._get_locator_for_dom_element(element)
        except Exception as exc:
            return {"success": False, "error": f"Locator error: {exc}"}

        selector_wait_hint = ""
        try:
            selector_wait_hint = str(getattr(element, "selector", "") or "").strip()
        except Exception:
            selector_wait_hint = ""

        try:
            if action == "click":
                locator.click()
            elif action == "type":
                locator.type(value or "")
            elif action == "fill":
                locator.fill(value or "")
            elif action == "select":
                locator.select_option(value)
            elif action == "check":
                locator.check()
            elif action == "uncheck":
                locator.uncheck()
            elif action == "hover":
                locator.hover()
            elif action == "focus":
                locator.focus()
            elif action == "scroll":
                locator.scroll_into_view_if_needed()
            elif action == "press":
                locator.press(value or "Enter")
            else:
                return {"success": False, "error": f"Unknown action: {action}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

        wait_ok = False
        if selector_wait_hint:
            wait_ok = self.wait_for_selector(selector_wait_hint, timeout_ms=5000)
        if not wait_ok:
            wait_ok = self._wait_with_timeout(timeout_ms=5000, ref_hint=ref)

        screenshot = None
        if screenshot_after:
            try:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                safe_ref = re.sub(r"[^a-zA-Z0-9_\\-]+", "_", ref)[:40]
                filename = f"after_{safe_ref}_{action}_{timestamp}.png"
                screenshot = self.take_screenshot(filename)
            except Exception:
                screenshot = None

        # Invalidate cached snapshot after any action.
        self._last_structured_dom = None

        return {
            "success": True,
            "ref": ref,
            "action": action,
            "url": getattr(self._page, "url", "") or "",
            "title": self._page.title() if self._page else "",
            "screenshot": screenshot,
            "wait_ok": wait_ok,
        }

    def _get_locator_for_dom_element(self, element):
        """Best-effort locator builder for DOMElement."""
        attrs = getattr(element, "attributes", {}) or {}
        try:
            data_testid = attrs.get("data-testid") or attrs.get("data_testid")
            if data_testid:
                return self._page.locator(f"[data-testid='{data_testid}']")
        except Exception:
            pass

        try:
            el_id = attrs.get("id")
            if el_id:
                return self._page.locator(f"#{el_id}")
        except Exception:
            pass

        try:
            name = attrs.get("name")
            if name:
                return self._page.locator(f"[name='{name}']")
        except Exception:
            pass

        role = str(attrs.get("role") or "").strip().lower()
        text = str(getattr(element, "text", "") or "").strip()
        if role and text:
            try:
                return self._page.get_by_role(role, name=text[:60])
            except Exception:
                pass

        # Fallback: use a coarse CSS selector (may match multiple elements).
        selector = getattr(element, "selector", None)
        if selector:
            loc = self._page.locator(str(selector))
            # If the ref ends with _N (N>=2), best-effort select the Nth match.
            try:
                ref = str(getattr(element, "ref", "") or "")
                m = re.search(r"_(\\d+)$", ref)
                if m:
                    idx = max(0, int(m.group(1)) - 1)
                    return loc.nth(idx)
            except Exception:
                pass
            return loc.first
        return self._page.locator("body")

    def _best_text_match_ref(self, target_text: str) -> Optional[str]:
        """Return a best-effort interactive ref for target text."""
        try:
            dom = self.snapshot_structured()
            matches = dom.get_by_text(target_text, partial=True)
            interactive = [m for m in matches if getattr(m, "interactive", False) and getattr(m, "visible", True)]
            if not interactive:
                return None

            def _score(elem) -> Tuple[int, int]:
                role = getattr(elem, "role", None)
                role_value = getattr(role, "value", "") if role else ""
                role_bonus = 2 if role_value in {"button", "link"} else 1
                text_len = len(str(getattr(elem, "text", "") or ""))
                return (role_bonus, -text_len)

            interactive.sort(key=_score, reverse=True)
            return str(getattr(interactive[0], "ref", "") or "").strip() or None
        except Exception:
            return None
    
    def close(self):
        """Close the browser."""
        with self._lock:
            if self._context and not self._browser:
                try:
                    self._context.close()
                except Exception as e:
                    logger.warning(f"Failed to close browser context: {e}")
                self._context = None
                self._page = None
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
        # Keep browser sessions stable across task boundaries.
        # Do not auto-close on object finalization; explicit close() or
        # process exit should own lifecycle.
        try:
            pass
        except Exception:
            pass


# Global instance
_browser_controllers: Dict[Tuple[Optional[str], bool], BrowserController] = {}


def _resolve_profile_name(profile_name: Optional[str], headless: bool) -> Optional[str]:
    """Resolve default profile for interactive sessions.

    We prefer a persistent logged-in profile for non-headless flows so Chintu
    can continue navigation instead of opening fresh ephemeral browser sessions.
    """
    raw = str(profile_name or "").strip()
    if raw:
        return raw
    if bool(headless):
        return None
    try:
        from chintu_backend.core.config import get_config

        cfg = get_config()
        default_enabled = bool(getattr(cfg, "browser_default_profile_enabled", True))
        if not default_enabled:
            return None
        preferred = str(
            getattr(cfg, "research_browser_loggedin_profile", "")
            or getattr(cfg, "research_browser_default_profile", "")
            or ""
        ).strip()
        return preferred or None
    except Exception:
        return None


def get_browser_controller(headless: bool = True, profile_name: Optional[str] = None) -> BrowserController:
    """Get the browser controller instance for a given profile."""
    resolved_profile = _resolve_profile_name(profile_name, headless)
    key = (resolved_profile, headless)
    controller = _browser_controllers.get(key)
    if controller is None:
        controller = BrowserController(headless=headless, profile_name=resolved_profile)
        _browser_controllers[key] = controller
    return controller


def get_open_browser_controller(headless: bool = False, profile_name: Optional[str] = None) -> Optional[BrowserController]:
    """Return an already-open controller when available.

    Preference order:
    1) exact resolved profile + headless match
    2) any open controller with same headless mode
    """
    resolved_profile = _resolve_profile_name(profile_name, headless)
    exact = _browser_controllers.get((resolved_profile, headless))
    if exact and exact.is_open:
        return exact
    for (cached_profile, cached_headless), controller in _browser_controllers.items():
        if cached_headless != headless:
            continue
        if controller and controller.is_open:
            return controller
    return None


def close_all_browser_controllers() -> None:
    """Explicitly close all cached controllers (useful at app shutdown)."""
    items = list(_browser_controllers.items())
    _browser_controllers.clear()
    for _key, controller in items:
        try:
            controller.close()
        except Exception:
            continue
