"""App Listing Capability - List open windows/applications.

Uses pygetwindow to enumerate active windows.
"""

import logging
from typing import Dict, Any, List

from ..core.capabilities import ActionResult

logger = logging.getLogger(__name__)


def handle_list_open_apps(text: str, context: Dict[str, Any]) -> ActionResult:
    """List currently open applications and windows.
    
    Examples:
    - "What apps are open?"
    - "List open windows"
    - "What is running?"
    """
    try:
        import pygetwindow as gw
        
        # Get all window objects (better than titles for filtering)
        windows = gw.getAllWindows()
        
        # Filter for visible windows with titles
        active_windows = []
        for w in windows:
            # Check for title and visibility
            # Note: valid windows usually have a title and are visible (not minimized/hidden)
            if w.title and w.visible and w.title not in ["Program Manager", "Windows Input Experience"]:
                active_windows.append(w.title)
        
        # Deduplicate
        unique_windows = sorted(list(set(active_windows)))
        
        logger.info(f"Found {len(unique_windows)} visible windows: {unique_windows}")
        
        if not unique_windows:
            return ActionResult.ok(
                "I don't see any open application windows.",
                {"count": 0, "windows": []},
                "list_open_apps"
            )
        
        count = len(unique_windows)
        
        # Format response
        if count <= 5:
            response = f"You have {count} apps open:\n" + "\n".join(f"• {w}" for w in unique_windows)
        else:
            top_5 = unique_windows[:5]
            response = f"You have {count} apps open, including:\n" + "\n".join(f"• {w}" for w in top_5) + f"\n...and {count-5} others."
            
        return ActionResult.ok(
            response,
            {"count": count, "windows": unique_windows},
            "list_open_apps"
        )
        
    except ImportError:
        return ActionResult.fail(
            "I need 'pygetwindow' to list apps. Please install it.",
            "list_open_apps"
        )
    except Exception as e:
        logger.error(f"Error listing apps: {e}")
        return ActionResult.fail(f"I couldn't list open apps: {e}", "list_open_apps")



def handle_close_app(text: str, context: Dict[str, Any]) -> ActionResult:
    """Close an open application."""
    import re
    
    # Extract app name
    query = text.lower()
    match = re.search(r"(?:close|kill|quit|exit)\s+(.+?)(?:\s+window)?(?:$|\.)", query)
    if not match:
        return ActionResult.fail("Which app should I close?", "close_app")
    
    target = match.group(1).strip()
    if target in ["it", "that", "this"]:
        # Try to use last opened app from context/state
        from ..core.state import get_state_manager
        last_app = get_state_manager().state.last_opened_app
        if last_app:
            target = last_app
        else:
            return ActionResult.fail("I don't know what 'that' refers to. Which app?", "close_app")

    try:
        import pygetwindow as gw
        windows = gw.getWindowsWithTitle(target)
        
        # Filter for actual matches (fuzzy or exact)
        matches = [w for w in windows if w.title and w.visible]
        
        if not matches:
             # Try broader search?
             all_wins = gw.getAllWindows()
             matches = [w for w in all_wins if target in w.title.lower() and w.visible]
        
        if not matches:
            return ActionResult.fail(f"I couldn't find any open window named '{target}'.", "close_app")
        
        # Close them
        count = 0
        for w in matches:
            try:
                w.close()
                count += 1
            except Exception as e:
                logger.error(f"Failed to close window '{w.title}': {e}")
        
        if count > 0:
            return ActionResult.ok(f"Closed {count} window(s) matching '{target}'.", {"app": target, "count": count}, "close_app")
        else:
            return ActionResult.fail(f"Found '{target}' but couldn't close it.", "close_app")

    except ImportError:
        return ActionResult.fail("I need 'pygetwindow' to close apps.", "close_app")
    except Exception as e:
        logger.error(f"Error closing app: {e}")
        return ActionResult.fail(f"I ran into trouble closing '{target}'.", "close_app")


def register_app_listing_capabilities():
    """Register app listing capabilities."""
    from ..core.capabilities import get_registry, Capability, CapabilityType
    
    registry = get_registry()
    
    registry.register(Capability(
        name="list_open_apps",
        handler=handle_list_open_apps,
        triggers=[
            "what apps are open",
            "list open apps",
            "list open windows",
            "what is running",
            "show running apps",
            "show active apps",
        ],
        description="List currently open applications",
        capability_type=CapabilityType.SYSTEM,
        examples=["What apps are open?", "List open windows"],

    ))
    
    registry.register(Capability(
        name="close_app",
        handler=handle_close_app,
        triggers=[
            "close app", "close window", "kill app", "close it", "close that", "exit app"
        ],
        description="Close a running application",
        capability_type=CapabilityType.SYSTEM,
        examples=["Close Chrome", "Close Notepad", "Close it"],
    ))
    
    logger.info("Registered app listing capabilities")
