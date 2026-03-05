"""
Tool Profiles - Grouped tool packages and context-based loading.

Features:
- Predefined profiles (minimal, coding, full)
- Dynamic profile switching
- Auto-detection based on task context
- Provider-specific tool policies
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List, Set, Callable
from dataclasses import dataclass, field
from enum import Enum

from chintu_backend.core.config import get_config

logger = logging.getLogger(__name__)


class ProfileName(Enum):
    """Standard profile names."""
    MINIMAL = "minimal"
    CONVERSATION = "conversation"
    CODING = "coding"
    RESEARCH = "research"
    AUTOMATION = "automation"
    FULL = "full"
    CUSTOM = "custom"


@dataclass
class ToolProfile:
    """A tool profile configuration."""
    name: str
    description: str
    tools: List[str]  # Tool names included
    excluded_tools: List[str] = field(default_factory=list)
    max_tool_calls: int = 50  # Per turn
    requires_approval: List[str] = field(default_factory=list)  # Tools needing approval
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "tools": self.tools,
            "excluded_tools": self.excluded_tools,
            "max_tool_calls": self.max_tool_calls,
            "requires_approval": self.requires_approval
        }


# Predefined profiles
BUILTIN_PROFILES: Dict[str, ToolProfile] = {
    ProfileName.MINIMAL.value: ToolProfile(
        name="minimal",
        description="Basic conversation with memory only",
        tools=["memory_search", "memory_store", "search_web"],
        requires_approval=[]
    ),
    
    ProfileName.CONVERSATION.value: ToolProfile(
        name="conversation",
        description="General conversation with search and memory",
        tools=[
            "memory_search", "memory_store", "memory_recall",
            "search_web", "read_url",
            "get_time", "get_weather"
        ],
        requires_approval=[]
    ),
    
    ProfileName.CODING.value: ToolProfile(
        name="coding",
        description="Software development tasks",
        tools=[
            "memory_search", "memory_store",
            "search_web", "read_url",
            "file_read", "file_write", "file_list",
            "exec_command", "exec_python",
            "code_search", "code_analyze",
            "git_status", "git_commit", "git_diff"
        ],
        requires_approval=["exec_command", "file_write", "git_commit"],
        max_tool_calls=100
    ),
    
    ProfileName.RESEARCH.value: ToolProfile(
        name="research",
        description="Deep research and analysis",
        tools=[
            "memory_search", "memory_store",
            "search_web", "read_url",
            "browser_open", "browser_screenshot", "browser_read",
            "file_read", "file_write",
            "summarize", "extract_entities"
        ],
        requires_approval=["file_write"]
    ),
    
    ProfileName.AUTOMATION.value: ToolProfile(
        name="automation",
        description="System automation and scripting",
        tools=[
            "memory_search", "memory_store",
            "exec_command", "exec_python",
            "file_read", "file_write", "file_list", "file_delete",
            "browser_open", "browser_click", "browser_type", "browser_screenshot",
            "schedule_task", "send_notification"
        ],
        requires_approval=["exec_command", "file_delete", "file_write"],
        max_tool_calls=200
    ),
    
    ProfileName.FULL.value: ToolProfile(
        name="full",
        description="All tools available",
        tools=["*"],  # All tools
        requires_approval=[
            "exec_command", "exec_python",
            "file_write", "file_delete",
            "git_commit", "git_push",
            "deploy", "send_email"
        ],
        max_tool_calls=200
    ),
}


class ToolProfileManager:
    """
    Manages tool profiles and dynamic loading.
    
    Features:
    - Switch between profiles
    - Auto-detect profile from context
    - Custom profile creation
    - Tool approval requirements
    """
    
    def __init__(self):
        self.config = get_config()
        self.profiles_file = self.config.data_dir / "tool_profiles.json"
        
        # Load builtin and custom profiles
        self._profiles = dict(BUILTIN_PROFILES)
        self._load_custom_profiles()
        
        # Current active profile
        self._active_profile: str = ProfileName.CONVERSATION.value
        
    # --- Profile Management ---
    
    def get_profile(self, name: str) -> Optional[ToolProfile]:
        """Get a profile by name."""
        return self._profiles.get(name)
    
    def set_profile(self, name: str) -> Dict[str, Any]:
        """
        Set the active profile.
        
        Args:
            name: Profile name
            
        Returns:
            Result with active tools
        """
        if name not in self._profiles:
            return {"success": False, "error": f"Profile '{name}' not found"}
        
        self._active_profile = name
        profile = self._profiles[name]
        
        logger.info(f"Switched to profile: {name}")
        
        return {
            "success": True,
            "profile": name,
            "tools": profile.tools,
            "requires_approval": profile.requires_approval
        }
    
    def get_active_profile(self) -> ToolProfile:
        """Get the currently active profile."""
        return self._profiles.get(self._active_profile, BUILTIN_PROFILES["conversation"])
    
    def get_active_tools(self) -> List[str]:
        """Get list of tools available in the active profile."""
        profile = self.get_active_profile()
        
        if "*" in profile.tools:
            # Full profile - return all tools except excluded
            all_tools = self._get_all_tool_names()
            return [t for t in all_tools if t not in profile.excluded_tools]
        
        return [t for t in profile.tools if t not in profile.excluded_tools]
    
    def is_tool_available(self, tool_name: str) -> bool:
        """Check if a tool is available in the active profile."""
        profile = self.get_active_profile()
        
        if "*" in profile.tools:
            return tool_name not in profile.excluded_tools
        
        return tool_name in profile.tools and tool_name not in profile.excluded_tools
    
    def requires_approval(self, tool_name: str) -> bool:
        """Check if a tool requires approval before execution."""
        profile = self.get_active_profile()
        return tool_name in profile.requires_approval
    
    # --- Auto Detection ---
    
    def auto_detect_profile(self, context: str) -> str:
        """
        Auto-detect appropriate profile based on task context.
        
        Args:
            context: Task description or user message
            
        Returns:
            Recommended profile name
        """
        context_lower = context.lower()
        
        # Coding indicators
        coding_keywords = [
            "code", "function", "class", "debug", "implement", "refactor",
            "python", "javascript", "typescript", "api", "database", "git"
        ]
        if any(kw in context_lower for kw in coding_keywords):
            return ProfileName.CODING.value
        
        # Research indicators
        research_keywords = [
            "research", "analyze", "compare", "study", "investigate",
            "find information", "look up", "summarize"
        ]
        if any(kw in context_lower for kw in research_keywords):
            return ProfileName.RESEARCH.value
        
        # Automation indicators
        automation_keywords = [
            "automate", "script", "run command", "execute", "schedule",
            "click", "type", "browser", "scrape"
        ]
        if any(kw in context_lower for kw in automation_keywords):
            return ProfileName.AUTOMATION.value
        
        # Default to conversation
        return ProfileName.CONVERSATION.value
    
    def auto_switch_profile(self, context: str) -> Dict[str, Any]:
        """Auto-detect and switch to appropriate profile."""
        detected = self.auto_detect_profile(context)
        
        if detected != self._active_profile:
            return self.set_profile(detected)
        
        return {
            "success": True,
            "profile": self._active_profile,
            "switched": False
        }
    
    # --- Custom Profiles ---
    
    def create_profile(
        self,
        name: str,
        description: str,
        tools: List[str],
        requires_approval: List[str] = None,
        max_tool_calls: int = 50
    ) -> Dict[str, Any]:
        """Create a custom profile."""
        if name in BUILTIN_PROFILES:
            return {"success": False, "error": "Cannot override builtin profiles"}
        
        profile = ToolProfile(
            name=name,
            description=description,
            tools=tools,
            requires_approval=requires_approval or [],
            max_tool_calls=max_tool_calls
        )
        
        self._profiles[name] = profile
        self._save_custom_profiles()
        
        return {"success": True, "profile": profile.to_dict()}
    
    def delete_profile(self, name: str) -> Dict[str, Any]:
        """Delete a custom profile."""
        if name in BUILTIN_PROFILES:
            return {"success": False, "error": "Cannot delete builtin profiles"}
        
        if name in self._profiles:
            del self._profiles[name]
            self._save_custom_profiles()
            return {"success": True}
        
        return {"success": False, "error": "Profile not found"}
    
    def list_profiles(self) -> List[Dict[str, Any]]:
        """List all available profiles."""
        return [
            {
                "name": p.name,
                "description": p.description,
                "tool_count": len(p.tools) if "*" not in p.tools else "all",
                "builtin": p.name in BUILTIN_PROFILES,
                "active": p.name == self._active_profile
            }
            for p in self._profiles.values()
        ]
    
    # --- Tool Policies ---
    
    def add_tool(self, tool_name: str) -> bool:
        """Add a tool to the active profile."""
        profile = self.get_active_profile()
        
        if tool_name not in profile.tools:
            profile.tools.append(tool_name)
            self._save_custom_profiles()
            return True
        
        return False
    
    def remove_tool(self, tool_name: str) -> bool:
        """Remove a tool from the active profile."""
        profile = self.get_active_profile()
        
        if tool_name in profile.tools:
            profile.tools.remove(tool_name)
            profile.excluded_tools.append(tool_name)
            self._save_custom_profiles()
            return True
        
        return False
    
    def set_requires_approval(self, tool_name: str, requires: bool = True):
        """Set whether a tool requires approval."""
        profile = self.get_active_profile()
        
        if requires and tool_name not in profile.requires_approval:
            profile.requires_approval.append(tool_name)
        elif not requires and tool_name in profile.requires_approval:
            profile.requires_approval.remove(tool_name)
        
        self._save_custom_profiles()
    
    # --- Private Methods ---
    
    def _get_all_tool_names(self) -> List[str]:
        """Get all available tool names."""
        # This would integrate with the actual tool registry
        return [
            "memory_search", "memory_store", "memory_recall",
            "search_web", "read_url",
            "file_read", "file_write", "file_list", "file_delete",
            "exec_command", "exec_python",
            "browser_open", "browser_click", "browser_type", "browser_screenshot", "browser_read",
            "code_search", "code_analyze",
            "git_status", "git_commit", "git_diff", "git_push",
            "get_time", "get_weather",
            "schedule_task", "send_notification",
            "deploy", "send_email"
        ]
    
    def _load_custom_profiles(self):
        """Load custom profiles from disk."""
        if self.profiles_file.exists():
            try:
                data = json.loads(self.profiles_file.read_text())
                for name, profile_data in data.items():
                    if name not in BUILTIN_PROFILES:
                        self._profiles[name] = ToolProfile(
                            name=profile_data["name"],
                            description=profile_data["description"],
                            tools=profile_data["tools"],
                            excluded_tools=profile_data.get("excluded_tools", []),
                            max_tool_calls=profile_data.get("max_tool_calls", 50),
                            requires_approval=profile_data.get("requires_approval", [])
                        )
            except Exception as e:
                logger.warning(f"Could not load custom profiles: {e}")
    
    def _save_custom_profiles(self):
        """Save custom profiles to disk."""
        custom = {
            name: profile.to_dict()
            for name, profile in self._profiles.items()
            if name not in BUILTIN_PROFILES
        }
        
        self.profiles_file.write_text(json.dumps(custom, indent=2))


# Singleton
_profile_manager: Optional[ToolProfileManager] = None


def get_profile_manager() -> ToolProfileManager:
    """Get or create the tool profile manager singleton."""
    global _profile_manager
    if _profile_manager is None:
        _profile_manager = ToolProfileManager()
    return _profile_manager
