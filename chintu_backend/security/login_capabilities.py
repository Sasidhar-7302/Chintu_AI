"""Login and credential management capabilities.

Provides voice commands for:
- Saving login credentials
- Auto-login to websites
- Managing stored credentials
"""

import logging
from urllib.parse import urlparse
from typing import Dict, Any, Optional

from ..core.capabilities import (
    ActionResult,
    Capability,
    CapabilityRegistry,
    CapabilityType,
    get_registry,
)

logger = logging.getLogger(__name__)


_SITE_ALIASES = {
    "yt": "youtube",
    "googlemail": "gmail",
    "mail": "gmail",
}


def _normalize_site(site: str) -> str:
    raw = str(site or "").strip().lower()
    return _SITE_ALIASES.get(raw, raw)


def _infer_site_from_active_browser() -> str:
    try:
        from ..automation.browser.browser_controller import get_browser_controller

        controller = get_browser_controller(headless=False, profile_name=None)
        if not controller or not getattr(controller, "is_open", False):
            return ""
        info = controller.get_page_info()
        url = str(getattr(info, "url", "") or "").strip()
        if not url:
            return ""
        host = str(urlparse(url).hostname or "").lower()
        if host.endswith("youtube.com") or host.endswith("youtu.be"):
            return "youtube"
        if host.endswith("accounts.google.com") or host.endswith("google.com"):
            return "google"
        if host.endswith("mail.google.com") or host.endswith("gmail.com"):
            return "gmail"
        return ""
    except Exception:
        return ""


def _open_login_page(site: str) -> Optional[str]:
    try:
        from .auto_login import get_auto_login
        from ..automation.browser.browser_controller import get_browser_controller
        from ..core.config import get_config

        auto_login = get_auto_login()
        login_url = auto_login.get_login_url(site)
        if not login_url:
            return None
        profile_name = str(getattr(get_config(), "research_browser_loggedin_profile", "") or "").strip() or "assistant_accounts"
        controller = get_browser_controller(headless=False, profile_name=profile_name)
        page = controller.open_url(login_url)
        return str(getattr(page, "url", "") or login_url)
    except Exception:
        return None


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
    text_lower = text.lower()
    waiting_meta = context.get("_waiting_input_meta") if isinstance(context.get("_waiting_input_meta"), dict) else {}
    resume_waiting_input = bool(context.get("_resume_waiting_input"))

    if resume_waiting_input and any(
        marker in text_lower
        for marker in ("done", "finished", "completed", "logged in", "signed in", "continue", "resume")
    ):
        site_hint = _normalize_site(str(waiting_meta.get("site") or "").strip())
        if not site_hint:
            site_hint = _infer_site_from_active_browser()
        site_label = site_hint or "the site"
        return ActionResult.ok(
            f"Great. I marked the manual login step complete for {site_label}. I'm ready for the next action.",
            {"site": site_hint, "awaiting_user_action": False, "manual_login_required": False},
            "login_to",
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

    ambiguous_site_tokens = {"here", "there", "this", "that", "now", "it"}
    if site and str(site).strip().lower() in ambiguous_site_tokens:
        site = None

    if not site:
        hinted_site = _normalize_site(str(waiting_meta.get("site") or "").strip())
        if hinted_site:
            site = hinted_site
    if not site:
        site = _infer_site_from_active_browser()

    if not site:
        supported = ", ".join(auto_login.get_supported_sites())
        return ActionResult.fail(
            f"Please specify which site to log into. Supported: {supported}",
            "login_to"
        )

    site = _normalize_site(site)
    lookup_order = [site]
    if site == "youtube":
        lookup_order.extend(["google", "gmail"])
    elif site == "google":
        lookup_order.append("gmail")
    elif site == "gmail":
        lookup_order.append("google")

    # Get stored credentials (alias-aware)
    cred = None
    cred_site = ""
    for candidate in lookup_order:
        cred = vault.get_credential(candidate)
        if cred:
            cred_site = candidate
            break

    if not cred:
        opened = _open_login_page(site)
        if opened:
            return ActionResult.ok(
                f"I opened the sign-in page for {site} ({opened}). "
                "Please complete login manually in that browser window. I will wait for your next instruction. "
                "If you want auto-login next time, save credentials in the vault first.",
                {
                    "site": site,
                    "url": opened,
                    "manual_login_required": True,
                    "awaiting_user_action": True,
                    "awaiting_user_action_type": "manual_login",
                },
                "login_to",
            )
        return ActionResult.fail(
            f"I don't have stored credentials for '{site}'. "
            f"Say 'Save my {site} login' first. For security, I only use vault credentials, not chat history.",
            "login_to"
        )
    
    # Perform login
    result = auto_login.login(site, cred.username, cred.password, headless=False)
    
    if result.success:
        used = cred_site or site
        waiting_user = bool(getattr(result, "requires_user_action", False))
        return ActionResult.ok(
            str(result.message or f"Successfully logged into {site.title()} using stored credentials for {used}."),
            {
                "site": site,
                "credential_site": used,
                "url": result.url,
                "awaiting_user_action": waiting_user,
                "awaiting_user_action_type": str(getattr(result, "user_action", "") or "").strip(),
            },
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
                "log in to",
                "sign in to",
                "sign me in to",
                "login here",
                "sign in here",
                "continue login",
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
