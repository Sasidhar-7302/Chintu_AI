"""Security module for Chintu.

Provides secure credential storage, auto-login, and authentication.
"""

from .credential_vault import CredentialVault, Credential, get_credential_vault
from .auto_login import AutoLogin, get_auto_login, LOGIN_CONFIGS
from .identity_vault import IdentityVault, get_identity_vault
from .identity_capabilities import register_identity_capabilities
from .login_capabilities import register_login_capabilities

__all__ = [
    "CredentialVault",
    "Credential", 
    "get_credential_vault",
    "AutoLogin",
    "get_auto_login",
    "LOGIN_CONFIGS",
    "IdentityVault",
    "get_identity_vault",
    "register_identity_capabilities",
    "register_login_capabilities",
]
