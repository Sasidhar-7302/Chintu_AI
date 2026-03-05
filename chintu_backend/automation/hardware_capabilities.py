"""
Hardware Capabilities
---------------------
Provides access to detailed system hardware specifications using WMI/PowerShell.
Useful for checking compatibility, upgrades, and troubleshooting.
"""

import logging
import subprocess
import json
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from chintu_backend.core.capabilities import Capability, CapabilityType, get_registry

logger = logging.getLogger(__name__)

# ============================================================================
# SCHEMAS
# ============================================================================

class SystemSpecsSchema(BaseModel):
    component: Optional[str] = Field(None, description="Specific component to check (cpu, gpu, ram, os, motherboard).")

def run_powershell(command: str) -> str:
    """Run a PowerShell command and return output."""
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            startupinfo=startupinfo,
            timeout=10
        )
        return result.stdout.strip()
    except Exception as e:
        logger.error(f"PowerShell command failed: {e}")
        return ""

def _handle_get_system_specs(text: str, context: Dict[str, Any] = None) -> str:
    """
    Retrieves detailed hardware info.
    Supports filtering by component if schema is used.
    """
    from chintu_backend.core.capabilities import ActionResult
    
    target_component = None
    validated = context.get("_validated_params")
    if validated and isinstance(validated, SystemSpecsSchema):
        target_component = validated.component.lower() if validated.component else None
    
    logger.info(f"Scanning system hardware specs (Target: {target_component})...")
    
    specs = []
    
    # helper to check if we should fetch this component
    def should_fetch(comp_name):
        if not target_component: return True
        return comp_name in target_component or target_component in comp_name
    
    # 1. CPU
    if should_fetch("cpu") or should_fetch("processor"):
        cpu = run_powershell("Get-CimInstance Win32_Processor | Select-Object -ExpandProperty Name")
        if cpu:
            specs.append(f"**CPU:** {cpu.strip()}")
        
    # 2. GPU (Video Controller)
    if should_fetch("gpu") or should_fetch("graphics") or should_fetch("video"):
        gpu = run_powershell("Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name")
        if gpu:
            # Handle multiple GPUs (e.g. iGPU + dGPU)
            gpus = [g.strip() for g in gpu.split('\n') if g.strip()]
            specs.append(f"**GPU:** {', '.join(gpus)}")
        
    # 3. RAM
    if should_fetch("ram") or should_fetch("memory"):
        try:
            ram_capacity = run_powershell("Get-CimInstance Win32_PhysicalMemory | Measure-Object -Property Capacity -Sum | Select-Object -ExpandProperty Sum")
            ram_gb = round(int(ram_capacity) / (1024**3), 1)
            
            ram_speed = run_powershell("Get-CimInstance Win32_PhysicalMemory | Select-Object -First 1 -ExpandProperty Speed")
            specs.append(f"**RAM:** {ram_gb} GB ({ram_speed} MHz)")
        except Exception:
            specs.append("**RAM:** Unknown")

    # 4. Motherboard
    if should_fetch("motherboard") or should_fetch("board"):
        board_maker = run_powershell("Get-CimInstance Win32_BaseBoard | Select-Object -ExpandProperty Manufacturer")
        board_product = run_powershell("Get-CimInstance Win32_BaseBoard | Select-Object -ExpandProperty Product")
        if board_maker and board_product:
            specs.append(f"**Motherboard:** {board_maker.strip()} {board_product.strip()}")
        
    # 5. OS
    if should_fetch("os") or should_fetch("operating system") or should_fetch("windows"):
        os_name = run_powershell("Get-CimInstance Win32_OperatingSystem | Select-Object -ExpandProperty Caption")
        if os_name:
            specs.append(f"**OS:** {os_name.strip()}")

    if not specs:
        return ActionResult.fail("I couldn't retrieve the hardware specifications (or specific component not found).")

    result_text = "Here are your detected system specifications:\n\n" + "\n".join(specs)
    return ActionResult.ok(result_text)

def register_hardware_capabilities() -> None:
    """Register hardware capabilities."""
    registry = get_registry()
    
    registry.register(Capability(
        name="get_system_specs",
        triggers=["pc specs", "hardware info", "my components", "computer specs", "system specs", "my pc hardware"],
        handler=_handle_get_system_specs,
        description="Scan and report detailed PC hardware specifications (CPU, GPU, RAM, Motherboard).",
        capability_type=CapabilityType.SYSTEM,
        schema=SystemSpecsSchema
    ))

