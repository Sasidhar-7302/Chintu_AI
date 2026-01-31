"""Phone ecosystem capabilities.

Voice commands to control phone: camera, mic, screen, GPS, etc.
"""

import logging
import json
import base64
from typing import Dict, Any, Optional
from pathlib import Path

import requests

from ..core.capabilities import ActionResult

logger = logging.getLogger(__name__)


def get_connected_phone() -> Optional[str]:
    """Get IP of first connected phone."""
    from ..device.mobile_connector import get_mobile_connector
    
    connector = get_mobile_connector()
    devices = [d for d in connector.get_devices() if d.connected]
    
    if devices:
        return devices[0].ip
    return None


def call_phone_api(endpoint: str, method: str = "GET", 
                   data: Dict = None, timeout: int = 30) -> Dict:
    """Call the phone's ecosystem agent API."""
    phone_ip = get_connected_phone()
    
    if not phone_ip:
        return {"error": "No phone connected. Say 'Scan for devices' first."}
    
    url = f"http://{phone_ip}:5050{endpoint}"
    
    try:
        if method == "GET":
            response = requests.get(url, timeout=timeout)
        else:
            response = requests.post(url, json=data or {}, timeout=timeout)
        
        return response.json()
    except requests.exceptions.ConnectionError:
        return {"error": "Phone agent not running. Start it on your phone."}
    except Exception as e:
        return {"error": str(e)}


# ============================================================================
# CAMERA
# ============================================================================

def handle_phone_camera(text: str, context: Dict[str, Any]) -> ActionResult:
    """Take a photo with phone camera.
    
    Examples:
    - "Take a photo with my phone"
    - "Phone camera"
    - "Capture from phone"
    """
    # Determine which camera (front/back)
    camera = 0  # Back camera by default
    if "front" in text.lower() or "selfie" in text.lower():
        camera = 1
    
    result = call_phone_api("/camera/photo", "POST", {"camera": camera})
    
    if "error" in result:
        return ActionResult.fail(result["error"], "phone_camera")
    
    if result.get("success"):
        # Save the image locally
        try:
            image_data = base64.b64decode(result["data"])
            save_path = Path.home() / ".chintu" / "phone_photos" / result["filename"]
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_bytes(image_data)
            
            return ActionResult.ok(
                f"Photo captured! Saved to: {save_path}",
                {"path": str(save_path), "size": result["size"]},
                "phone_camera"
            )
        except Exception as e:
            return ActionResult.fail(f"Photo captured but couldn't save: {e}", "phone_camera")
    
    return ActionResult.fail("Failed to take photo", "phone_camera")


# ============================================================================
# BATTERY
# ============================================================================

def handle_phone_battery(text: str, context: Dict[str, Any]) -> ActionResult:
    """Get phone battery status.
    
    Examples:
    - "What's my phone battery?"
    - "Phone battery status"
    - "How much charge does my phone have?"
    """
    result = call_phone_api("/battery")
    
    if "error" in result:
        return ActionResult.fail(result["error"], "phone_battery")
    
    percentage = result.get("percentage", "?")
    status = result.get("status", "unknown")
    plugged = result.get("plugged", "")
    
    msg = f"Your phone battery is at {percentage}%"
    if status == "CHARGING":
        msg += f" and charging via {plugged}"
    elif status == "FULL":
        msg += " and fully charged"
    
    return ActionResult.ok(msg, result, "phone_battery")


# ============================================================================
# NOTIFICATIONS
# ============================================================================

def handle_phone_notify(text: str, context: Dict[str, Any]) -> ActionResult:
    """Send notification to phone.
    
    Examples:
    - "Notify my phone"
    - "Send notification to phone"
    - "Alert my phone"
    """
    import re
    
    # Extract message if provided
    match = re.search(r"(?:notify|alert|tell)\s+(?:my\s+)?phone\s+(?:that\s+)?(.+)", text.lower())
    message = match.group(1) if match else "Hello from Chintu!"
    
    result = call_phone_api("/display/notification", "POST", {
        "title": "Chintu",
        "content": message
    })
    
    if "error" in result:
        return ActionResult.fail(result["error"], "phone_notify")
    
    return ActionResult.ok(
        f"Notification sent to your phone: '{message}'",
        {"message": message},
        "phone_notify"
    )


# ============================================================================
# TTS (SPEAK ON PHONE)
# ============================================================================

