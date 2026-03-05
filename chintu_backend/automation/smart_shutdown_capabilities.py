"""Smart shutdown after download completion (network-idle monitor)."""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import psutil
from pydantic import BaseModel, Field

from chintu_backend.core.capabilities import ActionResult, Capability, CapabilityType
from chintu_backend.core.state import get_state_manager

logger = logging.getLogger(__name__)


class SmartShutdownSchema(BaseModel):
    idle_minutes: int = Field(2, ge=1, le=30, description="How long download speed must stay low before shutdown.")
    idle_kbps: int = Field(30, ge=1, le=5000, description="Below this download rate (KB/s) counts as idle.")
    active_kbps: int = Field(200, ge=10, le=50000, description="Above this download rate (KB/s) counts as active download.")
    sample_seconds: int = Field(5, ge=1, le=60, description="Sampling interval in seconds.")
    require_user_idle_seconds: int = Field(120, ge=0, le=3600, description="Require user idle before shutdown.")


@dataclass
class MonitorState:
    running: bool = False
    started_at: float = 0.0
    last_rate_kbps: float = 0.0
    seen_active: bool = False
    idle_seconds: int = 0
    config: Optional[SmartShutdownSchema] = None


class SmartShutdownMonitor:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.state = MonitorState()

    def start(self, cfg: SmartShutdownSchema) -> Tuple[bool, str]:
        with self._lock:
            if self.state.running:
                return False, "Smart shutdown monitor is already running."
            self._stop.clear()
            self.state = MonitorState(running=True, started_at=time.time(), config=cfg)
            self._thread = threading.Thread(target=self._loop, name="chintu-smart-shutdown", daemon=True)
            self._thread.start()
        get_state_manager().update_feature("smart_shutdown", enabled=True, status="active", error=None)
        return True, "Monitoring network activity. I will shut down once the download finishes."

    def cancel(self) -> Tuple[bool, str]:
        with self._lock:
            if not self.state.running:
                return False, "Smart shutdown monitor is not running."
            self._stop.set()
            self.state.running = False
        get_state_manager().update_feature("smart_shutdown", enabled=False, status="inactive", error=None)
        return True, "Cancelled smart shutdown."

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            s = self.state
            cfg = s.config
            return {
                "running": bool(s.running),
                "started_at": float(s.started_at),
                "last_rate_kbps": float(s.last_rate_kbps),
                "seen_active": bool(s.seen_active),
                "idle_seconds": int(s.idle_seconds),
                "config": cfg.model_dump() if cfg else {},
            }

    def _loop(self) -> None:
        cfg = self.state.config
        if not cfg:
            return

        sample = max(1, int(cfg.sample_seconds))
        idle_target = int(cfg.idle_minutes) * 60
        idle_kbps = float(cfg.idle_kbps)
        active_kbps = float(cfg.active_kbps)

        prev = psutil.net_io_counters()
        prev_t = time.time()

        while not self._stop.is_set():
            time.sleep(sample)
            now = time.time()
            cur = psutil.net_io_counters()
            dt = max(0.1, now - prev_t)
            # Download rate based on bytes received.
            d_recv = max(0, int(cur.bytes_recv) - int(prev.bytes_recv))
            rate_kbps = (d_recv / 1024.0) / dt

            with self._lock:
                self.state.last_rate_kbps = float(rate_kbps)
                if rate_kbps >= active_kbps:
                    self.state.seen_active = True
                    self.state.idle_seconds = 0
                elif self.state.seen_active and rate_kbps <= idle_kbps:
                    self.state.idle_seconds += int(sample)
                else:
                    # Not active yet, or hovering.
                    self.state.idle_seconds = 0

            prev = cur
            prev_t = now

            # Update UI state (best-effort).
            try:
                msg = f"rate={rate_kbps:.0f} KB/s idle={self.state.idle_seconds}s seen_active={self.state.seen_active}"
                get_state_manager().update_feature("smart_shutdown", status="active", error=msg[:200])
            except Exception:
                pass

            # Only shutdown after we've seen a real download, then prolonged low throughput.
            if not self.state.seen_active:
                continue
            if self.state.idle_seconds < idle_target:
                continue

            # Require user idle (best-effort) to reduce surprise shutdowns.
            if int(cfg.require_user_idle_seconds) > 0:
                try:
                    from chintu_backend.core.system_idle import get_idle_seconds

                    idle_s = get_idle_seconds()
                    # If we can measure idle time and the user is active, do not shutdown.
                    if idle_s is not None and idle_s < float(cfg.require_user_idle_seconds):
                        with self._lock:
                            self.state.idle_seconds = 0
                        continue
                except Exception:
                    pass

            # Require no active Chintu runs (best-effort).
            try:
                from chintu_backend.core.run_manager import get_run_manager

                rm = get_run_manager()
                snap = rm.snapshot(limit=30)
                runs = snap.get("runs") if isinstance(snap, dict) else None
                if isinstance(runs, list):
                    active = [r for r in runs if (r or {}).get("status") in {"running", "queued", "waiting_approval", "waiting_input"}]
                    if active:
                        with self._lock:
                            self.state.idle_seconds = 0
                        continue
            except Exception:
                pass

            # Shutdown now.
            try:
                get_state_manager().log_activity("Smart shutdown triggered (download idle).")
            except Exception:
                pass
            try:
                subprocess.run(["shutdown", "/s", "/t", "0"], check=False, timeout=5.0)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Shutdown command failed: %s", exc)
            break

        with self._lock:
            self.state.running = False
        try:
            get_state_manager().update_feature("smart_shutdown", enabled=False, status="inactive", error=None)
        except Exception:
            pass


