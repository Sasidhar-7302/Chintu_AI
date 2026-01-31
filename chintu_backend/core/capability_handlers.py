"""
Core capability handlers for Chintu Assistant.
All OS actions go through these handlers, not directly through LLM.
"""

import os
import re
import logging
import subprocess
import datetime
import webbrowser
from typing import Dict, Any, Optional
from pathlib import Path

from .capabilities import (
    Capability, CapabilityType, ActionResult, 
    get_registry
)
from .model_router import Intent, TaskComplexity

logger = logging.getLogger(__name__)


def _send_ui_to_back():
    """Helper to send UI to back when opening apps/websites."""
    try:
        from .websocket_server import get_ws_server
        ws = get_ws_server()
        if ws:
            ws.send_ui_to_back()
    except Exception:
        pass  # Silently fail if WebSocket not available


# ============================================================================
# SYSTEM CAPABILITIES
# ============================================================================

def handle_open_app(text: str, context: Dict[str, Any]) -> ActionResult:
    """Open an application, website, or search Google - with smart routing.
    
    Priority:
    1. Known local apps (with fuzzy matching)
    2. Known websites (YouTube, Gmail, etc.)
    3. Offer to search Google for unknown items
    """
    from ..brain.memory.preferences import get_preference_manager
    from ..automation.platform.app_discovery import get_app_discovery
    from .state import get_state_manager
    import webbrowser
    
    prefs = get_preference_manager().preferences
    app_discovery = get_app_discovery()
    
    # Check if this is a close command routed here (from model_router)
    if context.get("action") == "close":
        return handle_control_window(text, context)
    
    # Known websites - maps to URLs
    KNOWN_WEBSITES = {
        "youtube": "https://youtube.com",
        "gmail": "https://mail.google.com",
        "google": "https://google.com",
        "google drive": "https://drive.google.com",
        "google docs": "https://docs.google.com",
        "google sheets": "https://sheets.google.com",
        "google maps": "https://maps.google.com",
        "google photos": "https://photos.google.com",
        "facebook": "https://facebook.com",
        "twitter": "https://twitter.com",
        "x": "https://twitter.com",
        "instagram": "https://instagram.com",
        "linkedin": "https://linkedin.com",
        "github": "https://github.com",
        "reddit": "https://reddit.com",
        "whatsapp web": "https://web.whatsapp.com",
        "netflix": "https://netflix.com",
        "amazon": "https://amazon.com",
        "flipkart": "https://flipkart.com",
        "wikipedia": "https://wikipedia.org",
        "stackoverflow": "https://stackoverflow.com",
        "stack overflow": "https://stackoverflow.com",
        "chatgpt": "https://chat.openai.com",
        "claude": "https://claude.ai",
        "pinterest": "https://pinterest.com",
        "twitch": "https://twitch.tv",
        "spotify web": "https://open.spotify.com",
        "gmail": "https://mail.google.com",
        "outlook web": "https://outlook.live.com",
        "hotmail": "https://outlook.live.com",
        "yahoo": "https://yahoo.com",
        "ebay": "https://ebay.com",
    }
    
    # STT corrections for Indian accent and common mishearings
    STT_CORRECTIONS = {
        # Chrome
        "cloth": "chrome", "crome": "chrome", "chrom": "chrome", "ground": "chrome",
        "grown": "chrome", "krome": "chrome", "crown": "chrome", "crumb": "chrome",
        "groomed": "chrome", "brome": "chrome", "crawm": "chrome", "groom": "chrome",
        # Calculator
        "call": "calculator", "caliclaker": "calculator", "calclaker": "calculator",
        "calculaker": "calculator", "calq": "calculator", "calcular": "calculator",
        "calculate": "calculator", "calculater": "calculator", "calcul": "calculator",
        "calkulator": "calculator", "calculat": "calculator", "calekulator": "calculator",
        "calc later": "calculator", "kelly later": "calculator", "kelly lator": "calculator",
        # Notepad
        "note": "notepad", "notpad": "notepad", "note pad": "notepad",
        "notepadd": "notepad", "note that": "notepad", "not bad": "notepad",
        "notebad": "notepad", "note book": "notepad", "know pad": "notepad", "not pad": "notepad",
        # Firefox
        "firedox": "firefox", "fire fox": "firefox", "firefax": "firefox", "fire fax": "firefox",
        # Edge
        "edg": "edge", "etch": "edge", "hedge": "edge", "age": "edge",
        # Explorer
        "explor": "explorer", "file manager": "explorer", "explore": "explorer",
        # VS Code - MANY MISHEARINGS
        "vs": "vscode", "vis code": "vscode", "visual code": "vscode",
        "v.s. code": "vscode", "we s code": "vscode", "escort": "vscode",
        "a score": "vscode", "score": "vscode", "vs cold": "vscode",
        "vesicle": "vscode", "vs coat": "vscode", "the s code": "vscode",
        "wes code": "vscode", "v s code": "vscode", "visa code": "vscode",
        # YouTube
        "you tube": "youtube", "utube": "youtube", "u tube": "youtube",
    }
    
    text_lower = text.lower()
    
    # Apply STT corrections
    for wrong, correct in STT_CORRECTIONS.items():
        if wrong in text_lower:
            text_lower = text_lower.replace(wrong, correct)
            logger.debug(f"STT correction: '{wrong}' -> '{correct}'")
    
    # Extract the target from "open X" pattern
    target = None
    match = re.search(r"(?:open|launch|start|run|show|go to)\s+(.+?)(?:\s+for me|\s+please|$|\.)", text_lower)
    if match:
        target = match.group(1).strip()
    else:
        target = text_lower.replace("open", "").replace("launch", "").replace("start", "").strip()
    
    # Clean punctuation
    if target:
        target = target.strip(".,!? ")

    # If the extracted target lost its TLD (e.g. 'example' from 'example.com'),
    # recover a URL-like token from the original text.
    if target and ("." not in target or " " in target):
        url_match = re.search(r'(https?://\S+|www\.\S+|\S+\.(com|org|net|io|ai))', text_lower)
        if url_match:
            candidate = url_match.group(0).strip(".,!? ")
            if "." in candidate and " " not in candidate:
                target = candidate

    if not target:
        return ActionResult.fail("Please specify what to open.", "open_app")
    
    logger.info(f"Smart open: target='{target}'")
    
    # 1. Try to find local app first
    app = app_discovery.find_app(target)
    if app:
        if app_discovery.open_app(app):
            get_preference_manager().track_app_usage(app.name)
            sm = get_state_manager()
            sm.set_last_opened_app(app.name)
            sm.record_opened_app(app.name)
            _send_ui_to_back()  # Let user see the opened app
            return ActionResult.ok(f"Opening {app.name}.", {"app": app.name}, "open_app")
        else:
            return ActionResult.fail(f"I couldn't open {app.name}. It might not be installed.", "open_app")
    
    # 2. Check if it's a known website (word-aware to avoid false positives like matching 'x' inside 'example.com')
    for site_name, url in KNOWN_WEBSITES.items():
        # Multi-word site names: simple substring match is fine (e.g. "google drive")
        if " " in site_name:
            if site_name in target:
                webbrowser.open(url)
                logger.info(f"Opened website: {site_name} -> {url}")
                get_state_manager().set_last_opened_app(site_name)
                _send_ui_to_back()  # Let user see the browser
                return ActionResult.ok(f"Opening {site_name.title()} in your browser.", {"url": url}, "open_app")
        else:
            # Single-word sites: require whole-word or exact match
            words = target.split()
            if target == site_name or site_name in words:
                webbrowser.open(url)
                logger.info(f"Opened website: {site_name} -> {url}")
                get_state_manager().set_last_opened_app(site_name)
                _send_ui_to_back()  # Let user see the browser
                return ActionResult.ok(f"Opening {site_name.title()} in your browser.", {"url": url}, "open_app")
    
    # 3. Check if it looks like a URL
    if "." in target and " " not in target:
        url = target if target.startswith("http") else f"https://{target}"
        webbrowser.open(url)
        logger.info(f"Opened URL: {url}")
        get_state_manager().set_last_opened_app(target)
        _send_ui_to_back()  # Let user see the browser
        return ActionResult.ok(f"Opening {target} in your browser.", {"url": url}, "open_app")
    
    # 4. Check if it's a search query
    search_keywords = ["search", "find", "look for", "google", "look up"]
    is_search = any(kw in text_lower for kw in search_keywords)
    
    if is_search:
        search_query = target.replace("search", "").replace("for", "").replace("google", "").strip()
        if search_query:
            search_url = f"https://www.google.com/search?q={search_query.replace(' ', '+')}"
            webbrowser.open(search_url)
            logger.info(f"Google search: {search_query}")
            return ActionResult.ok(f"Searching Google for '{search_query}'.", {"query": search_query}, "open_app")
    
    # 5. Fallback: Offer to search Google
    search_url = f"https://www.google.com/search?q={target.replace(' ', '+')}"
    webbrowser.open(search_url)
    logger.info(f"Fallback Google search: {target}")
    return ActionResult.ok(
        f"I couldn't find '{target}' as an app. I've searched Google for it instead.",
        {"query": target, "fallback": True},
        "open_app"
    )


