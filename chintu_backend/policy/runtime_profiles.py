"""Runtime profile resolution shared by policy and workspace layers."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional


_KNOWN_PROFILES = {"safe_mode", "high_trust", "balanced"}


def normalize_runtime_profile(value: Optional[str], default: str = "balanced") -> str:
    raw = str(value or "").strip().lower()
    if raw in _KNOWN_PROFILES:
        return raw
    fallback = str(default or "balanced").strip().lower()
    return fallback if fallback in _KNOWN_PROFILES else "balanced"


def resolve_runtime_profile(
    context: Optional[Dict[str, Any]],
    *,
    default_profile: str = "balanced",
    safe_mode_channels: Optional[Iterable[str]] = None,
) -> str:
    """Resolve effective runtime profile from context + defaults.

    Precedence:
    1) explicit context override (`_runtime_profile`/`runtime_profile`)
    2) untrusted/remote channel coercion to safe_mode
    3) configured default
    """

    ctx = context if isinstance(context, dict) else {}
    explicit = str(ctx.get("_runtime_profile") or ctx.get("runtime_profile") or "").strip().lower()
    if explicit in _KNOWN_PROFILES:
        return explicit

    channel = str(ctx.get("channel") or "").strip().lower()
    channel_trust = str(ctx.get("channel_trust") or "").strip().lower()
    remote_hint = bool(ctx.get("remote_channel")) or channel_trust in {"untrusted", "remote"}
    if not remote_hint and channel:
        safe_channels = {str(x).strip().lower() for x in (safe_mode_channels or []) if str(x).strip()}
        remote_hint = channel in safe_channels
    if remote_hint:
        return "safe_mode"

    return normalize_runtime_profile(default_profile, default="balanced")
