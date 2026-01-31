"""
Browser capability handlers for Chintu AI Assistant.
Provides voice commands for browser automation.
"""

import re
import logging
from pathlib import Path
from typing import Dict, Any

from ...core.capabilities import Capability, CapabilityType, ActionResult

logger = logging.getLogger(__name__)


def handle_open_browser(text: str, context: Dict[str, Any]) -> ActionResult:
    """
    Open a URL in the browser.
    
    Examples:
        "Open google.com in browser"
        "Browse to github.com"
        "Go to amazon.com in the browser"
    """
    from .browser_controller import get_browser_controller
    
    # Extract URL
    query = text.lower().strip()
    prefixes = [
        "open in browser ", "browse to ", "go to ", "navigate to ",
        "open ", "visit ", "browser open ", "browser go to "
    ]
    
    url = query
    for prefix in prefixes:
        if query.startswith(prefix):
            url = query[len(prefix):].strip()
            break
    
    # Clean up
    url = url.replace("in browser", "").replace("in the browser", "").strip()
    url = re.sub(r"\s+", "", url)  # Remove spaces
    
    if not url or len(url) < 3:
        return ActionResult.fail(
            "Which website would you like me to open?",
            "open_browser"
        )
    
    try:
        controller = get_browser_controller(headless=False)  # Show browser
        page_info = controller.open_url(url)
        
        return ActionResult.ok(
            f"Opened **{page_info.title}** ({page_info.url})",
            {"url": page_info.url, "title": page_info.title},
            "open_browser"
        )
        
    except Exception as e:
        logger.error(f"Failed to open browser: {e}")
        return ActionResult.fail(
            f"Failed to open {url}: {e}",
            "open_browser"
        )


def handle_browser_search(text: str, context: Dict[str, Any]) -> ActionResult:
    """
    Search Google using the browser.
    
    Examples:
        "Browser search for Python tutorials"
        "Search in browser Python documentation"
    """
    from .browser_controller import get_browser_controller
    
    # Extract search query
    query = text.lower().strip()
    prefixes = [
        "browser search for ", "browser search ", "search in browser for ",
        "search in browser ", "google in browser ", "search using browser "
    ]
    
    search_query = query
    for prefix in prefixes:
        if query.startswith(prefix):
            search_query = query[len(prefix):].strip()
            break
    
    if not search_query or len(search_query) < 2:
        return ActionResult.fail(
            "What would you like me to search for in the browser?",
            "browser_search"
        )
    
    try:
        controller = get_browser_controller(headless=False)
        page_info = controller.search_google(search_query)
        
        return ActionResult.ok(
            f"Searched Google for '{search_query}'\n\n{page_info.text_preview}",
            {"query": search_query, "url": page_info.url},
            "browser_search"
        )
        
    except Exception as e:
        logger.error(f"Browser search failed: {e}")
        return ActionResult.fail(
            f"Search failed: {e}",
            "browser_search"
        )


def handle_screenshot(text: str, context: Dict[str, Any]) -> ActionResult:
    """
    Take a screenshot of the current browser page.
    
    Examples:
        "Take a screenshot"
        "Screenshot the page"
        "Capture this page"
    """
    from .browser_controller import get_browser_controller
    
    controller = get_browser_controller()
    
    # Try browser screenshot
    if controller.is_open:
        try:
            filepath = controller.take_screenshot()
            return ActionResult.ok(
                f"Screenshot saved to: {filepath}",
                {"filepath": filepath},
                "screenshot"
            )
        except Exception as e:
            logger.warning(f"Browser screenshot failed, trying desktop capture: {e}")
            
    # Fallback to Desktop Screenshot
    from ..vision.screen_capture import get_screen_manager
    screen_manager = get_screen_manager()
    
    capture = screen_manager.capture_screen(save=True)
    if capture and capture.path:
        return ActionResult.ok(
            f"Desktop screenshot saved: {capture.path}",
            {"filepath": str(capture.path)},
            "screenshot"
        )
        
    return ActionResult.fail(
        "Failed to take screenshot (browser and desktop capture failed).",
        "screenshot"
    )


def handle_page_content(text: str, context: Dict[str, Any]) -> ActionResult:
    """
    Get the text content of the current browser page.
    
    Examples:
        "Read this page"
        "What's on this page?"
        "Get page content"
    """
    from .browser_controller import get_browser_controller
    
    controller = get_browser_controller()
    
    if not controller.is_open:
        return ActionResult.fail(
            "No browser page is open. First say 'open google.com in browser'.",
            "page_content"
        )
    
    try:
        page_info = controller.get_page_info()
        content = controller.get_page_content(max_length=2000)
        
        response = f"**{page_info.title}**\n{page_info.url}\n\n{content}"
        
        return ActionResult.ok(
            response,
            {"url": page_info.url, "title": page_info.title},
            "page_content"
        )
        
    except Exception as e:
        logger.error(f"Failed to get page content: {e}")
        return ActionResult.fail(
            f"Failed to read page: {e}",
            "page_content"
        )


