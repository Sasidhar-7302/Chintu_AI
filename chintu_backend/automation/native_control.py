"""
Native UI Control for Chintu AI Assistant.
Uses Windows UI Automation (uiautomation) to inspect and control the screen structure directly.
"""

import logging
import time
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

try:
    import uiautomation as auto
    HAS_UIA = True
    # Configure uiautomation
    auto.TIME_OUT_SECOND = 5  # Timeout for finding elements
except ImportError:
    HAS_UIA = False
    logger.warning("uiautomation not installed - Native UI control disabled")


class NativeController:
    """Controls Windows native UI elements via UIA."""

    def __init__(self):
        self.enabled = HAS_UIA

    def find_and_click(self, text: str, exact_match: bool = False) -> bool:
        """
        Finds an element by name/automationId and clicks it.
        Scope: Currently active window or entire desktop.
        """
        if not self.enabled:
            return False

        logger.info(f"Native UI Search: Looking for '{text}'...")

        try:
            # 1. Try to find in the active window first (faster)
            # window = auto.GetForegroundWindow() # WinAPI handle
            # We want the UIA control for foreground
            window_ctrl = auto.GetForegroundControl()
            if window_ctrl:
                element = self._search_in_scope(window_ctrl, text, exact_match)
                if element:
                    return self._click_uia_element(element)

            # 2. If not found, try root (Desktop) - can be slow
            logger.info("Not found in active window, scanning Desktop...")
            root = auto.GetRootControl()
            element = self._search_in_scope(root, text, exact_match)
            if element:
                return self._click_uia_element(element)

            logger.info(f"Native UI: Element '{text}' not found.")
            return False

        except Exception as e:
            logger.error(f"Native UI Click Error: {e}")
            return False

    def _search_in_scope(self, scope_control, text: str, exact_match: bool):
        """Helper to search tree with a specific scope."""
        # Try finding by Name (most common)
        found = scope_control.Control(Name=text, searchDepth=5) if exact_match else \
                scope_control.Control(searchDepth=5, Name=text, SubName=text) # partial match via lambda? No, strict params.
        
        # uiautomation.Control(Name=...) usually does partial match if regex/wildcars used, 
        # but let's stick to simple property matching first.
        # "searchDepth" limits recursion to speed it up.
        
        if found.Exists(maxSearchSeconds=2):
            return found
            
        # Try case-insensitive manually by iterating (expensive but accurate)
        # Note: 'Control' creates a proxy, doesn't immediately find. 'Exists' triggers the search.
        # If strict search failed, let's try walking looking for substring
        # For efficiency, we rely on the library's find capabilities.
        return None

    def _click_uia_element(self, element) -> bool:
        """Perform the click action."""
        try:
            logger.info(f"Clicking element: {element.Name} ({element.ControlTypeName})")
            
            # Try Invoke pattern (cleanest for buttons)
            if element.GetPattern(auto.PatternId.InvokePattern):
                element.GetInvokePattern().Invoke()
                return True
                
            # Try Toggle pattern
            if element.GetPattern(auto.PatternId.TogglePattern):
                element.GetTogglePattern().Toggle()
                return True
                
            # Try Legacy (Click)
            element.Click(simulateMove=True) # Move mouse and click physically
            return True
            
        except Exception as e:
            logger.error(f"Click action failed: {e}")
            try:
                 # Fallback to physical click
                 element.Click(simulateMove=True, waitTime=0.1)
                 return True
            except:
                return False

    def close_window_by_title(self, title_text: str) -> int:
        """
        Finds top-level windows by title (partial match) and closes them.
        Returns number of windows closed.
        """
        if not self.enabled:
            return 0
            
        logger.info(f"Native UI: Attempting to close windows matching '{title_text}'...")
        count = 0
        
        try:
            root = auto.GetRootControl()
            # Find window - ensure it's a WindowControl
            
            condition = lambda c: title_text.lower() in c.Name.lower() and c.ControlTypeName == "WindowControl"
            
            # Walk top level windows
            # We collect first to avoid issues while iterating and closing
            targets = []
            for window in root.GetChildren():
                if condition(window):
                    targets.append(window)
            
            if not targets:
                logger.info(f"Native UI: No window found matching '{title_text}'")
                return 0
                
            for found_window in targets:
                try:
                    logger.info(f"Native UI: Found window '{found_window.Name}', closing...")
                    
                    # Try WindowPattern (standard close)
                    if found_window.GetPattern(auto.PatternId.WindowPattern):
                        found_window.GetWindowPattern().Close()
                        count += 1
                        continue
                        
                    # Try finding a close button
                    close_btn = found_window.ButtonControl(Name="Close")
                    if close_btn.Exists(maxSearchSeconds=1):
                        self._click_uia_element(close_btn)
                        count += 1
                        continue
                        
                    # Fallback: Alt+F4
                    found_window.SetFocus()
                    auto.SendKeys('{Alt}{F4}')
                    count += 1
                except Exception as e:
                    logger.warning(f"Failed to close window '{found_window.Name}': {e}")
            
            return count
            
        except Exception as e:
            logger.error(f"Native UI Close Window Error: {e}")
            return count

    def maximize_window_by_title(self, title_text: str) -> bool:
        """
        Finds a top-level window by title (partial match) and maximizes it.
        Returns True if successful.
        """
        if not self.enabled:
            return False
            
        logger.info(f"Native UI: Attempting to maximize window matching '{title_text}'...")
        
        try:
            root = auto.GetRootControl()
            condition = lambda c: title_text.lower() in c.Name.lower() and c.ControlTypeName == "WindowControl"
            
            targets = []
            for window in root.GetChildren():
                if condition(window):
                    targets.append(window)
            
            if not targets:
                logger.info(f"Native UI: No window found matching '{title_text}'")
                return False
                
            # Maximize the first match
            for found_window in targets:
                try:
                    logger.info(f"Native UI: Found window '{found_window.Name}', maximizing...")
                    
                    if found_window.GetPattern(auto.PatternId.WindowPattern):
                        pattern = found_window.GetWindowPattern()
                        
                        # Smart Check: Is it already maximized?
                        if pattern.CurrentWindowVisualState == auto.WindowVisualState.Maximized:
                            logger.info(f"Window '{found_window.Name}' is already maximized.")
                            found_window.SetFocus()
                            return True
                            
                        pattern.SetWindowVisualState(auto.WindowVisualState.Maximized)
                        found_window.SetFocus() # Bring to front
                        return True
                except Exception as e:
                    logger.warning(f"Failed to maximize window '{found_window.Name}': {e}")
            
            return False
            
        except Exception as e:
            logger.error(f"Native UI Maximize Window Error: {e}")
            return False

    def list_elements_in_active_window(self) -> List[str]:
        """Debug helper: Dump visible names in active window."""
        if not self.enabled: return []
        
        try:
            window = auto.GetForegroundControl()
            names = []
            
            def walk(control, depth):
                if depth > 3: return
                name = control.Name
                if name and len(name.strip()) > 0:
                    names.append(name)
                for child in control.GetChildren():
                    walk(child, depth + 1)
                    
            walk(window, 0)
            return names
        except:
            return []

_native_controller = None

def get_native_controller() -> NativeController:
    global _native_controller
    if _native_controller is None:
        _native_controller = NativeController()
    return _native_controller
