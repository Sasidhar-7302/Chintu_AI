"""Keyring-backed identity vault with local encryption.

This vault is designed for automation-friendly secrets storage:
- Secrets are encrypted locally with a Fernet key.
- The encrypted secrets are stored in the OS keyring.
- Metadata is stored separately without secrets.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..core.config import get_config

logger = logging.getLogger(__name__)


try:  # pragma: no cover - dependency availability is environment-specific.
    import keyring

    KEYRING_AVAILABLE = True
    KEYRING_IMPORT_ERROR = ""
except Exception as exc:  # noqa: BLE001 - robust import guard.
    keyring = None  # type: ignore[assignment]
    KEYRING_AVAILABLE = False
    KEYRING_IMPORT_ERROR = str(exc)

try:  # pragma: no cover - dependency availability is environment-specific.
    from cryptography.fernet import Fernet, InvalidToken

    CRYPTO_AVAILABLE = True
    CRYPTO_IMPORT_ERROR = ""
except Exception as exc:  # noqa: BLE001 - robust import guard.
    Fernet = None  # type: ignore[assignment]
    InvalidToken = Exception  # type: ignore[assignment]
    CRYPTO_AVAILABLE = False
    CRYPTO_IMPORT_ERROR = str(exc)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SecretRef:
    """A non-sensitive reference to a stored secret."""

    service: str
    username: str


class IdentityVault:
    """Secure secret storage for automation tasks."""

    def __init__(self) -> None:
        self.config = get_config()
        self.enabled = bool(getattr(self.config, "identity_vault_enabled", True))
        # Fallback for data_dir if not present in config
        data_dir = getattr(self.config, "data_dir", None)
        if not data_dir:
            data_dir = Path.home() / ".chintu"
        else:
            data_dir = Path(data_dir)

        self.key_path: Path = Path(
            getattr(self.config, "identity_vault_key_path", data_dir / "identity.key")
        )
        self.meta_path: Path = Path(
            getattr(self.config, "identity_vault_meta_path", data_dir / "identity_meta.json")
        )
        self.keyring_service_name: str = str(
            getattr(self.config, "identity_vault_keyring_service_name", "chintu_ai_identity")
        )

        self.available, self.unavailable_reason = self._check_availability()
        self._cipher: Optional[Fernet] = None
        self._meta: Dict[str, Dict[str, Any]] = {}

        if not self.available:
            logger.warning("IdentityVault unavailable: %s", self.unavailable_reason)
            return

        try:
            self.key_path.parent.mkdir(parents=True, exist_ok=True)
            self.meta_path.parent.mkdir(parents=True, exist_ok=True)
            self._cipher = self._load_or_create_key()
            self._meta = self._load_meta()
        except Exception as exc:  # noqa: BLE001
            self.available = False
            self.unavailable_reason = f"Initialization error: {exc}"
            logger.warning("IdentityVault initialization failed: %s", exc)

    def _check_availability(self) -> Tuple[bool, str]:
        if not self.enabled:
            return False, "disabled by config"
        if not KEYRING_AVAILABLE:
            return False, f"keyring missing: {KEYRING_IMPORT_ERROR}"
        if not CRYPTO_AVAILABLE:
            return False, f"cryptography missing: {CRYPTO_IMPORT_ERROR}"
        return True, ""

    # ------------------------------------------------------------------
    # Key + metadata management
    # ------------------------------------------------------------------
    def _load_or_create_key(self) -> Fernet:
        assert Fernet is not None  # guarded by availability check.
        if self.key_path.exists():
            key_bytes = self.key_path.read_bytes()
            return Fernet(key_bytes)

        key_bytes = Fernet.generate_key()
        self.key_path.write_bytes(key_bytes)
        return Fernet(key_bytes)

    def _load_meta(self) -> Dict[str, Dict[str, Any]]:
        if not self.meta_path.exists():
            return {}
        try:
            data = json.loads(self.meta_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load identity meta store: %s", exc)
        return {}

    def _save_meta(self) -> None:
        tmp_path = self.meta_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(self._meta, indent=2, sort_keys=True), encoding="utf-8")
        tmp_path.replace(self.meta_path)

    # ------------------------------------------------------------------
    # Secret operations
    # ------------------------------------------------------------------
    def _entry_key(self, ref: SecretRef) -> str:
        return f"{ref.service}:{ref.username}"

    def _encrypt(self, secret: str) -> str:
        if not self._cipher:
            raise RuntimeError("IdentityVault cipher not initialized")
        token = self._cipher.encrypt(secret.encode("utf-8"))
        return token.decode("utf-8")

    def _decrypt(self, token: str) -> Optional[str]:
        if not self._cipher:
            return None
        try:
            raw = self._cipher.decrypt(token.encode("utf-8"))
            return raw.decode("utf-8")
        except InvalidToken:
            logger.warning("IdentityVault failed to decrypt token (invalid key or data)")
            return None

    def store_secret(
        self,
        service: str,
        username: str,
        secret: str,
        *,
        note: str = "",
        tags: Optional[List[str]] = None,
    ) -> Tuple[bool, str]:
        """Store a secret securely."""
        if not self.available:
            return False, f"Identity vault unavailable: {self.unavailable_reason}"
        if not service or not username:
            return False, "Service and username are required."
        if not secret:
            return False, "Secret is empty."

        ref = SecretRef(service=service.strip(), username=username.strip())
        encrypted = self._encrypt(secret)

        assert keyring is not None  # guarded by availability check.
        keyring.set_password(self.keyring_service_name, self._entry_key(ref), encrypted)

        key = self._entry_key(ref)
        now = _utc_now_iso()
        prev = self._meta.get(key) or {}
        self._meta[key] = {
            "service": ref.service,
            "username": ref.username,
            "note": note.strip(),
            "tags": list(tags or prev.get("tags") or []),
            "created_at": prev.get("created_at") or now,
            "updated_at": now,
        }
        self._save_meta()
        return True, f"Stored secret for {ref.service}/{ref.username}."

    def get_secret(self, service: str, username: str) -> Optional[str]:
        """Retrieve a secret. Use with care."""
        if not self.available:
            return None
        ref = SecretRef(service=service.strip(), username=username.strip())
        assert keyring is not None  # guarded by availability check.
        encrypted = keyring.get_password(self.keyring_service_name, self._entry_key(ref))
        if not encrypted:
            return None
        return self._decrypt(encrypted)

    def delete_secret(self, service: str, username: str) -> Tuple[bool, str]:
        """Delete a stored secret."""
        if not self.available:
            return False, f"Identity vault unavailable: {self.unavailable_reason}"
        ref = SecretRef(service=service.strip(), username=username.strip())
        key = self._entry_key(ref)

        assert keyring is not None  # guarded by availability check.
        try:
            keyring.delete_password(self.keyring_service_name, key)
        except Exception:  # noqa: BLE001 - delete should be best-effort.
            pass

        if key in self._meta:
            del self._meta[key]
            self._save_meta()
        return True, f"Deleted secret for {ref.service}/{ref.username}."

    def list_secrets(self) -> List[Dict[str, Any]]:
        """List non-sensitive metadata about stored secrets."""
        if not self.available:
            return []
        items = list(self._meta.values())
        items.sort(key=lambda x: (x.get("service", ""), x.get("username", "")))
        # Explicitly exclude any secret material.
        return [
            {
                "service": item.get("service", ""),
                "username": item.get("username", ""),
                "note": item.get("note", ""),
                "tags": item.get("tags", []),
                "created_at": item.get("created_at", ""),
                "updated_at": item.get("updated_at", ""),
            }
            for item in items
        ]

    def has_secret(self, service: str, username: str) -> bool:
        if not self.available:
            return False
        ref = SecretRef(service=service.strip(), username=username.strip())
        assert keyring is not None  # guarded by availability check.
        return keyring.get_password(self.keyring_service_name, self._entry_key(ref)) is not None


_identity_vault: Optional[IdentityVault] = None


def get_identity_vault() -> IdentityVault:
    global _identity_vault
    if _identity_vault is None:
        _identity_vault = IdentityVault()
    return _identity_vault

