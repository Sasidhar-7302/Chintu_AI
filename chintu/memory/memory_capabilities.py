"""
Preference and Memory Capabilities for Chintu Assistant.
Handlers for user preference management and memory operations.
"""

import logging
from typing import Dict, Any

from ..core.capabilities import (
    Capability, CapabilityType, ActionResult, get_registry
)
from .preferences import get_preference_manager
from .tiered_memory import get_memory_store, MemoryType

logger = logging.getLogger(__name__)


# ============================================================================
# PREFERENCE CAPABILITIES
# ============================================================================

def handle_set_preference(text: str, context: Dict[str, Any]) -> ActionResult:
    """Set a user preference."""
    text_lower = text.lower()
    pref_manager = get_preference_manager()
    
    # Response style
    if "concise" in text_lower or "brief" in text_lower or "short" in text_lower:
        pref_manager.set("response_style", "concise")
        return ActionResult.ok("I'll keep my responses concise from now on.", capability="set_preference")
    
    if "detailed" in text_lower or "thorough" in text_lower or "elaborate" in text_lower:
        pref_manager.set("response_style", "detailed")
        return ActionResult.ok("I'll give more detailed responses from now on.", capability="set_preference")
    
    if "balanced" in text_lower:
        pref_manager.set("response_style", "balanced")
        return ActionResult.ok("I'll use a balanced response style.", capability="set_preference")
    
    # Name
    if "my name is" in text_lower or "call me" in text_lower:
        import re
        match = re.search(r"(?:my name is|call me)\s+(\w+)", text_lower)
        if match:
            name = match.group(1).capitalize()
            pref_manager.set("user_name", name)
            return ActionResult.ok(f"Nice to meet you, {name}! I'll remember your name.", capability="set_preference")
    
    # Confirmation preference
    if "ask before" in text_lower or "confirm before" in text_lower:
        pref_manager.set("confirmation_required", True)
        return ActionResult.ok("I'll ask for confirmation before important actions.", capability="set_preference")
    
    if "don't ask" in text_lower or "no confirmation" in text_lower:
        pref_manager.set("confirmation_required", False)
        return ActionResult.ok("I won't ask for confirmation for most actions.", capability="set_preference")
    
    # Location
    if "i live in" in text_lower or "i'm in" in text_lower or "my location is" in text_lower:
        import re
        match = re.search(r"(?:i live in|i'm in|my location is)\s+(.+?)(?:\.|$)", text_lower)
        if match:
            location = match.group(1).strip().title()
            pref_manager.set("location", location)
            return ActionResult.ok(f"Got it! I'll remember you're in {location}.", capability="set_preference")
    
    return ActionResult.fail(
        "I can set preferences like: response style (concise/detailed), your name, location, or confirmation settings.",
        "set_preference"
    )


def handle_get_preferences(text: str, context: Dict[str, Any]) -> ActionResult:
    """Show current user preferences."""
    pref_manager = get_preference_manager()
    prefs = pref_manager.preferences
    
    parts = []
    if prefs.user_name:
        parts.append(f"Name: {prefs.user_name}")
    if prefs.location:
        parts.append(f"Location: {prefs.location}")
    parts.append(f"Response style: {prefs.response_style}")
    parts.append(f"Confirmation required: {'Yes' if prefs.confirmation_required else 'No'}")
    
    if prefs.frequently_used_apps:
        parts.append(f"Frequent apps: {', '.join(prefs.frequently_used_apps[:3])}")
    
    msg = "Here are your current preferences:\n" + "\n".join(f"- {p}" for p in parts)
    return ActionResult.ok(msg, {"preferences": prefs.to_dict()}, "get_preferences")


def handle_reset_preferences(text: str, context: Dict[str, Any]) -> ActionResult:
    """Reset preferences to defaults."""
    pref_manager = get_preference_manager()
    pref_manager.reset()
    return ActionResult.ok("I've reset all preferences to defaults.", capability="reset_preferences")


# ============================================================================
# MEMORY CAPABILITIES
# ============================================================================

def handle_remember_fact(text: str, context: Dict[str, Any]) -> ActionResult:
    """Remember a fact about the user."""
    memory = get_memory_store()
    text_lower = text.lower()
    
    # Extract fact content
    for prefix in ["remember that", "remember this", "remember"]:
        if prefix in text_lower:
            idx = text_lower.find(prefix) + len(prefix)
            fact = text[idx:].strip().strip(":").strip()
            break
    else:
        fact = text
    
    if not fact or len(fact) < 5:
        return ActionResult.fail("What would you like me to remember?", "remember_fact")
    
    memory.add_fact(fact, importance=0.7)
    return ActionResult.ok(f"I'll remember that.", {"fact": fact}, "remember_fact")


