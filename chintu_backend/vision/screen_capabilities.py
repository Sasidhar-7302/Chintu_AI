"""Screen analysis and visual intelligence capabilities.

Provides voice commands for:
- "What's on my screen?"
- "Take a screenshot"
- "Read the text on screen"
"""

import logging
from typing import Dict, Any, Optional, Tuple

from ..core.capabilities import ActionResult

logger = logging.getLogger(__name__)


def handle_whats_on_screen(text: str, context: Dict[str, Any]) -> ActionResult:
    """Describe what's visible on the screen.
    
    Examples:
    - "What's on my screen?"
    - "What am I looking at?"
    - "Describe my screen"
    """
    from .screen_capture import get_screen_manager
    from .omniparser import get_omniparser
    
    screen_manager = get_screen_manager()
    parser = get_omniparser()
    
    # Capture the current screen
    capture = screen_manager.capture_screen(save=True)
    
    if not capture:
        return ActionResult.fail(
            "I couldn't capture your screen. Make sure screen capture permissions are enabled.",
            "whats_on_screen"
        )
    
    # Try OmniParser first (Vision)
    try:
        analysis = parser.analyze_screen(image_path=str(capture.path))
        
        if "error" not in analysis:
            description = analysis.get("description", "I see your screen.")
            text_content = analysis.get("text_content", "")
            elements = len(analysis.get("elements", []))
            
            return ActionResult.ok(
                f"{description}\n\nVisible elements: {elements}",
                {"analysis": analysis, "path": str(capture.path)},
                "whats_on_screen"
            )
    except Exception as e:
        logger.warning(f"OmniParser analysis failed: {e}")

    # Fallback to OCR
    extracted_text = screen_manager.extract_text_from_screen()
    
    # Get Accurate Window List (New Feature)
    from ..platform.window_manager import get_window_manager
    window_summary = get_window_manager().get_window_summary()
    
    response_text = ""
    
    if extracted_text:
        # Truncate if too long
        if len(extracted_text) > 500:
            extracted_text = extracted_text[:500] + "..."
        response_text = f"I can see your screen. Vision unavailable, but here's the text I found:\n\n{extracted_text}"
    else:
        response_text = f"I captured your screen ({capture.width}x{capture.height})."

    # Append window summary
    response_text += f"\n\n**Running Apps:**\n{window_summary}"
        
    return ActionResult.ok(
        response_text,
        {"width": capture.width, "height": capture.height, "text": extracted_text, "windows": window_summary},
        "whats_on_screen"
    )


def handle_take_screenshot(text: str, context: Dict[str, Any]) -> ActionResult:
    """Take and save a screenshot.
    
    Examples:
    - "Take a screenshot"
    - "Capture my screen"
    - "Screenshot this"
    """
    from .screen_capture import get_screen_manager
    
    screen_manager = get_screen_manager()
    
    # Capture and save
    capture = screen_manager.capture_screen(save=True)
    
    if capture and capture.path:
        return ActionResult.ok(
            f"Screenshot saved! You can find it at: {capture.path}",
            {"path": str(capture.path), "timestamp": capture.timestamp},
            "take_screenshot"
        )
    else:
        return ActionResult.fail(
            "I couldn't take a screenshot. Make sure screen capture is allowed.",
            "take_screenshot"
        )


def handle_read_screen_text(text: str, context: Dict[str, Any]) -> ActionResult:
    """Read text visible on the screen using OCR.
    
    Examples:
    - "Read what's on screen"
    - "What text is visible?"
    - "Read the screen text"
    """
    from .screen_capture import get_screen_manager
    
    screen_manager = get_screen_manager()
    
    # Capture the current screen
    capture = screen_manager.capture_screen()
    
    if not capture:
        return ActionResult.fail(
            "I couldn't capture your screen.",
            "read_screen_text"
        )
    
    # Extract text
    extracted_text = screen_manager.extract_text_from_screen()
    
    if extracted_text:
        return ActionResult.ok(
            f"Here's the text I found on your screen:\n\n{extracted_text}",
            {"text": extracted_text},
            "read_screen_text"
        )
    else:
        return ActionResult.fail(
            "I couldn't extract any text from the screen. "
            "Make sure pytesseract is installed for OCR support.",
            "read_screen_text"
        )


