"""Smart Command Parser - Handles unclear and incomplete instructions.

Parses user commands intelligently, identifies missing information,
asks clarifying questions, and provides suggestions.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from chintu_backend.core.context_manager import get_context_manager, PendingType
from chintu_backend.core.validators import get_input_validator

logger = logging.getLogger(__name__)


class CommandIntent(str, Enum):
    """Types of user intents."""
    # Actions
    OPEN = "open"
    SEARCH = "search"
    CREATE = "create"
    DELETE = "delete"
    SEND = "send"
    PLAY = "play"
    STOP = "stop"
    SCHEDULE = "schedule"
    REMIND = "remind"
    AUTOMATE = "automate"
    LEARN = "learn"
    REMEMBER = "remember"
    RECALL = "recall"
    INSTALL = "install"
    RUN = "run"
    
    # Questions
    WHAT = "what"
    HOW = "how"
    WHERE = "where"
    WHEN = "when"
    WHO = "who"
    WHY = "why"
    
    # Confirmations
    CONFIRM = "confirm"
    CANCEL = "cancel"
    
    # Unclear
    UNKNOWN = "unknown"


@dataclass
class ParsedCommand:
    """Result of parsing a user command."""
    original: str
    intent: CommandIntent
    target: Optional[str] = None           # What to act on
    parameters: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0                # 0-1 confidence score
    is_complete: bool = True               # Has all required info?
    missing_info: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    clarification_needed: bool = False
    clarification_question: Optional[str] = None


class SmartCommandParser:
    """Parses commands intelligently with clarification handling.
    
    Features:
    - Intent detection from natural language
    - Parameter extraction
    - Missing info identification
    - Clarification question generation
    - Context-aware interpretation
    """
    
    # Intent patterns
    INTENT_PATTERNS = {
        CommandIntent.OPEN: [
            r"\b(open|launch|start|run|go to)\b",
            r"\b(browse|visit|navigate)\b",
        ],
        CommandIntent.SEARCH: [
            r"\b(search|find|look for|google|lookup)\b",
            r"\b(what is|who is|where is)\b",
        ],
        CommandIntent.CREATE: [
            r"\b(create|make|build|generate|write|new)\b",
        ],
        CommandIntent.DELETE: [
            r"\b(delete|remove|erase|clear|destroy)\b",
        ],
        CommandIntent.SEND: [
            r"\b(send|email|message|text|share)\b",
        ],
        CommandIntent.PLAY: [
            r"\b(play|music|video|stream|listen)\b",
        ],
        CommandIntent.STOP: [
            r"\b(stop|pause|halt|quit|exit|close)\b",
        ],
        CommandIntent.SCHEDULE: [
            r"\b(schedule|calendar|meeting|appointment|book)\b",
        ],
        CommandIntent.REMIND: [
            r"\b(remind|reminder|alert|notify|remember to)\b",
        ],
        CommandIntent.AUTOMATE: [
            r"\b(automate|automation|rpa|record|macro)\b",
        ],
        CommandIntent.LEARN: [
            r"\b(learn|remember that|note that|save that)\b",
            r"\b(my birthday is|i love|i like)\b",
        ],
        CommandIntent.REMEMBER: [
            r"\b(do you remember|what did i|recall|memory)\b",
        ],
        CommandIntent.INSTALL: [
            r"\b(install|setup|configure|download)\b",
        ],
        CommandIntent.RUN: [
            r"\b(run|execute|do|perform)\b",
        ],
        CommandIntent.CONFIRM: [
            r"^(yes|yeah|yep|ok|confirm|approve|go ahead)\b",
        ],
        CommandIntent.CANCEL: [
            r"^(no|nope|cancel|stop|abort|never)\b",
        ],
    }
    
    # Parameter patterns
    PARAM_PATTERNS = {
        "url": r'(https?://[^\s]+)',
        "file_path": r'([A-Za-z]:[\\\/][^\s]+|~\/[^\s]+|\/[^\s]+)',
        "email": r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
        "time": r'(at\s+)?(\d{1,2}:\d{2}(?:\s*[aApP][mM])?)',
        "date": r'(tomorrow|today|next\s+\w+|\d{1,2}\/\d{1,2}(?:\/\d{2,4})?)',
        "duration": r'(\d+\s*(?:minute|min|hour|hr|second|sec|day|week)s?)',
        "number": r'\b(\d+(?:\.\d+)?)\b',
    }
    
    # Action-specific required parameters
    REQUIRED_PARAMS = {
        CommandIntent.OPEN: ["target"],
        CommandIntent.SEARCH: ["query"],
        CommandIntent.CREATE: ["what", "type"],
        CommandIntent.SEND: ["to", "content"],
        CommandIntent.SCHEDULE: ["what", "when"],
        CommandIntent.REMIND: ["what", "when"],
        CommandIntent.INSTALL: ["package"],
    }
    
    # Clarification templates
    CLARIFICATION_TEMPLATES = {
        "target": "What would you like me to {intent}?",
        "query": "What would you like me to search for?",
        "what": "What exactly should I {intent}?",
        "type": "What type of {target} should I create?",
        "to": "Who should I send this to?",
        "content": "What message should I send?",
        "when": "When should I do this?",
        "where": "Where should I save/put this?",
        "package": "What package or app should I install?",
    }

    def __init__(self):
        self.context_manager = get_context_manager()
        self.validator = get_input_validator()
        self.last_parsed: Optional[ParsedCommand] = None
    
    def parse(self, text: str) -> ParsedCommand:
        """Parse a user command into structured data.
        
        Args:
            text: Raw user input
            
        Returns:
            ParsedCommand with intent, parameters, and status
        """
        if not text or not text.strip():
            return ParsedCommand(
                original=text or "",
                intent=CommandIntent.UNKNOWN,
                is_complete=False,
                clarification_needed=True,
                clarification_question="How can I help you?",
            )
        
        text = text.strip()
        
        # First check if this resolves a pending request
        handled, msg, result = self.context_manager.process_user_input(text)
        if handled:
            return ParsedCommand(
                original=text,
                intent=CommandIntent.CONFIRM if result else CommandIntent.CANCEL,
                is_complete=True,
                parameters={"response_message": msg, "result": result},
            )
        
        # Detect intent
        intent, confidence = self._detect_intent(text)
        
        # Extract parameters
        params = self._extract_parameters(text)
        
        # Identify target (what to act on)
        target = self._extract_target(text, intent)
        
        # Check for missing required info
        missing = self._find_missing_info(intent, params, target)
        
        # Build result
        parsed = ParsedCommand(
            original=text,
            intent=intent,
            target=target,
            parameters=params,
            confidence=confidence,
            is_complete=len(missing) == 0,
            missing_info=missing,
        )
        
        # Generate clarification if needed
        if missing and confidence > 0.5:
            parsed.clarification_needed = True
            parsed.clarification_question = self._generate_clarification(intent, missing[0])
            
            # Create pending request
            self.context_manager.create_pending_request(
                request_type=PendingType.MISSING_INFO,
                prompt=parsed.clarification_question,
                original_command=text,
                required_fields=missing,
                callback_name="continue_task",
                context={"intent": intent.value, "params": params},
            )
        
        # Handle low confidence
        if confidence < 0.5:
            parsed.suggestions = self._generate_suggestions(text)
            if not parsed.clarification_question:
                parsed.clarification_question = "I'm not sure what you mean. Did you want to:\n" + \
                    "\n".join(f"  {i+1}. {s}" for i, s in enumerate(parsed.suggestions[:3]))
                parsed.clarification_needed = True
        
        self.last_parsed = parsed
        return parsed
    
    def _detect_intent(self, text: str) -> Tuple[CommandIntent, float]:
        """Detect the intent from text."""
        text_lower = text.lower()
        
        best_intent = CommandIntent.UNKNOWN
        best_confidence = 0.0
        
        for intent, patterns in self.INTENT_PATTERNS.items():
            for pattern in patterns:
                match = re.search(pattern, text_lower, re.IGNORECASE)
                if match:
                    # Calculate confidence based on match position and length
                    match_start = match.start()
                    confidence = 0.8 if match_start < 10 else 0.6
                    
                    if confidence > best_confidence:
                        best_confidence = confidence
                        best_intent = intent
        
        # Boost confidence if it's a question
        if text.strip().endswith("?"):
            question_intents = [CommandIntent.WHAT, CommandIntent.HOW, CommandIntent.WHERE]
            for qi in question_intents:
                if qi.value in text_lower:
                    return qi, 0.9
        
        return best_intent, best_confidence
    
    def _extract_parameters(self, text: str) -> Dict[str, Any]:
        """Extract parameters from text."""
        params = {}
        
        for param_name, pattern in self.PARAM_PATTERNS.items():
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                # Take the first match, handle tuples from groups
                value = matches[0]
                if isinstance(value, tuple):
                    value = value[-1]  # Take last group
                params[param_name] = value
        
        return params
    
    def _extract_target(self, text: str, intent: CommandIntent) -> Optional[str]:
        """Extract the target of the action."""
        text_lower = text.lower()
        
        # Remove common intent words to find target
        intent_words = {
            CommandIntent.OPEN: ["open", "launch", "start", "run"],
            CommandIntent.SEARCH: ["search", "find", "lookup", "google"],
            CommandIntent.CREATE: ["create", "make", "build", "new"],
            CommandIntent.DELETE: ["delete", "remove", "erase"],
            CommandIntent.PLAY: ["play", "listen to", "stream"],
            CommandIntent.STOP: ["stop", "close", "quit", "exit"],
        }
        
        words_to_remove = intent_words.get(intent, [])
        target_text = text_lower
        
        for word in words_to_remove:
            target_text = re.sub(rf'\b{word}\b', '', target_text, flags=re.IGNORECASE)
        
        # Clean up
        target_text = target_text.strip()
        target_text = re.sub(r'\s+', ' ', target_text)
        
        # Remove common fillers
        fillers = ["the", "a", "an", "please", "can you", "i want to", "i need to"]
        for filler in fillers:
            target_text = re.sub(rf'\b{filler}\b', '', target_text, flags=re.IGNORECASE)
        
        target_text = target_text.strip()
        
        return target_text if target_text else None
    
    def _find_missing_info(
        self, 
        intent: CommandIntent, 
        params: Dict[str, Any],
        target: Optional[str],
    ) -> List[str]:
        """Find missing required information."""
        missing = []
        
        required = self.REQUIRED_PARAMS.get(intent, [])
        
        for req in required:
            if req == "target":
                if not target:
                    missing.append(req)
            elif req not in params or not params[req]:
                missing.append(req)
        
        return missing
    
    def _generate_clarification(self, intent: CommandIntent, missing: str) -> str:
        """Generate a clarification question."""
        template = self.CLARIFICATION_TEMPLATES.get(
            missing, 
            f"What {missing} would you like?"
        )
        return template.format(intent=intent.value, target="{target}")
    
    def _generate_suggestions(self, text: str) -> List[str]:
        """Generate suggestions for unclear input."""
        text_lower = text.lower()
        
        suggestions = []
        
        # Common actions
        if any(word in text_lower for word in ["app", "program", "software"]):
            suggestions.append("Open an application")
            suggestions.append("Install software")
        
        if any(word in text_lower for word in ["web", "site", "page", "browser"]):
            suggestions.append("Open a website")
            suggestions.append("Search the web")
        
        if any(word in text_lower for word in ["file", "document", "folder"]):
            suggestions.append("Open a file")
            suggestions.append("Create a new file")
        
        if any(word in text_lower for word in ["time", "date", "schedule", "meeting"]):
            suggestions.append("Schedule a meeting")
            suggestions.append("Set a reminder")
        
        # Default suggestions
        if not suggestions:
            suggestions = [
                "Open an app or website",
                "Search for something",
                "Create or run a file",
                "Set a reminder",
            ]
        
        return suggestions

    def get_help_for_intent(self, intent: CommandIntent) -> str:
        """Get usage help for an intent."""
        help_texts = {
            CommandIntent.OPEN: "Open apps or websites: 'open chrome', 'open google.com'",
            CommandIntent.SEARCH: "Search the web: 'search for AI news', 'google python tutorials'",
            CommandIntent.CREATE: "Create files: 'create a new python file', 'make a todo list'",
            CommandIntent.SEND: "Send messages: 'send email to john@example.com', 'text mom'",
            CommandIntent.SCHEDULE: "Schedule events: 'schedule meeting tomorrow at 3pm'",
            CommandIntent.REMIND: "Set reminders: 'remind me to call John in 2 hours'",
            CommandIntent.AUTOMATE: "Record automations: 'record a macro', 'automate login'",
            CommandIntent.LEARN: "Teach me facts: 'remember that my birthday is March 15'",
            CommandIntent.INSTALL: "Install packages: 'install numpy', 'setup docker'",
        }
        return help_texts.get(intent, "I can help with various tasks. Try asking!")


# Singleton
_parser: Optional[SmartCommandParser] = None


def get_command_parser() -> SmartCommandParser:
    """Get or create the global Smart Command Parser."""
    global _parser
    if _parser is None:
        _parser = SmartCommandParser()
    return _parser
