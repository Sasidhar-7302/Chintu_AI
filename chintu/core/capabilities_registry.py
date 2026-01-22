"""Chintu's Complete Capabilities Registry.

This module documents ALL capabilities Chintu has, organized by category.
Used for help responses and self-awareness.
"""

# Complete list of all Chintu capabilities
CAPABILITIES = {
    # =========================================================================
    # CORE SYSTEM
    # =========================================================================
    "system": {
        "name": "System Control",
        "description": "Control system functions",
        "icon": "desktop_windows",
        "color": "0xFF2196F3", # Blue
        "commands": [
            {"pattern": "open [app]", "desc": "Open any application", "examples": ["open chrome", "open notepad"]},
            {"pattern": "close [app]", "desc": "Close an application", "examples": ["close chrome"]},
            {"pattern": "take a screenshot", "desc": "Capture screen", "examples": ["take a screenshot", "screenshot"]},
            {"pattern": "what's on my screen", "desc": "Describe screen content", "examples": ["what's on my screen"]},
            {"pattern": "read screen text", "desc": "OCR the screen", "examples": ["read the text on screen"]},
            {"pattern": "what windows are open", "desc": "List open windows", "examples": ["what windows are open", "show running apps"]},
        ]
    },
    
    # =========================================================================
    # CLIPBOARD
    # =========================================================================
    "clipboard": {
        "name": "Clipboard",
        "description": "Manage clipboard content",
        "icon": "content_paste",
        "color": "0xFF607D8B", # Blue Grey
        "commands": [
            {"pattern": "copy that", "desc": "Copy last response", "examples": ["copy that", "copy to clipboard"]},
            {"pattern": "what's in my clipboard", "desc": "Read clipboard", "examples": ["what's in my clipboard", "paste"]},
        ]
    },
    
    # =========================================================================
    # WEB & BROWSER
    # =========================================================================
    "web": {
        "name": "Web & Browser",
        "description": "Open websites and search the web",
        "icon": "language",
        "color": "0xFF03A9F4", # Light Blue
        "commands": [
            {"pattern": "open [website]", "desc": "Open a website", "examples": ["open youtube", "open gmail"]},
            {"pattern": "search for [query]", "desc": "Google search", "examples": ["search for weather", "google python tutorials"]},
            {"pattern": "go to [url]", "desc": "Open URL", "examples": ["go to github.com"]},
        ]
    },
    
    # =========================================================================
    # CREDENTIALS & LOGIN
    # =========================================================================
    "security": {
        "name": "Credentials & Login",
        "description": "Manage passwords and auto-login",
        "icon": "security",
        "color": "0xFFF44336", # Red
        "commands": [
            {"pattern": "set up my password vault", "desc": "Create master password", "examples": ["set up my vault"]},
            {"pattern": "unlock my vault", "desc": "Unlock credentials", "examples": ["unlock my vault"]},
            {"pattern": "save my [site] login", "desc": "Store credentials", "examples": ["save my gmail login"]},
            {"pattern": "log me into [site]", "desc": "Auto-login", "examples": ["log me into gmail", "login to linkedin"]},
            {"pattern": "what logins do I have", "desc": "List saved logins", "examples": ["what logins do I have saved"]},
        ]
    },
    
    # =========================================================================
    # PHONE / MOBILE DEVICE
    # =========================================================================
    "phone": {
        "name": "Phone Control",
        "description": "Control connected Android phone via Termux",
        "icon": "smartphone",
        "color": "0xFF4CAF50", # Green
        "commands": [
            {"pattern": "scan for devices", "desc": "Find phones on network", "examples": ["scan for devices", "find my phone"]},
            {"pattern": "connect to my phone", "desc": "SSH to phone", "examples": ["connect to my phone"]},
            {"pattern": "device status", "desc": "Show connected devices", "examples": ["what devices are connected"]},
            {"pattern": "vibrate my phone", "desc": "Vibrate phone", "examples": ["vibrate my phone", "ring my phone"]},
            {"pattern": "phone battery", "desc": "Get battery status", "examples": ["what's my phone battery", "phone charge"]},
            {"pattern": "notify my phone", "desc": "Send notification", "examples": ["notify my phone", "send notification"]},
            {"pattern": "say [text] on my phone", "desc": "TTS on phone", "examples": ["say hello on my phone"]},
            {"pattern": "show [text] on my phone", "desc": "Display toast", "examples": ["show hello on my phone"]},
            {"pattern": "take photo with phone", "desc": "Phone camera", "examples": ["take a photo with my phone"]},
            {"pattern": "open [site] on my phone", "desc": "Open URL on phone", "examples": ["open youtube on my phone"]},
            {"pattern": "where is my phone", "desc": "GPS location", "examples": ["where is my phone", "phone location"]},
        ]
    },
    
    # =========================================================================
    # TASKS & AUTOMATION
    # =========================================================================
    "tasks": {
        "name": "Tasks & Reminders",
        "description": "Create and manage tasks",
        "icon": "check_circle",
        "color": "0xFFFF9800", # Orange
        "commands": [
            {"pattern": "create task [name]", "desc": "Create a task", "examples": ["create task buy groceries"]},
            {"pattern": "show my tasks", "desc": "List tasks", "examples": ["show my tasks", "what tasks do I have"]},
            {"pattern": "complete task [name]", "desc": "Mark done", "examples": ["complete task buy groceries"]},
            {"pattern": "remind me to [action]", "desc": "Set reminder", "examples": ["remind me to call mom at 5pm"]},
        ]
    },
    
    # =========================================================================
    # MEMORY & LEARNING
    # =========================================================================
    "memory": {
        "name": "Memory & Learning",
        "description": "Remember information and learn preferences",
        "icon": "psychology",
        "color": "0xFF9C27B0", # Purple
        "commands": [
            {"pattern": "remember that [fact]", "desc": "Store information", "examples": ["remember that my birthday is May 15"]},
            {"pattern": "what do you know about [topic]", "desc": "Recall info", "examples": ["what do you know about me"]},
            {"pattern": "forget [fact]", "desc": "Remove memory", "examples": ["forget my address"]},
        ]
    },
    
    # =========================================================================
    # VISION & SCREEN
    # =========================================================================
    "vision": {
        "name": "Vision & Screen",
        "description": "See and understand your screen",
        "icon": "visibility",
        "color": "0xFF673AB7", # Deep Purple
        "commands": [
            {"pattern": "what's on my screen", "desc": "Describe screen content", "examples": ["what's on my screen", "describe this app"]},
            {"pattern": "read screen text", "desc": "Extract text", "examples": ["read the text on screen", "copy screen text"]},
            {"pattern": "find [element]", "desc": "Locate UI element", "examples": ["find the submit button", "where is the search bar"]},
            {"pattern": "take a screenshot", "desc": "Capture screen", "examples": ["take a screenshot", "save screen"]},
        ]
    },

    # =========================================================================
    # TEMPORAL MEMORY
    # =========================================================================
    "temporal": {
        "name": "Time Travel Memory",
        "description": "Recall past conversations and facts",
        "icon": "history",
        "color": "0xFF795548", # Brown
        "commands": [
            {"pattern": "what did I say about [topic]", "desc": "Recall past topics", "examples": ["what did I say about coffee"]},
            {"pattern": "when did I mention [topic]", "desc": "Find time of mention", "examples": ["when did I mention vacation"]},
            {"pattern": "what did we discuss [time]", "desc": "Conversation history", "examples": ["what did we discuss yesterday"]},
            {"pattern": "remember that [fact]", "desc": "Store new fact", "examples": ["remember that I like sushi"]},
        ]
    },
    
    # =========================================================================
    # FILES & DOCUMENTS
    # =========================================================================
    "files": {
        "name": "Files & Documents",
        "description": "Work with files",
        "icon": "folder",
        "color": "0xFFFFC107", # Amber
        "commands": [
            {"pattern": "read [file]", "desc": "Read file content", "examples": ["read readme.md"]},
            {"pattern": "summarize [file]", "desc": "Summarize document", "examples": ["summarize report.pdf"]},
        ]
    },
    
    # =========================================================================
    # HELP & INFO
    # =========================================================================
    "help": {
        "name": "Help & Information",
        "description": "Get help and information",
        "icon": "help",
        "color": "0xFF009688", # Teal
        "commands": [
            {"pattern": "help", "desc": "Show all capabilities", "examples": ["help", "what can you do"]},
            {"pattern": "help with [topic]", "desc": "Topic-specific help", "examples": ["help with phone", "help with login"]},
            {"pattern": "how do I [action]", "desc": "Get instructions", "examples": ["how do I connect my phone"]},
        ]
    },
}


