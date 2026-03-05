"""LLM-in-browser research assistant with profile isolation (Phase 23)."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from chintu_backend.automation.browser.browser_controller import get_browser_controller
from chintu_backend.core.config import get_config

logger = logging.getLogger(__name__)


_SITE_URLS = {
    "chatgpt": "https://chatgpt.com",
    "claude": "https://claude.ai",
    "gemini": "https://gemini.google.com",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_site(site: str) -> str:
    low = str(site or "").strip().lower()
    if "chatgpt" in low or "openai" in low:
        return "chatgpt"
    if "claude" in low or "anthropic" in low:
        return "claude"
    if "gemini" in low or "bard" in low or "google" in low:
        return "gemini"
    return "chatgpt"


class BrowserResearchAssistant:
    """Draft/send/capture workflows against LLM websites in isolated browser profiles."""

    def __init__(self, *, config=None) -> None:
        self.config = config or get_config()
        self.enabled = bool(getattr(self.config, "research_browser_enabled", True))
        self.capture_dir = Path(getattr(self.config, "research_browser_capture_dir"))
        self.capture_dir.mkdir(parents=True, exist_ok=True)

    def draft_prompt(self, *, site: str, prompt: str, logged_in: bool = True) -> Dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "error": "research_browser_disabled"}

        normalized = _normalize_site(site)
        controller = get_browser_controller(
            headless=False,
            profile_name=self._profile_for(logged_in=logged_in),
        )
        page_info = controller.open_url(_SITE_URLS.get(normalized, _SITE_URLS["chatgpt"]), wait_for="domcontentloaded")

        # Best-effort fill only (no submit in draft mode).
        filled = False
        for selector in ("textarea", "#prompt-textarea", "[contenteditable='true']"):
            if controller.fill_input(selector, prompt):
                filled = True
                break

        payload = {
            "ok": True,
            "mode": "draft",
            "site": normalized,
            "profile": self._profile_for(logged_in=logged_in),
            "page_url": getattr(page_info, "url", ""),
            "page_title": getattr(page_info, "title", ""),
            "prompt": str(prompt or "").strip(),
            "filled": bool(filled),
            "requires_explicit_send_approval": True,
            "created_at_utc": _utc_now_iso(),
        }
        payload["artifact_path"] = str(self._write_capture("draft", normalized, payload))
        return payload

    def send_prompt(self, *, site: str, prompt: str, logged_in: bool = True) -> Dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "error": "research_browser_disabled"}

        normalized = _normalize_site(site)
        controller = get_browser_controller(
            headless=False,
            profile_name=self._profile_for(logged_in=logged_in),
        )
        page_info = controller.open_url(_SITE_URLS.get(normalized, _SITE_URLS["chatgpt"]), wait_for="domcontentloaded")

        filled = False
        for selector in ("textarea", "#prompt-textarea", "[contenteditable='true']"):
            if controller.fill_input(selector, prompt):
                filled = True
                break

        submitted = self._try_submit_prompt(controller)
        screenshot_path = ""
        try:
            screenshot_path = str(controller.take_screenshot(f"research_{normalized}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"))
        except Exception:
            screenshot_path = ""

        payload = {
            "ok": True,
            "mode": "send",
            "site": normalized,
            "profile": self._profile_for(logged_in=logged_in),
            "page_url": getattr(page_info, "url", ""),
            "page_title": getattr(page_info, "title", ""),
            "prompt": str(prompt or "").strip(),
            "filled": bool(filled),
            "submitted": bool(submitted),
            "screenshot_path": screenshot_path,
            "created_at_utc": _utc_now_iso(),
        }
        payload["artifact_path"] = str(self._write_capture("send", normalized, payload))
        return payload

    def capture_response(self, *, site: str, note: str = "", logged_in: bool = True) -> Dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "error": "research_browser_disabled"}

        normalized = _normalize_site(site)
        controller = get_browser_controller(
            headless=False,
            profile_name=self._profile_for(logged_in=logged_in),
        )
        # Ensure site is open in dedicated profile before capture.
        page_info = controller.open_url(_SITE_URLS.get(normalized, _SITE_URLS["chatgpt"]), wait_for="domcontentloaded")
        page_text = str(controller.get_page_content(max_length=4000) or "").strip()
        screenshot_path = ""
        try:
            screenshot_path = str(controller.take_screenshot(f"research_capture_{normalized}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"))
        except Exception:
            screenshot_path = ""

        payload = {
            "ok": True,
            "mode": "capture",
            "site": normalized,
            "profile": self._profile_for(logged_in=logged_in),
            "page_url": getattr(page_info, "url", ""),
            "page_title": getattr(page_info, "title", ""),
            "note": str(note or "").strip(),
            "response_text": page_text,
            "screenshot_path": screenshot_path,
            "created_at_utc": _utc_now_iso(),
        }
        payload["artifact_path"] = str(self._write_capture("capture", normalized, payload))
        return payload

    def _profile_for(self, *, logged_in: bool) -> str:
        if logged_in:
            return str(getattr(self.config, "research_browser_loggedin_profile", "assistant_accounts") or "assistant_accounts")
        return str(getattr(self.config, "research_browser_default_profile", "research") or "research")

    def _write_capture(self, mode: str, site: str, payload: Dict[str, Any]) -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = self.capture_dir / f"{mode}_{site}_{stamp}.json"
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
        return out

    @staticmethod
    def _try_submit_prompt(controller) -> bool:
        try:
            snapshot = controller.list_interactive_elements(max_elements=120)
            for element in list(snapshot.get("elements") or []):
                text = str(element.get("text") or "").lower()
                role = str(element.get("role") or "").lower()
                if not element.get("ref"):
                    continue
                if role not in {"button", "link", "menuitem"}:
                    continue
                if any(token in text for token in ("send", "submit", "ask", "run")):
                    acted = controller.act_by_ref(str(element["ref"]), action="click", screenshot_after=False)
                    if bool(acted.get("success")):
                        return True
        except Exception:
            return False
        return False


_assistant: Optional[BrowserResearchAssistant] = None


def get_browser_research_assistant() -> BrowserResearchAssistant:
    global _assistant
    if _assistant is None:
        _assistant = BrowserResearchAssistant()
    return _assistant


def detect_site_from_text(text: str) -> str:
    low = str(text or "").lower()
    if "claude" in low:
        return "claude"
    if "gemini" in low:
        return "gemini"
    if "chatgpt" in low or "openai" in low:
        return "chatgpt"
    return "chatgpt"


def extract_prompt_from_text(text: str) -> str:
    raw = str(text or "").strip()
    # Common forms:
    # - "research X using chatgpt"
    # - "send this to claude: ..."
    parts = re.split(r"(?i)(?:using\s+(?:chatgpt|claude|gemini)|to\s+(?:chatgpt|claude|gemini)\s*:?)", raw, maxsplit=1)
    if len(parts) > 1:
        candidate = str(parts[0]).strip()
    else:
        candidate = raw
    candidate = re.sub(r"(?i)^\s*(research|draft|send|ask|capture)\s*", "", candidate).strip()
    return candidate or raw
