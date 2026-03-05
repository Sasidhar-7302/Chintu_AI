"""Workspace abstraction layer for safer autonomy and execution placement."""

from .manager import (
    WorkspaceExecutionResult,
    WorkspaceManager,
    WorkspacePlacement,
    get_workspace_manager,
)

__all__ = [
    "WorkspaceExecutionResult",
    "WorkspaceManager",
    "WorkspacePlacement",
    "get_workspace_manager",
]

