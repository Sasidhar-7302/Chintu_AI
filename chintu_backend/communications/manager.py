"""Communications manager: owner-first call + reservation workflows (Phase 24)."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from chintu_backend.core.config import get_config
from chintu_backend.security.identity_vault import get_identity_vault

logger = logging.getLogger(__name__)


_OWNER_SERVICE = "communications_owner"
_OWNER_USERNAME = "primary_phone"
_PAYMENT_BLOCK_WORDS = (
    "payment",
    "deposit",
    "card",
    "checkout",
    "pay",
    "upi",
    "wire",
    "transfer",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_phone(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    plus = raw.startswith("+")
    digits = re.sub(r"\D+", "", raw)
    if not digits:
        return ""
    return f"+{digits}" if plus else digits


def _mask_phone(value: str) -> str:
    phone = _normalize_phone(value)
    if not phone:
        return ""
    digits = re.sub(r"\D+", "", phone)
    if len(digits) <= 4:
        return "*" * len(digits)
    return f"{digits[:2]}{'*' * max(2, len(digits) - 4)}{digits[-2:]}"


def _extract_phone(text: str) -> str:
    match = re.search(r"(\+?[0-9][0-9\s\-()]{7,}[0-9])", str(text or ""))
    return _normalize_phone(match.group(1)) if match else ""


@dataclass
class CallPlan:
    ok: bool
    reason: str
    target_name: str
    target_phone: str
    is_owner: bool
    requires_confirmation: bool
    script_preview: str
    blocked: bool = False


class CommunicationsManager:
    def __init__(self, *, config=None) -> None:
        self.config = config or get_config()
        self.enabled = bool(getattr(self.config, "communications_enabled", True))
        self.owner_profile_path = Path(getattr(self.config, "communications_owner_profile_path"))
        self.receipts_dir = Path(getattr(self.config, "communications_receipts_dir"))
        self.owner_profile_path.parent.mkdir(parents=True, exist_ok=True)
        self.receipts_dir.mkdir(parents=True, exist_ok=True)

    def set_owner_profile(self, *, owner_name: str, owner_phone: str) -> Dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "message": "communications_disabled"}
        name = str(owner_name or "").strip()
        phone = _normalize_phone(owner_phone)
        if not name or not phone:
            return {"ok": False, "message": "Owner name and phone are required."}

        vault = get_identity_vault()
        if not vault.available:
            return {
                "ok": False,
                "message": "Identity vault is unavailable. Configure keyring/cryptography before storing owner contact.",
            }

        ok, message = vault.store_secret(
            _OWNER_SERVICE,
            _OWNER_USERNAME,
            phone,
            note="Owner/master contact for communications",
            tags=["communications", "owner"],
        )
        if not ok:
            return {"ok": False, "message": message}

        payload = {
            "owner_name": name,
            "owner_phone_masked": _mask_phone(phone),
            "owner_contact_ref": {
                "service": _OWNER_SERVICE,
                "username": _OWNER_USERNAME,
            },
            "updated_at_utc": _utc_now_iso(),
        }
        self.owner_profile_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
        return {"ok": True, "profile": payload, "owner_profile_path": str(self.owner_profile_path)}

    def owner_profile(self) -> Dict[str, Any]:
        if not self.owner_profile_path.exists():
            return {}
        try:
            data = json.loads(self.owner_profile_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            return {}
        return {}

    def owner_phone(self) -> str:
        vault = get_identity_vault()
        if not vault.available:
            return ""
        phone = vault.get_secret(_OWNER_SERVICE, _OWNER_USERNAME)
        return _normalize_phone(phone or "")

    def plan_call(self, *, text: str) -> CallPlan:
        if not self.enabled:
            return CallPlan(False, "communications disabled", "", "", False, False, "", blocked=True)

        profile = self.owner_profile()
        owner_name = str(profile.get("owner_name") or "").strip().lower()
        owner_phone = self.owner_phone()

        low = str(text or "").lower()
        phone = _extract_phone(text)
        target_name = ""
        name_match = re.search(r"\bcall\s+([a-zA-Z][a-zA-Z0-9\s._-]{1,60})", str(text or ""), flags=re.IGNORECASE)
        if name_match:
            target_name = str(name_match.group(1) or "").strip()

        is_owner = False
        if "owner" in low or "call me" in low or "call master" in low:
            is_owner = True
        if owner_name and owner_name in low:
            is_owner = True
        if phone and owner_phone and _normalize_phone(phone) == _normalize_phone(owner_phone):
            is_owner = True

        if is_owner:
            target_name = target_name or profile.get("owner_name") or "Owner"
            phone = phone or owner_phone

        if not target_name and not phone:
            return CallPlan(False, "Please specify who to call (name or phone number).", "", "", False, False, "", blocked=True)

        allow_owner_no_confirm = bool(getattr(self.config, "communications_allow_owner_call_without_confirmation", True))
        requires_confirmation = not (is_owner and allow_owner_no_confirm)

        script = (
            f"Hello, this is Chintu assistant calling on behalf of the user. "
            f"Purpose: {str(text or '').strip()[:220]}."
        )
        return CallPlan(
            ok=True,
            reason="ready",
            target_name=target_name or ("Owner" if is_owner else "Contact"),
            target_phone=phone,
            is_owner=is_owner,
            requires_confirmation=requires_confirmation,
            script_preview=script,
            blocked=False,
        )

    def plan_reservation(self, *, text: str) -> CallPlan:
        low = str(text or "").lower()
        if any(tok in low for tok in _PAYMENT_BLOCK_WORDS):
            return CallPlan(
                ok=False,
                reason="Blocked by policy: payment/deposit actions are not allowed.",
                target_name="",
                target_phone="",
                is_owner=False,
                requires_confirmation=False,
                script_preview="",
                blocked=True,
            )

        place_match = re.search(r"\bat\s+([a-zA-Z0-9\s&'._-]{2,80})", str(text or ""), flags=re.IGNORECASE)
        place = str(place_match.group(1) or "restaurant") if place_match else "restaurant"
        script = (
            f"Hello, I am calling to make a reservation at {place}. "
            f"Request details: {str(text or '').strip()[:260]}. "
            "Please confirm availability and policies."
        )
        return CallPlan(
            ok=True,
            reason="ready",
            target_name=place,
            target_phone="",
            is_owner=False,
            requires_confirmation=True,
            script_preview=script,
            blocked=False,
        )

    def execute_call(self, *, plan: CallPlan, mode: str) -> Dict[str, Any]:
        if not plan.ok or plan.blocked:
            return {"ok": False, "message": plan.reason}

        staged_browser = False
        adapter = str(getattr(self.config, "communications_default_adapter", "google_voice_browser") or "google_voice_browser")
        if adapter == "google_voice_browser":
            try:
                from chintu_backend.automation.browser.browser_controller import get_browser_controller

                controller = get_browser_controller(
                    headless=False,
                    profile_name=str(getattr(self.config, "research_browser_loggedin_profile", "assistant_accounts") or "assistant_accounts"),
                )
                controller.open_url("https://voice.google.com", wait_for="domcontentloaded")
                staged_browser = True
            except Exception as exc:
                logger.debug("Communications browser staging failed: %s", exc)

        receipt = {
            "ok": True,
            "mode": mode,
            "adapter": adapter,
            "owner_call": bool(plan.is_owner),
            "target_name": plan.target_name,
            "target_phone_masked": _mask_phone(plan.target_phone),
            "script_preview": plan.script_preview,
            "staged_in_browser": staged_browser,
            "executed_at_utc": _utc_now_iso(),
            "status": "staged",
        }
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = self.receipts_dir / f"call_receipt_{mode}_{stamp}.json"
        out.write_text(json.dumps(receipt, indent=2, ensure_ascii=True), encoding="utf-8")
        receipt["receipt_path"] = str(out)
        return receipt


_manager: Optional[CommunicationsManager] = None


def get_communications_manager() -> CommunicationsManager:
    global _manager
    if _manager is None:
        _manager = CommunicationsManager()
    return _manager
