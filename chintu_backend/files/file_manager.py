"""File management utilities for coding workflows."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class FileManager:
    """Simple file manager for reading and writing source files."""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = Path(base_dir or Path.cwd()).resolve()

    def read_file(self, path: str) -> str:
        file_path = self._resolve_path(path)
        if not file_path.exists():
            return ""
        try:
            return file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return file_path.read_text(encoding="utf-8", errors="replace")

    def write_file(self, path: str, content: str) -> bool:
        file_path = self._resolve_path(path)
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            return True
        except Exception as exc:
            logger.error("Failed to write file %s: %s", file_path, exc)
            return False

    def _resolve_path(self, path: str) -> Path:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self.base_dir / candidate
        resolved = candidate.resolve()
        if not str(resolved).startswith(str(self.base_dir)):
            raise ValueError(f"Path outside base dir: {resolved}")
        return resolved