def handle_recall_facts(text: str, context: Dict[str, Any]) -> ActionResult:
    """Recall facts about the user."""
    memory = get_memory_store()
    text_lower = text.lower()
    
    # Check for specific search
    if "about" in text_lower:
        import re
        match = re.search(r"about\s+(.+?)(?:\?|$)", text_lower)
        if match:
            query = match.group(1).strip()
            facts = memory.search_facts(query)
            if facts:
                fact_list = "\n".join(f"- {f.content}" for f in facts[:5])
                return ActionResult.ok(f"Here's what I remember about '{query}':\n{fact_list}", capability="recall_facts")
            return ActionResult.ok(f"I don't have any memories about '{query}'.", capability="recall_facts")
    
    # Get all facts
    facts = memory.get_facts(limit=10)
    if not facts:
        return ActionResult.ok("I don't have any facts stored yet. Say 'remember that...' to teach me.", capability="recall_facts")
    
    fact_list = "\n".join(f"- {f.content}" for f in facts)
    return ActionResult.ok(f"Here's what I remember about you:\n{fact_list}", {"facts": [f.content for f in facts]}, "recall_facts")


def handle_forget(text: str, context: Dict[str, Any]) -> ActionResult:
    """Forget memories (with confirmation)."""
    memory = get_memory_store()
    text_lower = text.lower()
    
    if "everything" in text_lower or "all" in text_lower:
        stats = memory.get_stats()
        total = sum(stats.values())
        if total == 0:
            return ActionResult.ok("I don't have any memories to forget.", capability="forget")
        
        # This should trigger confirmation
        def do_forget():
            for mem_type in MemoryType:
                memory._clear_type(mem_type)
            return ActionResult.ok(f"I've forgotten everything ({total} memories cleared).", capability="forget")
        
        return ActionResult.confirm(
            f"I have {total} memories stored. Do you really want me to forget everything?",
            do_forget,
            "forget"
        )
    
    return ActionResult.fail("Say 'forget everything' to clear all memories.", "forget")


def handle_memory_stats(text: str, context: Dict[str, Any]) -> ActionResult:
    """Show memory statistics."""
    memory = get_memory_store()
    stats = memory.get_stats()
    
    parts = []
    total = 0
    for mem_type, count in stats.items():
        parts.append(f"- {mem_type.replace('_', ' ').title()}: {count}")
        total += count
    
    if not parts:
        return ActionResult.ok("I don't have any memories stored yet.", capability="memory_stats")
    
    msg = f"Memory Statistics (Total: {total}):\n" + "\n".join(parts)
    return ActionResult.ok(msg, {"stats": stats}, "memory_stats")


# ============================================================================
# REGISTRY INITIALIZATION
# ============================================================================

def register_memory_capabilities() -> None:
    """Register all memory and preference capabilities."""
    registry = get_registry()
    
    # Set Preference
    registry.register(Capability(
        name="set_preference",
        triggers=["be concise", "be detailed", "my name is", "call me", "i live in", 
                  "ask before", "confirm before", "don't ask", "no confirmation",
                  "set preference", "change preference"],
        handler=handle_set_preference,
        requires_confirmation=False,
        description="set a user preference",
        capability_type=CapabilityType.SYSTEM,
        examples=["Be concise", "My name is John", "I live in New York"]
    ))
    
    # Get Preferences
    registry.register(Capability(
        name="get_preferences",
        triggers=["my preferences", "show preferences", "what are my preferences", "settings"],
        handler=handle_get_preferences,
        requires_confirmation=False,
        description="show current preferences",
        capability_type=CapabilityType.SYSTEM,
        examples=["Show my preferences", "What are my settings?"]
    ))
    
    # Reset Preferences
    registry.register(Capability(
        name="reset_preferences",
        triggers=["reset preferences", "clear preferences", "default settings"],
        handler=handle_reset_preferences,
        requires_confirmation=True,
        description="reset preferences to defaults",
        capability_type=CapabilityType.SYSTEM,
        examples=["Reset my preferences"]
    ))
    

    
    # Recall Facts
    registry.register(Capability(
        name="recall_facts",
        triggers=["what do you remember", "what do you know about me", 
                  "recall", "my facts", "what did i tell you"],
        handler=handle_recall_facts,
        requires_confirmation=False,
        description="recall facts about you",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=["What do you remember about me?", "Recall my preferences"]
    ))
    
    # Forget - handler handles confirmation itself via ActionResult.confirm
    registry.register(Capability(
        name="forget",
        triggers=["forget everything", "forget all", "clear memory", "erase memory"],
        handler=handle_forget,
        requires_confirmation=False,  # Handler returns ActionResult.confirm
        description="forget stored memories",
        capability_type=CapabilityType.SYSTEM,
        examples=["Forget everything"]
    ))
    
    # Memory Stats
    registry.register(Capability(
        name="memory_stats",
        triggers=["memory stats", "memory status", "how much do you remember"],
        handler=handle_memory_stats,
        requires_confirmation=False,
        description="show memory statistics",
        capability_type=CapabilityType.SYSTEM,
        examples=["Memory stats", "How much do you remember?"]
    ))
    
    logger.info("Registered memory capabilities")
