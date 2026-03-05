"""
Structured DOM - Element references for browser automation.

Provides structured snapshots of web pages with unique refs for each
interactive element, enabling precise actions like "click ref=btn_submit".
"""

import re
import hashlib
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from enum import Enum


class ElementRole(Enum):
    """Semantic roles for elements."""
    BUTTON = "button"
    LINK = "link"
    INPUT = "input"
    SELECT = "select"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    TEXTAREA = "textarea"
    IMAGE = "image"
    HEADING = "heading"
    TEXT = "text"
    CONTAINER = "container"
    NAVIGATION = "navigation"
    FORM = "form"
    TABLE = "table"
    LIST = "list"
    UNKNOWN = "unknown"


@dataclass
class DOMElement:
    """A single element in the structured DOM."""
    ref: str  # Unique reference like "btn_1", "input_email"
    tag: str  # HTML tag
    role: ElementRole
    text: str  # Visible text content
    attributes: Dict[str, str] = field(default_factory=dict)
    interactive: bool = False  # Can be clicked/typed
    visible: bool = True
    bounding_box: Optional[Dict[str, float]] = None  # x, y, width, height
    children_refs: List[str] = field(default_factory=list)
    parent_ref: Optional[str] = None
    
    @property
    def selector(self) -> str:
        """Generate a CSS selector for this element."""
        if self.attributes.get("id"):
            return f"#{self.attributes['id']}"
        if self.attributes.get("name"):
            return f"[name='{self.attributes['name']}']"
        if self.attributes.get("data-testid"):
            return f"[data-testid='{self.attributes['data-testid']}']"
        # Fallback to tag + class
        classes = self.attributes.get("class", "").split()
        if classes:
            return f"{self.tag}.{'.'.join(classes[:2])}"
        return self.tag
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "ref": self.ref,
            "tag": self.tag,
            "role": self.role.value,
            "text": self.text[:100] if self.text else "",
            "interactive": self.interactive,
            "visible": self.visible,
            "selector": self.selector
        }


@dataclass
class StructuredDOM:
    """
    Structured representation of a web page's DOM.
    
    Provides:
    - Unique refs for each element
    - Filtered view of interactive elements
    - Role-based querying
    """
    url: str
    title: str
    elements: Dict[str, DOMElement] = field(default_factory=dict)
    root_refs: List[str] = field(default_factory=list)
    timestamp: float = 0
    
    def add_element(self, element: DOMElement):
        """Add an element to the DOM."""
        self.elements[element.ref] = element
    
    def get_by_ref(self, ref: str) -> Optional[DOMElement]:
        """Get element by its unique ref."""
        return self.elements.get(ref)
    
    def get_interactive(self) -> List[DOMElement]:
        """Get all interactive elements (buttons, inputs, links, etc.)."""
        return [e for e in self.elements.values() 
                if e.interactive and e.visible]
    
    def get_by_role(self, role: ElementRole) -> List[DOMElement]:
        """Get elements by semantic role."""
        return [e for e in self.elements.values() if e.role == role]
    
    def get_by_text(self, text: str, partial: bool = True) -> List[DOMElement]:
        """Find elements containing specific text."""
        text_lower = text.lower()
        if partial:
            return [e for e in self.elements.values() 
                    if text_lower in (e.text or "").lower()]
        return [e for e in self.elements.values() 
                if text_lower == (e.text or "").lower()]
    
    def get_inputs(self) -> List[DOMElement]:
        """Get all input elements (text, select, checkbox, etc.)."""
        input_roles = {ElementRole.INPUT, ElementRole.SELECT, 
                       ElementRole.CHECKBOX, ElementRole.RADIO, ElementRole.TEXTAREA}
        return [e for e in self.elements.values() 
                if e.role in input_roles and e.visible]
    
    def get_buttons(self) -> List[DOMElement]:
        """Get all button elements."""
        return [e for e in self.elements.values() 
                if e.role == ElementRole.BUTTON and e.visible]
    
    def get_links(self) -> List[DOMElement]:
        """Get all link elements."""
        return [e for e in self.elements.values() 
                if e.role == ElementRole.LINK and e.visible]
    
    def to_summary(self, max_elements: int = 50) -> str:
        """Generate a text summary for LLM consumption."""
        lines = [
            f"Page: {self.title}",
            f"URL: {self.url}",
            f"Total elements: {len(self.elements)}",
            "",
            "Interactive elements:"
        ]
        
        interactive = self.get_interactive()[:max_elements]
        for elem in interactive:
            text = elem.text[:50] if elem.text else ""
            lines.append(f"  [{elem.ref}] {elem.role.value}: {text}")
        
        if len(self.get_interactive()) > max_elements:
            lines.append(f"  ... and {len(self.get_interactive()) - max_elements} more")
        
        return "\n".join(lines)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "url": self.url,
            "title": self.title,
            "element_count": len(self.elements),
            "interactive_count": len(self.get_interactive()),
            "elements": [e.to_dict() for e in self.get_interactive()[:100]]
        }


