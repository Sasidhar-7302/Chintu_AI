"""Command parsing from transcribed text."""

import re
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Tuple
import logging

logger = logging.getLogger(__name__)


class CommandType(Enum):
    """Types of commands Chintu can handle."""
    OPEN_APP = "open_app"           # Open an application
    OPEN_URL = "open_url"           # Open a website
    SEARCH_JOBS = "search_jobs"     # Search for jobs
    DRAFT_RESUME = "draft_resume"   # Draft a resume
    DRAFT_SOP = "draft_sop"         # Draft statement of purpose
    DRAFT_EMAIL = "draft_email"     # Draft an email
    ASK_QUESTION = "ask_question"   # General Q&A with LLM
    SYSTEM_COMMAND = "system"       # System commands (volume, screenshot, etc.)
    UNKNOWN = "unknown"             # Unrecognized command


@dataclass
class Command:
    """Parsed command structure."""
    type: CommandType
    action: str
    target: Optional[str] = None
    parameters: Dict[str, Any] = None
    raw_text: str = ""
    confidence: float = 1.0
    
    def __post_init__(self):
        if self.parameters is None:
            self.parameters = {}


class CommandParser:
    """
    Parses natural language text into structured commands.
    Uses keyword matching and pattern recognition.
    """
    
    # Known applications and their launch commands/paths
    KNOWN_APPS = {
        "linkedin": ("https://www.linkedin.com", "url"),
        "youtube": ("https://www.youtube.com", "url"),
        "google": ("https://www.google.com", "url"),
        "gmail": ("https://mail.google.com", "url"),
        "github": ("https://github.com", "url"),
        "twitter": ("https://twitter.com", "url"),
        "x": ("https://twitter.com", "url"),
        "spotify": ("spotify", "app"),
        "chrome": ("chrome", "app"),
        "firefox": ("firefox", "app"),
        "notepad": ("notepad", "app"),
        "calculator": ("calc", "app"),
        "file explorer": ("explorer", "app"),
        "settings": ("ms-settings:", "app"),
        "word": ("winword", "app"),
        "excel": ("excel", "app"),
        "powerpoint": ("powerpnt", "app"),
        "vs code": ("code", "app"),
        "visual studio code": ("code", "app"),
        "terminal": ("wt", "app"),
        "cmd": ("cmd", "app"),
    }
    
    # Patterns for different command types
    PATTERNS = {
        CommandType.OPEN_APP: [
            r"open\s+(.+)",
            r"launch\s+(.+)",
            r"start\s+(.+)",
            r"go\s+to\s+(.+)",
        ],
        CommandType.SEARCH_JOBS: [
            r"search\s+(?:for\s+)?(.+?)\s+jobs?",
            r"find\s+(.+?)\s+jobs?",
            r"look\s+for\s+(.+?)\s+jobs?",
            r"job\s+search\s+(?:for\s+)?(.+)",
        ],
        CommandType.DRAFT_RESUME: [
            r"(?:draft|write|create)\s+(?:a\s+)?resume\s+(?:for\s+)?(?:a\s+)?(.+)?",
            r"(?:help\s+(?:me\s+)?)?(?:with\s+)?(?:my\s+)?resume",
        ],
        CommandType.DRAFT_SOP: [
            r"(?:draft|write|create)\s+(?:a\s+)?(?:statement\s+of\s+purpose|sop)",
            r"sop\s+for\s+(.+)",
        ],
        CommandType.DRAFT_EMAIL: [
            r"(?:draft|write|compose)\s+(?:an?\s+)?email\s+(?:to\s+)?(.+)?",
        ],
    }
    
    def __init__(self):
        self._compiled_patterns = {
            cmd_type: [re.compile(p, re.IGNORECASE) for p in patterns]
            for cmd_type, patterns in self.PATTERNS.items()
        }
    
    def parse(self, text: str) -> Command:
        """
        Parse text into a command.
        
        Args:
            text: Transcribed text from speech
            
        Returns:
            Parsed Command object
        """
        text = text.strip().lower()
        
        if not text:
            return Command(CommandType.UNKNOWN, "empty", raw_text=text)
        
        # Try to match patterns
        for cmd_type, patterns in self._compiled_patterns.items():
            for pattern in patterns:
                match = pattern.search(text)
                if match:
                    return self._create_command(cmd_type, match, text)
        
        # Check for direct app/url mentions
        for app_name, (target, app_type) in self.KNOWN_APPS.items():
            if app_name in text:
                cmd_type = CommandType.OPEN_URL if app_type == "url" else CommandType.OPEN_APP
                return Command(
                    type=cmd_type,
                    action="open",
                    target=target,
                    parameters={"app_name": app_name},
                    raw_text=text,
                )
        
        # Default to asking the LLM
        return Command(
            type=CommandType.ASK_QUESTION,
            action="ask",
            parameters={"question": text},
            raw_text=text,
        )
    
    def _create_command(self, cmd_type: CommandType, match: re.Match, text: str) -> Command:
        """Create command from regex match."""
        groups = match.groups()
        target = groups[0].strip() if groups and groups[0] else None
        
        if cmd_type == CommandType.OPEN_APP and target:
            # Check if target is a known app
            target_lower = target.lower()
            if target_lower in self.KNOWN_APPS:
                app_target, app_type = self.KNOWN_APPS[target_lower]
                return Command(
                    type=CommandType.OPEN_URL if app_type == "url" else CommandType.OPEN_APP,
                    action="open",
                    target=app_target,
                    parameters={"app_name": target_lower},
                    raw_text=text,
                )
        
        return Command(
            type=cmd_type,
            action=cmd_type.value.split("_")[0],
            target=target,
            raw_text=text,
        )

