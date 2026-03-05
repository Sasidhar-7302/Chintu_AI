"""App Listing Capability - List open windows/applications.

Uses pygetwindow to enumerate active windows.
"""

import logging
from typing import Dict, Any, List

from ..core.capabilities import ActionResult


def close_windows_by_title(title: str) -> tuple[bool, str]:
    """Close windows matching the exact title."""
    try:
        import pygetwindow as gw
        windows = [w for w in gw.getAllWindows() if w.title and w.visible]
        matches = [w for w in windows if w.title.lower() == title.lower()]
        if not matches:
            return False, f"I couldn't find a window named '{title}'."
        count = 0
        for w in matches:
            try:
                w.close()
                count += 1
            except Exception as exc:
                logger.error(f"Failed to close window '{w.title}': {exc}")
        if count > 0:
            import time
            time.sleep(1.0)
            summary = get_open_apps_summary()
            return True, f"Closed {count} window(s) named '{title}'.\n\n{summary}"
        return False, f"Found '{title}' but couldn't close it."
    except ImportError:
        return False, "I need 'pygetwindow' to close apps."
    except Exception as exc:
        logger.error(f"Error closing app: {exc}")
        return False, f"I ran into trouble closing '{title}'."

logger = logging.getLogger(__name__)


def get_open_apps_summary() -> str:
    """Get a summary of open applications."""
    try:
        import pygetwindow as gw
        windows = gw.getAllWindows()
        active_windows = []
        for w in windows:
            if w.title and w.visible and w.title not in ["Program Manager", "Windows Input Experience"]:
                active_windows.append(w.title)
        
        unique_windows = sorted(list(set(active_windows)))
        count = len(unique_windows)
        
        if not unique_windows:
            return "I don't see any open application windows."
            
        if count <= 5:
            return f"You currently have {count} apps open: " + ", ".join(unique_windows)
        else:
            top_5 = unique_windows[:5]
            return f"You have {count} apps open, including: " + ", ".join(top_5) + f", and {count-5} others."
    except Exception as e:
        logger.error(f"Error getting app summary: {e}")
        return "I couldn't check what apps are open."


def handle_list_open_apps(text: str, context: Dict[str, Any]) -> ActionResult:
    """List currently open applications and windows."""
    summary = get_open_apps_summary()
    return ActionResult.ok(summary, {}, "list_open_apps")



def handle_close_app(text: str, context: Dict[str, Any]) -> ActionResult:
    """Close an open application."""
    import re
    from ..core.state import get_state_manager
    
    # Extract app name
    query = text.lower()
    match = re.search(r"(?:close|kill|quit|exit)\s+(.+?)(?:\s+window)?(?:$|\.)", query)
    if not match:
        return ActionResult.fail("Which app should I close?", "close_app")
    
    target = match.group(1).strip()
    if target in ["it", "that", "this"]:
        # Try to use last opened app from context/state
        last_app = get_state_manager().state.last_opened_app
        if last_app:
            target = last_app
        else:
            return ActionResult.fail("I don't know what 'that' refers to. Which app?", "close_app")

    try:
        import pygetwindow as gw
        state = get_state_manager()
        opened_apps = [a.lower() for a in state.get_opened_apps()]
        windows = []
        if hasattr(gw, "getWindowsWithTitle"):
            try:
                windows = [w for w in gw.getWindowsWithTitle(target) if getattr(w, "title", None) and getattr(w, "visible", True)]
            except Exception:
                windows = []
        if not windows and hasattr(gw, "getAllWindows"):
            windows = [w for w in gw.getAllWindows() if w.title and w.visible]

        # Normalize target
        target_lower = target.lower()
        exact_matches = [w for w in windows if w.title.lower() == target_lower]
        fuzzy_matches = [w for w in windows if target_lower in w.title.lower()]

        # Filter for actual matches (fuzzy or exact)
        matches = exact_matches if exact_matches else fuzzy_matches

        if not matches:
            return ActionResult.fail(f"I couldn't find any open window named '{target}'.", "close_app")

        # Only auto-close apps Chintu opened unless user gives an exact title
        opened_match = any(target_lower in a for a in opened_apps)
        if not opened_match and not exact_matches:
            # Ask for an exact window title to avoid closing the wrong app
            if len(matches) > 1:
                titles = [w.title for w in matches[:5]]
                return ActionResult.fail(
                    "I didn't open that app. Please tell me the exact window title to close. "
                    f"I see: {', '.join(titles)}",
                    "close_app",
                )
            return ActionResult.fail(
                "I didn't open that app. Please tell me the exact window title to close.",
                "close_app",
            )

        # If multiple windows match, ask which one to close
        if len(matches) > 1 and not exact_matches:
            titles = [w.title for w in matches[:5]]
            try:
                from ..core.context_manager import get_context_manager
                prompt = get_context_manager().request_choice(
                    question="I found multiple windows. Which one should I close?",
                    choices=titles,
                    original_command=text,
                    callback_name="close_app_choice",
                    context={"choices": titles},
                )
                return ActionResult.ok(prompt, {"choices": titles}, "close_app")
            except Exception:
                return ActionResult.fail(
                    f"I found multiple windows. Which one should I close? {', '.join(titles)}",
                    "close_app",
                )

        # Close them
        count = 0
        for w in matches:
            try:
                w.close()
                count += 1
            except Exception as e:
                logger.error(f"Failed to close window '{w.title}': {e}")
        
        if count > 0:
            # Update opened-by-Chintu list
            if opened_match:
                state.clear_opened_app(target) if target in state.get_opened_apps() else None
            
            # Brief delay to let OS update window list
            import time
            time.sleep(1.0)
            summary = get_open_apps_summary()
            
            return ActionResult.ok(f"Closed {count} window(s) matching '{target}'.\n\n{summary}", {"app": target, "count": count}, "close_app")
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
            "close app", "close window", "kill app", "close it", "close that", "exit app",
            "close notepad", "close chrome", "close firefox", "close edge", "close browser",
            "close word", "close excel", "close outlook", "close spotify", "close discord",
            "close teams", "close slack", "close vscode", "close code", "close calculator",
            "quit notepad", "quit chrome", "quit firefox", "quit app",
            "kill notepad", "kill chrome", "close the app", "close the window"
        ],
        description="Close a running application",
        capability_type=CapabilityType.SYSTEM,
        examples=["Close Chrome", "Close Notepad", "Close it"],
    ))
    
    logger.info("Registered app listing capabilities")
