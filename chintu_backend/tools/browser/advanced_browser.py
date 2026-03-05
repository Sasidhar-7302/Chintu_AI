"""
Advanced Browser Controller - Playwright-level automation with refs.

Features:
- Structured DOM snapshots with element refs
- Profile isolation (cookies, sessions)
- act(ref="btn_submit") style commands
- Video recording
- Screenshot capture
"""

import asyncio
import logging
import time
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from chintu_backend.core.config import get_config

logger = logging.getLogger(__name__)


class BrowserAction(Enum):
    """Available browser actions."""
    CLICK = "click"
    TYPE = "type"
    FILL = "fill"
    SELECT = "select"
    CHECK = "check"
    UNCHECK = "uncheck"
    HOVER = "hover"
    FOCUS = "focus"
    SCROLL = "scroll"
    PRESS = "press"  # keyboard key


@dataclass
class ActionResult:
    """Result of a browser action."""
    success: bool
    action: BrowserAction
    ref: str
    message: str
    screenshot_path: Optional[Path] = None
    duration_ms: float = 0


@dataclass
class BrowserProfile:
    """Browser profile for session isolation."""
    name: str
    user_data_dir: Path
    cookies: List[Dict] = field(default_factory=list)
    local_storage: Dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class BrowserSession:
    """Active browser session."""
    id: str
    profile: BrowserProfile
    current_url: str = ""
    current_title: str = ""
    recording_path: Optional[Path] = None
    started_at: datetime = field(default_factory=datetime.now)


