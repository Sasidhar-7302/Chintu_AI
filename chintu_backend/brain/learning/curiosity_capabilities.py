"""Curiosity engine capabilities (Phase 22)."""

from __future__ import annotations

from typing import Any, Dict

from chintu_backend.core.capabilities import ActionResult, Capability, CapabilityType

from .curiosity_engine import get_curiosity_engine


def handle_curiosity_status(_text: str, _context: Dict[str, Any]) -> ActionResult:
    engine = get_curiosity_engine()
    status = engine.status()
    lines = [
        "Curiosity engine status:",
        f"- Enabled: {bool(status.get('enabled'))}",
        f"- Daily schedule: {bool(status.get('daily_enabled'))} at hour {status.get('daily_hour')}",
        f"- Running: {bool(status.get('running'))}",
        f"- Last run (UTC): {status.get('last_run_utc') or 'never'}",
        f"- Last bi-weekly proposal: {status.get('last_biweekly_proposal_utc') or 'none'}",
    ]
    return ActionResult.ok("\n".join(lines), status, "curiosity_status")


def handle_curiosity_run(text: str, _context: Dict[str, Any]) -> ActionResult:
    engine = get_curiosity_engine()
    result = engine.run_cycle(reason="manual")
    if not bool(result.get("ok")):
        return ActionResult.fail(str(result.get("message") or "Curiosity cycle failed."), "curiosity_run_cycle")

    steps = result.get("steps") if isinstance(result.get("steps"), dict) else {}
    knowledge = steps.get("knowledge_refresh") if isinstance(steps, dict) else {}
    inbox = steps.get("telegram_inbox") if isinstance(steps, dict) else {}
    catalog = steps.get("model_catalog") if isinstance(steps, dict) else {}

    msg = (
        "Curiosity cycle completed.\n"
        f"- Telegram items processed: {int((inbox or {}).get('processed_count') or 0)}\n"
        f"- Knowledge ingested: {int((knowledge or {}).get('ingested_count') or 0)}\n"
        f"- Digest size: {int((knowledge or {}).get('digest_count') or 0)}\n"
        f"- Model catalog updates: {int((catalog or {}).get('release_updates') or 0)}"
    )
    return ActionResult.ok(msg, result, "curiosity_run_cycle")


def handle_curiosity_start(_text: str, _context: Dict[str, Any]) -> ActionResult:
    engine = get_curiosity_engine()
    engine.start()
    status = engine.status()
    return ActionResult.ok("Curiosity scheduler started.", status, "curiosity_start")


def handle_curiosity_stop(_text: str, _context: Dict[str, Any]) -> ActionResult:
    engine = get_curiosity_engine()
    engine.stop()
    status = engine.status()
    return ActionResult.ok("Curiosity scheduler stopped.", status, "curiosity_stop")


def register_curiosity_capabilities(registry) -> None:
    registry.register(
        Capability(
            name="curiosity_status",
            triggers=["curiosity status", "learning scheduler status", "scheduled learning status"],
            handler=handle_curiosity_status,
            requires_confirmation=False,
            description="show curiosity engine and scheduled learning status",
            capability_type=CapabilityType.SYSTEM,
        )
    )

    registry.register(
        Capability(
            name="curiosity_run_cycle",
            triggers=["run curiosity cycle", "run daily learning cycle", "refresh curiosity knowledge"],
            handler=handle_curiosity_run,
            requires_confirmation=False,
            description="run one curiosity ingest + summarize cycle now",
            capability_type=CapabilityType.AUTOMATION,
        )
    )

    registry.register(
        Capability(
            name="curiosity_start",
            triggers=["start curiosity scheduler", "enable curiosity scheduler"],
            handler=handle_curiosity_start,
            requires_confirmation=False,
            description="start background curiosity scheduler",
            capability_type=CapabilityType.SYSTEM,
        )
    )

    registry.register(
        Capability(
            name="curiosity_stop",
            triggers=["stop curiosity scheduler", "disable curiosity scheduler"],
            handler=handle_curiosity_stop,
            requires_confirmation=False,
            description="stop background curiosity scheduler",
            capability_type=CapabilityType.SYSTEM,
        )
    )
