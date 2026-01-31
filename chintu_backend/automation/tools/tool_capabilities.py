"""Capabilities that expose code-first utility tools to the assistant."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from chintu_backend.core.capabilities import (
    ActionResult,
    Capability,
    CapabilityRegistry,
    CapabilityType,
    get_registry,
)
from chintu_backend.core.config import get_config
from chintu_backend.core.state import get_state_manager
from chintu_backend.automation.tools.email_reader import get_email_reader
from chintu_backend.automation.tools.thumbnail import get_thumbnail_generator

logger = logging.getLogger(__name__)


def _extract_path_candidate(text: str) -> Optional[str]:
    if not text:
        return None

    quoted = re.search(r"\"([^\"]+)\"|'([^']+)'", text)
    if quoted:
        return quoted.group(1) or quoted.group(2)

    drive = re.search(r"([A-Za-z]:[\\/][^\\s]+)", text)
    if drive:
        return drive.group(1)

    file_like = re.search(
        r"([\\w./\\\\-]+\\.(?:png|jpg|jpeg|webp|pdf))",
        text,
        flags=re.IGNORECASE,
    )
    if file_like:
        return file_like.group(1)

    return None


def _resolve_path(candidate: str) -> Path:
    path = Path(candidate).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    return path


def _extract_kv(text: str, key: str) -> Optional[str]:
    if not text:
        return None
    pattern = rf"{key}\\s*[:=]\\s*\"([^\"]+)\"|{key}\\s*[:=]\\s*'([^']+)'|{key}\\s*[:=]\\s*([^,;]+)"
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    return (match.group(1) or match.group(2) or match.group(3) or "").strip()


def _pick_source_path(text: str, context: Dict[str, Any]) -> Tuple[Optional[Path], str]:
    data = context.get("data") or {}
    for key in ("source", "source_path", "path", "file"):
        if data.get(key):
            try:
                return _resolve_path(str(data[key])), ""
            except Exception as exc:  # pragma: no cover - defensive.
                return None, f"Invalid {key}: {exc}"

    candidate = _extract_path_candidate(text)
    if not candidate:
        return None, ""
    try:
        return _resolve_path(candidate), ""
    except Exception as exc:  # pragma: no cover - defensive.
        return None, f"Invalid path: {exc}"


def handle_generate_thumbnail(text: str, context: Dict[str, Any]) -> ActionResult:
    state = get_state_manager()
    generator = get_thumbnail_generator()

    if not generator.enabled:
        state.update_feature("thumbnail", status="error", error="disabled")
        return ActionResult.fail(
            "Thumbnail generation is disabled. Set `thumbnail_enabled=true`.",
            "generate_thumbnail",
        )
    if not generator.available:
        state.update_feature("thumbnail", status="error", error="pillow_missing")
        return ActionResult.fail(
            "Pillow is not installed. Add `pillow` to requirements and reinstall.",
            "generate_thumbnail",
        )

    source_path, err = _pick_source_path(text, context)
    if err:
        state.update_feature("thumbnail", status="error", error=err)
        return ActionResult.fail(err, "generate_thumbnail")
    if not source_path:
        return ActionResult.fail(
            "Usage: generate thumbnail \"path/to/preview.pdf\" title: \"ATS Resume\"",
            "generate_thumbnail",
        )

    data = context.get("data") or {}
    title = data.get("title") or _extract_kv(text, "title")
    subtitle = data.get("subtitle") or _extract_kv(text, "subtitle")
    output_name = data.get("output_name") or _extract_kv(text, "output")

    result = generator.generate(
        source_path,
        title=str(title) if title else None,
        subtitle=str(subtitle) if subtitle else None,
        output_name=str(output_name) if output_name else None,
    )
    if not result.success:
        state.update_feature("thumbnail", status="error", error=result.message)
        return ActionResult.fail(result.message, "generate_thumbnail")

    state.update_feature("thumbnail", status="active", error=None)
    return ActionResult.ok(
        result.message,
        data={
            "output_path": str(result.output_path) if result.output_path else None,
            "source_path": str(source_path),
        },
        capability="generate_thumbnail",
    )


def _extract_site_hint(text: str, context: Dict[str, Any]) -> str:
    data = context.get("data") or {}
    for key in ("site_hint", "site", "service", "sender"):
        value = data.get(key)
        if value:
            return str(value).strip()

    match = re.search(r"(?:from|for|site)\\s+([A-Za-z0-9._-]+)", text or "", re.IGNORECASE)
    if match:
        return match.group(1)
    return ""


def handle_email_read_codes(text: str, context: Dict[str, Any]) -> ActionResult:
    state = get_state_manager()
    config = get_config()
    reader = get_email_reader()

    configured = reader.configured
    if isinstance(configured, tuple):
        is_configured, reason = configured
    else:  # pragma: no cover - defensive for future refactors.
        is_configured, reason = bool(configured), ""

    if not is_configured:
        state.update_feature("email_reader", status="error", error="not_configured")
        return ActionResult.fail(
            reason
            or (
                "Email reader is not configured. Set email_reader_enabled=true and "
                "provide email_imap_host, email_imap_user, and email_imap_password."
            ),
            "email_read_codes",
        )

    site_hint = _extract_site_hint(text, context)
    data = context.get("data") or {}
    lookback = data.get("lookback_minutes") or getattr(config, "email_reader_lookback_minutes", 30)
    max_messages = data.get("max_messages") or getattr(config, "email_reader_max_messages", 10)

    matches, error = reader.fetch_recent_codes(
        site_hint=site_hint,
        lookback_minutes=int(lookback),
        max_messages=int(max_messages),
    )
    if error:
        state.update_feature("email_reader", status="error", error=error)
        return ActionResult.fail(error, "email_read_codes")
    if not matches:
        state.update_feature("email_reader", status="active", error=None)
        hint_msg = f" for {site_hint}" if site_hint else ""
        return ActionResult.fail(
            f"No recent verification codes found{hint_msg} in the last {lookback} minutes.",
            "email_read_codes",
        )

    codes = []
    senders: List[str] = []
    for match in matches[:3]:
        codes.extend(match.codes)
        if match.sender:
            senders.append(match.sender)

    state.update_feature("email_reader", status="active", error=None)
    unique_senders = sorted({s for s in senders if s})
    sender_preview = ", ".join(unique_senders[:3])
    if len(unique_senders) > 3:
        sender_preview += f" (+{len(unique_senders) - 3} more)"
    hint_msg = f" for {site_hint}" if site_hint else ""
    safe_message = f"Found {len(codes)} recent verification code(s){hint_msg}."
    if sender_preview:
        safe_message += f" Likely senders: {sender_preview}."
    return ActionResult.ok(
        safe_message,
        data={
            "sensitive": True,
            "safe_message": safe_message,
            "codes": codes[:10],
            "site_hint": site_hint,
            "senders": unique_senders[:10],
        },
        capability="email_read_codes",
    )


def register_tool_capabilities(registry: Optional[CapabilityRegistry] = None) -> None:
    registry = registry or get_registry()

    registry.register(
        Capability(
            name="generate_thumbnail",
            triggers=[
                "generate thumbnail",
                "create thumbnail",
                "make thumbnail",
                "thumbnail for",
            ],
            handler=handle_generate_thumbnail,
            description="Generate a clean thumbnail image from a PDF or image preview.",
            capability_type=CapabilityType.AUTOMATION,
            examples=[
                "generate thumbnail \"resume_preview.pdf\" title: \"ATS Resume\"",
                "create thumbnail for ./output/preview.png",
            ],
        )
    )

    registry.register(
        Capability(
            name="email_read_codes",
            triggers=[
                "read verification code",
                "get verification code",
                "check email code",
                "email verification code",
            ],
            handler=handle_email_read_codes,
            requires_confirmation=True,
            description="Read recent verification codes from configured email via IMAP.",
            capability_type=CapabilityType.AUTOMATION,
            examples=[
                "get verification code for gumroad",
                "check email code for pinterest",
            ],
        )
    )

    logger.info("Registered tool capabilities (thumbnail, email codes)")
