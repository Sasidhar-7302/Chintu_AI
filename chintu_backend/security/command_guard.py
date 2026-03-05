"""Command Guard: Security layer for shell executions."""

import re
import logging
from typing import Set, Tuple

logger = logging.getLogger(__name__)

class CommandGuard:
    """
    Validates and sanitizes shell commands to prevent system damage.
    Enforces Human-in-the-loop (HITL) for risky operations.
    """
    
    # Commands that are strictly forbidden
    BLACKLIST: Set[str] = {
        "rm -rf", "format", "mkfs", "dd if=",
        "del /s /q C:\\", "rd /s /q C:\\", "> /dev/", "chmod -R 777"
    }
    
    # Patterns that indicate risky system modification
    RISKY_PATTERNS = [
        (r"rm\s+-[rf]{1,2}\s+/", "Recursive root deletion"),
        (r"reg\s+delete", "Registry manipulation"),
        (r"net\s+user", "User account modification"),
        (r"taskkill\s+/f", "Forced process termination"),
        (r"\bshutdown(\.exe)?\b", "System shutdown"),
        (r"\breboot\b", "System reboot"),
        (r"powershell\s+-enc", "Encoded PowerShell execution"),
        (r"wget|curl.*\|\s*sh", "Direct pipe to shell")
    ]

    def is_safe(self, command: str) -> Tuple[bool, str]:
        """Checks if a command is strictly forbidden."""
        cmd_lower = command.lower().strip()
        
        # Check blacklist
        for blocked in self.BLACKLIST:
            if blocked.lower() in cmd_lower:
                return False, f"Forbidden command detected: {blocked}"
        
        # Check risky patterns
        for pattern, reason in self.RISKY_PATTERNS:
            if re.search(pattern, cmd_lower):
                return False, f"Risk detected ({reason})"
                
        return True, "Safe"

    def needs_confirmation(self, command: str) -> bool:
        """Decides if a command requires HITL confirmation."""
        # By default, any shell command in the assistant should be confirmed 
        # unless it's a known read-only command (like 'dir' or 'echo')
        safe_read_commands = {"dir", "ls", "echo", "pwd", "whoami", "type", "where", "rg"}
        
        tokens = command.strip().split() if command and command.strip() else []
        first_word = tokens[0].lower() if tokens else ""
        if first_word in safe_read_commands:
            return False

        # Permit common read-only developer commands without nagging approvals.
        # We keep this narrow by checking subcommands/flags.
        if first_word == "git" and len(tokens) >= 2:
            sub = tokens[1].lower()
            if sub in {"status", "diff", "log", "show", "rev-parse", "ls-files", "branch"}:
                return False

        if first_word == "python":
            lowered = command.lower()
            if re.search(r"\b(-v|--version)\b", lowered):
                return False
            if re.search(r"\b-m\s+pytest\b", lowered):
                return False

        if first_word in {"pytest"}:
            return False

        return True

_instance = None

def get_command_guard() -> CommandGuard:
    global _instance
    if _instance is None:
        _instance = CommandGuard()
    return _instance