class DOMParser:
    """
    Parses raw HTML/page content into StructuredDOM.
    
    Assigns unique refs and identifies interactive elements.
    """
    
    INTERACTIVE_TAGS = {
        "button", "a", "input", "select", "textarea", 
        "label", "option", "details", "summary"
    }
    
    ROLE_MAP = {
        "button": ElementRole.BUTTON,
        "a": ElementRole.LINK,
        "input": ElementRole.INPUT,
        "select": ElementRole.SELECT,
        "textarea": ElementRole.TEXTAREA,
        "h1": ElementRole.HEADING,
        "h2": ElementRole.HEADING,
        "h3": ElementRole.HEADING,
        "h4": ElementRole.HEADING,
        "h5": ElementRole.HEADING,
        "h6": ElementRole.HEADING,
        "img": ElementRole.IMAGE,
        "nav": ElementRole.NAVIGATION,
        "form": ElementRole.FORM,
        "table": ElementRole.TABLE,
        "ul": ElementRole.LIST,
        "ol": ElementRole.LIST,
        "div": ElementRole.CONTAINER,
        "span": ElementRole.TEXT,
        "p": ElementRole.TEXT,
    }

    AX_SKIP_ROLES = {
        "",
        "generic",
        "none",
        "presentation",
        "inline text box",
        "linebreak",
    }

    AX_SIGNAL_ROLES = {
        "heading",
        "link",
        "button",
        "menuitem",
        "tab",
        "textbox",
        "combobox",
        "checkbox",
        "radio",
        "option",
        "img",
        "text",
        "statictext",
    }
    
    def __init__(self):
        self._ref_counters: Dict[str, int] = {}
    
    def parse_from_playwright(
        self, 
        page_data: Dict[str, Any],
        url: str,
        title: str
    ) -> StructuredDOM:
        """
        Parse Playwright accessibility snapshot into StructuredDOM.
        
        Args:
            page_data: Playwright's accessibility tree
            url: Current page URL
            title: Page title
        """
        import time
        
        self._ref_counters = {}
        dom = StructuredDOM(url=url, title=title, timestamp=time.time())
        
        def process_node(node: Dict, parent_ref: Optional[str] = None) -> Optional[str]:
            role = str(node.get("role") or "")
            name = self._normalize_text(node.get("name", ""), max_len=120)
            tag = self._role_to_tag(role)
            interactive = self._is_interactive(role, node)
            visible = self._is_ax_node_visible(node)

            ref: Optional[str] = None
            if self._keep_ax_node(role, name, interactive, visible):
                ref = self._generate_ref(tag, name)
                elem_role = self._get_element_role(role, tag)
                element = DOMElement(
                    ref=ref,
                    tag=tag,
                    role=elem_role,
                    text=name,
                    attributes={"role": role},
                    interactive=interactive,
                    visible=visible,
                    parent_ref=parent_ref,
                )
                dom.add_element(element)

            next_parent_ref = ref if ref else parent_ref
            for child in node.get("children", []):
                process_node(child, next_parent_ref)
            return ref
        
        if page_data:
            root_ref = process_node(page_data)
            if root_ref:
                dom.root_refs.append(root_ref)
        
        return dom
    
    def parse_from_html(self, html: str, url: str, title: str) -> StructuredDOM:
        """Parse raw HTML into StructuredDOM."""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            # Fallback to basic parsing
            return self._basic_html_parse(html, url, title)
        
        import time
        
        self._ref_counters = {}
        soup = BeautifulSoup(html, "html.parser")
        dom = StructuredDOM(url=url, title=title, timestamp=time.time())
        
        # Find all potentially interesting elements
        for tag in soup.find_all(True):
            tag_name = tag.name.lower()
            
            # Skip script/style/meta
            if tag_name in {"script", "style", "meta", "link", "head", "html", "body"}:
                continue
            
            # Get text content
            text = tag.get_text(strip=True)[:200] if tag.string or tag.get_text() else ""
            
            # Generate ref
            ref = self._generate_ref(tag_name, text)
            
            # Get attributes
            attrs = {k: str(v) for k, v in tag.attrs.items() if isinstance(v, str)}
            if "class" in tag.attrs:
                attrs["class"] = " ".join(tag.attrs["class"]) if isinstance(tag.attrs["class"], list) else tag.attrs["class"]
            
            # Determine role
            elem_role = self.ROLE_MAP.get(tag_name, ElementRole.UNKNOWN)
            if tag_name == "input":
                input_type = tag.get("type", "text")
                if input_type == "checkbox":
                    elem_role = ElementRole.CHECKBOX
                elif input_type == "radio":
                    elem_role = ElementRole.RADIO
            
            # Check if interactive
            interactive = tag_name in self.INTERACTIVE_TAGS
            if tag.get("onclick") or tag.get("href"):
                interactive = True
            
            element = DOMElement(
                ref=ref,
                tag=tag_name,
                role=elem_role,
                text=text,
                attributes=attrs,
                interactive=interactive,
                visible=True
            )
            
            dom.add_element(element)
        
        return dom
    
    def _basic_html_parse(self, html: str, url: str, title: str) -> StructuredDOM:
        """Basic HTML parsing without BeautifulSoup."""
        import time
        
        self._ref_counters = {}
        dom = StructuredDOM(url=url, title=title, timestamp=time.time())
        
        # Simple regex-based extraction of interactive elements
        patterns = {
            "button": r'<button[^>]*>(.*?)</button>',
            "a": r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>(.*?)</a>',
            "input": r'<input[^>]*(?:name|id)=["\']([^"\']*)["\'][^>]*>',
        }
        
        for tag, pattern in patterns.items():
            for match in re.finditer(pattern, html, re.IGNORECASE | re.DOTALL):
                text = match.group(1) if match.lastindex else ""
                text = re.sub(r'<[^>]+>', '', text)  # Strip HTML tags
                
                ref = self._generate_ref(tag, text)
                elem_role = self.ROLE_MAP.get(tag, ElementRole.UNKNOWN)
                
                element = DOMElement(
                    ref=ref,
                    tag=tag,
                    role=elem_role,
                    text=text[:100],
                    interactive=True,
                    visible=True
                )
                dom.add_element(element)
        
        return dom
    
    def _generate_ref(self, tag: str, name: str = "") -> str:
        """Generate a unique, readable ref for an element."""
        # Create base ref from tag and name
        if name:
            # Sanitize name
            safe_name = re.sub(r'[^a-zA-Z0-9]', '_', name[:20]).lower().strip('_')
            base = f"{tag}_{safe_name}" if safe_name else tag
        else:
            base = tag
        
        # Add counter for uniqueness
        if base not in self._ref_counters:
            self._ref_counters[base] = 0
        self._ref_counters[base] += 1
        
        if self._ref_counters[base] == 1:
            return base
        return f"{base}_{self._ref_counters[base]}"
    
    def _role_to_tag(self, role: str) -> str:
        """Convert accessibility role to HTML tag."""
        role_tag_map = {
            "button": "button",
            "link": "a",
            "textbox": "input",
            "combobox": "select",
            "checkbox": "input",
            "radio": "input",
            "heading": "h2",
            "img": "img",
            "navigation": "nav",
        }
        return role_tag_map.get(role.lower(), "div")

    @staticmethod
    def _normalize_text(value: str, max_len: int = 120) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if len(text) > max_len:
            return text[:max_len]
        return text

    @staticmethod
    def _is_ax_node_visible(node: Dict[str, Any]) -> bool:
        if bool(node.get("hidden")):
            return False
        if bool(node.get("ignored")):
            return False
        return True

    def _keep_ax_node(self, role: str, name: str, interactive: bool, visible: bool) -> bool:
        role_lower = str(role or "").strip().lower()
        if interactive:
            return visible
        if not visible:
            return False
        if role_lower in self.AX_SKIP_ROLES and not name:
            return False
        if role_lower in self.AX_SIGNAL_ROLES and name:
            return True
        if role_lower in {"navigation", "form", "main", "dialog", "alert"} and name:
            return True
        return False
    
    def _get_element_role(self, role: str, tag: str) -> ElementRole:
        """Determine element role from accessibility role or tag."""
        role_lower = role.lower()
        
        if "button" in role_lower:
            return ElementRole.BUTTON
        if "link" in role_lower:
            return ElementRole.LINK
        if "textbox" in role_lower or "input" in role_lower:
            return ElementRole.INPUT
        if "combobox" in role_lower or "select" in role_lower:
            return ElementRole.SELECT
        if "checkbox" in role_lower:
            return ElementRole.CHECKBOX
        if "radio" in role_lower:
            return ElementRole.RADIO
        if "heading" in role_lower:
            return ElementRole.HEADING
        
        return self.ROLE_MAP.get(tag, ElementRole.UNKNOWN)
    
    def _is_interactive(self, role: str, node: Dict) -> bool:
        """Check if an element is interactive."""
        role_lower = role.lower()
        
        interactive_roles = {
            "button", "link", "textbox", "combobox", "checkbox",
            "radio", "menuitem", "tab", "slider", "spinbutton"
        }
        
        return role_lower in interactive_roles
