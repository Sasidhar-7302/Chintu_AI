"""System idle heuristics (Windows-focused with safe fallbacks).

Goal: Gate heavy background tasks (YouTube rendering, app scaffolding, fine-tuning)
so they run primarily when the PC is idle.

We use a layered heuristic:
- User inactivity (no keyboard/mouse input) via GetLastInputInfo (Windows)
- CPU utilization via psutil
- GPU utilization via nvidia-smi (if available)
"""

from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IdleSnapshot:
    idle_seconds: Optional[float]
    cpu_percent: Optional[float]
    gpu_util_percent: Optional[float]


def get_idle_seconds() -> Optional[float]:
    """Return seconds since last keyboard/mouse input, or None if unavailable."""

    if sys.platform != "win32":
        return None

    try:
        import ctypes
        from ctypes import wintypes

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.UINT),
                ("dwTime", wintypes.DWORD),
            ]

        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):  # type: ignore[attr-defined]
            return None

        # GetTickCount is milliseconds since system start (wraps at 2^32).
        tick = ctypes.windll.kernel32.GetTickCount()  # type: ignore[attr-defined]
        elapsed_ms = int(tick) - int(info.dwTime)
        if elapsed_ms < 0:
            # Handle wrap-around.
            elapsed_ms += 2**32
        return float(elapsed_ms) / 1000.0
    except Exception:
        return None


def get_cpu_percent(sample_seconds: float = 0.15) -> Optional[float]:
    try:
        import psutil

        return float(psutil.cpu_percent(interval=max(0.0, float(sample_seconds))))
    except Exception:
        return None


def get_gpu_util_percent() -> Optional[float]:
    """Return max GPU utilization across devices, or None if unavailable."""

    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
    except Exception:
        return None

    if proc.returncode != 0:
        return None

    values = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            values.append(float(line))
        except Exception:
            continue
    if not values:
        return None
    return float(max(values))


def snapshot() -> IdleSnapshot:
    return IdleSnapshot(
        idle_seconds=get_idle_seconds(),
        cpu_percent=get_cpu_percent(),
        gpu_util_percent=get_gpu_util_percent(),
    )


def is_idle(
    *,
    min_idle_seconds: float = 10 * 60,
    max_cpu_percent: float = 30.0,
    max_gpu_util_percent: float = 25.0,
) -> Tuple[bool, str, IdleSnapshot]:
    """Return (idle_ok, reason, snapshot)."""

    snap = snapshot()

    # If we cannot measure user idle time, fall back to CPU/GPU only.
    if snap.idle_seconds is not None and snap.idle_seconds < float(min_idle_seconds):
        return False, f"user_active({snap.idle_seconds:.0f}s<{min_idle_seconds:.0f}s)", snap

    if snap.cpu_percent is not None and snap.cpu_percent > float(max_cpu_percent):
        return False, f"cpu_busy({snap.cpu_percent:.0f}%>{max_cpu_percent:.0f}%)", snap

    if snap.gpu_util_percent is not None and snap.gpu_util_percent > float(max_gpu_util_percent):
        return False, f"gpu_busy({snap.gpu_util_percent:.0f}%>{max_gpu_util_percent:.0f}%)", snap

    return True, "idle", snap

