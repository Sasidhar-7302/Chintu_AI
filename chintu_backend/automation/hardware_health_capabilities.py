"""Hardware health snapshot (temps + CPU hogs).

Notes:
- GPU temperature/utilization are read via nvidia-smi when available.
- CPU temperature is not reliably available on Windows without extra sensor
  tooling; we attempt a best-effort WMI read and otherwise omit it.
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


class HardwareHealthSchema(BaseModel):
    top_processes: int = Field(5, ge=1, le=15, description="How many top CPU processes to show.")
    cpu_hog_threshold: int = Field(30, ge=5, le=95, description="Percent CPU to consider a hog.")


def _run_nvidia_smi() -> List[Dict[str, Any]]:
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
    except Exception:
        return []
    if proc.returncode != 0:
        return []
    rows = []
    for line in (proc.stdout or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5:
            continue
        name = parts[0]
        try:
            temp = int(float(parts[1]))
        except Exception:
            temp = None
        try:
            util = int(float(parts[2]))
        except Exception:
            util = None
        try:
            mem_used = int(float(parts[3]))
        except Exception:
            mem_used = None
        try:
            mem_total = int(float(parts[4]))
        except Exception:
            mem_total = None
        rows.append(
            {
                "name": name,
                "temp_c": temp,
                "util_percent": util,
                "mem_used_mb": mem_used,
                "mem_total_mb": mem_total,
            }
        )
    return rows


def _cpu_temp_wmi() -> Optional[float]:
    """Best-effort temperature read. Often returns nothing on desktops."""
    try:
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-WmiObject MSAcpi_ThermalZoneTemperature | "
                "Select-Object -ExpandProperty CurrentTemperature",
            ],
            capture_output=True,
            text=True,
            timeout=2.5,
            check=False,
        )
        if proc.returncode != 0:
            return None
        raw = (proc.stdout or "").strip().splitlines()
        if not raw:
            return None
        # WMI reports in tenths of Kelvin
        values = []
        for ln in raw:
            try:
                values.append(float(ln.strip()))
            except Exception:
                continue
        if not values:
            return None
        k_tenths = max(values)
        c = (k_tenths / 10.0) - 273.15
        if 0.0 < c < 120.0:
            return float(round(c, 1))
        return None
    except Exception:
        return None


def _top_cpu_processes(n: int) -> List[Dict[str, Any]]:
    # Prime cpu_percent counters
    for proc in psutil.process_iter(attrs=["pid", "name"]):
        try:
            proc.cpu_percent(interval=None)
        except Exception:
            continue
    time.sleep(0.35)

    procs: List[Dict[str, Any]] = []
    for proc in psutil.process_iter(attrs=["pid", "name"]):
        try:
            cpu = proc.cpu_percent(interval=None)
            mem = proc.memory_percent()
            name = proc.info.get("name") or ""
            if cpu is None:
                continue
            procs.append({"pid": proc.pid, "name": name, "cpu_percent": float(cpu), "mem_percent": float(mem)})
        except Exception:
            continue

    procs.sort(key=lambda p: p.get("cpu_percent", 0.0), reverse=True)
    return procs[: max(1, int(n))]


def handle_hardware_health(text: str, context: Dict[str, Any]) -> ActionResult:
    validated = context.get("_validated_params")
    top_n = 5
    threshold = 30
    if validated and isinstance(validated, HardwareHealthSchema):
        top_n = int(validated.top_processes)
        threshold = int(validated.cpu_hog_threshold)

    cpu_percent = psutil.cpu_percent(interval=0.4)
    vm = psutil.virtual_memory()

    gpu_rows = _run_nvidia_smi()
    cpu_temp = _cpu_temp_wmi()
    top = _top_cpu_processes(top_n)

    hogs = [p for p in top if float(p.get("cpu_percent") or 0.0) >= float(threshold)]

    lines = ["System health snapshot:"]
    lines.append(f"- CPU: {cpu_percent:.0f}%")
    if cpu_temp is not None:
        lines.append(f"- CPU temp (WMI): {cpu_temp:.1f} C")
    lines.append(f"- RAM: {vm.percent:.0f}% ({vm.used/ (1024**3):.1f} GB / {vm.total/ (1024**3):.1f} GB)")

    if gpu_rows:
        for i, g in enumerate(gpu_rows, start=1):
            temp = g.get("temp_c")
            util = g.get("util_percent")
            mem_used = g.get("mem_used_mb")
            mem_total = g.get("mem_total_mb")
            lines.append(
                f"- GPU{i}: {g.get('name')} | util={util}% temp={temp}C mem={mem_used}/{mem_total} MB"
            )
    else:
        lines.append("- GPU: nvidia-smi not available (or no NVIDIA GPU detected).")

    lines.append("")
    lines.append(f"Top CPU processes (sample):")
    for p in top:
        lines.append(
            f"- {p.get('name')} (pid {p.get('pid')}): {p.get('cpu_percent'):.0f}% CPU, {p.get('mem_percent'):.1f}% RAM"
        )

    if hogs:
        lines.append("")
        lines.append(f"Hogs (>= {threshold}% CPU):")
        for p in hogs:
            lines.append(f"- {p.get('name')} (pid {p.get('pid')})")
        lines.append("")
        lines.append("If you want, say: `Kill <process>` (I will ask for confirmation).")

    data = {"cpu_percent": cpu_percent, "cpu_temp_c": cpu_temp, "ram": {"percent": vm.percent}, "gpu": gpu_rows, "top_processes": top}
    return ActionResult.ok("\n".join(lines).strip(), data, "hardware_health")


def register_hardware_health_capabilities(registry) -> None:
    registry.register(
        Capability(
            name="hardware_health",
            triggers=[
                "how are my temps",
                "is anything hogging the cpu",
                "hardware health",
                "system health",
                "cpu hog",
                "check my temps",
            ],
            handler=handle_hardware_health,
            requires_confirmation=False,
            description="show CPU/RAM/GPU utilization + temperature (best-effort) and top CPU processes",
            capability_type=CapabilityType.SYSTEM,
            examples=[
                "How are my temps? Is anything hogging the CPU?",
                "Hardware health check",
            ],
            schema=HardwareHealthSchema,
        )
    )

