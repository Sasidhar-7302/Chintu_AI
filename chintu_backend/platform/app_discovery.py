"""Compatibility proxy for Windows app discovery (tests expect this path)."""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Optional

from chintu_backend.automation.platform.app_discovery import (
    AppDiscovery as _AppDiscovery,
    DiscoveredApp,
)

logger = logging.getLogger(__name__)


class AppDiscovery:
    """Proxy wrapper that exposes a stable patch surface for tests."""

    def __init__(self) -> None:
        self._inner = _AppDiscovery()

    def initialize(self) -> None:
        self._inner.initialize()

    def find_app(self, query: str) -> Optional[DiscoveredApp]:
        return self._inner.find_app(query)

    def open_app(self, app: DiscoveredApp) -> bool:
        """Open an application using this module's subprocess/os for patchability."""
        try:
            path = app.path
            if path.startswith("ms-") or path.endswith(".lnk"):
                os.startfile(path)
            else:
                if os.name == "nt" and not os.path.isabs(path) and "/" not in path and "\\" not in path:
                    subprocess.Popen(
                        ["cmd", "/c", "start", "", path],
                        shell=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                else:
                    subprocess.Popen(
                        [path],
                        shell=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
            logger.info("Opened app: %s (%s)", app.name, app.path)
            return True
        except Exception as exc:
            logger.warning("Failed to open app via proxy: %s", exc)
            return False


_app_discovery: Optional[AppDiscovery] = None


def get_app_discovery() -> AppDiscovery:
    """Get singleton AppDiscovery proxy."""
    global _app_discovery
    if _app_discovery is None:
        _app_discovery = AppDiscovery()
    return _app_discovery


__all__ = ["AppDiscovery", "DiscoveredApp", "get_app_discovery"]
