"""Dual-GPU resource manager for local-first task scheduling.

Provides:
- Inventory snapshot from nvidia-smi (multi-GPU aware)
- Role-based GPU selection hints (brain vs background/sanitizer)
- Step-level telemetry helpers (before/after/delta)
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from .config import get_config

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GPUDevice:
    index: int
    name: str
    total_mb: int
    used_mb: int
    util_percent: float
    temp_c: float

    @property
    def free_mb(self) -> int:
        return max(0, int(self.total_mb) - int(self.used_mb))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": int(self.index),
            "name": self.name,
            "total_mb": int(self.total_mb),
            "used_mb": int(self.used_mb),
            "free_mb": int(self.free_mb),
            "util_percent": float(self.util_percent),
            "temp_c": float(self.temp_c),
        }


@dataclass(frozen=True)
class GPUSelection:
    role: str
    gpu_id: Optional[int]
    reason: str
    allow_cpu_fallback: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "gpu_id": self.gpu_id,
            "reason": self.reason,
            "allow_cpu_fallback": bool(self.allow_cpu_fallback),
        }


CommandRunner = Callable[[List[str], int], Tuple[int, str, str]]


class GPUResourceManager:
    """Resource hints + telemetry for dual-GPU systems."""

    def __init__(self, config=None, runner: Optional[CommandRunner] = None) -> None:
        self.config = config or get_config()
        self._runner = runner or self._default_runner

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def inventory(self) -> List[GPUDevice]:
        rc, out, _err = self._runner(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total,memory.used,utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            2,
        )
        if rc != 0:
            return []

        devices: List[GPUDevice] = []
        for line in (out or "").splitlines():
            row = [part.strip() for part in line.split(",")]
            if len(row) < 6:
                continue
            try:
                device = GPUDevice(
                    index=int(float(row[0])),
                    name=str(row[1] or "").strip(),
                    total_mb=max(0, int(float(row[2]))),
                    used_mb=max(0, int(float(row[3]))),
                    util_percent=max(0.0, float(row[4])),
                    temp_c=max(0.0, float(row[5])),
                )
            except Exception:
                continue
            devices.append(device)
        return devices

    def capture_snapshot(self) -> Dict[str, Dict[str, Any]]:
        devices = self.inventory()
        return {str(dev.index): dev.to_dict() for dev in devices}

    def choose_for_role(
        self,
        *,
        role: str,
        max_vram_mb: int = 0,
        allow_cpu_fallback: Optional[bool] = None,
    ) -> GPUSelection:
        devices = self.inventory()
        if not devices:
            return GPUSelection(
                role=str(role or "brain"),
                gpu_id=None,
                reason="no_gpu_detected",
                allow_cpu_fallback=True if allow_cpu_fallback is None else bool(allow_cpu_fallback),
            )

        role_name = str(role or "brain").strip().lower()
        primary_id, secondary_id = self._resolve_primary_secondary(devices)
        allow_cpu = bool(
            getattr(self.config, "gpu_default_allow_cpu_fallback", True)
            if allow_cpu_fallback is None
            else allow_cpu_fallback
        )

        if role_name in {"background", "sanitizer", "embedding", "verifier"}:
            order = [secondary_id, primary_id]
        else:
            order = [primary_id, secondary_id]
        order = [idx for idx in order if idx is not None]

        by_id = {dev.index: dev for dev in devices}
        need_mb = max(0, int(max_vram_mb or 0))
        reserve_primary = int(getattr(self.config, "gpu_primary_reserved_vram_mb", 2048) or 0)
        reserve_secondary = int(getattr(self.config, "gpu_secondary_reserved_vram_mb", 1024) or 0)

        for idx in order:
            dev = by_id.get(idx)
            if not dev:
                continue
            reserve = reserve_primary if idx == primary_id else reserve_secondary
            free_budget = max(0, dev.free_mb - reserve)
            if free_budget >= need_mb:
                reason = f"selected_gpu_{idx}_free_budget_mb={free_budget}"
                return GPUSelection(role=role_name, gpu_id=idx, reason=reason, allow_cpu_fallback=allow_cpu)

        if allow_cpu:
            return GPUSelection(
                role=role_name,
                gpu_id=None,
                reason="gpu_budget_insufficient_cpu_fallback",
                allow_cpu_fallback=True,
            )
        return GPUSelection(
            role=role_name,
            gpu_id=order[0] if order else None,
            reason="gpu_budget_insufficient_forced_gpu",
            allow_cpu_fallback=False,
        )

    def role_for_capability(self, capability_name: str) -> str:
        name = str(capability_name or "").strip().lower()
        if not name:
            return "brain"
        if any(token in name for token in ("browser", "vision", "screenshot", "page_content", "search")):
            return "sanitizer"
        if any(token in name for token in ("embedding", "memory", "verify", "verification")):
            return "background"
        return "brain"

    def estimate_vram_need_mb(self, capability_name: str) -> int:
        name = str(capability_name or "").strip().lower()
        if any(token in name for token in ("browser_pilot", "research", "creative", "chat")):
            return 4096
        if any(token in name for token in ("vision", "embedding", "verification", "memory")):
            return 1024
        return 2048

    def build_step_meta(self, capability_name: str, before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
        role = self.role_for_capability(capability_name)
        need = self.estimate_vram_need_mb(capability_name)
        selection = self.choose_for_role(role=role, max_vram_mb=need)
        delta = self.usage_delta(before, after)
        return {
            "role": role,
            "estimated_need_mb": int(need),
            "selection": selection.to_dict(),
            "before": before,
            "after": after,
            "delta_mb": delta,
        }

    @staticmethod
    def usage_delta(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, int]:
        delta: Dict[str, int] = {}
        keys = sorted(set((before or {}).keys()) | set((after or {}).keys()))
        for key in keys:
            try:
                b = int(((before or {}).get(key) or {}).get("used_mb") or 0)
                a = int(((after or {}).get(key) or {}).get("used_mb") or 0)
                delta[str(key)] = int(a - b)
            except Exception:
                continue
        return delta

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _resolve_primary_secondary(self, devices: List[GPUDevice]) -> Tuple[Optional[int], Optional[int]]:
        if not devices:
            return None, None
        by_vram = sorted(devices, key=lambda dev: (dev.total_mb, -dev.index), reverse=True)

        configured_primary = int(getattr(self.config, "gpu_primary_device_id", -1) or -1)
        configured_secondary = int(getattr(self.config, "gpu_secondary_device_id", -1) or -1)
        valid_ids = {dev.index for dev in devices}

        primary_id: Optional[int] = configured_primary if configured_primary in valid_ids else by_vram[0].index
        secondary_id: Optional[int] = None
        if configured_secondary in valid_ids and configured_secondary != primary_id:
            secondary_id = configured_secondary
        else:
            for dev in by_vram:
                if dev.index != primary_id:
                    secondary_id = dev.index
                    break
        return primary_id, secondary_id

    @staticmethod
    def _default_runner(command: List[str], timeout_s: int) -> Tuple[int, str, str]:
        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=max(1, int(timeout_s)),
                shell=False,
                check=False,
            )
            return int(proc.returncode), str(proc.stdout or ""), str(proc.stderr or "")
        except Exception as exc:
            logger.debug("GPU command failed: %s", exc)
            return 1, "", str(exc)


_gpu_resource_manager: Optional[GPUResourceManager] = None


def get_gpu_resource_manager(config=None) -> GPUResourceManager:
    global _gpu_resource_manager
    if _gpu_resource_manager is None:
        _gpu_resource_manager = GPUResourceManager(config=config)
    return _gpu_resource_manager
