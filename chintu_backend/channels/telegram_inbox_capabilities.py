"""Telegram inbox intake capabilities (Phase 21)."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from chintu_backend.core.capabilities import ActionResult, Capability, CapabilityType

from .telegram_inbox import get_telegram_inbox_manager


def _extract_int(text: str, default: int, *, minimum: int = 1, maximum: int = 100) -> int:
    match = re.search(r"\b(\d{1,3})\b", str(text or ""))
    if not match:
        return default
    try:
        value = int(match.group(1))
    except Exception:
        return default
    return max(minimum, min(maximum, value))


def _extract_category(text: str) -> str:
    low = str(text or "").lower()
    for token in ("tech", "finance", "healthcare", "content", "general"):
        if token in low:
            return token
    return ""


def _extract_intake_id(text: str) -> str:
    match = re.search(r"\b(tgin_[a-z0-9]{6,16})\b", str(text or ""), flags=re.IGNORECASE)
    return str(match.group(1)).lower() if match else ""


def _format_item_line(item: Dict[str, Any], index: int) -> str:
    intake_id = str(item.get("intake_id") or "")
    category = str(item.get("category") or "general")
    summary = str(item.get("summary") or item.get("message_text") or "").strip()
    summary = summary.replace("\n", " ")
    if len(summary) > 180:
        summary = summary[:177] + "..."
    return f"{index:02d}. [{category}] {summary} (id: {intake_id})"


def handle_telegram_inbox_status(_text: str, _context: Dict[str, Any]) -> ActionResult:
    manager = get_telegram_inbox_manager()
    stats = manager.get_stats()
    lines = [
        "Telegram inbox status:",
        f"- Enabled: {bool(stats.get('enabled'))}",
        f"- Total: {int(stats.get('total') or 0)}",
        f"- Pending: {int(stats.get('pending') or 0)}",
        f"- Processed: {int(stats.get('processed') or 0)}",
        f"- Cancelled: {int(stats.get('cancelled') or 0)}",
    ]
    return ActionResult.ok("\n".join(lines), stats, "telegram_inbox_status")


def handle_telegram_inbox_process(text: str, _context: Dict[str, Any]) -> ActionResult:
    manager = get_telegram_inbox_manager()
    limit = _extract_int(text, default=5, minimum=1, maximum=50)
    result = manager.process_pending(max_items=limit)
    if not bool(result.get("ok")):
        return ActionResult.fail(str(result.get("message") or "Could not process telegram inbox."), "telegram_inbox_process")

    items = list(result.get("items") or [])
    if not items:
        return ActionResult.ok("No pending Telegram inbox items.", result, "telegram_inbox_process")

    lines = [f"Processed {len(items)} Telegram inbox item(s):"]
    for idx, item in enumerate(items[:8], start=1):
        lines.append(_format_item_line(item, idx))
    if len(items) > 8:
        lines.append(f"... and {len(items) - 8} more")
    lines.append("You can say: 'show telegram inbox this week' or 'search telegram inbox for <topic>'.")
    return ActionResult.ok("\n".join(lines), result, "telegram_inbox_process")


def handle_telegram_inbox_recent(text: str, _context: Dict[str, Any]) -> ActionResult:
    manager = get_telegram_inbox_manager()
    low = str(text or "").lower()
    category = _extract_category(low)
    limit = _extract_int(low, default=10, minimum=1, maximum=40)

    if "this week" in low or "last week" in low:
        items = manager.recent_items_since(days=7, limit=limit, category=category or None)
    elif "today" in low:
        items = manager.recent_items_since(days=1, limit=limit, category=category or None)
    else:
        items = manager.recent_items(limit=limit, category=category or None)

    if not items:
        return ActionResult.ok("No processed Telegram inbox items found for that filter.", {"items": []}, "telegram_inbox_recent")

    lines = [f"Recent Telegram inbox items ({len(items)}):"]
    for idx, item in enumerate(items, start=1):
        lines.append(_format_item_line(item, idx))
    lines.append("Use id with: 'cancel telegram inbox <id>' or 'resume telegram inbox <id>'.")
    return ActionResult.ok("\n".join(lines), {"items": items}, "telegram_inbox_recent")


def handle_telegram_inbox_search(text: str, _context: Dict[str, Any]) -> ActionResult:
    manager = get_telegram_inbox_manager()
    low = str(text or "")
    query = re.sub(r"(?i)^.*?search telegram inbox(?: for)?", "", low).strip()
    query = query.strip(" :")
    if not query:
        return ActionResult.fail("Tell me what to search in Telegram inbox.", "telegram_inbox_search")
    limit = _extract_int(low, default=10, minimum=1, maximum=40)
    rows = manager.search_items(query, limit=limit)
    if not rows:
        return ActionResult.ok("No Telegram inbox matches for that query.", {"query": query, "items": []}, "telegram_inbox_search")
    lines = [f"Telegram inbox matches for '{query}' ({len(rows)}):"]
    for idx, row in enumerate(rows, start=1):
        lines.append(_format_item_line(row, idx))
    return ActionResult.ok("\n".join(lines), {"query": query, "items": rows}, "telegram_inbox_search")


def handle_telegram_inbox_cancel(text: str, _context: Dict[str, Any]) -> ActionResult:
    intake_id = _extract_intake_id(text)
    if not intake_id:
        return ActionResult.fail("Provide an intake id like tgin_xxxxx to cancel.", "telegram_inbox_cancel")
    manager = get_telegram_inbox_manager()
    ok = manager.cancel_item(intake_id)
    if not ok:
        return ActionResult.fail("I could not cancel that intake id (it may already be processed).", "telegram_inbox_cancel")
    return ActionResult.ok(f"Cancelled Telegram inbox item {intake_id}.", {"intake_id": intake_id}, "telegram_inbox_cancel")


def handle_telegram_inbox_resume(text: str, _context: Dict[str, Any]) -> ActionResult:
    intake_id = _extract_intake_id(text)
    if not intake_id:
        return ActionResult.fail("Provide an intake id like tgin_xxxxx to resume.", "telegram_inbox_resume")
    manager = get_telegram_inbox_manager()
    ok = manager.resume_item(intake_id)
    if not ok:
        return ActionResult.fail("I could not resume that intake id (it may not be cancelled).", "telegram_inbox_resume")
    return ActionResult.ok(f"Resumed Telegram inbox item {intake_id}.", {"intake_id": intake_id}, "telegram_inbox_resume")


def register_telegram_inbox_capabilities(registry) -> None:
    registry.register(
        Capability(
            name="telegram_inbox_status",
            triggers=["telegram inbox status", "telegram intake status", "inbox queue status"],
            handler=handle_telegram_inbox_status,
            requires_confirmation=False,
            description="show Telegram inbox queue and extraction status",
            capability_type=CapabilityType.SYSTEM,
        )
    )

    registry.register(
        Capability(
            name="telegram_inbox_process",
            triggers=["process telegram inbox", "process inbox queue", "run telegram intake"],
            handler=handle_telegram_inbox_process,
            requires_confirmation=False,
            description="process pending Telegram inbox items",
            capability_type=CapabilityType.AUTOMATION,
        )
    )

    registry.register(
        Capability(
            name="telegram_inbox_recent",
            triggers=[
                "show telegram inbox",
                "telegram inbox this week",
                "what i saved from telegram",
                "telegram saved items",
            ],
            handler=handle_telegram_inbox_recent,
            requires_confirmation=False,
            description="list processed Telegram inbox items with summaries",
            capability_type=CapabilityType.SYSTEM,
        )
    )

    registry.register(
        Capability(
            name="telegram_inbox_search",
            triggers=["search telegram inbox", "find in telegram inbox", "telegram inbox search"],
            handler=handle_telegram_inbox_search,
            requires_confirmation=False,
            description="search extracted Telegram inbox knowledge",
            capability_type=CapabilityType.SYSTEM,
        )
    )

    registry.register(
        Capability(
            name="telegram_inbox_cancel",
            triggers=["cancel telegram inbox", "cancel intake"],
            handler=handle_telegram_inbox_cancel,
            requires_confirmation=False,
            description="cancel a pending Telegram inbox item",
            capability_type=CapabilityType.AUTOMATION,
        )
    )

    registry.register(
        Capability(
            name="telegram_inbox_resume",
            triggers=["resume telegram inbox", "resume intake"],
            handler=handle_telegram_inbox_resume,
            requires_confirmation=False,
            description="resume a cancelled Telegram inbox item",
            capability_type=CapabilityType.AUTOMATION,
        )
    )
