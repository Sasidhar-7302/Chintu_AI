"""Communications capabilities (Phase 24)."""

from __future__ import annotations

import re
from typing import Any, Dict

from chintu_backend.core.capabilities import ActionResult, Capability, CapabilityType

from .manager import get_communications_manager


def _parse_owner_fields(text: str) -> tuple[str, str]:
    raw = str(text or "")
    phone_match = re.search(r"(\+?[0-9][0-9\s\-()]{7,}[0-9])", raw)
    phone = str(phone_match.group(1) or "").strip() if phone_match else ""

    name = ""
    name_match = re.search(r"name\s*(?:is|:)?\s*([A-Za-z][A-Za-z0-9\s._-]{1,60})", raw, flags=re.IGNORECASE)
    if name_match:
        name = str(name_match.group(1) or "").strip()
    else:
        prefix_match = re.search(r"owner(?: contact)?\s*(?:is|:)?\s*([A-Za-z][A-Za-z0-9\s._-]{1,60})", raw, flags=re.IGNORECASE)
        if prefix_match:
            name = str(prefix_match.group(1) or "").strip()

    return name, phone


def handle_set_owner_profile(text: str, _context: Dict[str, Any]) -> ActionResult:
    manager = get_communications_manager()
    name, phone = _parse_owner_fields(text)
    if not name or not phone:
        return ActionResult.fail(
            "Provide owner details like: set owner contact name: John phone: +1 555 010 2222",
            "communications_set_owner",
        )
    result = manager.set_owner_profile(owner_name=name, owner_phone=phone)
    if not bool(result.get("ok")):
        return ActionResult.fail(str(result.get("message") or "Could not set owner profile."), "communications_set_owner")
    masked = str((result.get("profile") or {}).get("owner_phone_masked") or "")
    return ActionResult.ok(
        f"Owner profile saved for {name} ({masked}).",
        result,
        "communications_set_owner",
    )


def handle_owner_status(_text: str, _context: Dict[str, Any]) -> ActionResult:
    manager = get_communications_manager()
    profile = manager.owner_profile()
    if not profile:
        return ActionResult.ok("Owner profile is not configured yet.", {"configured": False}, "communications_owner_status")
    msg = (
        "Owner profile is configured.\n"
        f"- Name: {profile.get('owner_name') or 'n/a'}\n"
        f"- Phone: {profile.get('owner_phone_masked') or 'n/a'}"
    )
    return ActionResult.ok(msg, {"configured": True, "profile": profile}, "communications_owner_status")


def handle_call(text: str, context: Dict[str, Any]) -> ActionResult:
    manager = get_communications_manager()
    plan = manager.plan_call(text=text)
    if not plan.ok or plan.blocked:
        return ActionResult.fail(plan.reason, "communications_call")

    if plan.requires_confirmation and not bool(context.get("_communications_call_confirmed", False)):

        def _approve() -> ActionResult:
            next_ctx = dict(context or {})
            next_ctx["_communications_call_confirmed"] = True
            return handle_call(text, next_ctx)

        target = plan.target_name or "contact"
        return ActionResult.confirm(
            (
                f"Call confirmation required for {target}.\n"
                f"Script preview: {plan.script_preview}\n\n"
                "Confirm to stage this call."
            ),
            _approve,
            "communications_call",
        )

    receipt = manager.execute_call(plan=plan, mode="call")
    if not bool(receipt.get("ok")):
        return ActionResult.fail(str(receipt.get("message") or "Call staging failed."), "communications_call")

    return ActionResult.ok(
        (
            f"Call staged for {plan.target_name}. "
            f"Receipt: {receipt.get('receipt_path')}"
        ),
        receipt,
        "communications_call",
    )


def handle_reservation(text: str, context: Dict[str, Any]) -> ActionResult:
    manager = get_communications_manager()
    plan = manager.plan_reservation(text=text)
    if not plan.ok or plan.blocked:
        return ActionResult.fail(plan.reason, "communications_reservation")

    if not bool(context.get("_communications_reservation_confirmed", False)):

        def _approve() -> ActionResult:
            next_ctx = dict(context or {})
            next_ctx["_communications_reservation_confirmed"] = True
            return handle_reservation(text, next_ctx)

        return ActionResult.confirm(
            (
                f"Reservation confirmation required for {plan.target_name}.\n"
                f"Script preview: {plan.script_preview}\n\n"
                "Confirm to stage this reservation call."
            ),
            _approve,
            "communications_reservation",
        )

    receipt = manager.execute_call(plan=plan, mode="reservation")
    if not bool(receipt.get("ok")):
        return ActionResult.fail(str(receipt.get("message") or "Reservation staging failed."), "communications_reservation")

    return ActionResult.ok(
        f"Reservation call staged for {plan.target_name}. Receipt: {receipt.get('receipt_path')}",
        receipt,
        "communications_reservation",
    )


def register_communications_capabilities(registry) -> None:
    registry.register(
        Capability(
            name="communications_set_owner",
            triggers=["set owner contact", "set master contact", "configure owner phone"],
            handler=handle_set_owner_profile,
            requires_confirmation=False,
            description="configure owner/master contact for owner-first call policy",
            capability_type=CapabilityType.SYSTEM,
        )
    )

    registry.register(
        Capability(
            name="communications_owner_status",
            triggers=["owner contact status", "owner profile status", "communications owner status"],
            handler=handle_owner_status,
            requires_confirmation=False,
            description="show owner contact setup status",
            capability_type=CapabilityType.SYSTEM,
        )
    )

    registry.register(
        Capability(
            name="communications_call",
            triggers=["call owner", "call ", "place a call", "dial"],
            handler=handle_call,
            requires_confirmation=False,
            description="stage calls with owner-first no-confirm rules and confirmation for others",
            capability_type=CapabilityType.AUTOMATION,
        )
    )

    registry.register(
        Capability(
            name="communications_reservation",
            triggers=["make reservation", "book reservation", "reservation call"],
            handler=handle_reservation,
            requires_confirmation=False,
            description="stage reservation calls with payment/deposit hard-stop",
            capability_type=CapabilityType.AUTOMATION,
        )
    )