def handle_open_url(text: str, context: Dict[str, Any]) -> ActionResult:
    """Open a URL or website."""
    from ..brain.memory.preferences import get_preference_manager
    prefs = get_preference_manager().preferences
    default_browser = (prefs.default_browser or "").strip().lower()
    browser_map = {
        "chrome": "chrome",
        "google chrome": "chrome",
        "edge": "msedge",
        "microsoft edge": "msedge",
        "msedge": "msedge",
        "firefox": "firefox",
    }
    browser_cmd = browser_map.get(default_browser, default_browser)

    URL_MAPPING = {
        "google": "https://www.google.com",
        "youtube": "https://www.youtube.com",
        "github": "https://github.com",
        "linkedin": "https://www.linkedin.com",
        "twitter": "https://twitter.com",
        "x": "https://twitter.com",
        "facebook": "https://www.facebook.com",
        "instagram": "https://www.instagram.com",
        "reddit": "https://www.reddit.com",
        "amazon": "https://www.amazon.com",
        "netflix": "https://www.netflix.com",
        "gmail": "https://mail.google.com",
        "google mail": "https://mail.google.com",
        "google drive": "https://drive.google.com",
        "stack overflow": "https://stackoverflow.com",
        "stackoverflow": "https://stackoverflow.com",
        "chatgpt": "https://chat.openai.com",
        "claude": "https://claude.ai",
    }
    
    text_lower = text.lower()
    url_to_open = None
    site_name = None
    
    for name, url in URL_MAPPING.items():
        if name in text_lower:
            url_to_open = url
            site_name = name
            break
    
    if not url_to_open:
        # Check for explicit URL
        url_match = re.search(r'(https?://\S+|www\.\S+|\S+\.(com|org|net|io|ai))', text_lower)
        if url_match:
            url_to_open = url_match.group(0)
            if not url_to_open.startswith("http"):
                url_to_open = "https://" + url_to_open
            site_name = url_to_open
    
    if not url_to_open:
        return ActionResult.fail(
            "I couldn't find a website to open. Try saying 'open Google' or 'go to youtube.com'.",
            "open_url"
        )

    final_url = url_to_open if url_to_open.startswith(("http://", "https://")) else "https://" + url_to_open
    display_name = site_name.title() if site_name and site_name != url_to_open else "the website"
    browser_label_map = {"chrome": "Chrome", "msedge": "Edge", "edge": "Edge", "firefox": "Firefox"}
    browser_label = browser_label_map.get(browser_cmd, default_browser.title() if default_browser else "")

    def do_open():
        try:
            opened = False
            if browser_cmd:
                try:
                    subprocess.Popen([browser_cmd, final_url], shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    opened = True
                except Exception as e:
                    logger.warning(f"Preferred browser launch failed ({browser_cmd}): {e}")
            if not opened:
                webbrowser.open(final_url)

            get_preference_manager().track_site_usage(site_name or final_url)
            logger.info(f"Opened URL: {final_url}")
            _send_ui_to_back()  # Minimize UI
            
            if browser_label:
                return ActionResult.ok(f"Opening {display_name} in {browser_label}.", {"url": final_url}, "open_url")
            return ActionResult.ok(f"Opening {display_name}.", {"url": final_url}, "open_url")
        except Exception as e:
            logger.error(f"Failed to open URL: {e}")
            return ActionResult.fail("I couldn't open that website.", "open_url")

    if prefs.confirmation_required and not context.get("_confirmed"):
        prompt = f"Open {display_name}" + (f" in {browser_label}?" if browser_label else "?")
        return ActionResult.confirm(prompt, do_open, "open_url")

    return do_open()


def handle_update_preference(text: str, context: Dict[str, Any]) -> ActionResult:
    """
    Update a user preference.
    Usually triggered via confirmation flow from LearningSignalManager.
    """
    try:
        from ..brain.memory.preferences import get_preference_manager
        prefs = get_preference_manager()
        
        # Data is usually passed via context from the confirmation payload
        data = context.get("data", {})
        action_type = data.get("type")
        value = data.get("value")
        
        if not action_type or not value:
            # Fallback for voice commands like "Set my name to X" (handled elsewhere ideally)
            return ActionResult.fail("Missing preference data.", "update_preference")
            
        if action_type == "update_style":
            prefs.set("response_style", value)
            return ActionResult.ok(f"Preference saved: Response style set to {value}.", {}, "update_preference")
            
        elif action_type == "negative_preference":
            # Add to rules or specific negative list (simplified for now)
            # In future, this should go to a Rules engine. For now, we ack it.
            return ActionResult.ok(f"Noted. I will avoid using {value}.", {}, "update_preference")
            
        elif action_type == "positive_preference":
            # Similar to negative, simplified ack
            return ActionResult.ok(f"Noted. I will prefer using {value}.", {}, "update_preference")
            
        return ActionResult.fail(f"Unknown preference type: {action_type}", "update_preference")
        
    except Exception as e:
        logger.error(f"Failed to update preference: {e}")
        return ActionResult.fail(f"Could not save preference: {e}", "update_preference")


def handle_stop_command(text: str, context: Dict[str, Any]) -> ActionResult:
    """Stop current action, speech, or simply acknowledge 'stop'."""
    # The act of saying 'stop' usually triggers the wake word interrupt, stopping TTS.
    # This handler ensures we don't send 'stop' to the LLM.
    return ActionResult.ok("Stopped.", {"action": "stop"}, "stop_command")


def handle_control_window(text: str, context: Dict[str, Any]) -> ActionResult:
    """Control the assistant's window or close other applications."""
    try:
        from .websocket_server import get_ws_server
        from ..automation.native_control import get_native_controller
        
        ws = get_ws_server()
        text_lower = text.lower()

        # Check for closing external applications first
        # Pattern: close/exit/quit [app name]
        close_triggers = ["close ", "exit ", "quit "]
        app_to_close = None
        
        for trigger in close_triggers:
            if trigger in text_lower:
                # Extract potential app name
                parts = text_lower.split(trigger, 1)
                if len(parts) > 1:
                    candidate = parts[1].strip().strip('?.!')
                    # ignore generic terms that refer to Chintu itself
                    if candidate and candidate not in ["window", "it", "this", "the window", "assistant", "chintu"]:
                        app_to_close = candidate
                        break
        
        if app_to_close:
            # SAFETY FIX: Special handling for Browser/Chrome to prefer closing Chintu's instance first
            if app_to_close.lower() in ("chrome", "google chrome", "browser", "firefox", "edge"):
                try:
                    from ..automation.browser.browser_controller import get_browser_controller
                    bc = get_browser_controller()
                    if bc.is_open:
                        bc.close()
                        return ActionResult.ok("Closed my browser session.", {"action": "close_browser"}, "control_window")
                except Exception as e:
                    logger.warning(f"Failed to close Chintu browser: {e}")
            
            # If not Chintu's browser, or already closed, proceed to Native UI close
            native = get_native_controller()
            
            if native and native.close_window_by_title(app_to_close):
                 return ActionResult.ok(f"Closing {app_to_close}.", {"action": "close_app", "app": app_to_close}, "control_window")
            else:
                 return ActionResult.fail(f"I couldn't find a window named '{app_to_close}' to close.", "control_window")

        # Internal Window Control (Chintu UI)
        if not ws:
             return ActionResult.fail("UI not connected.", "control_window")

        if any(w in text_lower for w in ["minimize", "background", "hide", "go away"]):
            ws.send_ui_to_back()
            return ActionResult.ok("Minimizing window.", {"action": "minimize"}, "control_window")
        elif any(w in text_lower for w in ["maximize", "full screen"]):
            ws._schedule_window_command("maximize")
            return ActionResult.ok("Maximizing window.", {"action": "maximize"}, "control_window")
        elif any(w in text_lower for w in ["close", "exit", "quit", "shut down"]): # Only reaches here if no specific app named
            ws._schedule_window_command("close")
            return ActionResult.ok("Closing assistant window.", {"action": "close"}, "control_window")
        elif any(w in text_lower for w in ["show", "restore", "come back"]):
             ws.bring_ui_to_front()
             return ActionResult.ok("I'm back!", {"action": "show"}, "control_window")
            
        return ActionResult.fail("Unknown window command.", "control_window")
    except Exception as e:
        logger.error(f"Window control failed: {e}")
        return ActionResult.fail(f"Failed to control window: {e}", "control_window")



def handle_get_last_opened_app(text: str, context: Dict[str, Any]) -> ActionResult:
    """Get the name of the last application or website opened."""
    from .state import get_state_manager
    state = get_state_manager().state
    last_app = state.last_opened_app
    
    if last_app:
        return ActionResult.ok(f"The last thing I opened was {last_app}.", {"app": last_app}, "get_last_opened_app")
    
    return ActionResult.ok("I haven't opened any applications in this session yet.", {}, "get_last_opened_app")


def handle_system_info(text: str, context: Dict[str, Any]) -> ActionResult:
    """Get system information like time, date, battery."""
    text_lower = text.lower()
    
    # Time
    if any(word in text_lower for word in ["time", "clock"]):
        now = datetime.datetime.now()
        time_str = now.strftime("%I:%M %p")
        return ActionResult.ok(f"The current time is {time_str}.", {"time": time_str}, "system_info")
    
    # Date
    if any(word in text_lower for word in ["date", "today", "day"]):
        now = datetime.datetime.now()
        date_str = now.strftime("%A, %B %d, %Y")
        return ActionResult.ok(f"Today is {date_str}.", {"date": date_str}, "system_info")
    
    # Battery status
    if "battery" in text_lower:
        try:
            import psutil
            battery = psutil.sensors_battery()
            if battery:
                percent = battery.percent
                plugged = "plugged in" if battery.power_plugged else "on battery"
                return ActionResult.ok(
                    f"Your PC's battery is at {percent}% and {plugged}.",
                    {"battery": percent, "plugged": battery.power_plugged, "target": "pc"},
                    "system_info"
                )
            else:
                # No PC battery found (likely a desktop)
                msg = "I didn't find a battery on this PC—it's likely a desktop!"
                # Mention Phone Link if applicable
                msg += " If you're looking for your linked phone's battery via 'Link to Windows', I can't access that directly yet, but I can check your phone if you connect the Chintu Mobile app. "
                return ActionResult.fail(msg, "system_info")
        except ImportError:
            return ActionResult.fail("I'm sorry, I don't have the tools installed to check battery status right now.", "system_info")
        except Exception as e:
            return ActionResult.fail(f"I encountered an error while checking the battery: {e}", "system_info")
    
    # WiFi/Internet status
    if "wifi" in text_lower or "internet" in text_lower or "connection" in text_lower or "connected" in text_lower:
        import socket
        # Quick check for Phone Link process while we're at it
        has_phone_link = False
        try:
            import subprocess
            out = subprocess.check_output('tasklist /FI "IMAGENAME eq PhoneExperienceHost.exe" /NH', shell=True).decode()
            if "PhoneExperienceHost.exe" in out:
                has_phone_link = True
        except:
            pass

        from .config import get_config
        config = get_config()
        try:
            socket.create_connection(
                (config.network_check_host, config.network_check_port),
                timeout=config.network_check_timeout_seconds,
            )
            msg = "You're connected to the internet."
            if has_phone_link:
                msg += " I also see that 'Phone Link' is active on your PC! I can't talk to it directly yet, but it's good to see your phone is connected to Windows."
            return ActionResult.ok(msg, {"connected": True, "phone_link": has_phone_link}, "system_info")
        except OSError:
            return ActionResult.fail("No internet connection detected.", "system_info")
    
    return ActionResult.fail("I can tell you the time, date, battery status, or WiFi connection.", "system_info")


def handle_list_windows(text: str, context: Dict[str, Any]) -> ActionResult:
    """List all open visible windows - concise app names only, no hallucination."""
    from ..automation.window_services import list_windows_formatted, get_open_windows
    
    # Get the concise formatted list
    result_text = list_windows_formatted()
    
    # Also get raw list for data
    windows = get_open_windows()
    if windows and windows[0].startswith("("):
        windows = []
    
    return ActionResult.ok(result_text, {"windows": windows, "count": len(windows)}, "list_windows")


# ============================================================================
# PRODUCTIVITY CAPABILITIES
# ============================================================================


def handle_note_taking(text: str, context: Dict[str, Any]) -> ActionResult:
    """Take, save, or retrieve notes using persistent storage."""
    from ..brain.memory.tiered_memory import get_memory_store
    
    memory = get_memory_store()
    text_lower = text.lower()
    
    # Save a note
    if any(phrase in text_lower for phrase in ["take a note", "save a note", "note that"]):
        # Extract the note content
        for prefix in ["take a note", "save a note", "note that", "note:"]:
            if prefix in text_lower:
                idx = text_lower.find(prefix) + len(prefix)
                note_content = text[idx:].strip().strip(":").strip()
                break
        else:
            note_content = text
        
        if not note_content:
            return ActionResult.fail("What would you like me to note?", "note_taking")
        
        # Deduplication
        notes = memory.get_notes(limit=100)
        if any(n.content.lower() == note_content.lower() for n in notes):
            return ActionResult.ok("I've already saved that note!", {"content": note_content}, "note_taking")
            
        # Open Notepad as a visual cue
        try:
            subprocess.Popen(["notepad.exe"])
        except Exception as e:
            logger.warning(f"Failed to open Notepad: {e}")
            
        # Save to persistent storage
        note_id = memory.add_note(note_content)
        logger.info(f"Saved note: {note_id}")
        return ActionResult.ok(f"Got it! I've opened Notepad and saved that note: {note_content}", {"note_id": note_id}, "note_taking")
    
    # List notes
    if any(phrase in text_lower for phrase in ["my notes", "list notes", "show notes", "what notes"]):
        notes = memory.get_notes(limit=20)
        if not notes:
            return ActionResult.ok("You don't have any notes yet.", {"notes": []}, "note_taking")
        
        notes_list = "\n".join([f"- {n.content}" for n in notes])  # ASCII dash
        return ActionResult.ok(f"Here are your notes:\n{notes_list}", {"notes": [n.content for n in notes]}, "note_taking")
    
    # Clear notes (with confirmation)
    if any(phrase in text_lower for phrase in ["clear notes", "delete notes", "remove notes"]):
        notes = memory.get_notes(limit=100)
        count = len(notes)
        if count == 0:
            return ActionResult.ok("You don't have any notes to clear.", capability="note_taking")
        
        def do_clear():
            cleared = memory.clear_notes()
            return ActionResult.ok(f"Cleared {cleared} notes.", {"cleared": cleared}, "note_taking")
        
        return ActionResult.confirm(
            f"You have {count} notes. Do you want me to clear them all?",
            do_clear,
            "note_taking"
        )
    
    return ActionResult.fail("I can take notes, show your notes, or clear them.", "note_taking")


# ============================================================================
# CONVERSATION CAPABILITY (Routes to LLM)
# ============================================================================

def handle_conversation(text: str, context: Dict[str, Any]) -> ActionResult:
    """
    Route to LLM for general conversation.
    This is a special capability - it returns a marker that tells the system to use LLM.
    """
    # This will be handled specially in command_handler
    return ActionResult.ok(
        "__LLM_ROUTE__",  # Special marker
        {"query": text, "use_llm": True},
        "conversation"
    )


def handle_read_response(text: str, context: Dict[str, Any]) -> ActionResult:
    """Read the last assistant response aloud."""
    # Try to use command handler's smart TTS stored response first
    command_handler = context.get("command_handler")
    if command_handler and hasattr(command_handler, '_last_response') and command_handler._last_response:
        # Use the stored response from smart_speak
        response_to_read = command_handler._last_response
        logger.info(f"Reading stored response ({len(response_to_read)} chars)")
        return ActionResult.ok(
            "Reading it aloud.",
            {"force_speak": True, "speak_text": response_to_read},
            "read_response"
        )
    
    # Fallback to state manager's last response
    from .state import get_state_manager
    state = get_state_manager().state
    last_response = (state.last_response_raw or state.last_response or "").strip()
    if not last_response:
        return ActionResult.fail("There's nothing to read yet.", "read_response")
    return ActionResult.ok(
        "Reading it aloud.",
        {"force_speak": True, "speak_text": last_response},
        "read_response"
    )


# ============================================================================
# REGISTRY INITIALIZATION
# ============================================================================

def register_core_capabilities() -> None:
    """Register all core capabilities with the registry."""
    registry = get_registry()
    
    # Open App
    registry.register(Capability(
        name="open_app",
        triggers=["open", "launch", "start", "run"],
        handler=handle_open_app,
        requires_confirmation=False,
        description="open an application",
        capability_type=CapabilityType.SYSTEM,
        examples=["Open Chrome", "Launch Notepad", "Start Spotify"]
    ))

    # Stop / Cancel - High Priority
    registry.register(Capability(
        name="stop_command",
        triggers=["stop", "cancel", "quiet", "silence", "hush", "pause", "never mind", "nevermind"],
        handler=handle_stop_command,
        requires_confirmation=False,
        description="stop the assistant or current action",
        capability_type=CapabilityType.SYSTEM,
        examples=["Stop", "Cancel", "Be quiet"]
    ))
    
    registry.register(Capability(
        name="update_preference",
        triggers=["update preference", "save preference", "set preference"],
        handler=handle_update_preference,
        requires_confirmation=False, # Confirmation happens before calling this
        description="update a user preference",
        capability_type=CapabilityType.SYSTEM,
        examples=["Set response style to concise"]
    ))
    
    registry.register(Capability(
        name="screen_control",
        triggers=["click the", "type text", "write this", "dictate text", "scroll down", "scroll up", "move mouse to", "press key", "enter text"],
        description="Control mouse and keyboard (click, type, scroll)",
        intent_type=Intent.SCREEN_CONTROL,
        handler=handle_screen_control,
        complexity=TaskComplexity.SIMPLE
    ))
    
    registry.register(Capability(
        name="screen_query",
        triggers=["what is on my screen", "read screen", "describe screen", "scan screen"],
        description="Analyze screen content",
        intent_type=Intent.SCREEN_QUERY,
        handler=lambda t, c: _handle_vision_query(t, c),
        complexity=TaskComplexity.COMPLEX
    ))

    registry.register(Capability(
        name="smart_reader",
        triggers=["read this article", "start reading", "read for me"],
        description="Read articles from screen",
        intent_type=Intent.READ_ARTICLE,
        handler=handle_smart_reading,
        complexity=TaskComplexity.COMPLEX
    ))

    # Switch Window
    registry.register(Capability(
        name="switch_window",
        triggers=["switch to", "go to", "focus", "bring up"],
        description="Switch focus to a specific window",
        intent_type=Intent.SWITCH_WINDOW,
        handler=handle_switch_window,
        complexity=TaskComplexity.SIMPLE
    ))

    # Open URL
    registry.register(Capability(
        name="open_url",
        triggers=["go to", "visit", "browse", "website", ".com", ".org", ".io"],
        handler=handle_open_url,
        requires_confirmation=False,
        description="open a website",
        capability_type=CapabilityType.SYSTEM,
        examples=["Go to Google", "Open YouTube", "Visit github.com"]
    ))
    
    # System Info
    registry.register(Capability(
        name="system_info",
        triggers=["what time", "what's the time", "current time", "what date", "today's date", 
                  "battery", "wifi status", "internet connection", "connected to the internet"],
        handler=handle_system_info,
        requires_confirmation=False,
        description="get system information",
        capability_type=CapabilityType.SYSTEM,
        examples=["What time is it?", "What's today's date?", "Check battery"]
    ))
    
    # Note Taking
    registry.register(Capability(
        name="note_taking",
        triggers=["take a note", "save a note", "remember this", "my notes", "list notes", 
                  "show notes", "clear notes", "note that"],
        handler=handle_note_taking,
        requires_confirmation=False,
        description="take or manage notes",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=["Take a note: buy groceries", "Show my notes", "Clear notes"]
    ))
    
    # Conversation (fallback to LLM)
    registry.register(Capability(
        name="conversation",
        triggers=[],  # Empty triggers - this is the fallback
        handler=handle_conversation,
        requires_confirmation=False,
        description="have a conversation",
        capability_type=CapabilityType.COMMUNICATION,
        examples=["Tell me a joke", "Explain machine learning", "What's the weather?"]
    ))

    # Read Last Response
    registry.register(Capability(
        name="read_response",
        triggers=["read it", "read that", "read aloud", "say it", "speak it", "read the response"],
        handler=handle_read_response,
        requires_confirmation=False,
        description="read the last response aloud",
        capability_type=CapabilityType.COMMUNICATION,
        examples=["Read it", "Speak it"]
    ))
    
    # Get Last Opened App
    registry.register(Capability(
        name="get_last_opened_app",
        triggers=["last opened app", "what did you open", "what was the last app", "last window"],
        handler=handle_get_last_opened_app,
        requires_confirmation=False,
        description="check what was last opened",
        capability_type=CapabilityType.SYSTEM,
        examples=["What was the last app you opened?"]
    ))
    

    
    # List Windows - HIGH PRIORITY to avoid LLM hallucination
    registry.register(Capability(
        name="list_windows",
        triggers=[
            # Direct questions
            "what windows are open", "what all windows are open", "what is open",
            "what's open", "whats open", "what apps are open", "what applications are open",
            "what applications are running", "what apps are running", "what's running",
            "which windows are open", "which apps are open", "what programs are open",
            "what are the windows", "windows are open", "are open",
            # Commands
            "list open windows", "list windows", "list running apps", "list applications",
            "show running apps", "show open windows", "show open apps",
            "show me what's open", "show what's running",
            # Casual
            "windows open", "apps running", "running apps", "open windows", "open apps",
            "running applications", "active windows", "active apps", "currently open",
        ],
        handler=handle_list_windows,
        requires_confirmation=False,
        description="list all open windows",
        capability_type=CapabilityType.SYSTEM,
        examples=["What windows are open?", "List running apps", "What's open?"]
    ))
    
    # Document Reading
    registry.register(Capability(
        name="read_document",
        triggers=["read this document", "read the pdf", "summarize this file", "analyze this document", 
                  "what's in this pdf", "read the docx", "open document", "read file"],
        handler=handle_read_document,
        requires_confirmation=False,
        description="read and summarize PDF, DOCX, TXT, MD files",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=["Read this PDF", "Summarize the document at C:\\docs\\report.pdf"]
    ))
    
    # Live Web Search
    registry.register(Capability(
        name="live_search",
        triggers=["search for", "search the web", "look up", "web search", "find information about",
                  "what is the latest on", "google", "search online"],
        handler=handle_live_search,
        requires_confirmation=False,
        description="search the web for real-time information",
        capability_type=CapabilityType.SYSTEM,
        examples=["Search for Python tutorials", "What's the latest on AI?"]
    ))
    
    # Browse URL
    registry.register(Capability(
        name="browse_url",
        triggers=["read this url", "summarize this page", "read this website", "browse to",
                  "what does this page say", "read the article at"],
        handler=handle_browse_url,
        requires_confirmation=False,
        description="read and summarize web page content",
        capability_type=CapabilityType.SYSTEM,
        examples=["Read https://example.com/article", "Summarize this page"]
    ))

    logger.info(f"Registered {len(registry.list_capabilities())} core capabilities")


# ============================================================================
# SCREEN CAPABILITIES
# ============================================================================

def _handle_vision_query(text, context):
    from ..vision.screen_capabilities import handle_whats_on_screen
    return handle_whats_on_screen(text, context)

def handle_screen_control(text: str, context: Dict[str, Any]) -> ActionResult:
    """Control mouse and keyboard commands."""
    from ..automation.screen_control import get_screen_controller
    from .model_router import get_model_router
    
    controller = get_screen_controller()
    
    if not controller.enabled:
        return ActionResult.fail("Screen control is unavailable (pyautogui missing).", "screen_control")

    text_lower = text.lower()
    
    # Click
    if "click" in text_lower:
        # Simplistic click at current pos
        x, y = controller.get_mouse_position()
        controller.click_at(x, y)
        return ActionResult.ok("Clicked mouse.", {}, "screen_control")
    
    # Typing & Generative Typing
    # Triggers: type/write/dictate/enter text
    typing_triggers = ["type", "write", "dictate", "enter text", "input"]
    
    # Handle "type in notepad [text]" or "write [text]"
    content = text_lower
    for trigger in typing_triggers:
        if trigger in content:
            # Simple clean up: "type hello" -> "hello"
            # But tricky with "type in notepad hello" -> we want "hello"
            
            # Remove the trigger word
            parts = content.split(trigger, 1)
            if len(parts) > 1:
                potential_content = parts[1].strip()
                
                # Check for "in [app]" optional phrase and remove it
                # e.g. "in notepad", "in the text box"
                # Regex to remove "in [word] "
                potential_content = re.sub(r"^in\s+\w+\s+", "", potential_content).strip()
                
                if potential_content:
                    content = potential_content
                    break
    
    # Check if this is a "Generative" request
    # e.g. "about tech news", "a story", "a poem", "code for X"
    generative_keywords = ["about ", "a story", "a poem", "code for", "generate", "an email", "a cover letter"]
    should_generate = any(content.startswith(kw) for kw in generative_keywords)

    if should_generate:
        logger.info(f"Generative Typing detected for: '{content}'")
        try:
            router = get_model_router()
            # Ask LLM to generate the text
            # We want just the content, no "Here is the text" chatter.
            prompt = f"Generate {content}. Return ONLY the text to be typed. No conversational filler."
            response = router.route(prompt, context)
            
            if response and response.response:
                generated_text = response.response.strip().strip('"')
                logger.info(f"Generated text length: {len(generated_text)}")
                
                controller.type_text(generated_text)
                return ActionResult.ok(f"Typed generated text about: {content}", {"generated": True}, "screen_control")
        except Exception as e:
            logger.error(f"Generative typing failed: {e}")
            # Fallback to literal typing if generation happens to fail? Or fail?
            # Let's fail gracefully or fallback. Fallback is safer.
            pass

    # Direct Dictation / Fallback
    if "type" in text_lower or "write" in text_lower or "dictate" in text_lower:
        # Use the cleaned 'content' from above
        # If content matches exactly text_lower (stripping failed), try one more simple strip
        if content == text_lower:
             for t in typing_triggers:
                 content = content.replace(t, "", 1)
        
        content = content.replace("in notepad", "").strip() # Hardcoded common case cleanup
        
        if content:
            controller.type_text(content)
            return ActionResult.ok(f"Typed: {content}", {}, "screen_control")
            
    # Scroll
    if "scroll" in text_lower:
        amount = 500 if "up" in text_lower else -500
        controller.scroll(amount)
        direction = "up" if amount > 0 else "down"
        return ActionResult.ok(f"Scrolled {direction}.", {}, "screen_control")

    # ================================
    # VISUAL AUTOMATION FALLBACK (Eyes)
    # ================================
    # If regex failed, try to "see" the element (e.g. "Click the Start button")
    if "click" in text_lower or "find" in text_lower:
        target_desc = text_lower.replace("click", "").replace("find", "").strip()
        if target_desc:
            logger.info(f"Visual Automation: Looking for '{target_desc}'...")
            try:
                from ..vision.omniparser import get_omniparser
                from ..vision.screen_capture import get_screen_manager
                
                # 1. Capture Screen
                screen_manager = get_screen_manager()
                capture = screen_manager.capture_screen(save=True) # Save for debugging
                
                if capture:
                    # 2. Find Element
                    parser = get_omniparser()
                    result = parser.find_element(str(capture.path), target_desc)
                    
                    if result.get("found") and result.get("coordinates"):
                        # 3. Convert coordinates (percentages -> pixels)
                        coords = result["coordinates"] # [x%, y%] or [xmin, ymin, xmax, ymax]
                        
                        cx, cy = 0, 0
                        if len(coords) == 4:
                            # Bounding Box: [xmin, ymin, xmax, ymax]
                            cx = (coords[0] + coords[2]) / 2
                            cy = (coords[1] + coords[3]) / 2
                        elif len(coords) == 2:
                             # Point: [x, y]
                             cx, cy = coords[0], coords[1]
                        
                        # Clamp to 0-1 range just in case
                        cx = max(0, min(1, cx))
                        cy = max(0, min(1, cy))

                        px_x = int(cx * capture.width)
                        px_y = int(cy * capture.height)
                        
                        logger.info(f"Visual Automation: Clicking '{target_desc}' at {px_x}, {px_y}")
                        controller.click_at(px_x, px_y)
                        return ActionResult.ok(
                            f"I saw '{target_desc}' and clicked it.", 
                            {"visual_click": True, "x": px_x, "y": px_y}, 
                            "screen_control"
                        )
                    elif result.get("error"):
                         logger.warning(f"Visual Automation Error: {result['error']}")
            except Exception as e:
                logger.error(f"Visual Automation failed: {e}")

    return ActionResult.fail("I didn't understand that screen command.", "screen_control")

# ============================================================================
# SMART READER
# ============================================================================

def handle_smart_reading(text: str, context: Dict[str, Any]) -> ActionResult:
    """Start smart reading session."""
    from ..automation.browser.smart_reader import get_smart_reader
    import asyncio
    
    reader = get_smart_reader()
    
    if "stop" in text.lower():
        reader.stop()
        return ActionResult.ok("Stopped reading.", {}, "smart_reader")
    
    # Start async reading loop
    asyncio.run_coroutine_threadsafe(reader.start_reading(context), asyncio.get_running_loop())
    
    return ActionResult.ok(
        "I'm starting to read the article. I'll scroll automatically and check in with you every few minutes.",
        {},
        "smart_reader"
    )

# ============================================================================
# SWITCH WINDOW
# ============================================================================

def handle_switch_window(text: str, context: Dict[str, Any]) -> ActionResult:
    from ..automation.platform.window_manager import get_window_manager
    wm = get_window_manager()
    
    # Extract app name "Go to Chrome" -> "chrome"
    # Basic extraction
    target = ""
    text_lower = text.lower()
    for keyword in ["switch to", "go to", "focus", "bring up"]:
        if keyword in text_lower:
            parts = text_lower.split(keyword, 1)
            if len(parts) > 1:
                target = parts[1].strip()
                break
    
    if target:
        success = wm.switch_to_window(target)
        if success:
            return ActionResult.ok(f"Switched to {target}.", {}, "switch_window")
        else:
            return ActionResult.fail(f"Could not find window matching '{target}'.", "switch_window")
    
    return ActionResult.fail("No target window specified.", "switch_window")

# ============================================================================
# DOCUMENT UNDERSTANDING
# ============================================================================

def handle_read_document(text: str, context: Dict[str, Any]) -> ActionResult:
    """Read and understand a document (PDF, DOCX, TXT, MD)."""
    from ..knowledge.document_reader import get_document_reader
    import re
    
    # Extract file path from text
    # Look for quoted paths or common patterns
    quoted_match = re.search(r'["\']([^"\']+)["\']', text)
    if quoted_match:
        file_path = quoted_match.group(1)
    else:
        # Try to find file path pattern
        path_match = re.search(r'([a-zA-Z]:\\[^\s]+\.(pdf|docx|txt|md))', text, re.IGNORECASE)
        if path_match:
            file_path = path_match.group(1)
        else:
            # Check for common file references
            words = text.lower().split()
            for keyword in ["read", "open", "summarize", "analyze"]:
                if keyword in words:
                    idx = words.index(keyword)
                    if idx + 1 < len(words):
                        # Take rest as potential file reference
                        potential = " ".join(words[idx+1:])
                        potential = potential.strip().strip('"\'')
                        if potential:
                            file_path = potential
                            break
            else:
                return ActionResult.fail(
                    "Please specify which document to read. Example: 'Read the document at C:\\path\\to\\file.pdf'",
                    "read_document"
                )
    
    try:
        reader = get_document_reader()
        
        if not reader.can_read(file_path):
            return ActionResult.fail(
                f"I can't read that file type. I support: PDF, DOCX, TXT, MD",
                "read_document"
            )
        
        content, metadata = reader.read_file(file_path)
        
        # Build response
        title = metadata.get("title", metadata.get("filename", "Document"))
        word_count = metadata.get("word_count", len(content.split()))
        pages = metadata.get("pages", "")
        
        summary_intro = f"I've read '{title}'"
        if pages:
            summary_intro += f" ({pages} pages, {word_count} words)"
        else:
            summary_intro += f" ({word_count} words)"
        
        # Summarize if long
        if word_count > 300:
            summary = reader.summarize(content, max_length=500)
            response = f"{summary_intro}.\n\nSummary:\n{summary}\n\nWould you like me to read a specific section?"
        else:
            response = f"{summary_intro}.\n\nContent:\n{content}"
        
        return ActionResult.ok(response, {
            "content": content,
            "metadata": metadata,
        }, "read_document")
        
    except FileNotFoundError:
        return ActionResult.fail(f"File not found: {file_path}", "read_document")
    except ImportError as e:
        return ActionResult.fail(f"Missing library: {e}. Run: pip install pypdf python-docx", "read_document")
    except Exception as e:
        logger.error(f"Document read error: {e}")
        return ActionResult.fail(f"Error reading document: {e}", "read_document")

# ============================================================================
# LIVE WEB SEARCH
# ============================================================================

def handle_live_search(text: str, context: Dict[str, Any]) -> ActionResult:
    """Search the web for real-time information."""
    try:
        from ..automation.web.live_search import get_live_search
    except ImportError as e:
        logger.error(f"Live search import failed: {e}")
        return ActionResult.fail(
            "Web search components are missing. Please ensure the project structure is intact.",
            "live_search"
        )
    
    # Extract search query
    text_lower = text.lower()
    query = text
    
    # Remove common prefixes
    for prefix in ["search for", "search", "look up", "find", "google", "web search"]:
        if text_lower.startswith(prefix):
            query = text[len(prefix):].strip()
            break
    
    if not query or len(query) < 2:
        return ActionResult.fail("What would you like me to search for?", "live_search")
    
    search = get_live_search()
    
    if not search.is_available:
        return ActionResult.fail(
            "Web search is not available. Please install: pip install duckduckgo-search",
            "live_search"
        )
    
    try:
        results = search.search(query, max_results=5)
        
        if not results:
            return ActionResult.ok(
                f"I couldn't find any results for '{query}'.",
                {"query": query, "results": []},
                "live_search"
            )
        
        # Format for TTS-friendly output
        formatted = []
        for i, r in enumerate(results[:3], 1):  # Top 3 for voice
            formatted.append(f"{i}. {r['title']}: {r['snippet'][:150]}")
        
        response = f"Here's what I found for '{query}':\n\n" + "\n\n".join(formatted)
        
        if len(results) > 3:
            response += f"\n\nI found {len(results)} results. Would you like me to read more?"
        
        return ActionResult.ok(response, {
            "query": query,
            "results": results,
        }, "live_search")
        
    except Exception as e:
        logger.error(f"Search error: {e}")
        return ActionResult.fail(f"Search failed: {e}", "live_search")

# ============================================================================
# BROWSE URL
# ============================================================================

def handle_browse_url(text: str, context: Dict[str, Any]) -> ActionResult:
    """Read and summarize content from a web page."""
    try:
        from ..automation.web.url_reader import get_url_reader
    except ImportError as e:
        logger.error(f"URL reader import failed: {e}")
        return ActionResult.fail(
            "Browser components are missing. Please ensure the project structure is intact.",
            "browse_url"
        )
    import re
    
    # Extract URL from text
    url_match = re.search(r'https?://[^\s]+', text)
    if not url_match:
        return ActionResult.fail(
            "Please provide a URL. Example: 'Read https://example.com/article'",
            "browse_url"
        )
    
    url = url_match.group(0).rstrip('.,;:')
    
    reader = get_url_reader()
    
    if not reader.is_available:
        return ActionResult.fail(
            "URL reading is not available. Please install: pip install requests beautifulsoup4",
            "browse_url"
        )
    
    try:
        content, metadata = reader.fetch(url)
        
        title = metadata.get("title", "Page")
        word_count = metadata.get("word_count", 0)
        domain = metadata.get("domain", "")
        
        # Summarize if long
        if word_count > 500:
            summary = reader.summarize(content, max_length=600)
            response = f"From {domain}: '{title}'\n\n{summary}"
        else:
            response = f"From {domain}: '{title}'\n\n{content[:1000]}"
        
        return ActionResult.ok(response, {
            "url": url,
            "content": content,
            "metadata": metadata,
        }, "browse_url")
        
    except RuntimeError as e:
        return ActionResult.fail(str(e), "browse_url")
    except Exception as e:
        logger.error(f"URL read error: {e}")
        return ActionResult.fail(f"Could not read that page: {e}", "browse_url")

# ============================================================================
# SCREENSHOT CAPABILITY
# ============================================================================

def handle_screenshot(text: str, context: Dict[str, Any]) -> ActionResult:
    """Take a screenshot."""
    from ..automation.screenshot import get_screenshot_manager
    
    manager = get_screenshot_manager()
    
    if not manager.is_available:
        return ActionResult.fail(
            "Screenshot is not available. pyautogui is missing.",
            "screenshot"
        )
    
    text_lower = text.lower()
    
    # Determine type of screenshot
    if "window" in text_lower:
        filepath = manager.capture_active_window()
        desc = "active window"
    else:
        filepath = manager.capture_screen()
        desc = "screen"
    
    if filepath:
        return ActionResult.ok(
            f"I've taken a screenshot of your {desc}. Saved to: {filepath}",
            {"path": filepath},
            "screenshot"
        )
    else:
        return ActionResult.fail("Failed to take screenshot.", "screenshot")

# ============================================================================
# CLIPBOARD CAPABILITY
# ============================================================================

def handle_clipboard(text: str, context: Dict[str, Any]) -> ActionResult:
    """Read, summarize, or manipulate clipboard."""
    from ..automation.platform.clipboard import get_clipboard
    
    clipboard = get_clipboard()
    
    if not clipboard.is_available:
        return ActionResult.fail(
            "Clipboard is not available. Please install: pip install pyperclip",
            "clipboard"
        )
    
    text_lower = text.lower()
    
    # What's in clipboard?
    if any(w in text_lower for w in ["what", "show", "read", "get"]):
        content = clipboard.get()
        if not content:
            return ActionResult.ok("Your clipboard is empty.", {}, "clipboard")
        
        analysis = clipboard.analyze(content)
        
        if analysis['length'] > 500:
            preview = content[:200] + f"... ({analysis['words']} words total)"
        else:
            preview = content
        
        return ActionResult.ok(
            f"Your clipboard contains {analysis['type']}: {preview}",
            {"content": content, "analysis": analysis},
            "clipboard"
        )
    
    # Copy to clipboard
    if "copy" in text_lower:
        # Extract what to copy
        to_copy = text.replace("copy", "").strip()
        if to_copy:
            clipboard.set(to_copy)
            return ActionResult.ok(f"Copied to clipboard: {to_copy}", {}, "clipboard")
    
    # History
    if "history" in text_lower:
        history = clipboard.get_history(5)
        if not history:
            return ActionResult.ok("No clipboard history yet.", {}, "clipboard")
        
        lines = ["Recent clipboard entries:"]
        for i, entry in enumerate(history, 1):
            preview = entry['content'][:50] + "..." if len(entry['content']) > 50 else entry['content']
            lines.append(f"{i}. ({entry['type']}) {preview}")
        
        return ActionResult.ok("\n".join(lines), {"history": history}, "clipboard")
    
    return ActionResult.ok("I can tell you what's in your clipboard or show clipboard history.", {}, "clipboard")

# ============================================================================
# DO IT AGAIN / UNDO
# ============================================================================

def handle_repeat_command(text: str, context: Dict[str, Any]) -> ActionResult:
    """Repeat the last command."""
    from ..brain.memory.conversation_memory import get_conversation_memory
    
    memory = get_conversation_memory()
    last_command = memory.get_last_command()
    
    if not last_command:
        return ActionResult.fail("I don't have a previous command to repeat.", "repeat")
    
    return ActionResult.ok(
        f"Your last command was: '{last_command}'. Let me do that again.",
        {"last_command": last_command, "should_execute": True},
        "repeat"
    )

# ============================================================================
# CONTEXT AWARENESS
# ============================================================================

def handle_context_query(text: str, context: Dict[str, Any]) -> ActionResult:
    """Answer questions about current context."""
    from .context_awareness import get_context_awareness
    
    ctx = get_context_awareness()
    current = ctx.get_active_context()
    
    if not current:
        return ActionResult.ok(
            "I can't detect the current active application.",
            {},
            "context"
        )
    
    text_lower = text.lower()
    
    if any(w in text_lower for w in ["what app", "which app", "current app", "active app"]):
        return ActionResult.ok(
            f"You're currently in {current.app_name}.",
            {"app": current.app_name, "category": current.category},
            "context"
        )
    
    if "window" in text_lower or "title" in text_lower:
        return ActionResult.ok(
            f"The current window is: {current.window_title}",
            {"title": current.window_title},
            "context"
        )
    
    # General context
    summary = ctx.get_context_summary()
    return ActionResult.ok(summary, {"context": current}, "context")

# ============================================================================
# REGISTER ENHANCEMENT CAPABILITIES
# ============================================================================

def register_enhancement_capabilities():
    """Register enhancement capabilities."""
    registry = get_registry()
    
    # Clipboard
    registry.register(Capability(
        name="clipboard",
        triggers=["what's in my clipboard", "clipboard", "show clipboard", "clipboard history",
                  "what did I copy", "paste", "read clipboard"],
        handler=handle_clipboard,
        requires_confirmation=False,
        description="read or manage clipboard",
        capability_type=CapabilityType.SYSTEM,
        examples=["What's in my clipboard?", "Show clipboard history"]
    ))
    
    # Repeat/Do it again
    registry.register(Capability(
        name="repeat_command",
        triggers=["do it again", "repeat that", "again", "one more time", "do that again"],
        handler=handle_repeat_command,
        requires_confirmation=False,
        description="repeat the last command",
        capability_type=CapabilityType.SYSTEM,
        examples=["Do it again", "Repeat that"]
    ))
    
    # Context awareness
    registry.register(Capability(
        name="context_query",
        triggers=["what app am I in", "current app", "which app", "active window",
                  "what am I doing", "what's open"],
        handler=handle_context_query,
        requires_confirmation=False,
        description="answer questions about current context",
        capability_type=CapabilityType.SYSTEM,
        examples=["What app am I in?", "What's the current window?"]
    ))
    
    logger.info("Registered enhancement capabilities")

# ============================================================================
# CALENDAR CAPABILITIES (Self-Healing)
# ============================================================================

def handle_manage_calendar(text: str, context: Dict[str, Any]) -> ActionResult:
    "Read or modify calendar events."
    from ..integrations.google_calendar import get_calendar
    
    calendar = get_calendar()
    
    # Self-Healing Check
    if not calendar.is_configured:
        return ActionResult.fail(
            "I need access to your Google Calendar. Please paste the content of your 'credentials.json' file here.",
            "calendar"
        )
        
    if not calendar.is_authenticated:
        success = calendar.authenticate()
        if not success:
             return ActionResult.fail(
                "Authentication failed. Please check your credentials file.",
                "calendar"
            )

    text_lower = text.lower()
    
    # List Events
    events = calendar.get_upcoming_events(max_results=5)
    response = calendar.format_events_for_voice(events)
    
    return ActionResult.ok(response, {"events": events}, "calendar")

def handle_credential_setup(text: str, context: Dict[str, Any]) -> ActionResult:
    "Handle credential setup from JSON input."
    from ..integrations.google_calendar import get_calendar
    import json
    import re
    
    # Convert single quotes to double quotes if they look like JSON keys
    # Helper to clean up pasted python dicts
    cleaned_text = text
    if "'" in text and "\"" not in text:
        cleaned_text = text.replace("'", "\"").replace("True", "true").replace("False", "false")

    # Try to find JSON blob
    match = re.search(r'\{.*\}', cleaned_text, re.DOTALL)
    if not match:
        return ActionResult.fail("I didn't find valid JSON credentials in that text.", "credential_setup")
    
    json_str = match.group(0)
    
    try:
        # Validate JSON
        data = json.loads(json_str)
        # Check for OAuth fields
        if not ("installed" in data or "web" in data or "client_id" in data):
             return ActionResult.fail("That JSON doesn't look like Google OAuth credentials.", "credential_setup")
             
        calendar = get_calendar()
        success = calendar.save_credentials(json_str)
        
        if success:
            return ActionResult.ok("Credentials saved! I'm now attempting to authenticate... (Check for a browser window if running locally)", {}, "credential_setup")
        else:
            return ActionResult.fail("Failed to save credentials file.", "credential_setup")
            
    except Exception as e:
         return ActionResult.fail(f"Invalid JSON: {e}", "credential_setup")

# Register
try:
    registry = get_registry()
    
    registry.register(Capability(
        name="calendar",
        triggers=["what's on my calendar", "upcoming events", "list events", "calendar schedule", "check calendar"],
        handler=handle_manage_calendar,
        capability_type=CapabilityType.PRODUCTIVITY,
        description="Check google calendar events",
        requires_confirmation=False
    ))
    
    registry.register(Capability(
        name="credential_setup",
        triggers=["setup calendar", "configure calendar", "here is the key", "google credentials", "installed", "client_id"],
        handler=handle_credential_setup,
        capability_type=CapabilityType.SYSTEM,
        description="Setup authentication credentials",
        # Triggers include 'installed' and 'client_id' to catch raw JSON starts
        requires_confirmation=False
    ))
    
    logger.info("Registered calendar self-healing capabilities")
except Exception as e:
    logger.error(f"Failed to register calendar capabilities: {e}")




# ============================================================================
# DEEP REASONING CAPABILITIES (Phase 3)
# ============================================================================

def handle_reasoning(text: str, context: Dict[str, Any]) -> ActionResult:
    """Handle deep reasoning requests."""
    from ..brain.llm.reasoning import get_deep_reasoner
    
    reasoner = get_deep_reasoner()
    
    # If reasoner has no LLM, we can't do much.
    if not reasoner.llm:
         return ActionResult.fail("Deep reasoning engine not initialized.", "reasoning")
         
    # Extract query
    # Triggers: "analyze", "think deeply about", "reason through"
    query = text
    for trigger in DeepReasoner.DEEP_TRIGGERS + ["reason about", "explain"]:
        if text.lower().startswith(trigger):
            query = text[len(trigger):].strip()
            break
            
    # Perform reasoning
    result = reasoner.reason(query)
    
    if result["success"]:
        # Return the synthesized answer but keep decomposition in cache/context if needed
        return ActionResult.ok(result["answer"], result, "reasoning")
    else:
        return ActionResult.fail(f"Reasoning failed: {result.get('error')}", "reasoning")

# Register
try:
    from ..brain.llm.reasoning import DeepReasoner
    registry = get_registry()
    
    registry.register(Capability(
        name="reasoning",
        triggers=["think deeply", "reason through", "analyze step by step", "research deeply", "explain logic"],
        handler=handle_reasoning,
        capability_type=CapabilityType.AI_AGENT,
        description="Complex chain-of-thought reasoning",
        requires_confirmation=False
    ))
    
    registry.register(Capability(
        name="control_window",
        triggers=["minimize window", "maximize window", "hide window", "go to background", "minimize yourself", "come back", "show window"],
        handler=handle_control_window,
        capability_type=CapabilityType.SYSTEM,
        description="Control the application window (minimize, maximize, hide, show)",
        requires_confirmation=False
    ))
    
    logger.info("Registered deep reasoning capabilities")
except Exception as e:
    logger.error(f"Failed to register reasoning capabilities: {e}")
