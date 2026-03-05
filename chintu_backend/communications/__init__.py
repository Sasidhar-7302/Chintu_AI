"""Communications package (Phase 24)."""

from .manager import CommunicationsManager, get_communications_manager
from .capabilities import register_communications_capabilities

__all__ = [
    "CommunicationsManager",
    "get_communications_manager",
    "register_communications_capabilities",
]