class AdvancedBrowserController:
    """
    Advanced browser automation with Playwright.
    
    Provides:
    - Structured DOM snapshots with element refs
    - Profile isolation for multiple sessions
    - Action execution via refs
    - Video recording
    - Screenshot capture
    """
    
    def __init__(self, profile: str = "default", headless: bool = True):
        self.config = get_config()
        self.profile_name = profile
        self.headless = headless
        
        # Directories
        self.profiles_dir = self.config.data_dir / "browser_profiles"
        self.screenshots_dir = self.config.data_dir / "screenshots"
        self.recordings_dir = self.config.data_dir / "recordings"
        
        for d in [self.profiles_dir, self.screenshots_dir, self.recordings_dir]:
            d.mkdir(parents=True, exist_ok=True)
        
        # Playwright objects
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        
        # State
        self._session: Optional[BrowserSession] = None
        self._last_snapshot = None
        self._recording = False
    
    # --- Session Management ---
    
    def launch(self, record_video: bool = False) -> BrowserSession:
        """
        Launch browser with the configured profile.
        
        Args:
            record_video: Whether to record the session
            
        Returns:
            BrowserSession object
        """
        import uuid
        
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError("Playwright not installed. Run: pip install playwright && playwright install chromium")
        
        # Setup profile
        profile = self._get_or_create_profile(self.profile_name)
        
        # Launch playwright
        self._playwright = sync_playwright().start()
        
        # Context options
        context_options = {
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        # Add video recording if requested
        if record_video:
            video_dir = self.recordings_dir / f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            video_dir.mkdir(parents=True, exist_ok=True)
            context_options["record_video_dir"] = str(video_dir)
            context_options["record_video_size"] = {"width": 1280, "height": 720}
            self._recording = True
        
        # Launch browser
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        
        # Create context with profile
        if profile.user_data_dir.exists():
            context_options["storage_state"] = str(profile.user_data_dir / "state.json") \
                if (profile.user_data_dir / "state.json").exists() else None
        
        self._context = self._browser.new_context(**{k: v for k, v in context_options.items() if v})
        self._page = self._context.new_page()
        
        # Create session
        self._session = BrowserSession(
            id=str(uuid.uuid4())[:8],
            profile=profile,
            recording_path=context_options.get("record_video_dir")
        )
        
        logger.info(f"Browser launched with profile: {self.profile_name}")
        return self._session
    
    def close(self, save_profile: bool = True):
        """Close browser and optionally save profile state."""
        if self._session and save_profile:
            self._save_profile_state()
        
        if self._page:
            self._page.close()
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        
        self._session = None
        logger.info("Browser closed")
    
    # --- Navigation ---
    
    def goto(self, url: str, wait_until: str = "load") -> Dict[str, Any]:
        """
        Navigate to URL.
        
        Args:
            url: URL to navigate to
            wait_until: Wait strategy (load, domcontentloaded, networkidle)
            
        Returns:
            Dict with url, title, and snapshot summary
        """
        self._ensure_page()
        
        # Add protocol if missing
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        
        start = time.time()
        self._page.goto(url, wait_until=wait_until)
        duration = (time.time() - start) * 1000
        
        if self._session:
            self._session.current_url = self._page.url
            self._session.current_title = self._page.title()
        
        # Take snapshot
        snapshot = self.snapshot()
        
        return {
            "url": self._page.url,
            "title": self._page.title(),
            "load_time_ms": duration,
            "interactive_elements": len(snapshot.get_interactive()),
            "snapshot_summary": snapshot.to_summary(max_elements=20)
        }
    
    def back(self):
        """Go back in history."""
        self._ensure_page()
        self._page.go_back()
    
    def forward(self):
        """Go forward in history."""
        self._ensure_page()
        self._page.go_forward()
    
    def reload(self):
        """Reload the page."""
        self._ensure_page()
        self._page.reload()
    
    # --- Snapshots ---
    
    def snapshot(self) -> "StructuredDOM":
        """
        Take a structured snapshot of the current page.
        
        Returns:
            StructuredDOM with all elements and refs
        """
        from chintu_backend.tools.browser.structured_dom import DOMParser, StructuredDOM
        
        self._ensure_page()
        
        # Get accessibility tree from Playwright
        try:
            ax_tree = self._page.accessibility.snapshot()
        except Exception:
            ax_tree = None
        
        parser = DOMParser()
        
        if ax_tree:
            snapshot = parser.parse_from_playwright(
                ax_tree,
                url=self._page.url,
                title=self._page.title()
            )
        else:
            # Fallback to HTML parsing
            html = self._page.content()
            snapshot = parser.parse_from_html(
                html,
                url=self._page.url,
                title=self._page.title()
            )
        
        self._last_snapshot = snapshot
        return snapshot
    
    def get_interactive_elements(self) -> List[Dict[str, Any]]:
        """Get list of interactive elements with their refs."""
        snapshot = self.snapshot()
        return [elem.to_dict() for elem in snapshot.get_interactive()]
    
    # --- Actions via Refs ---
    
    def act(
        self,
        ref: str,
        action: str = "click",
        value: str = None,
        screenshot_after: bool = False
    ) -> ActionResult:
        """
        Perform an action on an element by its ref.
        
        Args:
            ref: Element reference from snapshot
            action: Action type (click, type, fill, select, etc.)
            value: Value for type/fill/select actions
            screenshot_after: Take screenshot after action
            
        Returns:
            ActionResult with success status
        """
        self._ensure_page()
        
        start = time.time()
        action_enum = BrowserAction(action.lower())
        
        # Get element from last snapshot
        if not self._last_snapshot:
            self._last_snapshot = self.snapshot()
        
        element = self._last_snapshot.get_by_ref(ref)
        if not element:
            return ActionResult(
                success=False,
                action=action_enum,
                ref=ref,
                message=f"Element with ref '{ref}' not found"
            )
        
        try:
            # Get locator
            locator = self._get_locator(element)
            
            # Execute action
            if action_enum == BrowserAction.CLICK:
                locator.click()
            elif action_enum == BrowserAction.TYPE:
                locator.type(value or "")
            elif action_enum == BrowserAction.FILL:
                locator.fill(value or "")
            elif action_enum == BrowserAction.SELECT:
                locator.select_option(value)
            elif action_enum == BrowserAction.CHECK:
                locator.check()
            elif action_enum == BrowserAction.UNCHECK:
                locator.uncheck()
            elif action_enum == BrowserAction.HOVER:
                locator.hover()
            elif action_enum == BrowserAction.FOCUS:
                locator.focus()
            elif action_enum == BrowserAction.SCROLL:
                locator.scroll_into_view_if_needed()
            elif action_enum == BrowserAction.PRESS:
                locator.press(value or "Enter")
            else:
                return ActionResult(
                    success=False,
                    action=action_enum,
                    ref=ref,
                    message=f"Unknown action: {action}"
                )
            
            duration = (time.time() - start) * 1000
            
            # Wait for navigation/updates
            self._page.wait_for_load_state("domcontentloaded", timeout=5000)
            
            # Screenshot if requested
            screenshot_path = None
            if screenshot_after:
                screenshot_path = self.screenshot(f"after_{ref}_{action}")
            
            # Invalidate snapshot cache
            self._last_snapshot = None
            
            return ActionResult(
                success=True,
                action=action_enum,
                ref=ref,
                message=f"Action '{action}' on '{ref}' completed",
                screenshot_path=screenshot_path,
                duration_ms=duration
            )
            
        except Exception as e:
            return ActionResult(
                success=False,
                action=action_enum,
                ref=ref,
                message=f"Action failed: {str(e)}"
            )
    
    def click(self, ref: str) -> ActionResult:
        """Click an element by ref."""
        return self.act(ref, "click")
    
    def type_text(self, ref: str, text: str) -> ActionResult:
        """Type text into an element."""
        return self.act(ref, "type", text)
    
    def fill(self, ref: str, value: str) -> ActionResult:
        """Fill an input field."""
        return self.act(ref, "fill", value)
    
    def select(self, ref: str, value: str) -> ActionResult:
        """Select an option from a dropdown."""
        return self.act(ref, "select", value)
    
    # --- Screenshots & Recording ---
    
    def screenshot(self, name: str = None, full_page: bool = False) -> Path:
        """
        Take a screenshot.
        
        Args:
            name: Screenshot name (auto-generated if not provided)
            full_page: Capture full page or just viewport
            
        Returns:
            Path to saved screenshot
        """
        self._ensure_page()
        
        if not name:
            name = f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        path = self.screenshots_dir / f"{name}.png"
        self._page.screenshot(path=str(path), full_page=full_page)
        
        logger.info(f"Screenshot saved: {path}")
        return path
    
    def get_video_path(self) -> Optional[Path]:
        """Get path to session recording video."""
        if self._recording and self._session and self._session.recording_path:
            return Path(self._session.recording_path)
        return None
    
    # --- Utilities ---
    
    def execute_script(self, script: str) -> Any:
        """Execute JavaScript in the page."""
        self._ensure_page()
        return self._page.evaluate(script)
    
    def wait_for_element(self, selector: str, timeout: int = 10000):
        """Wait for an element to appear."""
        self._ensure_page()
        self._page.wait_for_selector(selector, timeout=timeout)
    
    def get_text(self, ref: str) -> Optional[str]:
        """Get text content of an element."""
        if not self._last_snapshot:
            self._last_snapshot = self.snapshot()
        
        element = self._last_snapshot.get_by_ref(ref)
        return element.text if element else None
    
    def get_attribute(self, ref: str, attr: str) -> Optional[str]:
        """Get attribute value of an element."""
        if not self._last_snapshot:
            self._last_snapshot = self.snapshot()
        
        element = self._last_snapshot.get_by_ref(ref)
        return element.attributes.get(attr) if element else None
    
    # --- Private Methods ---
    
    def _ensure_page(self):
        """Ensure browser is launched and page is available."""
        if not self._page:
            self.launch()
    
    def _get_locator(self, element):
        """Get Playwright locator for an element."""
        # Try various selectors
        if element.attributes.get("data-testid"):
            return self._page.locator(f"[data-testid='{element.attributes['data-testid']}']")
        if element.attributes.get("id"):
            return self._page.locator(f"#{element.attributes['id']}")
        if element.attributes.get("name"):
            return self._page.locator(f"[name='{element.attributes['name']}']")
        
        # Try by role and text
        if element.role.value in ["button", "link"]:
            return self._page.get_by_role(element.role.value, name=element.text[:50])
        
        # Fallback to CSS selector
        return self._page.locator(element.selector)
    
    def _get_or_create_profile(self, name: str) -> BrowserProfile:
        """Get or create a browser profile."""
        profile_dir = self.profiles_dir / name
        profile_dir.mkdir(parents=True, exist_ok=True)
        
        return BrowserProfile(
            name=name,
            user_data_dir=profile_dir
        )
    
    def _save_profile_state(self):
        """Save current browser state to profile."""
        if not self._context or not self._session:
            return
        
        try:
            state_file = self._session.profile.user_data_dir / "state.json"
            self._context.storage_state(path=str(state_file))
            logger.info(f"Profile state saved: {self._session.profile.name}")
        except Exception as e:
            logger.warning(f"Could not save profile state: {e}")


# Singleton instances per profile
_controllers: Dict[str, AdvancedBrowserController] = {}


def get_advanced_browser(profile: str = "default", headless: bool = True) -> AdvancedBrowserController:
    """Get or create an advanced browser controller."""
    key = f"{profile}:{headless}"
    if key not in _controllers:
        _controllers[key] = AdvancedBrowserController(profile, headless)
    return _controllers[key]
