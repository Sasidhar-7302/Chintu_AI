"""Focus Mode capability (close distractions, open work apps, enable DND).

This is intentionally best-effort on Windows:
- Closing apps is done by terminating known processes (confirmation-gated).
- Do Not Disturb toggling uses UI automation; it may vary by Windows version.
"""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import psutil
from pydantic import BaseModel, Field

from chintu_backend.core.capabilities import ActionResult, Capability, CapabilityType

logger = logging.getLogger(__name__)


class FocusModeSchema(BaseModel):
    close_apps: List[str] = Field(default_factory=lambda: ["discord", "steam"], description="Apps to close.")
    open_apps: List[str] = Field(default_factory=lambda: ["vs code"], description="Apps to open.")
    open_urls: List[str] = Field(
        default_factory=lambda: ["https://open.spotify.com/search/lofi%20beats"],
        description="URLs to open (e.g., music playlist).",
    )
    enable_do_not_disturb: bool = Field(True, description="Try to enable Do Not Disturb.")


def _terminate_by_name_contains(needle: str) -> int:
    needle = (needle or "").strip().lower()
    if not needle:
        return 0
    killed = 0
    for proc in psutil.process_iter(attrs=["pid", "name"]):
        try:
            name = (proc.info.get("name") or "").lower()
            if needle in name:
                proc.terminate()
                killed += 1
        except Exception:
            continue
    return killed


def _enable_do_not_disturb() -> Tuple[bool, str]:
    """Best-effort toggle using UI automation."""
    try:
        import uiautomation as auto

        # Open Notification Center (Win+N) on Windows 11.
        try:
            auto.SendKeys("{Win}n")
            time.sleep(0.6)
        except Exception:
            pass

        root = auto.GetRootControl()

        # Candidate toggle names differ by Windows version / locale.
        candidates = [
            "Do not disturb",
            "Do Not Disturb",
            "Focus assist",
            "Focus Assist",
            "Focus",
        ]

        for name in candidates:
            try:
                ctrl = root.Control(searchDepth=6, Name=name, SubName=name)
                if not ctrl.Exists(maxSearchSeconds=1):
                    continue
                # Prefer TogglePattern so we don't accidentally turn it off.
                if ctrl.GetPattern(auto.PatternId.TogglePattern):
                    patt = ctrl.GetTogglePattern()
                    state = patt.CurrentToggleState
                    if state != auto.ToggleState.On:
                        patt.Toggle()
                        return True, f"Enabled: {name}"
                    return True, f"Already enabled: {name}"
                # Fallback: click.
                ctrl.Click(simulateMove=True)
                return True, f"Toggled: {name}"
            except Exception:
                continue

        return False, "Could not find a Do Not Disturb/Focus toggle."
    except Exception as exc:  # noqa: BLE001
        return False, f"UI automation unavailable: {exc}"


def handle_focus_mode(text: str, context: Dict[str, Any]) -> ActionResult:
    validated = context.get("_validated_params")
    close_apps = ["discord", "steam"]
    open_apps = ["vs code"]
    open_urls = ["https://open.spotify.com/search/lofi%20beats"]
    enable_dnd = True
    if validated and isinstance(validated, FocusModeSchema):
        close_apps = [str(a).strip() for a in (validated.close_apps or []) if str(a).strip()]
        open_apps = [str(a).strip() for a in (validated.open_apps or []) if str(a).strip()]
        open_urls = [str(u).strip() for u in (validated.open_urls or []) if str(u).strip()]
        enable_dnd = bool(validated.enable_do_not_disturb)

    plan_lines = ["Focus Mode plan:"]
    if close_apps:
        plan_lines.append("- Close: " + ", ".join(close_apps))
    if open_apps:
        plan_lines.append("- Open: " + ", ".join(open_apps))
    if open_urls:
        plan_lines.append("- Open URLs: " + ", ".join(open_urls))
    if enable_dnd:
        plan_lines.append("- Enable Do Not Disturb (best-effort)")

    def _do() -> ActionResult:
        killed: Dict[str, int] = {}
        for app in close_apps:
            try:
                killed[app] = _terminate_by_name_contains(app)
            except Exception:
                killed[app] = 0

        # Open apps/urls (best-effort).
        opened_apps: List[str] = []
        opened_urls: List[str] = []
        try:
            from chintu_backend.automation.app_launcher import AppLauncher

            launcher = AppLauncher()
            for app in open_apps:
                try:
                    if launcher.launch_app(app):
                        opened_apps.append(app)
                except Exception:
                    continue
            for url in open_urls:
                try:
                    if launcher.open_url(url):
                        opened_urls.append(url)
                except Exception:
                    continue
        except Exception:
            # As a fallback, attempt to spawn VS Code via subprocess.
            try:
                subprocess.Popen(["code"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                opened_apps.append("vs code")
            except Exception:
                pass

        dnd_ok = False
        dnd_msg = ""
        if enable_dnd:
            dnd_ok, dnd_msg = _enable_do_not_disturb()

        lines = ["Focus Mode enabled."]
        if killed:
            killed_bits = ", ".join(f"{k}:{v}" for k, v in killed.items())
            lines.append(f"- Closed processes: {killed_bits}")
        if opened_apps:
            lines.append(f"- Opened apps: {', '.join(opened_apps)}")
        if opened_urls:
            lines.append(f"- Opened URLs: {', '.join(opened_urls)}")
        if enable_dnd:
            lines.append(f"- Do Not Disturb: {'ok' if dnd_ok else 'not set'} ({dnd_msg})")
        return ActionResult.ok("\n".join(lines).strip(), {"killed": killed, "opened_apps": opened_apps, "opened_urls": opened_urls, "dnd": {"ok": dnd_ok, "message": dnd_msg}}, "focus_mode")

    # This can close apps; require a single explicit confirmation.
    if not context.get("_confirmed"):
        return ActionResult.confirm("\n".join(plan_lines) + "\n\nProceed?", _do, "focus_mode")
    return _do()


def register_focus_mode_capabilities(registry) -> None:
    registry.register(
        Capability(
            name="focus_mode",
            triggers=[
                "enable focus mode",
                "focus mode",
                "i'm starting coding now",
                "start coding now",
            ],
            handler=handle_focus_mode,
            requires_confirmation=False,  # handler provides its own confirmation
            description="close distracting apps, open work apps, and enable do not disturb",
            capability_type=CapabilityType.SYSTEM,
            examples=[
                "I'm starting coding now. Enable Focus Mode.",
                "Enable focus mode",
            ],
            schema=FocusModeSchema,
        )
    )

