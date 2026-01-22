"""Mobile device management capabilities.

Voice commands for connecting and managing mobile devices.
"""

import logging
from typing import Dict, Any

from ..core.capabilities import ActionResult

logger = logging.getLogger(__name__)


def handle_scan_devices(text: str, context: Dict[str, Any]) -> ActionResult:
    """Scan network for mobile devices with Termux.
    
    Examples:
    - "Scan for devices"
    - "Find my phone"
    - "Look for mobile devices"
    """
    from .mobile_connector import get_mobile_connector
    
    connector = get_mobile_connector()
    
    try:
        devices = connector.scan_network(timeout=0.5)
        
        if not devices:
            return ActionResult.ok(
                "No devices with Termux SSH found on the network. "
                "Make sure your phone has Termux installed and SSH running (sshd command).",
                {"devices": []},
                "scan_devices"
            )
        
        device_list = [f"• {d.ip}" for d in devices]
        return ActionResult.ok(
            f"Found {len(devices)} device(s) with SSH:\n" + "\n".join(device_list) + 
            "\n\nSay 'Connect to [IP]' to connect.",
            {"devices": [d.ip for d in devices]},
            "scan_devices"
        )
        
    except Exception as e:
        logger.error(f"Network scan failed: {e}")
        return ActionResult.fail(
            f"Network scan failed: {str(e)}",
            "scan_devices"
        )


def handle_connect_device(text: str, context: Dict[str, Any]) -> ActionResult:
    """Connect to a mobile device.
    
    Examples:
    - "Connect to my phone"
    - "Connect to 192.168.1.100"
    """
    import re
    from .mobile_connector import get_mobile_connector, PARAMIKO_AVAILABLE
    
    if not PARAMIKO_AVAILABLE:
        return ActionResult.fail(
            "SSH support requires paramiko. Run: pip install paramiko",
            "connect_device"
        )
    
    # Extract IP from text
    ip_match = re.search(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', text)
    
    if not ip_match:
        # No IP specified, prompt for it
        return ActionResult.ok(
            "Please specify the device IP address, or say 'Scan for devices' first. "
            "Then say 'Connect to [IP address]'.",
            {"needs_ip": True},
            "connect_device"
        )
    
    ip = ip_match.group(1)
    
    # For security, we need credentials from the UI, not voice
    return ActionResult.ok(
        f"To connect to {ip}, please enter your Termux username and password in the Devices settings. "
        "For security, credentials should be entered via the UI, not spoken aloud.",
        {"ip": ip, "needs_credentials": True},
        "connect_device"
    )


def handle_device_status(text: str, context: Dict[str, Any]) -> ActionResult:
    """Get status of connected devices.
    
    Examples:
    - "What devices are connected?"
    - "Show connected devices"
    - "Device status"
    """
    from .mobile_connector import get_mobile_connector
    
    connector = get_mobile_connector()
    devices = connector.get_devices()
    
    connected = [d for d in devices if d.connected]
    
    if not connected:
        return ActionResult.ok(
            "No devices connected. Say 'Scan for devices' to find nearby phones.",
            {"connected_count": 0},
            "device_status"
        )
    
    status_list = []
    for d in connected:
        agent_status = "🟢 Agent running" if d.agent_running else "🔴 Agent stopped"
        status_list.append(f"• {d.device_name or d.ip} ({d.android_version}) - {agent_status}")
    
    return ActionResult.ok(
        f"{len(connected)} device(s) connected:\n" + "\n".join(status_list),
        {"connected_count": len(connected), "devices": [d.ip for d in connected]},
        "device_status"
    )


def handle_disconnect_device(text: str, context: Dict[str, Any]) -> ActionResult:
    """Disconnect from a mobile device.
    
    Examples:
    - "Disconnect my phone"
    - "Disconnect from 192.168.1.100"
    """
    import re
    from .mobile_connector import get_mobile_connector
    
    connector = get_mobile_connector()
    devices = connector.get_devices()
    connected = [d for d in devices if d.connected]
    
    if not connected:
        return ActionResult.ok(
            "No devices are connected.",
            {},
            "disconnect_device"
        )
    
    # If only one device, disconnect it
    if len(connected) == 1:
        device = connected[0]
        connector.disconnect(device.ip)
        return ActionResult.ok(
            f"Disconnected from {device.device_name or device.ip}",
            {"ip": device.ip},
            "disconnect_device"
        )
    
    # Multiple devices - need to specify
    ip_match = re.search(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', text)
    if ip_match:
        ip = ip_match.group(1)
        connector.disconnect(ip)
        return ActionResult.ok(
            f"Disconnected from {ip}",
            {"ip": ip},
            "disconnect_device"
        )
    
    device_list = [f"• {d.ip} ({d.device_name})" for d in connected]
    return ActionResult.ok(
        f"Multiple devices connected. Please specify which one:\n" + "\n".join(device_list),
        {"devices": [d.ip for d in connected]},
        "disconnect_device"
    )


def register_mobile_capabilities():
    """Register mobile device capabilities."""
    from ..core.capabilities import CapabilityRegistry
    
    registry = CapabilityRegistry.get_instance()
    
    # Scan for devices
    registry.register(
        name="scan_devices",
        handler=handle_scan_devices,
        patterns=[
            r"scan\s+(?:for\s+)?devices?",
            r"find\s+(?:my\s+)?(?:phone|mobile|devices?)",
            r"look\s+for\s+(?:mobile\s+)?devices?",
            r"search\s+(?:for\s+)?(?:phone|devices?)",
            r"discover\s+devices?",
        ],
        description="Scan network for mobile devices with Termux",
        examples=[
            "Scan for devices",
            "Find my phone",
        ],
        risk_level="low"
    )
    
    # Connect to device
    registry.register(
        name="connect_device",
        handler=handle_connect_device,
        patterns=[
            r"connect\s+(?:to\s+)?(?:my\s+)?(?:phone|device|mobile)",
            r"connect\s+(?:to\s+)?\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}",
            r"pair\s+(?:with\s+)?(?:my\s+)?(?:phone|device)",
        ],
        description="Connect to a mobile device via SSH",
        examples=[
            "Connect to my phone",
            "Connect to 192.168.1.100",
        ],
        risk_level="medium"
    )
    
    # Device status
    registry.register(
        name="device_status",
        handler=handle_device_status,
        patterns=[
            r"(?:what|which)\s+devices?\s+(?:are\s+)?connected",
            r"show\s+(?:connected\s+)?devices?",
            r"device\s+status",
            r"list\s+(?:connected\s+)?devices?",
        ],
        description="Show connected device status",
        examples=[
            "What devices are connected?",
            "Device status",
        ],
        risk_level="low"
    )
    
    # Disconnect
    registry.register(
        name="disconnect_device",
        handler=handle_disconnect_device,
        patterns=[
            r"disconnect\s+(?:from\s+)?(?:my\s+)?(?:phone|device)",
            r"disconnect\s+(?:from\s+)?\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}",
            r"unpair\s+(?:my\s+)?(?:phone|device)",
        ],
        description="Disconnect from a mobile device",
        examples=[
            "Disconnect my phone",
            "Disconnect from device",
        ],
        risk_level="low"
    )
    
    logger.info("Registered mobile device capabilities")
