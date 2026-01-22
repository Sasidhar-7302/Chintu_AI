"""
Conversation Memory for Chintu AI Assistant.

Provides persistent conversation context across sessions:
- Remember what was discussed
- Track user preferences from conversations
- Enable "do it again" functionality
- Support multi-turn context
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from pathlib import Path
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


@dataclass
class ConversationTurn:
    """A single turn in the conversation."""
    role: str  # "user" or "assistant"
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    capability: str = ""  # What capability was used
    success: bool = True


@dataclass 
class ConversationSession:
    """A conversation session."""
    session_id: str
    started: str
    turns: List[ConversationTurn] = field(default_factory=list)
    last_command: str = ""
    last_response: str = ""
    last_capability: str = ""


class ConversationMemory:
    """
    Manages conversation history and context.
    
    Features:
    - Persistent storage across restarts
    - Recent context for LLM
    - "Last command" for "do it again"
    - Session management
    """
    
    def __init__(self, storage_path: Optional[str] = None, max_turns: int = 50):
        """
        Initialize conversation memory.
        
        Args:
            storage_path: Path to store conversation history
            max_turns: Maximum turns to keep in memory
        """
        self.storage_path = storage_path or str(
            Path.home() / '.chintu' / 'conversation_history.json'
        )
        self.max_turns = max_turns
        
        self._current_session: Optional[ConversationSession] = None
        self._history: List[Dict] = []
        
        self._load_history()
        self._start_session()
    
    def _load_history(self):
        """Load conversation history from disk."""
        try:
            if os.path.exists(self.storage_path):
                with open(self.storage_path, 'r', encoding='utf-8') as f:
                    self._history = json.load(f)
                logger.info(f"Loaded {len(self._history)} conversation sessions")
        except Exception as e:
            logger.warning(f"Could not load conversation history: {e}")
            self._history = []
    
    def _save_history(self):
        """Save conversation history to disk."""
        try:
            os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
            with open(self.storage_path, 'w', encoding='utf-8') as f:
                json.dump(self._history[-100:], f, indent=2)  # Keep last 100 sessions
        except Exception as e:
            logger.warning(f"Could not save conversation history: {e}")
    
    def _start_session(self):
        """Start a new conversation session."""
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._current_session = ConversationSession(
            session_id=session_id,
            started=datetime.now().isoformat(),
        )
        logger.debug(f"Started conversation session: {session_id}")
    
    def add_turn(self, role: str, content: str, capability: str = "", success: bool = True):
        """
        Add a turn to the conversation.
        
        Args:
            role: "user" or "assistant"
            content: The message content
            capability: Which capability was used
            success: Whether the action succeeded
        """
        if not self._current_session:
            self._start_session()
        
        turn = ConversationTurn(
            role=role,
            content=content,
            capability=capability,
            success=success,
        )
        
        self._current_session.turns.append(turn)
        
        # Track last command/response for "do it again"
        if role == "user":
            self._current_session.last_command = content
            self._current_session.last_capability = capability
        else:
            self._current_session.last_response = content
        
        # Trim if too long
        if len(self._current_session.turns) > self.max_turns:
            self._current_session.turns = self._current_session.turns[-self.max_turns:]
        
        # Auto-save periodically
        if len(self._current_session.turns) % 10 == 0:
            self._save_session()
    
    def _save_session(self):
        """Save current session to history."""
        if self._current_session and self._current_session.turns:
            session_dict = {
                'session_id': self._current_session.session_id,
                'started': self._current_session.started,
                'turns': [asdict(t) for t in self._current_session.turns],
                'last_command': self._current_session.last_command,
                'last_response': self._current_session.last_response,
                'last_capability': self._current_session.last_capability,
            }
            
            # Update or add session
            for i, h in enumerate(self._history):
                if h.get('session_id') == self._current_session.session_id:
                    self._history[i] = session_dict
                    break
            else:
                self._history.append(session_dict)
            
            self._save_history()
    
    def get_last_command(self) -> Optional[str]:
        """Get the last user command."""
        if self._current_session:
            return self._current_session.last_command
        return None
    
    def get_last_capability(self) -> Optional[str]:
        """Get the last capability used."""
        if self._current_session:
            return self._current_session.last_capability
        return None
    
    def get_context(self, max_turns: int = 10) -> str:
        """
        Get recent conversation context for LLM.
        
        Args:
            max_turns: Maximum turns to include
            
        Returns:
            Formatted conversation context
        """
        if not self._current_session or not self._current_session.turns:
            return ""
        
        recent = self._current_session.turns[-max_turns:]
        
        lines = []
        for turn in recent:
            role = "User" if turn.role == "user" else "Chintu"
            lines.append(f"{role}: {turn.content}")
        
        return "\n".join(lines)
    
    def get_context_for_llm(self, max_turns: int = 5) -> List[Dict[str, str]]:
        """
        Get context formatted for LLM messages.
        
        Returns:
            List of {"role": "user/assistant", "content": "..."}
        """
        if not self._current_session or not self._current_session.turns:
            return []
        
        recent = self._current_session.turns[-max_turns:]
        
        messages = []
        for turn in recent:
            messages.append({
                "role": turn.role,
                "content": turn.content,
            })
        
        return messages
    
    def search_history(self, query: str, max_results: int = 5) -> List[Dict]:
        """
        Search conversation history.
        
        Args:
            query: Search query
            max_results: Maximum results
            
        Returns:
            List of matching turns
        """
        query_lower = query.lower()
        results = []
        
        for session in reversed(self._history):
            for turn in session.get('turns', []):
                if query_lower in turn.get('content', '').lower():
                    results.append({
                        'session_id': session['session_id'],
                        'timestamp': turn.get('timestamp'),
                        'role': turn.get('role'),
                        'content': turn.get('content'),
                    })
                    if len(results) >= max_results:
                        return results
        
        return results
    
    def end_session(self):
        """End current session and save."""
        self._save_session()
        self._current_session = None


# Global instance
_memory: Optional[ConversationMemory] = None


def get_conversation_memory() -> ConversationMemory:
    """Get or create the global conversation memory."""
    global _memory
    if _memory is None:
        _memory = ConversationMemory()
    return _memory
