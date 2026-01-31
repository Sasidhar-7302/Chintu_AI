# Adding New Capabilities - Quick Guide

## 🎯 How to Add New Capabilities (Future-Proof System)

Your Chintu system uses a **plugin-based capability registry** - making it **100% future-proof** for adding new features!

---

## ✅ Example: Adding a New Capability

### Step 1: Create Capability Handler

Create a new file: `chintu/core/my_new_capability.py`

```python
from chintu_backend.core.capabilities import Capability, CapabilityType, ActionResult
from typing import Dict

def handle_weather(text: str, context: Dict) -> ActionResult:
    """Handle weather queries."""
    # Extract location from text
    location = "your city"  # Parse from text
    
    # Get weather (your logic here)
    weather = get_weather(location)
    
    # Return result
    return ActionResult.ok(
        f"The weather in {location} is {weather}",
        data={"weather": weather},
        capability="weather"
    )

def get_weather(location: str) -> str:
    """Get weather for location (implement your API call)."""
    # Your weather API integration
    return "sunny, 72°F"
```

### Step 2: Register the Capability

In `chintu/core/capability_handlers.py` or create new module:

```python
from chintu_backend.core.capabilities import get_registry, Capability, CapabilityType
from .my_new_capability import handle_weather

def register_weather_capability():
    """Register weather capability."""
    registry = get_registry()
    registry.register(Capability(
        name="weather",
        triggers=["weather", "temperature", "forecast", "what's the weather"],
        handler=handle_weather,
        requires_confirmation=False,
        description="get weather information",
        capability_type=CapabilityType.SYSTEM,
        examples=["What's the weather?", "Check temperature", "Weather forecast"]
    ))
```

### Step 3: Call Registration

In `chintu/core/command_handler.py`, add to `__init__`:

```python
# Register weather capability
from .my_new_capability import register_weather_capability
register_weather_capability()
```

**Done!** Your new capability is now available. Users can say "What's the weather?" and it will work!

---

## 📋 Capability Types

```python
class CapabilityType(Enum):
    SYSTEM = "system"        # OS actions (open app, weather, etc.)
    COMMUNICATION = "comm"   # Chat, questions
    PRODUCTIVITY = "prod"    # Notes, tasks, reminders
    AUTOMATION = "auto"      # Scripts, workflows
```

---

## 🔧 Advanced: Capability with Confirmation

```python
def handle_delete_file(text: str, context: Dict) -> ActionResult:
    """Handle file deletion (requires confirmation)."""
    # Extract filename
    filename = parse_filename(text)
    
    # Return confirmation required
    return ActionResult.confirm(
        f"Are you sure you want to delete {filename}?",
        pending_action=lambda: delete_file(filename),
        capability="delete_file"
    )
```

---

## 🎯 Current Capabilities (45 total)

You can extend any of these categories:

### System (4)
- `open_app`, `open_url`, `system_info`, `status`

### Web Search (3)
- `web_search`, `news_search`, `deep_search`

### Browser (6)
- `open_browser`, `browser_navigate`, `browser_click`, etc.

### Memory (7)
- `remember`, `recall`, `forget`, `take_note`, etc.

### Tasks (5)
- `set_reminder`, `list_reminders`, `cancel_reminder`, etc.

### Automation (6)
- `create_workflow`, `execute_workflow`, `schedule_workflow`, etc.

### Files (5)
- `read_file`, `list_files`, `summarize_file`, etc.

### Agents (3)
- `plan_task`, `execute_plan`, `agent_research`

### General (6)
- `help`, `stop`, `read_response`, `conversation`, etc.

**Add unlimited new capabilities using the same pattern!**

---

## ✅ System is 100% Future-Proof for Capabilities

The capability registry makes it **impossible to run out of room** for new features:
- ✅ Add capabilities dynamically
- ✅ No code changes needed to core system
- ✅ Policy engine automatically applies safety
- ✅ Telemetry automatically tracks usage
- ✅ Works with all LLM routing

**Your system can grow to 100+ capabilities easily!**

