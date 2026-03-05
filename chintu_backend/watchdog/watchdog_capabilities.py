"""Capabilities for managing project watchdogs."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional, Tuple

from chintu_backend.core.capabilities import (
    ActionResult,
    Capability,
    CapabilityRegistry,
    CapabilityType,
    get_registry,
)
from chintu_backend.watchdog.manager import get_watchdog_manager

logger = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
HOST_PORT_RE = re.compile(r"([a-zA-Z0-9_.-]+:\d{2,5})")
PORT_ONLY_RE = re.compile(r"\bport\s+(\d{2,5})\b", re.IGNORECASE)
PROCESS_RE = re.compile(r"\bprocess\s+([a-zA-Z0-9_.-]+)\b", re.IGNORECASE)
EVAL_RE = re.compile(r"\b(eval|evaluation)\b", re.IGNORECASE)
METRICS_RE = re.compile(r"\bmetrics?\b", re.IGNORECASE)
RELIABILITY_RE = re.compile(r"\b(reliability|gate)\b", re.IGNORECASE)


def _parse_watchdog_target(text: str) -> Tuple[str, str]:
    text = text or ""
    if RELIABILITY_RE.search(text):
        return "reliability", "default"
    if METRICS_RE.search(text):
        return "metrics", "default"
    if EVAL_RE.search(text):
        # Optional: allow an explicit cases file path
        tokens = [t.strip() for t in re.split(r"\s+", text) if t.strip()]
        for tok in tokens:
            if tok.lower().endswith(".jsonl"):
                return "eval", tok
        return "eval", "default"

    url_match = URL_RE.search(text)
    if url_match:
        return "http", url_match.group(0)

    host_port = HOST_PORT_RE.search(text)
    if host_port:
        return "port", host_port.group(1)

    port_only = PORT_ONLY_RE.search(text)
    if port_only:
        return "port", port_only.group(1)

    proc_match = PROCESS_RE.search(text)
    if proc_match:
        return "process", proc_match.group(1)

    # Fallback: treat last token as a process name.
    tokens = [t for t in re.split(r"\s+", text.strip()) if t]
    if tokens:
        return "process", tokens[-1]
    return "", ""


def handle_watchdog_add(text: str, _context: Dict[str, Any]) -> ActionResult:
    manager = get_watchdog_manager()
    manager.start()

    kind, target = _parse_watchdog_target(text)
    if not kind or not target:
        return ActionResult.fail(
            "Tell me what to monitor, e.g. 'monitor http://localhost:3000', "
            "'monitor port 5173', or 'monitor eval gate'.",
            "watchdog_add",
        )

    try:
        entry = manager.add_watchdog(kind=kind, target=target)
    except Exception as exc:  # noqa: BLE001
        return ActionResult.fail(f"Failed to add watchdog: {exc}", "watchdog_add")

    return ActionResult.ok(
        f"Watching {entry.kind} target '{entry.target}' every {entry.interval_seconds:.0f}s (id={entry.id}).",
        data={"id": entry.id, "kind": entry.kind, "target": entry.target},
        capability="watchdog_add",
    )


def handle_watchdog_list(_text: str, _context: Dict[str, Any]) -> ActionResult:
    manager = get_watchdog_manager()
    entries = manager.list_watchdogs()
    if not entries:
        return ActionResult.ok("No watchdogs configured yet.", capability="watchdog_list")

    lines = []
    for entry in entries[:25]:
        lines.append(
            f"- {entry.id}: {entry.name} [{entry.kind}] {entry.target} -> {entry.last_status}"
        )
    if len(entries) > 25:
        lines.append(f"...and {len(entries) - 25} more")

    return ActionResult.ok(
        "Configured watchdogs:\n" + "\n".join(lines),
        data={"count": len(entries)},
        capability="watchdog_list",
    )


def handle_watchdog_remove(text: str, _context: Dict[str, Any]) -> ActionResult:
    manager = get_watchdog_manager()
    identifier = _extract_identifier(text)
    if not identifier:
        return ActionResult.fail(
            "Specify the watchdog id or name to remove, e.g. 'remove watchdog 2'.",
            "watchdog_remove",
        )

    removed = manager.remove_watchdog(identifier)
    if not removed:
        return ActionResult.fail(f"No watchdog found for '{identifier}'.", "watchdog_remove")
    return ActionResult.ok(f"Removed watchdog '{identifier}'.", capability="watchdog_remove")


def handle_watchdog_check(_text: str, _context: Dict[str, Any]) -> ActionResult:
    manager = get_watchdog_manager()
    manager.start()
    summary = manager.run_checks(force=True)
    return ActionResult.ok(
        "Watchdog check complete: "
        f"{summary['healthy']} healthy, {summary['failing']} failing, {summary['skipped']} skipped.",
        data=summary,
        capability="watchdog_check",
    )


def _extract_identifier(text: str) -> str:
    tokens = [t for t in re.split(r"\s+", (text or "").strip()) if t]
    if not tokens:
        return ""
    # Prefer a numeric id if present.
    for tok in tokens:
        if tok.isdigit():
            return tok
    return tokens[-1]


def register_watchdog_capabilities(registry: Optional[CapabilityRegistry] = None) -> None:
    registry = registry or get_registry()

    registry.register(
        Capability(
            name="watchdog_add",
            triggers=[
                "watchdog add",
                "monitor project",
                "monitor this",
                "watch this",
                "start monitoring",
            ],
            handler=handle_watchdog_add,
            description="Create a watchdog to monitor a URL, port, or process",
            capability_type=CapabilityType.AUTOMATION,
            examples=[
                "monitor http://localhost:3000",
                "watch port 5173",
                "watch process node",
                "monitor eval gate",
            ],
        )
    )

    registry.register(
        Capability(
            name="watchdog_list",
            triggers=[
                "list watchdogs",
                "show watchdogs",
                "list monitors",
                "watchdogs",
            ],
            handler=handle_watchdog_list,
            description="List configured project watchdogs",
            capability_type=CapabilityType.AUTOMATION,
        )
    )

    registry.register(
        Capability(
            name="watchdog_remove",
            triggers=[
                "remove watchdog",
                "delete watchdog",
                "stop monitoring",
                "disable watchdog",
            ],
            handler=handle_watchdog_remove,
            description="Remove a configured watchdog by id or name",
            capability_type=CapabilityType.AUTOMATION,
        )
    )

    registry.register(
        Capability(
            name="watchdog_check",
            triggers=[
                "check watchdogs",
                "run watchdogs",
                "watchdog check",
                "monitor check",
            ],
            handler=handle_watchdog_check,
            description="Run watchdog checks immediately",
            capability_type=CapabilityType.AUTOMATION,
        )
    )

    logger.info("Registered watchdog capabilities")

