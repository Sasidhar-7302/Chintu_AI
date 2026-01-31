"""Enhanced Accessibility Tree - More robust element finding.

Provides comprehensive Windows UI automation using the accessibility tree,
with smart caching, fuzzy matching, and element type filtering.
Uses free libraries: uiautomation, pywinauto (optional).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import uiautomation as auto
    HAS_UIA = True
    auto.TIME_OUT_SECOND = 3
except ImportError:
    HAS_UIA = False
    auto = None
    logger.warning("uiautomation not installed. Install with: pip install uiautomation")


@dataclass
class UIElement:
    """Represents a UI element from the accessibility tree."""
    name: str
    control_type: str
    automation_id: str
    class_name: str
    bounding_rect: Tuple[int, int, int, int]  # x, y, width, height
    is_enabled: bool
    is_visible: bool
    value: str = ""
    patterns: List[str] = field(default_factory=list)
    _native: Any = None  # Native UIA control reference
    
    @property
    def center(self) -> Tuple[int, int]:
        """Get center point of element."""
        x, y, w, h = self.bounding_rect
        return (x + w // 2, y + h // 2)
    
    @property
    def is_clickable(self) -> bool:
        """Check if element is likely clickable."""
        clickable_types = {"Button", "CheckBox", "RadioButton", "MenuItem", 
                         "ListItem", "TreeItem", "TabItem", "Hyperlink"}
        return (self.control_type in clickable_types or 
                "Invoke" in self.patterns or 
                "Toggle" in self.patterns)
    
    @property
    def is_input(self) -> bool:
        """Check if element accepts text input."""
        return self.control_type in {"Edit", "Document", "ComboBox"} or "Value" in self.patterns


class AccessibilityTree:
    """Enhanced accessibility tree for robust UI element finding.
    
    Features:
    - Full tree traversal with filtering
    - Fuzzy name matching
    - Element type filtering
    - Smart caching for performance
    - Pattern-based actions (Invoke, Toggle, SetValue)
    """

    def __init__(self):
        self._cache: Dict[str, List[UIElement]] = {}
        self._cache_time: float = 0
        self._cache_duration = 2.0  # Seconds

    @property
    def available(self) -> bool:
        return HAS_UIA

    def _control_to_element(self, control) -> Optional[UIElement]:
        """Convert a UIA control to our UIElement."""
        try:
            rect = control.BoundingRectangle
            patterns = []
            
            # Check available patterns
            pattern_checks = [
                ("Invoke", auto.PatternId.InvokePattern),
                ("Toggle", auto.PatternId.TogglePattern),
                ("Value", auto.PatternId.ValuePattern),
                ("Selection", auto.PatternId.SelectionPattern),
                ("Scroll", auto.PatternId.ScrollPattern),
                ("ExpandCollapse", auto.PatternId.ExpandCollapsePattern),
            ]
            
            for name, pattern_id in pattern_checks:
                if control.GetPattern(pattern_id):
                    patterns.append(name)
            
            # Get value if available
            value = ""
            if "Value" in patterns:
                try:
                    value = control.GetValuePattern().Value or ""
                except:
                    pass
            
            return UIElement(
                name=control.Name or "",
                control_type=control.ControlTypeName or "",
                automation_id=control.AutomationId or "",
                class_name=control.ClassName or "",
                bounding_rect=(rect.left, rect.top, rect.width(), rect.height()),
                is_enabled=control.IsEnabled,
                is_visible=rect.width() > 0 and rect.height() > 0,
                value=value,
                patterns=patterns,
                _native=control,
            )
        except Exception as exc:
            logger.debug("Failed to convert control: %s", exc)
            return None

    def get_focused_element(self) -> Optional[UIElement]:
        """Get the currently focused UI element."""
        if not HAS_UIA:
            return None
        try:
            focused = auto.GetFocusedControl()
            return self._control_to_element(focused)
        except Exception:
            return None

    def get_active_window_elements(
        self,
        max_depth: int = 8,
        filter_visible: bool = True,
        filter_types: Optional[List[str]] = None,
    ) -> List[UIElement]:
        """Get all elements in the active window.
        
        Args:
            max_depth: Maximum traversal depth
            filter_visible: Only return visible elements
            filter_types: Only return these control types (e.g., ["Button", "Edit"])
            
        Returns:
            List of UIElement objects
        """
        if not HAS_UIA:
            return []
        
        elements = []
        
        try:
            window = auto.GetForegroundControl()
            
            def traverse(control, depth):
                if depth > max_depth:
                    return
                
                elem = self._control_to_element(control)
                if elem:
                    # Apply filters
                    if filter_visible and not elem.is_visible:
                        pass  # Skip
                    elif filter_types and elem.control_type not in filter_types:
                        pass  # Skip
                    else:
                        elements.append(elem)
                
                # Recurse
                for child in control.GetChildren():
                    traverse(child, depth + 1)
            
            traverse(window, 0)
            
        except Exception as exc:
            logger.warning("Failed to get window elements: %s", exc)
        
        return elements

    def find_element(
        self,
        name: Optional[str] = None,
        control_type: Optional[str] = None,
        automation_id: Optional[str] = None,
        fuzzy: bool = True,
        visible_only: bool = True,
    ) -> Optional[UIElement]:
        """Find a single element matching criteria.
        
        Args:
            name: Element name to match
            control_type: Control type to match (Button, Edit, etc.)
            automation_id: Automation ID to match
            fuzzy: Use fuzzy matching for name
            visible_only: Only search visible elements
            
        Returns:
            First matching UIElement or None
        """
        elements = self.find_elements(
            name=name,
            control_type=control_type,
            automation_id=automation_id,
            fuzzy=fuzzy,
            visible_only=visible_only,
            max_results=1,
        )
        return elements[0] if elements else None

    def find_elements(
        self,
        name: Optional[str] = None,
        control_type: Optional[str] = None,
        automation_id: Optional[str] = None,
        fuzzy: bool = True,
        visible_only: bool = True,
        max_results: int = 50,
    ) -> List[UIElement]:
        """Find all elements matching criteria.
        
        Args:
            name: Element name to match
            control_type: Control type to match
            automation_id: Automation ID to match
            fuzzy: Use fuzzy matching for name
            visible_only: Only search visible elements
            max_results: Maximum elements to return
            
        Returns:
            List of matching UIElements
        """
        all_elements = self.get_active_window_elements(
            filter_visible=visible_only,
            filter_types=[control_type] if control_type else None,
        )
        
        results = []
        
        for elem in all_elements:
            if len(results) >= max_results:
                break
            
            # Check automation_id (exact match)
            if automation_id:
                if elem.automation_id != automation_id:
                    continue
            
            # Check name
            if name:
                if fuzzy:
                    if not self._fuzzy_match(name, elem.name):
                        # Also check automation_id as fallback
                        if not self._fuzzy_match(name, elem.automation_id):
                            continue
                else:
                    if elem.name != name:
                        continue
            
            results.append(elem)
        
        return results

    def _fuzzy_match(self, query: str, text: str) -> bool:
        """Check if query fuzzy-matches text."""
        if not query or not text:
            return False
        
        query_lower = query.lower()
        text_lower = text.lower()
        
        # Exact match
        if query_lower == text_lower:
            return True
        
        # Substring match
        if query_lower in text_lower:
            return True
        
        # Word-based match (all query words in text)
        query_words = query_lower.split()
        if all(word in text_lower for word in query_words):
            return True
        
        return False

    def click_element(self, element: UIElement) -> bool:
        """Click a UI element.
        
        Args:
            element: The UIElement to click
            
        Returns:
            True if successful
        """
        if not element._native or not HAS_UIA:
            return False
        
        try:
            control = element._native
            
            # Try Invoke pattern first (cleanest)
            if control.GetPattern(auto.PatternId.InvokePattern):
                control.GetInvokePattern().Invoke()
                return True
            
            # Try Toggle pattern
            if control.GetPattern(auto.PatternId.TogglePattern):
                control.GetTogglePattern().Toggle()
                return True
            
            # Fallback to physical click
            control.Click(simulateMove=True)
            return True
            
        except Exception as exc:
            logger.warning("Click failed: %s", exc)
            # Last resort: pyautogui click at center
            try:
                import pyautogui
                center = element.center
                pyautogui.click(center[0], center[1])
                return True
            except:
                pass
        
        return False

    def set_value(self, element: UIElement, value: str) -> bool:
        """Set value of an input element.
        
        Args:
            element: The UIElement (must be an input field)
            value: Value to set
            
        Returns:
            True if successful
        """
        if not element._native or not HAS_UIA:
            return False
        
        try:
            control = element._native
            
            # Try Value pattern
            if control.GetPattern(auto.PatternId.ValuePattern):
                control.GetValuePattern().SetValue(value)
                return True
            
            # Fallback: focus and type
            control.SetFocus()
            control.SendKeys("{Ctrl}a")  # Select all
            control.SendKeys(value)
            return True
            
        except Exception as exc:
            logger.warning("Set value failed: %s", exc)
        
        return False

    def get_element_tree(self, max_depth: int = 3) -> Dict[str, Any]:
        """Get a simplified tree structure of the active window.
        
        Returns:
            Nested dict representing the element tree
        """
        if not HAS_UIA:
            return {}
        
        def build_tree(control, depth) -> Optional[Dict]:
            if depth > max_depth:
                return None
            
            try:
                children = []
                for child in control.GetChildren():
                    child_tree = build_tree(child, depth + 1)
                    if child_tree:
                        children.append(child_tree)
                
                node = {
                    "name": control.Name or "(unnamed)",
                    "type": control.ControlTypeName,
                    "id": control.AutomationId or "",
                }
                
                if children:
                    node["children"] = children
                
                return node
            except:
                return None
        
        try:
            window = auto.GetForegroundControl()
            return build_tree(window, 0) or {}
        except:
            return {}

    def find_by_description(self, description: str) -> Optional[UIElement]:
        """Find element by natural language description.
        
        Args:
            description: Natural description like "search box", "submit button"
            
        Returns:
            Best matching UIElement or None
        """
        description_lower = description.lower()
        
        # Map common descriptions to control types
        type_hints = {
            "button": "Button",
            "input": "Edit",
            "text field": "Edit",
            "textbox": "Edit",
            "search box": "Edit",
            "checkbox": "CheckBox",
            "dropdown": "ComboBox",
            "menu": "MenuItem",
            "link": "Hyperlink",
            "tab": "TabItem",
            "list item": "ListItem",
        }
        
        # Detect type from description
        detected_type = None
        for hint, ctrl_type in type_hints.items():
            if hint in description_lower:
                detected_type = ctrl_type
                # Remove the type hint from search
                description_lower = description_lower.replace(hint, "").strip()
                break
        
        # Search with detected type
        return self.find_element(
            name=description_lower if description_lower else None,
            control_type=detected_type,
            fuzzy=True,
        )


# Singleton
_accessibility_tree: Optional[AccessibilityTree] = None


def get_accessibility_tree() -> AccessibilityTree:
    """Get or create the global Accessibility Tree instance."""
    global _accessibility_tree
    if _accessibility_tree is None:
        _accessibility_tree = AccessibilityTree()
    return _accessibility_tree