def handle_click_link(text: str, context: Dict[str, Any]) -> ActionResult:
    """
    Click a link on the current page.
    
    Examples:
        "Click on 'Sign In'"
        "Click the login button"
    """
    from .browser_controller import get_browser_controller
    
    controller = get_browser_controller()
    

    
    # Extract link text
    query = text.lower().strip()
    prefixes = ["click on ", "click ", "press ", "tap "]
    
    link_text = query
    for prefix in prefixes:
        if query.startswith(prefix):
            link_text = query[len(prefix):].strip()
            break
    
    # Remove quotes
    link_text = link_text.strip('"\'')
    
    if not link_text:
        return ActionResult.fail(
            "Which link should I click?",
            "click_link"
        )
    
    # Try Browser Automation first
    if controller.is_open:
        try:
            success = controller.click_link(link_text)
            
            if success:
                page_info = controller.get_page_info()
                return ActionResult.ok(
                    f"Clicked '{link_text}'. Now on: {page_info.title}",
                    {"clicked": link_text, "new_url": page_info.url},
                    "click_link"
                )
        except Exception as e:
            logger.warning(f"Browser automation click failed, trying native UI: {e}")

    # Try Native UI (Windows UIA) - Always on
    from ..automation.native_control import get_native_controller
    native_ctrl = get_native_controller()
    
    logger.info(f"Attempting Native UI click for: {link_text}")
    if native_ctrl.find_and_click(link_text):
        return ActionResult.ok(
            f"Clicked '{link_text}' using Native/Accessibility control.",
            {"clicked": link_text, "method": "native_uia"},
            "click_link"
        )
        
    # Fallback to Visual Click (OCR/Vision)
    from ..vision.screen_capabilities import find_coordinates
    from ..automation.screen_control import get_screen_controller
    
    logger.info(f"Native UI failed, attempting visual click for: {link_text}")
    coords = find_coordinates(link_text)
    
    if coords:
        x, y = coords
        screen_ctrl = get_screen_controller()
        if screen_ctrl.click_at(x, y):
             return ActionResult.ok(
                f"I saw '{link_text}' (via Vision) and clicked it.",
                {"clicked": link_text, "method": "visual", "coords": [x, y]},
                "click_link"
            )
    
    # Final Failure
    return ActionResult.fail(
        f"Could not click '{link_text}'. Tried: Browser DOM (failed/closed), Native UI (not found), Vision (not visible).",
        "click_link"
    )


def handle_close_browser(text: str, context: Dict[str, Any]) -> ActionResult:
    """
    Close the browser.
    
    Examples:
        "Close the browser"
        "Close browser"
    """
    from .browser_controller import get_browser_controller
    
    controller = get_browser_controller()
    controller.close()
    
    return ActionResult.ok(
        "Browser closed.",
        {},
        "close_browser"
    )


def register_browser_capabilities(registry) -> None:
    """Register all browser-related capabilities."""
    
    # Open Browser
    registry.register(Capability(
        name="open_browser",
        triggers=[
            "open in browser", "browse to", "browser open",
            "navigate to in browser", "go to in browser"
        ],
        handler=handle_open_browser,
        requires_confirmation=False,
        description="open a website in the browser",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=[
            "Open google.com in browser",
            "Browse to github.com"
        ]
    ))
    
    # Browser Search
    registry.register(Capability(
        name="browser_search",
        triggers=[
            "browser search", "search in browser", "google in browser",
            "search using browser"
        ],
        handler=handle_browser_search,
        requires_confirmation=False,
        description="search Google using the browser",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=[
            "Browser search for Python tutorials"
        ]
    ))
    
    # Screenshot
    registry.register(Capability(
        name="screenshot",
        triggers=[
            "take a screenshot", "screenshot", "capture this page",
            "screenshot the page", "take screenshot"
        ],
        handler=handle_screenshot,
        requires_confirmation=False,
        description="take a screenshot of the browser",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=[
            "Take a screenshot",
            "Capture this page"
        ]
    ))
    
    # Page Content
    registry.register(Capability(
        name="page_content",
        triggers=[
            "read this page", "what's on this page", "get page content",
            "read the page", "page content", "summarize this page"
        ],
        handler=handle_page_content,
        requires_confirmation=False,
        description="read the current browser page",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=[
            "Read this page",
            "What's on this page?"
        ]
    ))
    
    # Click Link
    registry.register(Capability(
        name="click_link",
        triggers=[
            "click on", "click the", "press the", "tap on"
        ],
        handler=handle_click_link,
        requires_confirmation=False,
        description="click a link on the page",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=[
            "Click on 'Sign In'",
            "Click the login button"
        ]
    ))
    
    # Close Browser
    registry.register(Capability(
        name="close_browser",
        triggers=[
            "close the browser", "close browser", "exit browser"
        ],
        handler=handle_close_browser,
        requires_confirmation=False,
        description="close the browser",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=[
            "Close the browser"
        ]
    ))
    
    logger.info("Registered browser capabilities")
