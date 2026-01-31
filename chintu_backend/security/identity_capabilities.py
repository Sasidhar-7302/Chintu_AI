"""Identity vault capabilities for secure secret management."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from ..core.capabilities import (
    ActionResult,
    Capability,
    CapabilityRegistry,
    CapabilityType,
    get_registry,
)
from ..core.state import get_state_manager
from .identity_vault import get_identity_vault

logger = logging.getLogger(__name__)


def _extract_kv(text: str, key: str) -> Optional[str]:
    if not text:
        return None
    pattern = rf"{key}\s*[:=]\s*\"([^\"]+)\"|{key}\s*[:=]\s*'([^']+)'|{key}\s*[:=]\s*([^,;]+)"
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    return (match.group(1) or match.group(2) or match.group(3) or "").strip()


def _extract_service(text: str, data: Dict[str, Any]) -> str:
    for key in ("service", "site", "provider", "app"):
        value = data.get(key)
        if value:
            return str(value).strip()
    for prefix in ("for", "service", "site", "provider"):
        match = re.search(rf"{prefix}\s+([A-Za-z0-9._-]+)", text or "", re.IGNORECASE)
        if match:
            return match.group(1)
    return _extract_kv(text, "service") or ""


def _extract_username(text: str, data: Dict[str, Any]) -> str:
    for key in ("username", "user", "email", "login"):
        value = data.get(key)
        if value:
            return str(value).strip()
    # Try explicit key first.
    explicit = _extract_kv(text, "username") or _extract_kv(text, "user") or _extract_kv(text, "email")
    if explicit:
        return explicit
    # Fall back to simple email detection.
    email = re.search(r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})", text or "")
    if email:
        return email.group(1)
    return ""


def _extract_secret(text: str, data: Dict[str, Any]) -> str:
    for key in ("secret", "password", "token", "api_key", "key"):
        value = data.get(key)
        if value:
            return str(value)
    secret = _extract_kv(text, "secret") or _extract_kv(text, "password") or _extract_kv(text, "token")
    return secret or ""


def _extract_note(text: str, data: Dict[str, Any]) -> str:
    note = data.get("note") or _extract_kv(text, "note") or ""
    return str(note).strip()


def _extract_tags(data: Dict[str, Any]) -> List[str]:
    tags = data.get("tags")
    if not tags:
        return []
    if isinstance(tags, (list, tuple, set)):
        return [str(t).strip() for t in tags if str(t).strip()]
    return [str(tags).strip()]


def _vault_ready() -> Tuple[bool, str]:
    vault = get_identity_vault()
    if not vault.available:
        reason = vault.unavailable_reason or "Identity vault is unavailable."
        return False, reason
    return True, ""


def handle_identity_store_secret(text: str, context: Dict[str, Any]) -> ActionResult:
    state = get_state_manager()
    ready, reason = _vault_ready()
    if not ready:
        state.update_feature("identity_vault", status="error", error=reason[:200])
        return ActionResult.fail(reason, "identity_store_secret")

    data = context.get("data") or {}
    service = _extract_service(text, data)
    username = _extract_username(text, data)
    secret = _extract_secret(text, data)
    note = _extract_note(text, data)
    tags = _extract_tags(data)

    if not service or not username or not secret:
        state.update_feature("identity_vault", status="testing", error="missing_fields")
        return ActionResult.fail(
            "To store a secret, provide service, username, and secret. "
            "Example: store secret service: gumroad username: you@example.com secret: \"...\"",
            "identity_store_secret",
        )

    vault = get_identity_vault()
    ok, message = vault.store_secret(service, username, secret, note=note, tags=tags)
    if not ok:
        state.update_feature("identity_vault", status="error", error=message[:200])
        return ActionResult.fail(message, "identity_store_secret")

    state.update_feature("identity_vault", status="active", error=None)
    safe_message = f"Stored a secret for {service}/{username}."
    return ActionResult.ok(
        safe_message,
        data={
            "sensitive": True,
            "safe_message": safe_message,
            "service": service,
            "username": username,
            "stored": True,
        },
        capability="identity_store_secret",
    )


def handle_identity_list_secrets(text: str, context: Dict[str, Any]) -> ActionResult:
    state = get_state_manager()
    ready, reason = _vault_ready()
    if not ready:
        state.update_feature("identity_vault", status="error", error=reason[:200])
        return ActionResult.fail(reason, "identity_list_secrets")

    vault = get_identity_vault()
    items = vault.list_secrets()
    state.update_feature("identity_vault", status="active", error=None)
    if not items:
        return ActionResult.ok(
            "Your identity vault is empty.",
            data={"items": []},
            capability="identity_list_secrets",
        )

    preview = ", ".join(f"{i['service']}/{i['username']}" for i in items[:8])
    message = f"Stored secrets: {preview}."
    if len(items) > 8:
        message += f" (+{len(items) - 8} more)"
    return ActionResult.ok(
        message,
        data={"items": items, "count": len(items)},
        capability="identity_list_secrets",
    )


def handle_identity_delete_secret(text: str, context: Dict[str, Any]) -> ActionResult:
    state = get_state_manager()
    ready, reason = _vault_ready()
    if not ready:
        state.update_feature("identity_vault", status="error", error=reason[:200])
        return ActionResult.fail(reason, "identity_delete_secret")

    data = context.get("data") or {}
    service = _extract_service(text, data)
    username = _extract_username(text, data)
    if not service or not username:
        state.update_feature("identity_vault", status="testing", error="missing_fields")
        return ActionResult.fail(
            "Specify which secret to delete. Example: delete secret service: gumroad username: you@example.com",
            "identity_delete_secret",
        )

    vault = get_identity_vault()
    ok, message = vault.delete_secret(service, username)
    if not ok:
        state.update_feature("identity_vault", status="error", error=message[:200])
        return ActionResult.fail(message, "identity_delete_secret")

    state.update_feature("identity_vault", status="active", error=None)
    safe_message = f"Deleted secret for {service}/{username}."
    return ActionResult.ok(
        safe_message,
        data={
            "sensitive": True,
            "safe_message": safe_message,
            "service": service,
            "username": username,
            "deleted": True,
        },
        capability="identity_delete_secret",
    )


def handle_identity_get_secret(text: str, context: Dict[str, Any]) -> ActionResult:
    state = get_state_manager()
    ready, reason = _vault_ready()
    if not ready:
        state.update_feature("identity_vault", status="error", error=reason[:200])
        return ActionResult.fail(reason, "identity_get_secret")

    data = context.get("data") or {}
    service = _extract_service(text, data)
    username = _extract_username(text, data)
    if not service or not username:
        state.update_feature("identity_vault", status="testing", error="missing_fields")
        return ActionResult.fail(
            "Specify which secret to retrieve. Example: get secret service: gumroad username: you@example.com",
            "identity_get_secret",
        )

    vault = get_identity_vault()
    secret = vault.get_secret(service, username)
    state.update_feature("identity_vault", status="active", error=None)

    if not secret:
        safe_message = f"No secret found for {service}/{username}."
        return ActionResult.fail(safe_message, "identity_get_secret")

    # Only return the raw secret when explicitly requested for internal use.
    include_secret = bool(context.get("_internal_use") or data.get("include_secret"))
    safe_message = f"Retrieved secret for {service}/{username}."
    payload: Dict[str, Any] = {
        "sensitive": True,
        "safe_message": safe_message,
        "service": service,
        "username": username,
        "found": True,
    }
    if include_secret:
        payload["secret"] = secret

    return ActionResult.ok(safe_message, data=payload, capability="identity_get_secret")


def register_identity_capabilities(registry: Optional[CapabilityRegistry] = None) -> None:
    registry = registry or get_registry()

    registry.register(
        Capability(
            name="identity_store_secret",
            triggers=[
                "store secret",
                "save secret",
                "save credential",
                "store credential",
                "remember password for",
                "save token for",
            ],
            handler=handle_identity_store_secret,
            requires_confirmation=False,
            description="store a secret securely in the identity vault",
            capability_type=CapabilityType.AUTOMATION,
            examples=[
                "store secret service: gumroad username: you@example.com secret: \"...\"",
                "save token for github username: you secret: \"ghp_...\"",
            ],
        )
    )

    registry.register(
        Capability(
            name="identity_list_secrets",
            triggers=[
                "list secrets",
                "show secrets",
                "what secrets",
                "list credentials",
                "show credentials",
            ],
            handler=handle_identity_list_secrets,
            requires_confirmation=False,
            description="list stored secrets without revealing them",
            capability_type=CapabilityType.AUTOMATION,
            examples=[
                "list secrets",
                "show my stored credentials",
            ],
        )
    )

    registry.register(
        Capability(
            name="identity_get_secret",
            triggers=[
                "get secret",
                "retrieve secret",
                "fetch secret",
                "get password for",
                "get token for",
            ],
            handler=handle_identity_get_secret,
            requires_confirmation=True,
            description="retrieve a stored secret (confirmation required)",
            capability_type=CapabilityType.AUTOMATION,
            examples=[
                "get secret service: gumroad username: you@example.com",
                "retrieve token for github username: you",
            ],
        )
    )

    registry.register(
        Capability(
            name="identity_delete_secret",
            triggers=[
                "delete secret",
                "remove secret",
                "forget secret",
                "delete credential",
                "remove credential",
            ],
            handler=handle_identity_delete_secret,
            requires_confirmation=True,
            description="delete a stored secret (confirmation required)",
            capability_type=CapabilityType.AUTOMATION,
            examples=[
                "delete secret service: gumroad username: you@example.com",
                "remove credential for github username: you",
            ],
        )
    )

    logger.info("Registered identity vault capabilities")

