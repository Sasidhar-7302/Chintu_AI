"""Login and credential management capabilities.

Provides voice commands for:
- Saving login credentials
- Auto-login to websites
- Managing stored credentials
"""

import logging
from typing import Dict, Any, Optional

from ..core.capabilities import (
    ActionResult,
    Capability,
    CapabilityRegistry,
    CapabilityType,
    get_registry,
)

logger = logging.getLogger(__name__)


def handle_save_login(text: str, context: Dict[str, Any]) -> ActionResult:
    """Save login credentials for a website.
    
    Examples:
    - "Save my Gmail login"
    - "Remember my LinkedIn password"
    """
    from .credential_vault import get_credential_vault
    
    vault = get_credential_vault()
    
    # Check if vault is set up
    if not vault.is_setup:
        return ActionResult.ok(
            "I need to set up your secure vault first. Please say 'Set up my password vault' to create a master password.",
            {"needs_setup": True},
            "save_login"
        )
    
    # Check if vault is unlocked
    if not vault.is_unlocked:
        return ActionResult.ok(
            "Your vault is locked. Please say 'Unlock my vault' first.",
            {"needs_unlock": True},
            "save_login"
        )
    
    # This would typically be a multi-turn conversation
    # For now, return instructions
    return ActionResult.ok(
        "To save a login, I need the website name, your username, and password. "
        "For security, please type these in the UI rather than speaking them aloud.",
        {"action": "prompt_credentials"},
        "save_login"
    )


def handle_login_to(text: str, context: Dict[str, Any]) -> ActionResult:
    """Log in to a website using stored credentials.
    
    Examples:
    - "Log me into Gmail"
    - "Sign in to LinkedIn"
    - "Login to GitHub"
    """
    import re
    from .credential_vault import get_credential_vault
    from .auto_login import get_auto_login, PLAYWRIGHT_AVAILABLE
    
    if not PLAYWRIGHT_AVAILABLE:
        return ActionResult.fail(
            "Auto-login requires Playwright. Run: pip install playwright && playwright install chromium",
            "login_to"
        )
    
    vault = get_credential_vault()
    auto_login = get_auto_login()
    
    # Check if vault is set up
    if not vault.is_setup:
        return ActionResult.ok(
            "I need to set up your secure vault first. Please say 'Set up my password vault'.",
            {"needs_setup": True},
            "login_to"
        )
    
    # Check if vault is unlocked
    if not vault.is_unlocked:
        return ActionResult.ok(
            "Your vault is locked. Please say 'Unlock my vault' and provide your master password.",
            {"needs_unlock": True},
            "login_to"
        )
    
    # Extract site name
    text_lower = text.lower()
    site = None
    
    # Try to find site name in command
    patterns = [
        r"(?:log(?:in)?|sign\s*in)\s*(?:to|into)\s+(\w+)",
        r"(?:log(?:in)?|sign\s*in)\s+(\w+)",
        r"open\s+(\w+)\s+and\s+(?:log|sign)\s*in",
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text_lower)
        if match:
            site = match.group(1)
            break
    
    if not site:
        supported = ", ".join(auto_login.get_supported_sites())
        return ActionResult.fail(
            f"Please specify which site to log into. Supported: {supported}",
            "login_to"
        )
    
    # Get stored credentials
    cred = vault.get_credential(site)
    
    if not cred:
        return ActionResult.fail(
            f"I don't have stored credentials for '{site}'. Say 'Save my {site} login' first.",
            "login_to"
        )
    
    # Perform login
    result = auto_login.login(site, cred.username, cred.password, headless=False)
    
    if result.success:
        return ActionResult.ok(
            f"Successfully logged into {site.title()}!",
            {"site": site, "url": result.url},
            "login_to"
        )
    else:
        return ActionResult.fail(
            result.message,
            "login_to"
        )


def handle_setup_vault(text: str, context: Dict[str, Any]) -> ActionResult:
    """Set up the password vault with a master password.
    
    Examples:
    - "Set up my password vault"
    - "Create my vault"
    """
    from .credential_vault import get_credential_vault
    
    vault = get_credential_vault()
    
    if vault.is_setup:
        return ActionResult.ok(
            "Your vault is already set up. Say 'Unlock my vault' to access it.",
            {"already_setup": True},
            "setup_vault"
        )
    
    # This would be a multi-turn interaction in a full implementation
    return ActionResult.ok(
        "To set up your vault, please enter a master password in the UI. "
        "This password will encrypt all your saved credentials. "
        "Make sure it's at least 8 characters long and memorable!",
        {"action": "prompt_master_password"},
        "setup_vault"
    )


