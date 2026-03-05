"""Integration onboarding capabilities (Phase 20)."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from chintu_backend.core.capabilities import ActionResult, Capability, CapabilityType
from chintu_backend.integrations.oauth_onboarding import (
    connect_google_calendar,
    get_google_calendar_onboarding_steps,
    google_calendar_health,
    revoke_google_calendar,
)
from chintu_backend.integrations.status import get_integrations_snapshot


class ConnectGoogleCalendarSchema(BaseModel):
    credentials_path: Optional[str] = Field(None, description="Path to OAuth desktop credentials.json")
    write_access: bool = Field(False, description="Request calendar write scope in addition to readonly")
    force_reauth: bool = Field(False, description="Delete existing token and force browser re-auth")


class RevokeGoogleCalendarSchema(BaseModel):
    remove_credentials: bool = Field(False, description="Also remove local credentials.json file")


def _extract_credentials_path(text: str) -> Optional[str]:
    raw = str(text or "").strip()
    if not raw:
        return None
    patterns = [
        r"([A-Za-z]:\\[^\n\r\t\"']*credentials\.json)",
        r"((?:\.{0,2}[\\/])?[^\n\r\t\"']*credentials\.json)",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def handle_connect_google_calendar(text: str, context: Dict[str, Any]) -> ActionResult:
    params = context.get("_validated_params")
    credentials_path: Optional[str] = None
    write_access = False
    force_reauth = False
    if isinstance(params, ConnectGoogleCalendarSchema):
        credentials_path = params.credentials_path
        write_access = bool(params.write_access)
        force_reauth = bool(params.force_reauth)
    if not credentials_path:
        credentials_path = _extract_credentials_path(text)

    result = connect_google_calendar(
        credentials_path=credentials_path,
        write_access=write_access,
        force_reauth=force_reauth,
    )
    if bool(result.get("ok")):
        return ActionResult.ok(
            str(result.get("message") or "Google Calendar connected."),
            {
                "receipt_path": result.get("receipt_path"),
                "scopes": result.get("scopes"),
                "write_access": result.get("write_access"),
            },
            capability="integration_connect_google_calendar",
        )
    return ActionResult.fail(
        str(result.get("message") or "Failed to connect Google Calendar."),
        capability="integration_connect_google_calendar",
    )


def handle_integration_status(_: str, __: Dict[str, Any]) -> ActionResult:
    snapshot = get_integrations_snapshot()
    health = google_calendar_health()
    cal = snapshot.get("google_calendar", {}) if isinstance(snapshot, dict) else {}
    email = snapshot.get("email_imap", {}) if isinstance(snapshot, dict) else {}
    jira = snapshot.get("jira", {}) if isinstance(snapshot, dict) else {}
    mode = "read/write" if bool(cal.get("write_access")) else "read-only"
    msg = (
        "Integrations status:\n"
        f"- Google Calendar: {'connected' if health.get('ok') else 'not fully connected'} ({mode})\n"
        f"- Token valid: {bool(cal.get('token_valid'))}\n"
        f"- Credentials present: {bool(cal.get('configured'))}\n"
        f"- Email IMAP: {'configured' if bool(email.get('configured')) else 'not configured'}\n"
        f"- Jira: {'configured' if bool(jira.get('configured')) else 'not configured'}"
    )
    return ActionResult.ok(msg, {"snapshot": snapshot, "google_calendar_health": health}, capability="integration_status")


def handle_integration_setup_wizard(_: str, context: Dict[str, Any]) -> ActionResult:
    write_access = bool(context.get("write_access") or context.get("calendar_write_access"))
    steps = get_google_calendar_onboarding_steps(write_access=write_access)
    extra = [
        "Email IMAP (read-only): set CHINTU_EMAIL_IMAP_HOST/USER, then store password in Identity Vault as service=email username=imap_password.",
        "Jira: set CHINTU_JIRA_BASE_URL/EMAIL/PROJECT_KEY and store token in Identity Vault as service=jira username=api_token.",
        "Run 'integration status' after setup to verify Calendar, Email, and Jira readiness.",
    ]
    message = (
        "Integration setup wizard:\n"
        "Google Calendar OAuth:\n"
        + "\n".join(f"- {row}" for row in steps)
        + "\n\nOther integrations:\n"
        + "\n".join(f"- {row}" for row in extra)
    )
    return ActionResult.ok(
        message,
        {
            "integration": "google_calendar",
            "steps": steps,
            "write_access": write_access,
            "extra_integrations": extra,
        },
        capability="integration_setup_wizard",
    )


def handle_revoke_google_calendar(_: str, context: Dict[str, Any]) -> ActionResult:
    params = context.get("_validated_params")
    remove_credentials = False
    if isinstance(params, RevokeGoogleCalendarSchema):
        remove_credentials = bool(params.remove_credentials)
    result = revoke_google_calendar(remove_credentials=remove_credentials)
    return ActionResult.ok(
        str(result.get("message") or "Google Calendar revoked."),
        result,
        capability="integration_revoke_google_calendar",
    )


def register_integration_capabilities(registry) -> None:
    registry.register(
        Capability(
            name="integration_connect_google_calendar",
            triggers=[
                "connect google calendar oauth",
                "setup google calendar oauth",
                "calendar oauth connect",
                "integration connect calendar",
            ],
            handler=handle_connect_google_calendar,
            description="Connect Google Calendar through OAuth onboarding",
            capability_type=CapabilityType.AUTOMATION,
            schema=ConnectGoogleCalendarSchema,
            examples=[
                "Connect Google Calendar OAuth with credentials at C:\\Users\\me\\Downloads\\credentials.json",
                "Setup Google Calendar OAuth read only",
            ],
        )
    )
    registry.register(
        Capability(
            name="integration_setup_wizard",
            triggers=[
                "integration setup wizard",
                "oauth setup wizard",
                "calendar oauth setup steps",
            ],
            handler=handle_integration_setup_wizard,
            description="Show guided OAuth onboarding steps for integrations",
            capability_type=CapabilityType.SYSTEM,
        )
    )
    registry.register(
        Capability(
            name="integration_status",
            triggers=[
                "integration status",
                "show integrations status",
                "oauth status",
            ],
            handler=handle_integration_status,
            description="Show integration and OAuth health status",
            capability_type=CapabilityType.SYSTEM,
        )
    )
    registry.register(
        Capability(
            name="integration_revoke_google_calendar",
            triggers=[
                "revoke google calendar integration",
                "disconnect google calendar",
                "remove calendar oauth",
            ],
            handler=handle_revoke_google_calendar,
            description="Revoke local Google Calendar OAuth connection",
            capability_type=CapabilityType.SYSTEM,
            requires_confirmation=True,
            schema=RevokeGoogleCalendarSchema,
        )
    )
