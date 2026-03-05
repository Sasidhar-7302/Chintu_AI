"""OAuth onboarding helpers (Phase 20)."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from typing import Any, Dict, List, Optional

from chintu_backend.core.config import get_config
from chintu_backend.integrations.google_calendar import HAS_GOOGLE_API, GoogleCalendar, get_calendar
from chintu_backend.integrations.integration_store import load_integrations, save_integrations
from chintu_backend.integrations.status import get_integrations_snapshot


_GOOGLE_REVOKE_URL = "https://myaccount.google.com/permissions"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _get_identity_vault():
    # Lazy import avoids circular import during startup paths.
    from chintu_backend.security.identity_vault import get_identity_vault

    return get_identity_vault()


def _write_receipt(kind: str, payload: Dict[str, Any]) -> Path:
    cfg = get_config()
    receipts_dir = Path(
        getattr(cfg, "integrations_receipts_dir", None)
        or (Path(cfg.data_dir) / "integrations" / "receipts")
    )
    receipts_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = receipts_dir / f"{kind}_{stamp}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    return path


def _stage_credentials(source: Path, destination: Path) -> Dict[str, Any]:
    src = Path(source).expanduser()
    dst = Path(destination).expanduser()
    if not src.exists():
        return {"ok": False, "error": f"credentials file not found: {src}"}
    try:
        parsed = json.loads(src.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict) or not any(k in parsed for k in ("installed", "web")):
            return {"ok": False, "error": "credentials JSON must contain an 'installed' or 'web' section."}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"invalid credentials JSON: {exc}"}

    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        if src.resolve() == dst.resolve():
            return {"ok": True, "path": str(dst)}
    except Exception:
        pass
    shutil.copy2(src, dst)
    return {"ok": True, "path": str(dst)}


def _set_calendar_scopes(calendar: GoogleCalendar, write_access: bool) -> List[str]:
    scopes = GoogleCalendar.scopes_for(write_access=write_access)
    calendar.set_scopes(scopes)
    return scopes


def get_google_calendar_onboarding_steps(*, write_access: bool = False) -> List[str]:
    mode = "read/write" if write_access else "read-only"
    return [
        "1) In Google Cloud Console, enable Google Calendar API for your project.",
        "2) Create OAuth Client ID (Application type: Desktop app).",
        "3) Download credentials.json to your machine.",
        (
            "4) Run: chintu integrations connect-google-calendar "
            "--credentials <path-to-credentials.json>"
            + (" --write-access" if write_access else "")
        ),
        f"5) Complete browser consent flow; Chintu stores {mode} token with vault backup.",
        f"6) Verify with: chintu integrations health (revoke URL: {_GOOGLE_REVOKE_URL})",
    ]


def connect_google_calendar(
    *,
    credentials_path: Optional[str] = None,
    write_access: Optional[bool] = None,
    force_reauth: bool = False,
) -> Dict[str, Any]:
    """Connect Google Calendar with least-privilege OAuth defaults."""

    cfg = get_config()
    write = bool(cfg.google_calendar_default_write_access if write_access is None else write_access)
    calendar = get_calendar()

    if not HAS_GOOGLE_API:
        return {
            "ok": False,
            "message": "Google Calendar libraries missing. Install: pip install google-auth-oauthlib google-api-python-client",
        }

    if credentials_path:
        stage = _stage_credentials(Path(credentials_path), Path(str(calendar.credentials_path)).expanduser())
        if not stage.get("ok"):
            return {"ok": False, "message": str(stage.get("error") or "failed to stage credentials")}

    if not Path(str(calendar.credentials_path)).expanduser().exists():
        return {
            "ok": False,
            "message": (
                "Calendar credentials.json is missing. Download OAuth desktop credentials from Google Cloud, "
                "then run connect again with --credentials <path>."
            ),
        }

    scopes = _set_calendar_scopes(calendar, write_access=write)
    token_path = Path(str(calendar.token_path)).expanduser()
    if force_reauth and token_path.exists():
        try:
            token_path.unlink()
        except Exception:
            pass

    auth_ok = bool(calendar.authenticate())
    token_json = ""
    if token_path.exists():
        token_json = token_path.read_text(encoding="utf-8")
    elif getattr(calendar, "_creds", None) is not None:
        token_json = str(calendar._creds.to_json())  # type: ignore[attr-defined]

    vault_ok = False
    vault_error = ""
    if token_json:
        try:
            vault = _get_identity_vault()
            if vault.available:
                vault_ok, vault_msg = vault.store_secret(
                    service="google_calendar",
                    username="oauth_token",
                    secret=token_json,
                    note="OAuth token for Google Calendar integration.",
                    tags=["oauth", "google_calendar"],
                )
                if not vault_ok:
                    vault_error = vault_msg
            else:
                vault_error = vault.unavailable_reason
        except Exception as exc:  # noqa: BLE001
            vault_error = str(exc)

    store = load_integrations()
    if not isinstance(store, dict):
        store = {}
    store["google_calendar"] = {
        "connected": bool(auth_ok),
        "connected_at": _utc_now() if auth_ok else str((store.get("google_calendar") or {}).get("connected_at") or ""),
        "credentials_path": str(Path(str(calendar.credentials_path)).expanduser()),
        "token_path": str(token_path),
        "scopes": scopes,
        "write_access": bool(write),
        "token_in_vault": bool(vault_ok),
        "vault_error": str(vault_error or ""),
        "last_setup_at": _utc_now(),
        "revoke_url": _GOOGLE_REVOKE_URL,
    }
    save_ok, save_msg = save_integrations(store)

    receipt_payload = {
        "timestamp_utc": _utc_now(),
        "integration": "google_calendar",
        "result": "connected" if auth_ok else "failed",
        "credentials_path": str(Path(str(calendar.credentials_path)).expanduser()),
        "token_path": str(token_path),
        "scopes": scopes,
        "write_access": bool(write),
        "token_in_vault": bool(vault_ok),
        "vault_error": str(vault_error or ""),
        "store_saved": bool(save_ok),
        "store_message": save_msg,
    }
    receipt_path = _write_receipt("google_calendar_connect", receipt_payload)

    if not auth_ok:
        return {
            "ok": False,
            "message": "Google Calendar authentication failed. Re-run and complete the browser OAuth prompt.",
            "receipt_path": str(receipt_path),
        }

    scope_desc = "read/write" if write else "read-only"
    msg = f"Google Calendar connected ({scope_desc} scope)."
    if not vault_ok:
        msg += " Token stored locally; vault backup unavailable."
    return {
        "ok": True,
        "message": msg,
        "scopes": scopes,
        "write_access": bool(write),
        "receipt_path": str(receipt_path),
    }


def revoke_google_calendar(*, remove_credentials: bool = False) -> Dict[str, Any]:
    """Revoke local Google Calendar integration state (token + optional credentials)."""

    calendar = get_calendar()
    token_path = Path(str(calendar.token_path)).expanduser()
    credentials_path = Path(str(calendar.credentials_path)).expanduser()
    removed_token = False
    removed_credentials = False

    if token_path.exists():
        try:
            token_path.unlink()
            removed_token = True
        except Exception:
            removed_token = False

    try:
        vault = _get_identity_vault()
        if vault.available:
            vault.delete_secret("google_calendar", "oauth_token")
    except Exception:
        pass

    if remove_credentials and credentials_path.exists():
        try:
            credentials_path.unlink()
            removed_credentials = True
        except Exception:
            removed_credentials = False

    store = load_integrations()
    if not isinstance(store, dict):
        store = {}
    calendar_store = store.get("google_calendar")
    if not isinstance(calendar_store, dict):
        calendar_store = {}
    calendar_store.update(
        {
            "connected": False,
            "revoked_at": _utc_now(),
            "token_in_vault": False,
            "revoked": True,
            "revoke_url": _GOOGLE_REVOKE_URL,
        }
    )
    store["google_calendar"] = calendar_store
    save_integrations(store)

    receipt_path = _write_receipt(
        "google_calendar_revoke",
        {
            "timestamp_utc": _utc_now(),
            "removed_token": removed_token,
            "removed_credentials": removed_credentials,
            "credentials_path": str(credentials_path),
            "token_path": str(token_path),
            "remove_credentials_requested": bool(remove_credentials),
            "revoke_url": _GOOGLE_REVOKE_URL,
        },
    )

    return {
        "ok": True,
        "message": (
            "Calendar token removed locally. "
            f"To revoke server-side access, open {_GOOGLE_REVOKE_URL} and remove Chintu's access."
        ),
        "removed_token": removed_token,
        "removed_credentials": removed_credentials,
        "receipt_path": str(receipt_path),
        "revoke_url": _GOOGLE_REVOKE_URL,
    }


def google_calendar_health() -> Dict[str, Any]:
    """Return health + revocation info for the Google Calendar integration."""

    snapshot = get_integrations_snapshot().get("google_calendar", {})
    ok = bool(snapshot.get("available") and snapshot.get("configured") and snapshot.get("token_valid"))
    mode = "read/write" if bool(snapshot.get("write_access")) else "read-only"
    return {
        "ok": ok,
        "mode": mode,
        "snapshot": snapshot,
        "revoke_url": _GOOGLE_REVOKE_URL,
    }
