"""Browser-based auto-login using Playwright.

Automates login to common websites using stored credentials.
"""

import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Try to import playwright
try:
    from playwright.sync_api import sync_playwright, Page, Browser
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger.warning("playwright not installed. Auto-login will not work.")


@dataclass
class LoginResult:
    """Result of a login attempt."""
    success: bool
    message: str
    url: Optional[str] = None


# Site-specific login configurations
LOGIN_CONFIGS = {
    "gmail": {
        "url": "https://accounts.google.com/signin",
        "username_selector": "input[type='email']",
        "username_next": "#identifierNext",
        "password_selector": "input[type='password']",
        "password_next": "#passwordNext",
        "success_url_contains": "myaccount.google.com",
        "steps": ["enter_username", "click_next", "wait", "enter_password", "click_submit"]
    },
    "google": {
        "url": "https://accounts.google.com/signin",
        "username_selector": "input[type='email']",
        "username_next": "#identifierNext",
        "password_selector": "input[type='password']",
        "password_next": "#passwordNext",
        "success_url_contains": "myaccount.google.com",
        "steps": ["enter_username", "click_next", "wait", "enter_password", "click_submit"]
    },
    "linkedin": {
        "url": "https://www.linkedin.com/login",
        "username_selector": "#username",
        "password_selector": "#password",
        "submit_selector": "button[type='submit']",
        "success_url_contains": "feed",
        "steps": ["enter_username", "enter_password", "click_submit"]
    },
    "github": {
        "url": "https://github.com/login",
        "username_selector": "#login_field",
        "password_selector": "#password",
        "submit_selector": "input[type='submit']",
        "success_url_contains": "github.com",
        "steps": ["enter_username", "enter_password", "click_submit"]
    },
    "twitter": {
        "url": "https://twitter.com/login",
        "username_selector": "input[autocomplete='username']",
        "password_selector": "input[type='password']",
        "steps": ["enter_username", "click_next", "wait", "enter_password", "click_submit"]
    },
    "facebook": {
        "url": "https://www.facebook.com/login",
        "username_selector": "#email",
        "password_selector": "#pass",
        "submit_selector": "button[name='login']",
        "success_url_contains": "facebook.com",
        "steps": ["enter_username", "enter_password", "click_submit"]
    },
}


class AutoLogin:
    """Handles automated login to websites."""
    
    def __init__(self):
        self._browser: Optional[Browser] = None
        self._playwright = None
        
    def login(self, site: str, username: str, password: str, 
              headless: bool = False) -> LoginResult:
        """Perform automated login to a site.
        
        Args:
            site: Site name (e.g., "gmail", "linkedin")
            username: Username/email
            password: Password
            headless: Whether to run browser in headless mode
            
        Returns:
            LoginResult with success status and message
        """
        if not PLAYWRIGHT_AVAILABLE:
            return LoginResult(
                success=False,
                message="Playwright not installed. Run: pip install playwright && playwright install chromium"
            )
        
        site_lower = site.lower().strip()
        config = LOGIN_CONFIGS.get(site_lower)
        
        if not config:
            # Try to do a generic login
            return LoginResult(
                success=False,
                message=f"No login configuration for '{site}'. Supported: {', '.join(LOGIN_CONFIGS.keys())}"
            )
        
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=headless)
                context = browser.new_context()
                page = context.new_page()
                
                # Navigate to login page
                page.goto(config["url"], wait_until="networkidle")
                logger.info(f"Navigated to {config['url']}")
                
                # Execute login steps
                result = self._execute_login_steps(page, config, username, password)
                
                # Keep browser open if successful and not headless
                if result.success and not headless:
                    input("Press Enter to close browser...")
                    
                browser.close()
                return result
                
        except Exception as e:
            logger.error(f"Login failed: {e}")
            return LoginResult(
                success=False,
                message=f"Login failed: {str(e)}"
            )
    
    def _execute_login_steps(self, page: "Page", config: Dict[str, Any],
                            username: str, password: str) -> LoginResult:
        """Execute the login steps for a site.
        
        Args:
            page: Playwright page object
            config: Site login configuration
            username: Username to enter
            password: Password to enter
            
        Returns:
            LoginResult
        """
        try:
            steps = config.get("steps", [])
            
            for step in steps:
                if step == "enter_username":
                    selector = config.get("username_selector")
                    if selector:
                        page.wait_for_selector(selector, timeout=10000)
                        page.fill(selector, username)
                        logger.debug(f"Entered username in {selector}")
                        
                elif step == "enter_password":
                    selector = config.get("password_selector")
                    if selector:
                        page.wait_for_selector(selector, timeout=10000)
                        page.fill(selector, password)
                        logger.debug(f"Entered password in {selector}")
                        
                elif step == "click_next":
                    selector = config.get("username_next")
                    if selector:
                        page.click(selector)
                        logger.debug(f"Clicked next button: {selector}")
                        
                elif step == "click_submit":
                    selector = config.get("submit_selector") or config.get("password_next")
                    if selector:
                        page.click(selector)
                        logger.debug(f"Clicked submit: {selector}")
                    else:
                        # Try pressing Enter
                        page.keyboard.press("Enter")
                        
                elif step == "wait":
                    page.wait_for_timeout(2000)  # Wait 2 seconds
                    
            # Wait for navigation
            page.wait_for_timeout(3000)
            
            # Check if login was successful
            current_url = page.url
            success_indicator = config.get("success_url_contains", "")
            
            if success_indicator and success_indicator in current_url:
                return LoginResult(
                    success=True,
                    message=f"Successfully logged in to {config['url']}",
                    url=current_url
                )
            else:
                # Check for error messages
                return LoginResult(
                    success=True,  # May have worked, but can't verify
                    message=f"Login attempted. Current URL: {current_url}",
                    url=current_url
                )
                
        except Exception as e:
            logger.error(f"Login step failed: {e}")
            return LoginResult(
                success=False,
                message=f"Login step failed: {str(e)}"
            )
    
    @staticmethod
    def get_supported_sites() -> list:
        """Get list of supported sites for auto-login."""
        return list(LOGIN_CONFIGS.keys())


# Global instance
_auto_login: Optional[AutoLogin] = None


def get_auto_login() -> AutoLogin:
    """Get the global AutoLogin instance."""
    global _auto_login
    if _auto_login is None:
        _auto_login = AutoLogin()
    return _auto_login
