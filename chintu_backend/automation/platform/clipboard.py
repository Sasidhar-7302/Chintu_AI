"""
Clipboard Utilities for Chintu AI Assistant.

Provides clipboard interaction:
- Read clipboard content
- Write to clipboard
- Clipboard history
- Content analysis
"""

import logging
from typing import Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)

try:
    import pyperclip
    HAS_PYPERCLIP = True
except ImportError:
    HAS_PYPERCLIP = False
    logger.warning("pyperclip not installed - clipboard disabled")


class ClipboardManager:
    """
    Manages clipboard interactions.
    
    Features:
    - Read/write clipboard
    - Track clipboard history
    - Analyze content type
    """
    
    def __init__(self, max_history: int = 20):
        """
        Initialize clipboard manager.
        
        Args:
            max_history: Maximum history entries to keep
        """
        self.max_history = max_history
        self._history: List[dict] = []
        
    @property
    def is_available(self) -> bool:
        """Check if clipboard is available."""
        return HAS_PYPERCLIP
    
    def get(self) -> Optional[str]:
        """
        Get current clipboard content.
        
        Returns:
            Clipboard text or None
        """
        if not HAS_PYPERCLIP:
            return None
        
        try:
            content = pyperclip.paste()
            return content if content else None
        except Exception as e:
            logger.error(f"Failed to read clipboard: {e}")
            return None
    
    def set(self, text: str) -> bool:
        """
        Set clipboard content.
        
        Args:
            text: Text to copy to clipboard
            
        Returns:
            True if successful
        """
        if not HAS_PYPERCLIP:
            return False
        
        try:
            pyperclip.copy(text)
            
            # Add to history
            self._add_to_history(text)
            
            logger.debug(f"Copied to clipboard: {len(text)} chars")
            return True
        except Exception as e:
            logger.error(f"Failed to set clipboard: {e}")
            return False
    
    def _add_to_history(self, text: str):
        """Add text to clipboard history."""
        entry = {
            'content': text,
            'timestamp': datetime.now().isoformat(),
            'length': len(text),
            'type': self._detect_type(text),
        }
        
        # Avoid duplicates
        if self._history and self._history[-1]['content'] == text:
            return
        
        self._history.append(entry)
        
        # Trim history
        if len(self._history) > self.max_history:
            self._history = self._history[-self.max_history:]
    
    def _detect_type(self, text: str) -> str:
        """Detect content type of text."""
        text = text.strip()
        
        # URL
        if text.startswith(('http://', 'https://', 'www.')):
            return 'url'
        
        # Email
        if '@' in text and '.' in text and len(text) < 100:
            return 'email'
        
        # Phone
        if text.replace('-', '').replace(' ', '').replace('(', '').replace(')', '').replace('+', '').isdigit():
            if 7 <= len(text.replace('-', '').replace(' ', '')) <= 15:
                return 'phone'
        
        # Code (has common code patterns)
        code_indicators = ['def ', 'function ', 'class ', 'import ', 'const ', 'let ', 'var ', '{}', '();']
        if any(ind in text for ind in code_indicators):
            return 'code'
        
        # File path
        if ':\\' in text or text.startswith('/'):
            return 'path'
        
        return 'text'
    
    def get_history(self, count: int = 5) -> List[dict]:
        """
        Get clipboard history.
        
        Args:
            count: Number of entries to return
            
        Returns:
            List of history entries
        """
        return self._history[-count:]
    
    def get_from_history(self, index: int) -> Optional[str]:
        """
        Get content from history by index (1 = most recent).
        
        Args:
            index: 1-based index from most recent
            
        Returns:
            Content or None
        """
        if not self._history:
            return None
        
        try:
            return self._history[-index]['content']
        except (IndexError, KeyError):
            return None
    
    def clear_history(self):
        """Clear clipboard history."""
        self._history.clear()
    
    def analyze(self, text: Optional[str] = None) -> dict:
        """
        Analyze clipboard content.
        
        Args:
            text: Text to analyze (defaults to current clipboard)
            
        Returns:
            Analysis dict with type, length, etc.
        """
        if text is None:
            text = self.get()
        
        if not text:
            return {'empty': True}
        
        return {
            'empty': False,
            'length': len(text),
            'words': len(text.split()),
            'lines': len(text.splitlines()),
            'type': self._detect_type(text),
            'preview': text[:100] + '...' if len(text) > 100 else text,
        }


# Global instance
_clipboard: Optional[ClipboardManager] = None


def get_clipboard() -> ClipboardManager:
    """Get or create the global clipboard manager."""
    global _clipboard
    if _clipboard is None:
        _clipboard = ClipboardManager()
    return _clipboard
