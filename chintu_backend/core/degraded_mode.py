"""Backward-compatible degraded mode exports (moved to chintu.policy)."""

from ..policy.offline_mode import (
    OfflineDegradedMode,
    SystemMode,
    CapabilityAvailability,
    get_degraded_mode,
    reset_degraded_mode,
)

__all__ = [
    "OfflineDegradedMode",
    "SystemMode",
    "CapabilityAvailability",
    "get_degraded_mode",
    "reset_degraded_mode",
]