def handle_phone_speak(text: str, context: Dict[str, Any]) -> ActionResult:
    """Speak text on phone.
    
    Examples:
    - "Say hello on my phone"
    - "Speak on phone: Good morning"
    - "Phone say something"
    """
    import re
    
    # Extract what to say
    patterns = [
        r"(?:say|speak)\s+(?:on\s+)?(?:my\s+)?phone[:\s]+(.+)",
        r"phone\s+(?:say|speak)[:\s]+(.+)",
        r"(?:say|speak)\s+(.+)\s+on\s+(?:my\s+)?phone",
    ]
    
    message = None
    for pattern in patterns:
        match = re.search(pattern, text.lower())
        if match:
            message = match.group(1)
            break
    
    if not message:
        message = "Hello from Chintu!"
    
    result = call_phone_api("/speak", "POST", {"text": message})
    
    if "error" in result:
        return ActionResult.fail(result["error"], "phone_speak")
    
    return ActionResult.ok(
        f"Speaking on your phone: '{message}'",
        {"text": message},
        "phone_speak"
    )


# ============================================================================
# LOCATION
# ============================================================================

def handle_phone_location(text: str, context: Dict[str, Any]) -> ActionResult:
    """Get phone location.
    
    Examples:
    - "Where is my phone?"
    - "Phone location"
    - "Find my phone"
    """
    result = call_phone_api("/location", timeout=35)
    
    if "error" in result:
        return ActionResult.fail(result["error"], "phone_location")
    
    lat = result.get("latitude")
    lon = result.get("longitude")
    
    if lat and lon:
        maps_url = f"https://www.google.com/maps?q={lat},{lon}"
        return ActionResult.ok(
            f"Your phone is at coordinates: {lat}, {lon}\nMaps: {maps_url}",
            {"latitude": lat, "longitude": lon, "maps_url": maps_url},
            "phone_location"
        )
    
    return ActionResult.fail("Couldn't get location. Make sure GPS is enabled.", "phone_location")


# ============================================================================
# VIBRATE
# ============================================================================

def handle_phone_vibrate(text: str, context: Dict[str, Any]) -> ActionResult:
    """Vibrate the phone.
    
    Examples:
    - "Vibrate my phone"
    - "Make my phone vibrate"
    - "Ring my phone"
    """
    result = call_phone_api("/vibrate", "POST", {"duration": 1000})
    
    if "error" in result:
        return ActionResult.fail(result["error"], "phone_vibrate")
    
    return ActionResult.ok(
        "Vibrating your phone!",
        {},
        "phone_vibrate"
    )


# ============================================================================
# SHOW ON PHONE SCREEN
# ============================================================================

def handle_show_on_phone(text: str, context: Dict[str, Any]) -> ActionResult:
    """Show message on phone screen.
    
    Examples:
    - "Show hello on my phone"
    - "Display this on phone"
    """
    import re
    
    # Extract message
    match = re.search(r"(?:show|display)\s+(.+?)\s+on\s+(?:my\s+)?phone", text.lower())
    message = match.group(1) if match else "Hello from Chintu!"
    
    result = call_phone_api("/display/toast", "POST", {"message": message})
    
    if "error" in result:
        return ActionResult.fail(result["error"], "show_on_phone")
    
    return ActionResult.ok(
        f"Showing on phone: '{message}'",
        {"message": message},
        "show_on_phone"
    )


# ============================================================================
# OPEN URL/BROWSER ON PHONE
# ============================================================================

def handle_phone_browser(text: str, context: Dict[str, Any]) -> ActionResult:
    """Open a URL or website on phone.
    
    Examples:
    - "Open YouTube on my phone"
    - "Open google.com on phone"
    - "Phone open Chrome"
    """
    import re
    
    # Common websites
    WEBSITES = {
        "youtube": "https://youtube.com",
        "google": "https://google.com",
        "gmail": "https://mail.google.com",
        "facebook": "https://facebook.com",
        "instagram": "https://instagram.com",
        "twitter": "https://twitter.com",
        "whatsapp": "https://web.whatsapp.com",
        "amazon": "https://amazon.com",
        "netflix": "https://netflix.com",
        "reddit": "https://reddit.com",
        "linkedin": "https://linkedin.com",
        "github": "https://github.com",
    }
    
    text_lower = text.lower()
    
    # Find the target
    patterns = [
        r"open\s+(.+?)\s+on\s+(?:my\s+)?phone",
        r"phone\s+open\s+(.+)",
        r"browse\s+(.+?)\s+on\s+phone",
    ]
    
    target = None
    for pattern in patterns:
        match = re.search(pattern, text_lower)
        if match:
            target = match.group(1).strip()
            break
    
    if not target:
        target = "google"
    
    # Convert to URL
    if target in WEBSITES:
        url = WEBSITES[target]
    elif "." in target:
        url = target if target.startswith("http") else f"https://{target}"
    else:
        url = WEBSITES.get(target, f"https://www.google.com/search?q={target}")
    
    result = call_phone_api("/browser/open", "POST", {"url": url})
    
    if "error" in result:
        return ActionResult.fail(result["error"], "phone_browser")
    
    return ActionResult.ok(
        f"Opening {target} on your phone browser!",
        {"url": url, "target": target},
        "phone_browser"
    )


