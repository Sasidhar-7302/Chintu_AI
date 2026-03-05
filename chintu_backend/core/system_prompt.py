"""
System Prompt Builder for Chintu AI.
Implements the "Smart Session Initialization" strategy:
1. Loads SOUL.md (Core Principles)
2. Loads USER.md (User Preferences & Context)
3. Loads IDENTITY.md (Persona)
4. AVOIDS loading full history by default to save tokens.
"""

import logging
from pathlib import Path
from typing import Optional
from chintu_backend.core.config import get_config

logger = logging.getLogger(__name__)

class SystemPromptBuilder:
    def __init__(self):
        self.config = get_config()
        self.brain_dir = self.config.data_dir / "brain_md"
        self.brain_dir.mkdir(parents=True, exist_ok=True)
        
        # Default fallback content
        self.default_soul = """# SOUL
- Name: Chintu
- Role: Personal AI Assistant
- Core Principle: Be helpful, harmless, and honest.
- Style: Direct, concise, no fluff.
"""
        self.default_user = """# USER context
- Name: User
"""
        self.default_identity = """# IDENTITY
You are Chintu. Start answers directly. Use Python for tasks.
"""

    def _read_file(self, filename: str, default: str) -> str:
        path = self.brain_dir / filename
        if path.exists():
            try:
                return path.read_text(encoding="utf-8").strip()
            except Exception as e:
                logger.warning(f"Failed to read {filename}: {e}")
        return default

    def build(self) -> str:
        """Construct the optimized system prompt."""
        # 1. Load Essential Context (Strict Loading Rule)
        soul = self._read_file("SOUL.md", self.default_soul)
        user = self._read_file("USER.md", self.default_user)
        identity = self._read_file("IDENTITY.md", self.default_identity)
        
        # 2. Combine
        prompt = f"{soul}\n\n{user}\n\n{identity}\n"
        
        # 3. Add Dynamic Context (Time/Date)
        # (Optional: Add time here if needed, or let the specific tool handle it)
        
        return prompt

_builder: Optional[SystemPromptBuilder] = None

def get_system_prompt() -> str:
    global _builder
    if _builder is None:
        _builder = SystemPromptBuilder()
    return _builder.build()
