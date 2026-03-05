"""Deal watch capabilities: track prices and notify on drops."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from chintu_backend.core.capabilities import ActionResult, Capability, CapabilityType
from chintu_backend.core.events import Event, EventType, get_event_bus

from .deal_finder_capabilities import _extract_query, _default_vendors, run_deal_finder
from .deal_watch_store import DealWatch, get_deal_watch_store

logger = logging.getLogger(__name__)


class DealWatchAddSchema(BaseModel):
    query: str = Field(..., description="Item to track, e.g. '2TB NVMe SSD'.")
    target_price: Optional[float] = Field(None, ge=0, description="Alert when best total reaches this value or lower.")
    interval_minutes: int = Field(180, ge=10, le=1440, description="How often to re-check deals.")
    vendors: List[str] = Field(
        default_factory=lambda: list(_default_vendors()),
        description="Retailers to scan.",
    )
    include_web_search: bool = Field(
        True,
        description="Also scan trusted additional domains discovered via web search.",
    )
    max_results_per_vendor: int = Field(6, ge=1, le=20, description="Listings to parse per vendor.")
    max_web_results: int = Field(8, ge=1, le=25, description="Web results to inspect when include_web_search=true.")


class DealWatchRemoveSchema(BaseModel):
    watch_id: str = Field(..., description="Price watch id to remove.")


class DealWatchRunSchema(BaseModel):
    watch_id: str = Field(..., description="Price watch id to run now.")


class DealWatchListSchema(BaseModel):
    pass


def _extract_watch_id(text: str) -> str:
    raw = str(text or "")
    m = re.search(r"\b([a-f0-9]{6,16})\b", raw, flags=re.IGNORECASE)
    return m.group(1).lower() if m else ""


def _format_watch_line(w: DealWatch) -> str:
    target = f"${w.target_price:,.2f}" if w.target_price is not None else "-"
    last = f"${w.last_best_total:,.2f}" if w.last_best_total is not None else "n/a"
    state = "on" if w.enabled else "off"
    return (
        f"- `{w.id}` [{state}] every {w.interval_minutes}m | target {target} | last {last} | "
        f"{w.query}"
    )


def handle_deal_watch_add(text: str, context: Dict[str, Any]) -> ActionResult:
    validated = context.get("_validated_params")
    if validated and isinstance(validated, DealWatchAddSchema):
        query = str(validated.query or "").strip()
        target_price = validated.target_price
        interval_minutes = int(validated.interval_minutes or 180)
        vendors = [str(v).strip().lower() for v in (validated.vendors or []) if str(v).strip()]
        include_web_search = bool(validated.include_web_search)
        max_results_per_vendor = int(validated.max_results_per_vendor or 6)
        max_web_results = int(validated.max_web_results or 8)
    else:
        query = _extract_query(text)
        target_price = None
        m = re.search(r"(?:below|under|<=?)\s*\$?\s*(\d+(?:\.\d{1,2})?)", text or "", flags=re.IGNORECASE)
        if m:
            try:
                target_price = float(m.group(1))
            except Exception:
                target_price = None
        interval_minutes = 180
        vendors = list(_default_vendors())
        include_web_search = True
        max_results_per_vendor = 6
        max_web_results = 8

    if not query:
        return ActionResult.fail(
            "Tell me what to track. Example: 'Track price for 2TB NVMe SSD under $120'.",
            "deal_watch_add",
        )

    store = get_deal_watch_store()
    watch = store.add_watch(
        query=query,
        vendors=vendors,
        include_web_search=include_web_search,
        max_results_per_vendor=max_results_per_vendor,
        max_web_results=max_web_results,
        interval_minutes=interval_minutes,
        target_price=target_price,
    )

    scheduler_msg = "not scheduled"
    try:
        from chintu_backend.core.scheduler import get_scheduler

        scheduler = get_scheduler()
        command_handler = context.get("command_handler")
        if command_handler and hasattr(command_handler, "handle"):
            scheduler.set_callback(command_handler.handle)
        scheduler.start()
        task = scheduler.schedule(
            name=f"Deal watch: {query[:40]}",
            workflow=f"deal_watch_run {watch.id}",
            schedule_type="interval",
            schedule_time="00:00",
            interval_minutes=interval_minutes,
        )
        store.set_scheduled_task(watch.id, task.id)
        scheduler_msg = f"scheduled task `{task.id}`"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to schedule deal watch %s: %s", watch.id, exc)

    target_line = f"${target_price:,.2f}" if target_price is not None else "no target"
    msg = (
        f"Deal watch created: `{watch.id}`\n"
        f"- Query: {watch.query}\n"
        f"- Target: {target_line}\n"
        f"- Interval: every {interval_minutes} minutes\n"
        f"- Scheduler: {scheduler_msg}"
    )
    return ActionResult.ok(msg, {"watch": watch.to_dict()}, "deal_watch_add")


def handle_deal_watch_list(_text: str, _context: Dict[str, Any]) -> ActionResult:
    store = get_deal_watch_store()
    watches = store.list_watches()
    if not watches:
        return ActionResult.ok(
            "No deal watches yet. Example: track price for 2TB NVMe SSD under $120.",
            {"watches": []},
            "deal_watch_list",
        )
    lines = [f"Deal watches ({len(watches)}):"]
    for watch in watches[:20]:
        lines.append(_format_watch_line(watch))
    return ActionResult.ok("\n".join(lines), {"watches": [w.to_dict() for w in watches]}, "deal_watch_list")


def handle_deal_watch_remove(text: str, context: Dict[str, Any]) -> ActionResult:
    validated = context.get("_validated_params")
    watch_id = ""
    if validated and isinstance(validated, DealWatchRemoveSchema):
        watch_id = str(validated.watch_id or "").strip().lower()
    if not watch_id:
        watch_id = _extract_watch_id(text)
    if not watch_id:
        return ActionResult.fail("Provide the watch id to remove.", "deal_watch_remove")

    store = get_deal_watch_store()
    removed = store.remove_watch(watch_id)
    if not removed:
        return ActionResult.fail(f"Deal watch not found: {watch_id}", "deal_watch_remove")

    if removed.scheduled_task_id:
        try:
            from chintu_backend.core.scheduler import get_scheduler

            get_scheduler().cancel(str(removed.scheduled_task_id))
        except Exception:
            pass

    return ActionResult.ok(
        f"Removed deal watch `{removed.id}` for '{removed.query}'.",
        {"watch": removed.to_dict()},
        "deal_watch_remove",
    )


def _publish_watch_alert(watch: DealWatch, best_total: float, best_vendor: str, best_url: str) -> None:
    target_text = f"${watch.target_price:,.2f}" if watch.target_price is not None else "new low"
    msg = (
        f"{watch.query}: best now ${best_total:,.2f} at {best_vendor} "
        f"(target: {target_text}). {best_url}"
    )
    get_event_bus().publish_sync(
        Event(
            type=EventType.NOTIFICATION,
            source="deal_watch",
            data={
                "category": "deal_watch",
                "severity": "low",
                "title": f"Deal Alert: {watch.query}",
                "message": msg,
                "metadata": {
                    "watch_id": watch.id,
                    "query": watch.query,
                    "best_total": best_total,
                    "best_vendor": best_vendor,
                    "best_url": best_url,
                    "target_price": watch.target_price,
                },
            },
        )
    )


def handle_deal_watch_run(text: str, context: Dict[str, Any]) -> ActionResult:
    validated = context.get("_validated_params")
    watch_id = ""
    if validated and isinstance(validated, DealWatchRunSchema):
        watch_id = str(validated.watch_id or "").strip().lower()
    if not watch_id:
        watch_id = _extract_watch_id(text)
    if not watch_id:
        return ActionResult.fail("Missing watch id for deal watch run.", "deal_watch_run")

    store = get_deal_watch_store()
    watch = store.get_watch(watch_id)
    if not watch:
        return ActionResult.fail(f"Deal watch not found: {watch_id}", "deal_watch_run")
    if not watch.enabled:
        return ActionResult.fail(f"Deal watch {watch.id} is disabled.", "deal_watch_run")

    vendors_final, _per_vendor, errors, combined = run_deal_finder(
        watch.query,
        vendors=watch.vendors,
        max_results_per_vendor=watch.max_results_per_vendor,
        include_web_search=watch.include_web_search,
        max_web_results=watch.max_web_results,
    )
    if not combined:
        store.record_check(
            watch.id,
            best_total=None,
            best_vendor=None,
            best_url=None,
            alerted=False,
        )
        return ActionResult.ok(
            f"Deal watch `{watch.id}` checked but found no priced listings for '{watch.query}'.",
            {"watch_id": watch.id, "errors": errors, "vendors": vendors_final},
            "deal_watch_run",
        )

    best = combined[0]
    best_total = float(best.total or 0.0)
    prev = watch.last_best_total
    target = watch.target_price
    below_target = target is not None and best_total <= target
    new_low = prev is None or best_total < float(prev) - 1e-6

    should_alert = False
    if below_target:
        should_alert = prev is None or float(prev) > float(target) or new_low
    elif target is None and prev is not None and new_low:
        should_alert = True

    store.record_check(
        watch.id,
        best_total=best_total,
        best_vendor=best.vendor,
        best_url=best.url,
        alerted=should_alert,
    )
    if should_alert:
        _publish_watch_alert(watch, best_total=best_total, best_vendor=best.vendor, best_url=best.url)

    alert_line = "Alert sent." if should_alert else "No alert."
    msg = (
        f"Deal watch `{watch.id}` checked.\n"
        f"- Query: {watch.query}\n"
        f"- Best: {best.vendor} ${best_total:,.2f}\n"
        f"- URL: {best.url}\n"
        f"- {alert_line}"
    )
    data = {
        "watch_id": watch.id,
        "query": watch.query,
        "target_price": target,
        "best": best.to_dict(),
        "alerts_sent": bool(should_alert),
        "errors": errors,
        "vendors": vendors_final,
    }
    return ActionResult.ok(msg, data, "deal_watch_run")


def register_deal_watch_capabilities(registry) -> None:
    registry.register(
        Capability(
            name="deal_watch_add",
            triggers=[
                "track price for",
                "watch price for",
                "price alert for",
                "alert me when price drops",
            ],
            handler=handle_deal_watch_add,
            requires_confirmation=False,
            description="create a recurring price watch with optional target alert",
            capability_type=CapabilityType.AI_AGENT,
            examples=["Track price for 2TB NVMe SSD under $120 every 3 hours."],
            schema=DealWatchAddSchema,
        )
    )
    registry.register(
        Capability(
            name="deal_watch_list",
            triggers=["list price watches", "show price watches", "deal watch list"],
            handler=handle_deal_watch_list,
            requires_confirmation=False,
            description="list active deal watches",
            capability_type=CapabilityType.AUTOMATION,
            examples=["List my price watches"],
            schema=DealWatchListSchema,
        )
    )
    registry.register(
        Capability(
            name="deal_watch_remove",
            triggers=["remove price watch", "delete price watch", "stop tracking price"],
            handler=handle_deal_watch_remove,
            requires_confirmation=False,
            description="remove a deal watch",
            capability_type=CapabilityType.AUTOMATION,
            examples=["Remove price watch ab12cd34"],
            schema=DealWatchRemoveSchema,
        )
    )
    registry.register(
        Capability(
            name="deal_watch_run",
            triggers=["deal_watch_run", "run deal watch"],
            handler=handle_deal_watch_run,
            requires_confirmation=False,
            description="run a deal watch check now (used by scheduler)",
            capability_type=CapabilityType.AUTOMATION,
            examples=["deal_watch_run ab12cd34"],
            schema=DealWatchRunSchema,
        )
    )

