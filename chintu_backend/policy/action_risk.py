"""Risk signals for sensitive actions (payments, publish submits, destructive ops)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence


_PAYMENT_PATTERNS: Sequence[re.Pattern[str]] = (
    re.compile(r"\bcheckout\b", re.IGNORECASE),
    re.compile(r"\bpay(?:ment)?\b", re.IGNORECASE),
    re.compile(r"\bbuy\s+now\b", re.IGNORECASE),
    re.compile(r"\bplace\s+order\b", re.IGNORECASE),
    re.compile(r"\bconfirm\s+purchase\b", re.IGNORECASE),
    re.compile(r"\bconfirm\s+order\b", re.IGNORECASE),
    re.compile(r"\bsubscribe\b", re.IGNORECASE),
    re.compile(r"\bpurchase\b", re.IGNORECASE),
)

_PUBLISH_PATTERNS: Sequence[re.Pattern[str]] = (
    re.compile(r"\bpublish\b", re.IGNORECASE),
    re.compile(r"\bpost\b", re.IGNORECASE),
    re.compile(r"\bupload\b", re.IGNORECASE),
    re.compile(r"\bsend\b", re.IGNORECASE),
)

_AUTH_PATTERNS: Sequence[re.Pattern[str]] = (
    re.compile(r"\blog(?:\s|-)?in\b", re.IGNORECASE),
    re.compile(r"\bsign(?:\s|-)?in\b", re.IGNORECASE),
    re.compile(r"\bauth(?:entication)?\b", re.IGNORECASE),
    re.compile(r"\boauth\b", re.IGNORECASE),
    re.compile(r"\b2fa\b", re.IGNORECASE),
    re.compile(r"\botp\b", re.IGNORECASE),
    re.compile(r"\bpassword\b", re.IGNORECASE),
    re.compile(r"\baccount\b", re.IGNORECASE),
    re.compile(r"\bprofile\b", re.IGNORECASE),
    re.compile(r"\bsettings\b", re.IGNORECASE),
)

_DESTRUCTIVE_PATTERNS: Sequence[re.Pattern[str]] = (
    re.compile(r"\bdelete\b", re.IGNORECASE),
    re.compile(r"\bremove\b", re.IGNORECASE),
    re.compile(r"\berase\b", re.IGNORECASE),
    re.compile(r"\bformat\b", re.IGNORECASE),
    re.compile(r"\buninstall\b", re.IGNORECASE),
    re.compile(r"\breset\b", re.IGNORECASE),
    re.compile(r"\bkill\b", re.IGNORECASE),
    re.compile(r"\bterminate\b", re.IGNORECASE),
)

_BROWSER_FAMILY = {
    "click_link",
    "browser_act_ref",
    "browser_pilot",
    "open_browser",
    "browser_search",
    "screen_click",
    "screen_control",
    "job_apply",
    "social_stage_upload",
    "social_publish_post",
}


@dataclass(frozen=True)
class ActionScope:
    """Deterministic, privacy-safe action scope used by approval ledgers."""

    scope_hash: str
    categories: List[str]
    capability_name: str
    target: str
    request_text: str


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _extract_params(context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(context, dict):
        return {}
    params = context.get("_validated_params") or context.get("_extracted_params") or {}
    if isinstance(params, dict):
        return params
    out: Dict[str, Any] = {}
    for key in ("command", "cwd", "target", "ref", "action", "value", "url", "path", "file_path"):
        try:
            val = getattr(params, key, None)
        except Exception:
            val = None
        if val is not None:
            out[key] = val
    return out


def _extract_target(capability_name: str, request_text: str, context: Optional[Dict[str, Any]]) -> str:
    params = _extract_params(context)
    for key in ("target", "ref", "url", "path", "file_path", "command"):
        value = params.get(key)
        if value:
            return str(value).strip()[:240]
    if params.get("action") and params.get("value"):
        return f"{params.get('action')}::{params.get('value')}"[:240]
    if request_text:
        return request_text.strip()[:240]
    return str(capability_name or "").strip()[:240]


def _contains_any(text: str, patterns: Sequence[re.Pattern[str]]) -> bool:
    raw = text or ""
    for pattern in patterns:
        if pattern.search(raw):
            return True
    return False


def detect_action_categories(
    capability_name: str,
    request_text: str,
    context: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Return normalized sensitive categories for the action."""

    cap = _norm(capability_name)
    text = _norm(request_text)
    target = _norm(_extract_target(cap, request_text, context))
    combined = " ".join(part for part in (text, target, cap) if part).strip()

    categories: List[str] = []
    if _contains_any(combined, _PAYMENT_PATTERNS):
        categories.append("payment")

    browser_family = cap in _BROWSER_FAMILY or "browser" in cap or "screen" in cap
    if _contains_any(combined, _PUBLISH_PATTERNS):
        if browser_family:
            categories.append("browser_submit")

    # "submit" is intentionally narrower to avoid blocking harmless local button clicks.
    if browser_family and "submit" in combined:
        submit_context_markers = (
            "post",
            "application",
            "form",
            "publish",
            "upload",
            "reel",
            "short",
            "order",
            "checkout",
        )
        if any(marker in combined for marker in submit_context_markers):
            categories.append("browser_submit")

    if browser_family and _contains_any(combined, _AUTH_PATTERNS):
        categories.append("browser_auth")

    if _contains_any(combined, _DESTRUCTIVE_PATTERNS):
        categories.append("destructive")

    dedup: List[str] = []
    for item in categories:
        if item not in dedup:
            dedup.append(item)
    return dedup


def build_action_scope(
    capability_name: str,
    request_text: str,
    context: Optional[Dict[str, Any]] = None,
) -> ActionScope:
    """Build a deterministic approval scope hash from risk-significant fields only."""

    cap = str(capability_name or "").strip()
    req = str(request_text or "").strip()
    target = _extract_target(cap, req, context)
    categories = detect_action_categories(cap, req, context)
    payload = f"{cap.lower()}|{target.lower()}|{','.join(categories)}"
    digest = hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()
    return ActionScope(
        scope_hash=digest,
        categories=categories,
        capability_name=cap,
        target=target,
        request_text=req,
    )