def handle_copy_to_clipboard(text: str, context: Dict[str, Any]) -> ActionResult:
    """Copy text to the clipboard.
    
    Examples:
    - "Copy that"
    - "Copy the last response"
    - "Put that in my clipboard"
    """
    try:
        import pyperclip
        
        # Get the last response from context or command handler
        last_response = context.get("last_response", "")
        
        if not last_response:
            return ActionResult.fail(
                "There's nothing to copy. Ask me something first!",
                "copy_to_clipboard"
            )
        
        pyperclip.copy(last_response)
        
        # Truncate for display
        preview = last_response[:50] + "..." if len(last_response) > 50 else last_response
        
        return ActionResult.ok(
            f"Copied to clipboard: {preview}",
            {"copied_length": len(last_response)},
            "copy_to_clipboard"
        )
        
    except ImportError:
        return ActionResult.fail(
            "Clipboard support requires pyperclip. Run: pip install pyperclip",
            "copy_to_clipboard"
        )
    except Exception as e:
        return ActionResult.fail(
            f"Couldn't copy to clipboard: {str(e)}",
            "copy_to_clipboard"
        )


def handle_paste_from_clipboard(text: str, context: Dict[str, Any]) -> ActionResult:
    """Read what's in the clipboard.
    
    Examples:
    - "What's in my clipboard?"
    - "Read my clipboard"
    - "Paste"
    """
    try:
        import pyperclip
        
        clipboard_content = pyperclip.paste()
        
        if not clipboard_content:
            return ActionResult.ok(
                "Your clipboard is empty.",
                {"content": ""},
                "paste_from_clipboard"
            )
        
        # Truncate for display
        if len(clipboard_content) > 500:
            display = clipboard_content[:500] + f"\n\n... ({len(clipboard_content)} total characters)"
        else:
            display = clipboard_content
        
        return ActionResult.ok(
            f"Here's what's in your clipboard:\n\n{display}",
            {"content": clipboard_content, "length": len(clipboard_content)},
            "paste_from_clipboard"
        )
        
    except ImportError:
        return ActionResult.fail(
            "Clipboard support requires pyperclip. Run: pip install pyperclip",
            "paste_from_clipboard"
        )
    except Exception as e:
        return ActionResult.fail(
            f"Couldn't read clipboard: {str(e)}",
            "paste_from_clipboard"
        )


def find_coordinates(target_text: str) -> Optional[Tuple[int, int]]:
    """Helper to find pixel coordinates of a text/element on screen."""
    from .screen_capture import get_screen_manager
    from .omniparser import get_omniparser
    
    screen_manager = get_screen_manager()
    parser = get_omniparser()
    
    capture = screen_manager.capture_screen(save=True)
    if not capture:
        return None
        
    result = parser.find_element(str(capture.path), target_text)
    
    if result.get("found") and result.get("coordinates"):
        # Convert % to pixels
        # Expecting coordinates: [x_percent, y_percent] (0-100)
        coords = result["coordinates"]
        if len(coords) == 2:
            x_pct, y_pct = coords
            pixel_x = int((x_pct / 100) * capture.width)
            pixel_y = int((y_pct / 100) * capture.height)
            logger.info(f"Visual coordinate map: {target_text} -> {x_pct}%,{y_pct}% -> {pixel_x},{pixel_y}")
            return (pixel_x, pixel_y)
            
    logger.warning(f"Visual search failed for: {target_text}")
    return None


def handle_find_element(text: str, context: Dict[str, Any]) -> ActionResult:
    """Find a UI element on the screen using Vision.
    
    Examples:
    - "Find the submit button"
    - "Where is the search bar?"
    - "Locate the login link"
    """
    from .screen_capture import get_screen_manager
    from .omniparser import get_omniparser
    
    # Extract element name from text
    import re
    element = text
    patterns = [
        r"find\s+(?:the\s+)?(.+)",
        r"where\s+is\s+(?:the\s+)?(.+)",
        r"locate\s+(?:the\s+)?(.+)"
    ]
    
    for p in patterns:
        match = re.search(p, text.lower())
        if match:
            element = match.group(1).strip()
            break
            
    screen_manager = get_screen_manager()
    parser = get_omniparser()
    
    # Capture screen
    capture = screen_manager.capture_screen(save=True)
    
    if not capture:
        return ActionResult.fail("Couldn't capture screen.", "find_element")
        
    try:
        # Ask OmniParser
        result = parser.find_element(str(capture.path), element)
        
        if result.get("found"):
            desc = result.get("description", "Found it.")
            return ActionResult.ok(
                f"Found '{element}': {desc}",
                {"element": element, "result": result, "path": str(capture.path)},
                "find_element"
            )
        else:
            return ActionResult.ok(
                f"I couldn't find '{element}' on your screen. {result.get('description', '')}",
                {"element": element, "found": False},
                "find_element"
            )
            
    except Exception as e:
        return ActionResult.fail(f"Detailed vision search failed: {e}", "find_element")


