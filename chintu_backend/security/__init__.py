"""Security module for Chintu.

Uses lazy exports to avoid import cycles during startup/tests.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any, Dict, Tuple

_EXPORTS: Dict[str, Tuple[str, str]] = {
    "CredentialVault": (".credential_vault", "CredentialVault"),
    "Credential": (".credential_vault", "Credential"),
    "get_credential_vault": (".credential_vault", "get_credential_vault"),
    "AutoLogin": (".auto_login", "AutoLogin"),
    "get_auto_login": (".auto_login", "get_auto_login"),
    "LOGIN_CONFIGS": (".auto_login", "LOGIN_CONFIGS"),
    "IdentityVault": (".identity_vault", "IdentityVault"),
    "get_identity_vault": (".identity_vault", "get_identity_vault"),
    "register_identity_capabilities": (".identity_capabilities", "register_identity_capabilities"),
    "register_login_capabilities": (".login_capabilities", "register_login_capabilities"),
}


def __getattr__(name: str) -> Any:  # pragma: no cover - trivial lazy dispatch
    target = _EXPORTS.get(name)
    if not target:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr = target
    module = import_module(module_name, __name__)
    value = getattr(module, attr)
    globals()[name] = value
    return value


__all__ = list(_EXPORTS.keys())
