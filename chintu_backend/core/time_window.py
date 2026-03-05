"""Time window helpers (supports windows that span midnight).

Used by background schedulers/orchestrators to run work only during allowed hours.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HourWindow:
    """A daily hour window in local time.

    - start_hour: 0-23 (inclusive)
    - end_hour: 1-24 (inclusive). Use 24 to represent midnight-end.

    Windows may span midnight (e.g. 22 -> 6).
    """

    start_hour: int
    end_hour: int

    def contains(self, hour: int) -> bool:
        return is_hour_in_window(hour, self.start_hour, self.end_hour)


def _clamp_int(value: int, min_value: int, max_value: int) -> int:
    try:
        value = int(value)
    except Exception:
        value = min_value
    return max(min_value, min(max_value, value))


def is_hour_in_window(hour: int, start_hour: int, end_hour: int) -> bool:
    """Return True if `hour` (0-23) is inside the [start, end) window.

    Supports windows spanning midnight, e.g. start=22, end=6.
    """

    hour = _clamp_int(hour, 0, 23)
    start = _clamp_int(start_hour, 0, 23)
    end = _clamp_int(end_hour, 0, 24)

    # Prevent a zero-length window. Default to a 1-hour window.
    if end == start:
        end = 24 if start == 23 else start + 1

    # Non-wrapping window.
    if end > start:
        if end >= 24:
            return hour >= start
        return start <= hour < end

    # Wrapping window (spans midnight).
    return hour >= start or hour < end

