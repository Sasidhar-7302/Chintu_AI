"""
Help and Explainability Capabilities for Chintu Assistant.
Handlers for explaining actions, showing capabilities, and getting help.
"""

import logging
from typing import Dict, Any

from ..core.capabilities import (
    Capability, CapabilityType, ActionResult, get_registry
)
from ..core.explainability import get_explainability
from ..core.state import get_state_manager
from ..core.degraded_mode import get_degraded_mode

logger = logging.getLogger(__name__)


# ============================================================================
# EXPLAINABILITY CAPABILITIES
# ============================================================================

def handle_why(text: str, context: Dict[str, Any]) -> ActionResult:
    """Explain why the last action was taken."""
    explainer = get_explainability()
    explanation = explainer.explain_last_action()
    return ActionResult.ok(explanation, capability="why")


def handle_what_can_you_do(text: str, context: Dict[str, Any]) -> ActionResult:
    """List all available capabilities."""
    explainer = get_explainability()
    summary = explainer.get_capabilities_summary()
    return ActionResult.ok(summary, capability="what_can_you_do")


def handle_help(text: str, context: Dict[str, Any]) -> ActionResult:
    """Get help on using the assistant."""
    text_lower = text.lower()
    
    # Check for specific capability help
    registry = get_registry()
    caps = registry.list_capabilities()
    
    for cap in caps:
        if cap["name"] in text_lower:
            explainer = get_explainability()
            explanation = explainer.explain_capability(cap["name"])
            return ActionResult.ok(explanation, capability="help")
    
    # General help
    help_text = """**Chintu Help**

**Voice Commands:**
- "Open Chrome" - Open applications
- "Go to Google" - Open websites
- "What time is it?" - Get system info
- "Take a note: ..." - Save notes
- "Remind me in 10 minutes to..." - Set reminders

**Web & Search:**
- "Search for Python tutorials" - Web search
- "Research AI trends" - Deep search
- "Open browser" - Browser automation

**Memory:**
- "Remember that I like coffee" - Save facts
- "What do you remember about me?" - Recall facts
- "My name is John" - Set preferences

**Automation:**
- "Every day at 9am, search news" - Schedule tasks
- "In the background, research AI" - Background tasks
- "Check tasks" - View running tasks

**Understand Me:**
- "Why did you do that?" - Explain last action
- "What can you do?" - List all capabilities
- "Status" - Show assistant status
- "Read it" - Read the last response aloud

Say "Hey Chintu" to wake me up!"""
    
    return ActionResult.ok(help_text, capability="help")


def handle_history(text: str, context: Dict[str, Any]) -> ActionResult:
    """Show recent action history."""
    explainer = get_explainability()
    history = explainer.get_history(limit=5)
    
    if not history:
        return ActionResult.ok("No recent actions to show.", capability="history")
    
    lines = ["**Recent Actions:**"]
    for action in reversed(history):
        status = "[OK]" if action.success else "[FAIL]"
        lines.append(f"- {status} {action.capability_name}: {action.user_input[:40]}...")
    
    return ActionResult.ok("\n".join(lines), capability="history")


def handle_status(text: str, context: Dict[str, Any]) -> ActionResult:
    """Show system status summary."""
    state = get_state_manager().state
    degraded = get_degraded_mode()
    mode_report = degraded.get_status_report()

    lines = [
        f"Status: {state.assistant_state.value}",
        f"Mode: {mode_report.get('mode_message', 'unknown')}",
        f"Last command: {state.last_command[:60] if state.last_command else 'none'}",
        f"Last response: {state.last_response[:60] if state.last_response else 'none'}",
        "",
        "Features:",
    ]
    for name, feature in state.features.items():
        status = feature.status
        enabled = "on" if feature.enabled else "off"
        lines.append(f"- {feature.name}: {enabled} ({status})")

    return ActionResult.ok("\n".join(lines), capability="status")
    

def handle_identity(text: str, context: Dict[str, Any]) -> ActionResult:
    """Reveal assistant identity."""
    return ActionResult.ok("I am Chintu, your personal AI assistant. Created by Sasidhar Yepuri to help you with everything on your computer!", capability="identity")


def handle_who_am_i(text: str, context: Dict[str, Any]) -> ActionResult:
    """Reveal user identity."""
    from ..brain.memory.preferences import get_preference_manager
    user_name = get_preference_manager().get("user_name") or "User"
    return ActionResult.ok(f"You are {user_name}! And I am Chintu, your assistant.", capability="who_am_i")


