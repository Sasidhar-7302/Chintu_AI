"""Process management capabilities for Chintu (safe, confirmation-gated)."""

from __future__ import annotations

import logging
import re
from typing import Dict, Any

import psutil

from chintu_backend.core.capabilities import ActionResult, Capability, CapabilityType, get_registry

logger = logging.getLogger(__name__)


def _extract_process_name(text: str) -> str:
    match = re.search(r"(?:kill|terminate|stop|end)\s+(?:the\s+)?([a-zA-Z0-9_.-]+)", text, re.IGNORECASE)
    if match:
        return match.group(1)
    tokens = [t for t in re.split(r"\s+", text.strip()) if t]
    return tokens[-1] if tokens else ""


def handle_kill_process(text: str, context: Dict[str, Any]) -> ActionResult:
    name = _extract_process_name(text)
    if not name:
        return ActionResult.fail("Which process should I kill?", "kill_process")

    matches = []
    name_lower = name.lower()
    for proc in psutil.process_iter(attrs=["pid", "name"]):
        try:
            if name_lower in (proc.info.get("name") or "").lower():
                matches.append(proc)
        except Exception:
            continue

    if not matches:
        return ActionResult.fail(f"No running process found matching '{name}'.", "kill_process")

    def _do_kill() -> ActionResult:
        killed = 0
        for proc in matches:
            try:
                proc.terminate()
                killed += 1
            except Exception:
                continue
        return ActionResult.ok(f"Terminated {killed} process(es) matching '{name}'.", {"count": killed}, "kill_process")

    if not context.get("_confirmed"):
        return ActionResult.confirm(f"Kill process '{name}'? This will terminate it immediately.", _do_kill, "kill_process")
    return _do_kill()


def register_process_capabilities() -> None:
    registry = get_registry()
    registry.register(Capability(
        name="kill_process",
        triggers=["kill process", "terminate process", "end process", "kill ", "terminate ", "stop process"],
        handler=handle_kill_process,
        requires_confirmation=False,
        description="terminate a running process",
        capability_type=CapabilityType.SYSTEM,
        examples=["Kill the python process", "Terminate chrome"],
    ))

    logger.info("Registered process capabilities")
