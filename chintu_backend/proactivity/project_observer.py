"""Observer for Project workspace changes."""

import os
import time
import logging
import asyncio
from typing import Dict, Set
from pathlib import Path

from .base_observer import BaseObserver, SignalType

logger = logging.getLogger(__name__)

class ProjectObserver(BaseObserver):
    """
    Monitors the project workspace for file changes.
    Emits a PROJECT signal when code is modified.
    """
    def __init__(self, workspace_path: str, interval: int = 10):
        super().__init__("project_sensor", interval)
        self.workspace = Path(workspace_path)
        self._last_snapshot: Dict[str, float] = {}
        self._extensions = {'.py', '.md', '.txt', '.json'}
        self._ignore_dirs = {'.git', '__pycache__', '.pytest_cache', 'node_modules', '.venv', 'venv'}

    async def poll(self):
        """Poll the workspace for changes."""
        changes = self._get_file_changes()
        
        if changes:
            logger.info(f"Project changes detected: {len(changes)} files.")
            await self.emit_signal(
                SignalType.PROJECT,
                {
                    "event": "files_modified",
                    "file_count": len(changes),
                    "files": list(changes)[:5] # Send top 5 for context
                },
                priority=1
            )

    def _get_file_changes(self) -> Set[str]:
        """Scans the directory and returns set of modified file paths."""
        current_snapshot: Dict[str, float] = {}
        changed_files: Set[str] = set()

        try:
            for root, dirs, files in os.walk(self.workspace):
                # Prune ignored directories
                dirs[:] = [d for d in dirs if d not in self._ignore_dirs]
                
                for file in files:
                    if any(file.endswith(ext) for ext in self._extensions):
                        file_path = os.path.join(root, file)
                        try:
                            mtime = os.path.getmtime(file_path)
                            current_snapshot[file_path] = mtime
                            
                            # Check against last snapshot
                            if file_path in self._last_snapshot:
                                if mtime > self._last_snapshot[file_path]:
                                    changed_files.add(file_path)
                            else:
                                # New file detected
                                if self._last_snapshot: # Don't trigger on first scan
                                    changed_files.add(file_path)
                        except (OSError, FileNotFoundError):
                            continue
        except Exception as e:
            logger.error(f"Error scanning workspace: {e}")

        self._last_snapshot = current_snapshot
        return changed_files