_monitor: Optional[SmartShutdownMonitor] = None


def get_smart_shutdown_monitor() -> SmartShutdownMonitor:
    global _monitor
    if _monitor is None:
        _monitor = SmartShutdownMonitor()
    return _monitor


def handle_smart_shutdown_after_download(text: str, context: Dict[str, Any]) -> ActionResult:
    validated = context.get("_validated_params")
    cfg = SmartShutdownSchema()
    if validated and isinstance(validated, SmartShutdownSchema):
        cfg = validated

    monitor = get_smart_shutdown_monitor()
    snapshot = monitor.snapshot()
    if snapshot.get("running"):
        return ActionResult.ok(
            "Smart shutdown is already monitoring.\n"
            f"- Current rate: {snapshot.get('last_rate_kbps', 0):.0f} KB/s\n"
            f"- Idle seconds: {snapshot.get('idle_seconds', 0)}\n\n"
            "Say: `Cancel smart shutdown` to stop it.",
            snapshot,
            "smart_shutdown_after_download",
        )

    plan = (
        "I will monitor network download activity and shut down the PC once the download is finished.\n"
        f"- Consider download 'active' when rate >= {cfg.active_kbps} KB/s\n"
        f"- Consider download 'done' when rate <= {cfg.idle_kbps} KB/s for {cfg.idle_minutes} minutes\n"
        f"- Sampling every {cfg.sample_seconds} seconds\n"
        f"- Require user idle: {cfg.require_user_idle_seconds} seconds\n"
    )

    def _do() -> ActionResult:
        ok, msg = monitor.start(cfg)
        if ok:
            return ActionResult.ok(
                msg + "\n\nSay: `Cancel smart shutdown` to stop it.",
                monitor.snapshot(),
                "smart_shutdown_after_download",
            )
        return ActionResult.fail(msg, "smart_shutdown_after_download")

    if not context.get("_confirmed"):
        return ActionResult.confirm(plan + "\nProceed?", _do, "smart_shutdown_after_download")
    return _do()


def handle_cancel_smart_shutdown(text: str, context: Dict[str, Any]) -> ActionResult:
    monitor = get_smart_shutdown_monitor()
    ok, msg = monitor.cancel()
    if ok:
        return ActionResult.ok(msg, monitor.snapshot(), "cancel_smart_shutdown")
    return ActionResult.fail(msg, "cancel_smart_shutdown")


def register_smart_shutdown_capabilities(registry) -> None:
    registry.register(
        Capability(
            name="smart_shutdown_after_download",
            triggers=[
                "shut down once the download finishes",
                "shutdown after download",
                "smart shutdown",
                "shut down after download",
                "shutdown when download finishes",
            ],
            handler=handle_smart_shutdown_after_download,
            requires_confirmation=False,  # handler provides confirmation
            description="monitor network traffic and shut down the PC after download finishes",
            capability_type=CapabilityType.SYSTEM,
            examples=[
                "I'm going to sleep. Shut down the PC once the current download finishes.",
            ],
            schema=SmartShutdownSchema,
        )
    )

    registry.register(
        Capability(
            name="cancel_smart_shutdown",
            triggers=["cancel smart shutdown", "stop smart shutdown", "don't shut down"],
            handler=handle_cancel_smart_shutdown,
            requires_confirmation=False,
            description="cancel a pending smart shutdown monitor",
            capability_type=CapabilityType.SYSTEM,
            examples=["Cancel smart shutdown"],
        )
    )