def handle_unlock_vault(text: str, context: Dict[str, Any]) -> ActionResult:
    """Unlock the password vault.
    
    Examples:
    - "Unlock my vault"
    - "Open my password vault"
    """
    from .credential_vault import get_credential_vault
    
    vault = get_credential_vault()
    
    if not vault.is_setup:
        return ActionResult.ok(
            "Your vault isn't set up yet. Say 'Set up my password vault' first.",
            {"needs_setup": True},
            "unlock_vault"
        )
    
    if vault.is_unlocked:
        return ActionResult.ok(
            "Your vault is already unlocked!",
            {"already_unlocked": True},
            "unlock_vault"
        )
    
    return ActionResult.ok(
        "Please enter your master password in the UI to unlock your vault.",
        {"action": "prompt_master_password"},
        "unlock_vault"
    )


def handle_list_logins(text: str, context: Dict[str, Any]) -> ActionResult:
    """List saved login credentials.
    
    Examples:
    - "What logins do I have saved?"
    - "Show my saved passwords"
    """
    from .credential_vault import get_credential_vault
    
    vault = get_credential_vault()
    
    if not vault.is_setup:
        return ActionResult.ok(
            "You haven't set up your vault yet. Say 'Set up my password vault' first.",
            {"needs_setup": True},
            "list_logins"
        )
    
    if not vault.is_unlocked:
        return ActionResult.ok(
            "Your vault is locked. Say 'Unlock my vault' first.",
            {"needs_unlock": True},
            "list_logins"
        )
    
    sites = vault.list_sites()
    
    if not sites:
        return ActionResult.ok(
            "You don't have any saved logins yet. Say 'Save my [site] login' to add one.",
            {"sites": []},
            "list_logins"
        )
    
    site_list = ", ".join(sites)
    return ActionResult.ok(
        f"You have saved logins for: {site_list}. Say 'Login to [site]' to use them.",
        {"sites": sites},
        "list_logins"
    )


def register_login_capabilities(registry: Optional[CapabilityRegistry] = None) -> None:
    """Register all login-related capabilities."""
    registry = registry or get_registry()

    registry.register(
        Capability(
            name="login_to",
            triggers=[
                "log me into",
                "log into",
                "login to",
                "sign in to",
                "authenticate to",
            ],
            handler=handle_login_to,
            requires_confirmation=False,
            description="log into a website using saved credentials",
            capability_type=CapabilityType.AUTOMATION,
            examples=[
                "Log me into Gmail",
                "Sign in to LinkedIn",
                "Login to GitHub",
            ],
        )
    )

    registry.register(
        Capability(
            name="save_login",
            triggers=[
                "save my login",
                "save login",
                "remember my password",
                "store my credentials",
                "store credentials",
            ],
            handler=handle_save_login,
            requires_confirmation=False,
            description="save login credentials for a website",
            capability_type=CapabilityType.AUTOMATION,
            examples=[
                "Save my Gmail login",
                "Remember my LinkedIn password",
            ],
        )
    )

    registry.register(
        Capability(
            name="setup_vault",
            triggers=[
                "set up my vault",
                "set up my password vault",
                "create my vault",
                "initialize my vault",
            ],
            handler=handle_setup_vault,
            requires_confirmation=False,
            description="set up the secure password vault",
            capability_type=CapabilityType.AUTOMATION,
            examples=[
                "Set up my password vault",
                "Create my vault",
            ],
        )
    )

    registry.register(
        Capability(
            name="unlock_vault",
            triggers=[
                "unlock my vault",
                "open my vault",
                "unlock vault",
            ],
            handler=handle_unlock_vault,
            requires_confirmation=False,
            description="unlock the password vault",
            capability_type=CapabilityType.AUTOMATION,
            examples=[
                "Unlock my vault",
                "Open my password vault",
            ],
        )
    )

    registry.register(
        Capability(
            name="list_logins",
            triggers=[
                "what logins",
                "show my logins",
                "list my logins",
                "saved passwords",
                "stored credentials",
            ],
            handler=handle_list_logins,
            requires_confirmation=False,
            description="list saved login credentials",
            capability_type=CapabilityType.AUTOMATION,
            examples=[
                "What logins do I have saved?",
                "Show my saved passwords",
            ],
        )
    )

    logger.info("Registered login capabilities")