def handle_screen_click(text: str, context: Dict[str, Any]) -> ActionResult:
    """Click a UI element on the screen using Visual Grounding.
    
    Examples:
    - "Click the submit button"
    - "Click search"
    - "Click on login"
    """
    import pyautogui
    from .screen_capture import get_screen_manager
    from .omniparser import get_omniparser
    
    # Extract element name
    import re
    element = text
    patterns = [
        r"click\s+(?:on\s+)?(?:the\s+)?(.+)",
    ]
    
    for p in patterns:
        match = re.search(p, text.lower())
        if match:
            element = match.group(1).strip()
            break
            
    # Step 1: Find coordinates
    coords = find_coordinates(element)
    
    if not coords:
        return ActionResult.fail(
            f"I couldn't find '{element}' to click on (visual search failed).",
            "screen_click"
        )
        
    x, y = coords
    
    # Step 2: Click
    try:
        pyautogui.moveTo(x, y, duration=0.5)
        pyautogui.click()
        return ActionResult.ok(
            f"Clicked '{element}' at ({x}, {y}).",
            {"element": element, "coords": [x, y]},
            "screen_click"
        )
    except Exception as e:
        return ActionResult.fail(f"Failed to click: {e}", "screen_click")


def register_screen_capabilities():
    """Register all screen-related capabilities."""
    from ..core.capabilities import get_registry, Capability, CapabilityType
    
    registry = get_registry()
    
    # What's on screen
    registry.register(Capability(
        name="whats_on_screen",
        handler=handle_whats_on_screen,
        triggers=[
            "what's on my screen",
            "what is on my screen",
            "what am i looking at",
            "describe my screen",
            "what do you see",
            "analyze screen",
        ],
        description="Describe what's visible on the screen",
        capability_type=CapabilityType.SYSTEM,
        examples=["What's on my screen?", "What am I looking at?"],

    ))
    
    # Take screenshot
    registry.register(Capability(
        name="take_screenshot",
        handler=handle_take_screenshot,
        triggers=[
            "take a screenshot",
            "capture screen",
            "screenshot this",
            "save screen",
        ],
        description="Take and save a screenshot",
        capability_type=CapabilityType.SYSTEM,
        examples=["Take a screenshot", "Capture my screen"],

    ))
    
    # Find element (Antigravity)
    registry.register(Capability(
        name="find_element",
        handler=handle_find_element,
        triggers=[
            "find the",
            "where is the",
            "locate the",
        ],
        description="Locate UI element on screen",
        capability_type=CapabilityType.SYSTEM,
        examples=["Find the submit button", "Where is the search bar"],

    ))
    
    # Read screen text
    registry.register(Capability(
        name="read_screen_text",
        handler=handle_read_screen_text,
        triggers=[
            "read screen",
            "read text on screen",
            "what text is visible",
            "ocr screen",
            "extract text",
        ],
        description="Read text visible on the screen using OCR",
        capability_type=CapabilityType.SYSTEM,
        examples=["Read the text on screen", "What text is visible?"],

    ))
    
    # Copy to clipboard
    registry.register(Capability(
        name="copy_to_clipboard",
        handler=handle_copy_to_clipboard,
        triggers=[
            "copy that",
            "copy to clipboard",
            "copy response",
            "put in clipboard",
        ],
        description="Copy text to the clipboard",
        capability_type=CapabilityType.SYSTEM,
        examples=["Copy that", "Copy the last response"],

    ))
    
    # Paste/read clipboard
    registry.register(Capability(
        name="paste_from_clipboard",
        handler=handle_paste_from_clipboard,
        triggers=[
            "what's in my clipboard",
            "read clipboard",
            "show clipboard",
            "paste",
        ],
        description="Read what's in the clipboard",
        capability_type=CapabilityType.SYSTEM,
        examples=["What's in my clipboard?", "Read my clipboard"],

    ))
    
    # Screen Click (VLA)
    registry.register(Capability(
        name="screen_click",
        handler=handle_screen_click,
        triggers=[
            "click on",
            "click the",
            "click",
            "press",
        ],
        description="Click a UI element using visual search",
        capability_type=CapabilityType.SYSTEM,
        examples=["Click the submit button", "Click on search"],
    ))
    
    logger.info("Registered screen capabilities")