# ============================================================================
# REGISTRATION
# ============================================================================

def register_phone_capabilities():
    """Register all phone ecosystem capabilities."""
    from ..core.capabilities import CapabilityRegistry
    
    registry = CapabilityRegistry.get_instance()
    
    # Camera
    registry.register(
        name="phone_camera",
        handler=handle_phone_camera,
        patterns=[
            r"(?:take|capture)\s+(?:a\s+)?photo\s+(?:with|from|on)\s+(?:my\s+)?phone",
            r"phone\s+camera",
            r"(?:take|snap)\s+(?:a\s+)?(?:phone\s+)?(?:photo|picture|selfie)",
        ],
        description="Take a photo with phone camera",
        examples=["Take a photo with my phone", "Phone camera"],
        risk_level="low"
    )
    
    # Battery
    registry.register(
        name="phone_battery",
        handler=handle_phone_battery,
        patterns=[
            r"(?:what(?:'s|\s+is)\s+)?(?:my\s+)?phone\s+battery",
            r"(?:how\s+much\s+)?phone\s+(?:battery|charge|power)",
            r"phone\s+power\s+level",
        ],
        description="Get phone battery status",
        examples=["What's my phone battery?", "Phone battery"],
        risk_level="low"
    )
    
    # Notification
    registry.register(
        name="phone_notify",
        handler=handle_phone_notify,
        patterns=[
            r"(?:send\s+)?notif(?:y|ication)\s+(?:to\s+)?(?:my\s+)?phone",
            r"alert\s+(?:my\s+)?phone",
            r"tell\s+(?:my\s+)?phone",
        ],
        description="Send notification to phone",
        examples=["Notify my phone", "Send notification to phone"],
        risk_level="low"
    )
    
    # Speak
    registry.register(
        name="phone_speak",
        handler=handle_phone_speak,
        patterns=[
            r"(?:say|speak)\s+(?:.+\s+)?on\s+(?:my\s+)?phone",
            r"phone\s+(?:say|speak)",
        ],
        description="Speak text on phone",
        examples=["Say hello on my phone", "Phone say good morning"],
        risk_level="low"
    )
    
    # Location
    registry.register(
        name="phone_location",
        handler=handle_phone_location,
        patterns=[
            r"(?:where\s+is|find|locate)\s+(?:my\s+)?phone",
            r"phone\s+location",
            r"(?:my\s+)?phone(?:'s)?\s+(?:location|gps)",
        ],
        description="Get phone GPS location",
        examples=["Where is my phone?", "Phone location"],
        risk_level="low"
    )
    
    # Vibrate
    registry.register(
        name="phone_vibrate",
        handler=handle_phone_vibrate,
        patterns=[
            r"(?:make\s+)?(?:my\s+)?phone\s+vibrat",
            r"vibrat\s+(?:my\s+)?phone",
            r"ring\s+(?:my\s+)?phone",
        ],
        description="Vibrate the phone",
        examples=["Vibrate my phone", "Ring my phone"],
        risk_level="low"
    )
    
    # Show on screen
    registry.register(
        name="show_on_phone",
        handler=handle_show_on_phone,
        patterns=[
            r"(?:show|display)\s+.+\s+on\s+(?:my\s+)?phone",
            r"phone\s+(?:show|display)",
        ],
        description="Show message on phone screen",
        examples=["Show hello on my phone", "Display this on phone"],
        risk_level="low"
    )
    
    # Open URL/Browser
    registry.register(
        name="phone_browser",
        handler=handle_phone_browser,
        patterns=[
            r"open\s+.+\s+on\s+(?:my\s+)?phone",
            r"phone\s+open\s+.+",
            r"browse\s+.+\s+on\s+phone",
        ],
        description="Open URL on phone browser",
        examples=["Open YouTube on my phone", "Open google.com on phone"],
        risk_level="low"
    )
    
    logger.info("Registered phone ecosystem capabilities")
