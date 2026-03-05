"""
Offline degraded mode manager for Chintu AI Assistant.

Manages capability availability based on system state and connectivity.
"""

import socket
import logging
import urllib.request
from enum import Enum
from dataclasses import dataclass
from typing import Dict, Set, Optional

logger = logging.getLogger(__name__)


class SystemMode(Enum):
    """System operation modes."""

    FULL = "full"                 # All capabilities available
    LIMITED_CLOUD = "limited"     # Rate limited, prefer local
    OFFLINE = "offline"           # No internet connection
    LOW_POWER = "low_power"       # Battery saving mode
    QUIET = "quiet"               # No TTS, minimal outputs


@dataclass
class CapabilityAvailability:
    """Availability status for a capability."""

    available: bool
    reason: str = ""
    alternative: Optional[str] = None
    degraded: bool = False


class OfflineDegradedMode:
    """
    Manages system-wide degraded mode and capability availability.

    Ensures the assistant always works, even if with reduced functionality,
    rather than showing cryptic errors when things fail.
    """

    OFFLINE_SAFE: Set[str] = {
        "system_info", "status", "help", "what_can_you_do", "why", "history",
        "open_app",
        "get_preferences", "set_preference", "reset_preferences",
        "remember_fact", "recall_facts", "forget", "memory_stats",
        "set_reminder", "list_reminders", "cancel_reminder", "task_status",
        "note_taking",
        "read_file", "list_files", "file_info",
        "clipboard_read", "clipboard_copy",
        "read_response",
        "list_scheduled", "cancel_scheduled", "check_tasks",
    }

    REQUIRES_INTERNET: Set[str] = {
        "web_search", "news_search", "deep_search",
        "open_browser", "browser_search", "page_content", "click_link",
        "open_url",
        "conversation",
        "quick_action",
    }

    DEGRADED_OFFLINE: Dict[str, str] = {
        "conversation": "Will use local model with limited capability",
        "open_url": "Cannot open URLs without internet",
    }

    POWER_HUNGRY: Set[str] = {
        "deep_search",
        "execute_workflow",
        "background_task",
    }

    NOISY: Set[str] = {
        "read_response",
    }

    def __init__(self):
        self._current_mode = SystemMode.FULL
        self._manually_disabled: Set[str] = set()
        self._last_internet_check: float = 0
        self._internet_available: bool = True
        self._check_interval: float = 15.0
        self._check_host = "8.8.8.8"
        self._check_port = 53
        self._check_timeout = 2.0
        self._http_probe_urls = (
            "http://www.msftconnecttest.com/connecttest.txt",
            "http://connectivitycheck.gstatic.com/generate_204",
        )
        self._failures_before_offline = 2
        self._successes_before_online = 1
        self._failed_checks = 0
        self._successful_checks = 0

        try:
            from ..core.config import get_config
            config = get_config()
            self._check_host = config.network_check_host
            self._check_port = config.network_check_port
            self._check_timeout = config.network_check_timeout_seconds
            self._check_interval = float(getattr(config, "network_check_interval_seconds", self._check_interval))
            self._failures_before_offline = int(
                getattr(config, "network_check_failures_before_offline", self._failures_before_offline)
            )
            self._successes_before_online = int(
                getattr(config, "network_check_successes_before_online", self._successes_before_online)
            )
        except Exception:
            pass

        logger.info("OfflineDegradedMode manager initialized")

    def check_internet(self, force: bool = False) -> bool:
        import time

        now = time.time()
        if not force and (now - self._last_internet_check) < self._check_interval:
            return self._internet_available

        # Try multiple hosts for reliability - if ANY succeeds, we have internet
        hosts_to_try = [
            (self._check_host, self._check_port),
            ("1.1.1.1", 53),  # Cloudflare DNS
            ("208.67.222.222", 53),  # OpenDNS
        ]
        
        probe_success = False
        for host, port in hosts_to_try:
            sock = None
            try:
                sock = socket.create_connection(
                    (host, port),
                    timeout=self._check_timeout,
                )
                probe_success = True
                break  # Success - stop trying
            except (socket.timeout, socket.error, OSError):
                pass  # Try next host
            finally:
                if sock:
                    try:
                        sock.close()
                    except OSError:
                        pass
        if not probe_success:
            # Fallback HTTP probe: helps when outbound DNS-port checks are blocked by network policy.
            for probe_url in self._http_probe_urls:
                try:
                    with urllib.request.urlopen(probe_url, timeout=max(1.5, self._check_timeout)) as resp:
                        if getattr(resp, "status", 200) in (200, 204):
                            probe_success = True
                            break
                except Exception:
                    continue

        self._last_internet_check = now

        if probe_success:
            self._failed_checks = 0
            self._successful_checks += 1
            if self._current_mode == SystemMode.OFFLINE:
                if self._successful_checks >= max(1, self._successes_before_online):
                    self._internet_available = True
                    self._current_mode = SystemMode.FULL
                    logger.info("Internet restored - switching to full mode")
                else:
                    self._internet_available = False
            else:
                self._internet_available = True
        else:
            self._successful_checks = 0
            self._failed_checks += 1
            if self._failed_checks >= max(1, self._failures_before_offline):
                if self._current_mode != SystemMode.OFFLINE:
                    logger.warning("Internet connectivity check failed - switching to offline mode")
                self._internet_available = False
                self._current_mode = SystemMode.OFFLINE
            else:
                # Treat a single failed probe as transient; keep prior state.
                logger.debug(
                    "Transient internet probe failure (%d/%d). Keeping current mode '%s'.",
                    self._failed_checks,
                    self._failures_before_offline,
                    self._current_mode.value,
                )

        return self._internet_available

    def set_mode(self, mode: SystemMode):
        old_mode = self._current_mode
        self._current_mode = mode
        if old_mode != mode:
            logger.info("System mode changed: %s -> %s", old_mode.value, mode.value)

    def get_mode(self) -> SystemMode:
        return self._current_mode

    def disable_capability(self, capability_name: str):
        self._manually_disabled.add(capability_name)
        logger.info("Capability '%s' manually disabled", capability_name)

    def enable_capability(self, capability_name: str):
        self._manually_disabled.discard(capability_name)
        logger.info("Capability '%s' re-enabled", capability_name)

    def is_available(self, capability_name: str) -> CapabilityAvailability:
        if capability_name in self._manually_disabled:
            return CapabilityAvailability(
                available=False,
                reason="Capability is manually disabled",
            )

        if capability_name in self.OFFLINE_SAFE:
            if self._current_mode == SystemMode.QUIET and capability_name in self.NOISY:
                return CapabilityAvailability(
                    available=False,
                    reason="Disabled in quiet mode (audio output not allowed)",
                )
            return CapabilityAvailability(available=True)

        if capability_name in self.REQUIRES_INTERNET:
            if self._current_mode == SystemMode.OFFLINE or not self.check_internet():
                if capability_name in self.DEGRADED_OFFLINE:
                    return CapabilityAvailability(
                        available=True,
                        degraded=True,
                        reason=self.DEGRADED_OFFLINE[capability_name],
                    )
                return CapabilityAvailability(
                    available=False,
                    reason="Requires internet connection",
                    alternative=self._get_offline_alternative(capability_name),
                )

        if self._current_mode == SystemMode.LOW_POWER:
            if capability_name in self.POWER_HUNGRY:
                return CapabilityAvailability(
                    available=False,
                    reason="Disabled in low power mode to save battery",
                )

        if self._current_mode == SystemMode.LIMITED_CLOUD:
            if capability_name in self.REQUIRES_INTERNET:
                return CapabilityAvailability(
                    available=True,
                    degraded=True,
                    reason="Using local model due to rate limits",
                )

        return CapabilityAvailability(available=True)

    def _get_offline_alternative(self, capability_name: str) -> Optional[str]:
        alternatives = {
            "web_search": "recall_facts",
            "news_search": None,
            "deep_search": "read_file",
            "browser_search": "open_app",
            "open_url": "open_app",
            "page_content": "read_file",
            "click_link": None,
            "conversation": "recall_facts",
            "quick_action": "plan_task",
        }
        return alternatives.get(capability_name)

    def get_available_capabilities(self) -> Set[str]:
        available = self.OFFLINE_SAFE.copy()
        available -= self._manually_disabled

        if self._current_mode == SystemMode.QUIET:
            available -= self.NOISY

        if self._current_mode == SystemMode.LOW_POWER:
            available -= self.POWER_HUNGRY

        if self._current_mode not in (SystemMode.OFFLINE,) and self.check_internet():
            available |= self.REQUIRES_INTERNET

        return available

    def get_mode_message(self) -> str:
        messages = {
            SystemMode.FULL: "All features available",
            SystemMode.LIMITED_CLOUD: "Using local model (cloud rate limited)",
            SystemMode.OFFLINE: "Offline mode - internet features unavailable",
            SystemMode.LOW_POWER: "Low power mode - intensive features disabled",
            SystemMode.QUIET: "Quiet mode - audio output disabled",
        }
        return messages.get(self._current_mode, "Unknown mode")

    def get_status_report(self) -> Dict:
        available = self.get_available_capabilities()
        unavailable = (self.REQUIRES_INTERNET | self.POWER_HUNGRY) - available

        return {
            "mode": self._current_mode.value,
            "mode_message": self.get_mode_message(),
            "internet_available": self._internet_available,
            "available_count": len(available),
            "unavailable_count": len(unavailable),
            "manually_disabled": list(self._manually_disabled),
            "unavailable_capabilities": list(unavailable)[:10],
        }


_degraded_mode: Optional[OfflineDegradedMode] = None


def get_degraded_mode() -> OfflineDegradedMode:
    """Get or create the global degraded mode manager."""
    global _degraded_mode
    if _degraded_mode is None:
        _degraded_mode = OfflineDegradedMode()
    return _degraded_mode


def reset_degraded_mode():
    """Reset the global degraded mode manager (for testing)."""
    global _degraded_mode
    _degraded_mode = None