def get_all_capabilities_text() -> str:
    """Get formatted text of all capabilities for help responses."""
    lines = ["Here's everything I can do:\n"]
    
    for category_id, category in CAPABILITIES.items():
        lines.append(f"\n**{category['name']}**")
        for cmd in category["commands"]:
            lines.append(f"  • \"{cmd['pattern']}\" - {cmd['desc']}")
    
    return "\n".join(lines)


def get_capabilities_tree() -> Dict[str, Any]:
    """Get structured capabilities tree for UI."""
    return CAPABILITIES


def get_category_help(category: str) -> str:
    """Get help for a specific category."""
    category_lower = category.lower()
    
    for cat_id, cat_data in CAPABILITIES.items():
        if category_lower in cat_id or category_lower in cat_data["name"].lower():
            lines = [f"**{cat_data['name']}** - {cat_data['description']}\n"]
            for cmd in cat_data["commands"]:
                examples = ", ".join(f'"{e}"' for e in cmd["examples"][:2])
                lines.append(f"  • **{cmd['pattern']}** - {cmd['desc']}")
                lines.append(f"    Examples: {examples}")
            return "\n".join(lines)
    
    return f"I don't have a category called '{category}'. Try: system, web, vision, phone, security, tasks, memory, temporal, files, help"


def count_capabilities() -> int:
    """Count total number of capabilities."""
    return sum(len(cat["commands"]) for cat in CAPABILITIES.values())


# Quick reference for common questions
QUICK_ANSWERS = {
    "what can you do": get_all_capabilities_text,
    "help": get_all_capabilities_text,
    "capabilities": get_all_capabilities_text,
    "features": get_all_capabilities_text,
}