def handle_setup_guide(text: str, context: Dict[str, Any]) -> ActionResult:
    """Provide setup instructions for various features and integrations."""
    text_lower = text.lower()
    
    # Telegram setup
    if any(w in text_lower for w in ["telegram", "telegram bot"]):
        guide = """**Telegram Bot Setup**

To connect me to Telegram, you'll need to:

1. **Create a Telegram Bot:**
   - Open Telegram and search for @BotFather
   - Send /newbot and follow the prompts
   - Save the API token you receive

2. **Get Your User ID:**
   - Search for @userinfobot in Telegram
   - Send any message to get your user ID

3. **Configure Chintu:**
   Add these to your `.env` file or config:
   ```
   TELEGRAM_ENABLED=true
   TELEGRAM_BOT_TOKEN=your_bot_token_here
   TELEGRAM_ALLOWED_USER_ID=your_user_id_here
   ```

4. **Restart Chintu** and say "Status" to verify.

Link: https://t.me/BotFather"""
        return ActionResult.ok(guide, capability="setup_guide")
    
    # Google Calendar setup
    if any(w in text_lower for w in ["google calendar", "calendar", "gcal"]):
        guide = """**Google Calendar Setup**

⚠️ Google Calendar integration requires OAuth2 setup:

1. **Create a Google Cloud Project:**
   - Go to: https://console.cloud.google.com/
   - Create a new project
   - Enable the Google Calendar API

2. **Create OAuth2 Credentials:**
   - Go to APIs & Services > Credentials
   - Create OAuth 2.0 Client ID (Desktop app)
   - Download the credentials.json file

3. **Install Dependencies:**
   ```
   pip install google-auth-oauthlib google-api-python-client
   ```

4. **Place credentials.json** in your Chintu config folder

5. **First Run:** You'll be prompted to authorize access

Note: This feature requires implementation - let me know if you'd like me to guide you through adding it!"""
        return ActionResult.ok(guide, capability="setup_guide")
    
    # Feature status/issues
    if any(w in text_lower for w in ["feature", "status", "issues", "not working", "broken"]):
        state = get_state_manager().state
        issues = []
        for name, feature in state.features.items():
            if not feature.enabled or feature.error:
                status = f"❌ {feature.name}: {feature.error or 'disabled'}"
                issues.append(status)
        
        if issues:
            msg = "**Features with Issues:**\n" + "\n".join(issues)
            msg += "\n\nSay 'setup [feature name]' for help configuring any feature."
        else:
            msg = "All features are currently working! Say 'status' for full details."
        return ActionResult.ok(msg, capability="setup_guide")
    
    # General setup help
    guide = """**Setup & Configuration Help**

I can guide you through setting up:
- **Telegram Bot** - Say "setup telegram"
- **Google Calendar** - Say "setup google calendar" 
- **Feature Issues** - Say "what features have issues"

For general help, say "help".
For current status, say "status"."""
    return ActionResult.ok(guide, capability="setup_guide")





# ============================================================================
# REGISTRY INITIALIZATION
# ============================================================================

def register_help_capabilities() -> None:
    """Register help and explainability capabilities."""
    registry = get_registry()
    
    # Why did you do that?
    registry.register(Capability(
        name="why",
        triggers=["why did you do", "why did you take", "explain your action", "explain why you", "reason for doing"],
        handler=handle_why,
        requires_confirmation=False,
        description="explain the last action taken by the assistant",
        capability_type=CapabilityType.SYSTEM,
        examples=["Why did you do that?", "Explain why you opened the browser"]
    ))
    
    # What can you do?
    registry.register(Capability(
        name="what_can_you_do",
        triggers=["what can you do", "your abilities", "capabilities", "what do you do"],
        handler=handle_what_can_you_do,
        requires_confirmation=False,
        description="list available capabilities",
        capability_type=CapabilityType.SYSTEM,
        examples=["What can you do?", "Show capabilities"]
    ))
    
    # Help
    registry.register(Capability(
        name="help",
        triggers=["help", "how do i", "how to", "tutorial"],
        handler=handle_help,
        requires_confirmation=False,
        description="get help using the assistant",
        capability_type=CapabilityType.SYSTEM,
        examples=["Help", "How do I set a reminder?"]
    ))
    
    # History
    registry.register(Capability(
        name="history",
        triggers=["action history", "recent actions", "what did you do"],
        handler=handle_history,
        requires_confirmation=False,
        description="show recent action history",
        capability_type=CapabilityType.SYSTEM,
        examples=["What did you do?", "Action history"]
    ))

    # Status
    registry.register(Capability(
        name="status",
        triggers=[
            "status", "system status", "assistant status", 
            "are you listening", "what are you doing", 
            "are you active", "are you there", "current status"
        ],
        handler=handle_status,
        requires_confirmation=False,
        description="show assistant status",
        capability_type=CapabilityType.SYSTEM,
        examples=["Status", "Are you listening?"]
    ))
    
    # Identity
    registry.register(Capability(
        name="identity",
        triggers=["who are you", "what is your name", "who am i talking to", "what are you", "identify yourself", "tell me about yourself"],
        handler=handle_identity,
        requires_confirmation=False,
        description="reveal assistant identity",
        capability_type=CapabilityType.SYSTEM,
        examples=["Who are you?", "What's your name?"]
    ))
    
    # Who am I?
    registry.register(Capability(
        name="who_am_i",
        triggers=["who am i", "do you know who i am", "who is talking"],
        handler=handle_who_am_i,
        requires_confirmation=False,
        description="reveal user identity",
        capability_type=CapabilityType.SYSTEM,
        examples=["Who am I?", "Do you know who I am?"]
    ))
    
    # Setup Guide
    registry.register(Capability(
        name="setup_guide",
        triggers=[
            "setup", "configure", "how to setup",
            "guide", "integration", "not working", "broken"
        ],
        handler=handle_setup_guide,
        requires_confirmation=False,
        description="get setup instructions for integrations and features",
        capability_type=CapabilityType.SYSTEM,
        examples=["How do I setup Telegram?", "Google Calendar integration guide", "What features have issues?"]
    ))
    
    
    logger.info("Registered help capabilities")

