"""
Preference and Memory Capabilities for Chintu Assistant.
Handlers for user preference management and memory operations.
"""

import logging
import re
from typing import Dict, Any

from ...core.capabilities import (
    ActionResult,
    Capability,
    CapabilityRegistry,
    CapabilityType,
    get_registry,
)
from .preferences import get_preference_manager
from .tiered_memory import get_memory_store, MemoryType

logger = logging.getLogger(__name__)


def _normalize_memory_text(content: str) -> str:
    """Normalize noisy memory lines into a user-facing fact sentence."""
    text = str(content or "").strip()
    if not text:
        return ""

    text = re.sub(r"^\s*[-*]\s*", "", text)
    prefix_patterns = (
        r"i(?:'|’)ll remember that:",
        r"i(?:'|’)ll remember:",
        r"i already know that:",
        r"remember that:",
    )
    changed = True
    while changed:
        changed = False
        for pattern in prefix_patterns:
            cleaned = re.sub(rf"^\s*{pattern}\s*", "", text, flags=re.IGNORECASE).strip()
            if cleaned != text:
                text = cleaned
                changed = True

    text = re.sub(r"\s*\((?:recorded|saved|added):[^)]*\)\s*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\byour\b", "the user's", text, flags=re.IGNORECASE)
    text = re.sub(r"\byou are\b", "the user is", text, flags=re.IGNORECASE)
    text = re.sub(r"\byou\b", "the user", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" -:\t")
    return text


def _memory_dedupe_key(content: str) -> str:
    normalized = _normalize_memory_text(content).lower()
    normalized = normalized.replace("’", "'")
    normalized = re.sub(r"'s\b", "", normalized)
    normalized = re.sub(r"\b(the user|the users|user)\b", "", normalized)
    normalized = re.sub(r"[^a-z0-9 ]+", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


# ============================================================================
# PREFERENCE CAPABILITIES
# ============================================================================

def handle_set_preference(text: str, context: Dict[str, Any]) -> ActionResult:
    """Set a user preference."""
    text_lower = text.lower()
    pref_manager = get_preference_manager()

    # Avoid false-positive preference updates when the user is asking for
    # content that includes "YouTube Short" phrasing.
    if "youtube short" in text_lower or "short script" in text_lower:
        return ActionResult.fail(
            "This looks like a content request, not a preference update.",
            "set_preference",
        )
    
    # Response style
    short_pref_intent = (
        "short" in text_lower
        and any(
            hint in text_lower
            for hint in (
                "response",
                "responses",
                "reply",
                "replies",
                "keep it short",
                "be short",
                "short answers",
            )
        )
    )
    if "concise" in text_lower or "brief" in text_lower or short_pref_intent:
        pref_manager.set("response_style", "concise")
        return ActionResult.ok("I'll keep my responses concise from now on.", capability="set_preference")
    
    if "detailed" in text_lower or "thorough" in text_lower or "elaborate" in text_lower:
        pref_manager.set("response_style", "detailed")
        return ActionResult.ok("I'll give more detailed responses from now on.", capability="set_preference")
    
    if "balanced" in text_lower:
        pref_manager.set("response_style", "balanced")
        return ActionResult.ok("I'll use a balanced response style.", capability="set_preference")

    # Tone / empathy / directness
    if "empathetic" in text_lower or "empathy" in text_lower:
        if "less" in text_lower or "not" in text_lower or "don't" in text_lower:
            pref_manager.set("empathy_level", "low")
            return ActionResult.ok("Understood. I'll keep empathy minimal and focus on direct answers.", capability="set_preference")
        pref_manager.set("empathy_level", "high")
        return ActionResult.ok("Got it. I'll respond more empathetically.", capability="set_preference")

    if "be direct" in text_lower or "direct" in text_lower:
        pref_manager.set("directness", "high")
        return ActionResult.ok("I'll be more direct and action-oriented.", capability="set_preference")

    if "be gentle" in text_lower or "soften" in text_lower:
        pref_manager.set("directness", "low")
        return ActionResult.ok("I'll use a gentler, softer style.", capability="set_preference")

    if "formal" in text_lower or "professional" in text_lower:
        pref_manager.set("tone_style", "formal")
        return ActionResult.ok("I'll keep the tone formal and professional.", capability="set_preference")

    if "casual" in text_lower or "warm" in text_lower:
        pref_manager.set("tone_style", "warm")
        return ActionResult.ok("I'll keep the tone warm and casual.", capability="set_preference")

    # Busy mode
    if "busy mode" in text_lower or "i'm busy" in text_lower or "im busy" in text_lower:
        pref_manager.set("busy_mode", True)
        return ActionResult.ok("Understood. I'll keep responses brief while you're busy.", capability="set_preference")

    if "not busy" in text_lower or "exit busy mode" in text_lower:
        pref_manager.set("busy_mode", False)
        return ActionResult.ok("Okay. Back to normal response length.", capability="set_preference")

    # Role preference
    if "cofounder" in text_lower or "co-founder" in text_lower:
        pref_manager.set("behavior_role", "cofounder")
        return ActionResult.ok("Got it. I'll act as your cofounder.", capability="set_preference")
    if "manager" in text_lower:
        pref_manager.set("behavior_role", "manager")
        return ActionResult.ok("Got it. I'll act as your manager.", capability="set_preference")
    if "assistant" in text_lower:
        pref_manager.set("behavior_role", "assistant")
        return ActionResult.ok("Got it. I'll act as your assistant.", capability="set_preference")
    if "buddy" in text_lower or "friend" in text_lower:
        pref_manager.set("behavior_role", "buddy")
        return ActionResult.ok("Got it. I'll keep a friendly buddy vibe.", capability="set_preference")
    if "advisor" in text_lower:
        pref_manager.set("behavior_role", "advisor")
        return ActionResult.ok("Got it. I'll act as an advisor.", capability="set_preference")

    if "entrepreneur" in text_lower or "entrepreneurial" in text_lower:
        pref_manager.set("entrepreneurial_mode", True)
        return ActionResult.ok("Entrepreneurial mode enabled.", capability="set_preference")

    if "standard mode" in text_lower:
        pref_manager.set("entrepreneurial_mode", False)
        return ActionResult.ok("Standard mode enabled.", capability="set_preference")
    
    # Name
    if "my name is" in text_lower or "call me" in text_lower:
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
        match = re.search(r"(?:i live in|i'm in|my location is)\s+(.+?)(?:\.|$)", text_lower)
        if match:
            location = match.group(1).strip().title()
            pref_manager.set("location", location)
            return ActionResult.ok(f"Got it! I'll remember you're in {location}.", capability="set_preference")
    
    return ActionResult.fail(
        "I can set preferences like: response style, tone (formal/warm), empathy level, busy mode, your role, name, location, or confirmation settings.",
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
    parts.append(f"Tone: {prefs.tone_style}")
    parts.append(f"Empathy: {prefs.empathy_level}")
    parts.append(f"Directness: {prefs.directness}")
    parts.append(f"Busy mode: {'On' if prefs.busy_mode else 'Off'}")
    parts.append(f"Role: {prefs.behavior_role}")
    parts.append(f"Entrepreneurial mode: {'On' if prefs.entrepreneurial_mode else 'Off'}")
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


def handle_update_mental_model(text: str, context: Dict[str, Any]) -> ActionResult:
    """Update the user's mental model (role, values, focus, communication style)."""
    text_lower = text.lower()
    try:
        from ..behavior import MentalModelManager
        manager = MentalModelManager()
        model = manager.model
    except Exception:
        return ActionResult.fail("Mental model storage isn't available right now.", "update_mental_model")

    updated: Dict[str, Any] = {}
    comm = dict(model.communication or {})

    # Role updates
    role_map = {
        "cofounder": "cofounder",
        "co-founder": "cofounder",
        "manager": "manager",
        "assistant": "assistant",
        "buddy": "buddy",
        "advisor": "advisor",
    }
    for key, role in role_map.items():
        if key in text_lower:
            updated["role"] = role
            break

    # Values
    if "values" in text_lower:
        import re
        match = re.search(r"values(?: are|:)?\\s*(.+)", text_lower)
        if match:
            raw = match.group(1)
            values = [v.strip(" .") for v in re.split(r",|and", raw) if v.strip()]
            if values:
                updated["values"] = values

    # Product focus
    if "focus on" in text_lower or "product focus" in text_lower:
        import re
        match = re.search(r"(?:focus on|product focus|focus:)?\\s*(.+)", text_lower)
        if match:
            raw = match.group(1)
            focus = [v.strip(" .") for v in re.split(r",|and", raw) if v.strip()]
            if focus:
                updated["product_focus"] = focus

    # Communication style
    if "tone" in text_lower:
        if "formal" in text_lower or "professional" in text_lower:
            comm["tone"] = "formal"
        elif "warm" in text_lower or "casual" in text_lower:
            comm["tone"] = "warm"
    if "empathy" in text_lower or "empathetic" in text_lower:
        if "less" in text_lower or "low" in text_lower:
            comm["empathy"] = "low"
        elif "high" in text_lower or "more" in text_lower:
            comm["empathy"] = "high"
        else:
            comm["empathy"] = "medium"
    if "direct" in text_lower or "directness" in text_lower:
        if "less" in text_lower or "low" in text_lower or "gentle" in text_lower:
            comm["directness"] = "low"
        elif "high" in text_lower or "more" in text_lower:
            comm["directness"] = "high"
        else:
            comm["directness"] = "medium"

    if comm != (model.communication or {}):
        updated["communication"] = comm

    if not updated:
        return ActionResult.fail(
            "Tell me what to update (role, values, product focus, or communication style). Example: "
            "'Set role to cofounder' or 'Values: clarity, speed, quality'.",
            "update_mental_model",
        )

    manager.update(**updated)
    return ActionResult.ok("Mental model updated.", {"updates": updated}, "update_mental_model")


# ============================================================================
# MEMORY CAPABILITIES
# ============================================================================

def handle_remember_fact(text: str, context: Dict[str, Any]) -> ActionResult:
    """Remember a fact about the user with perspective normalization and deduplication."""
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
    
    # Normalize perspective: "I love" -> "User loves", "my birthday" -> "user's birthday"
    fact_normalized = fact
    fact_normalized = re.sub(r'\b(i am|i\'m)\b', 'the user is', fact_normalized, flags=re.IGNORECASE)
    fact_normalized = re.sub(r'\b(i love|i like)\b', 'the user loves', fact_normalized, flags=re.IGNORECASE)
    fact_normalized = re.sub(r'\bmy\b', 'the user\'s', fact_normalized, flags=re.IGNORECASE)
    fact_normalized = re.sub(r'\bi\b', 'the user', fact_normalized, flags=re.IGNORECASE)
    
    # Check for duplicates (case-insensitive semantic normalization)
    new_key = _memory_dedupe_key(fact_normalized)
    existing_facts = memory.search_facts(fact_normalized) 
    for existing in existing_facts:
        if new_key and _memory_dedupe_key(getattr(existing, "content", "")) == new_key:
            display = _normalize_memory_text(getattr(existing, "content", "") or fact_normalized) or fact_normalized
            created_at = str(getattr(existing, "created_at", "") or "")
            stamp = created_at[:16].replace("T", " ") if created_at else "unknown time"
            return ActionResult.ok(
                f"I already know that: {display} (Recorded: {stamp})",
                {"fact": fact_normalized},
                "remember_fact",
            )
    
    memory.add_fact(fact_normalized, importance=0.7)
    try:
        from .markdown_sync import get_markdown_sync

        sync = get_markdown_sync()
        if sync:
            sync.append_fact(fact_normalized)
    except Exception:
        pass
    return ActionResult.ok(f"I'll remember that: {fact_normalized}", {"fact": fact_normalized}, "remember_fact")


def handle_recall_facts(text: str, context: Dict[str, Any]) -> ActionResult:
    """Recall facts about the user."""
    memory = get_memory_store()
    text_lower = text.lower()

    def _query_tokens(value: str) -> list[str]:
        """Extract meaningful query tokens and drop generic memory words."""
        stop_words = {
            "what",
            "when",
            "where",
            "which",
            "who",
            "how",
            "is",
            "are",
            "was",
            "were",
            "my",
            "your",
            "the",
            "a",
            "an",
            "about",
            "me",
            "you",
            "name",
            "names",
            "thing",
            "things",
            "detail",
            "details",
            "fact",
            "facts",
            "memory",
            "memories",
        }
        tokens = [tok for tok in re.findall(r"[a-z0-9]+", str(value or "").lower()) if len(tok) >= 3]
        return [tok for tok in tokens if tok not in stop_words]

    def _is_noisy_memory_line(content: str) -> bool:
        low = str(content or "").strip().lower()
        if not low:
            return True
        noisy_prefixes = (
            "here's what i remember",
            "i don't have any specific memories about",
            "you can tell me to 'remember",
            "[dry run]",
        )
        return low.startswith(noisy_prefixes)

    def _render_fact_lines(items: list[Any], limit: int = 5) -> list[str]:
        """Render fact bullets with strong de-duplication for user-facing recall."""
        lines: list[str] = []
        seen: set[str] = set()
        for item in items:
            content = str(getattr(item, "content", "") or "")
            if _is_noisy_memory_line(content):
                continue
            normalized = _normalize_memory_text(content) or content
            key = _memory_dedupe_key(normalized)
            if not key or key in seen:
                continue
            seen.add(key)
            created_at = str(getattr(item, "created_at", "") or "")
            stamp = created_at[:16].replace("T", " ") if created_at else "unknown time"
            lines.append(f"- {normalized} (recorded: {stamp})")
            if len(lines) >= int(limit):
                break
        return lines
    
    # Check for specific search
    query = None
    if "about" in text_lower:
        match = re.search(r"about\s+(.+?)(?:\?|$|\.|\!|is)", text_lower)
        if match:
            query = match.group(1).strip()
            # Clean common filler queries
            fillers = ["me so far", "me", "yourself", "you", "everything you know", "us"]
            if any(query == f or query.rstrip("?") == f for f in fillers):
                query = None
    
    # Fallback: If no "about" but looks like a specific question
    if not query:
        question_marks = ["what is", "what are", "do you know", "do i like", "tell me", "when is"]
        for prefix in question_marks:
            if prefix in text_lower:
                query = text_lower.split(prefix)[-1].strip()
                break
        
        # Remove ownership words and trailing punctuation for better matching
        if query:
            query = re.sub(r"\b(my|the|about)\b", "", query).strip().rstrip("?").strip()
            if not query or query in ["me", "you", "us"]:
                query = None
            
    if query:
        facts = memory.search_facts(query)
        # Fallback to semantic search (simulated by broad keyword search if specific failed)
        if not facts and " " in query:
             # Try splitting terms (naive semantic fallback)
             keywords = [w for w in query.split() if len(w) > 3]
             if keywords:
                 logger.info(f"Recall: Exact match failed for '{query}', trying keywords: {keywords}")
                 for kw in keywords:
                     facts.extend(memory.search_facts(kw))

        # Final fallback: scan stored facts and match by token overlap.
        if not facts:
            query_tokens = _query_tokens(query)
            if query_tokens:
                for item in memory.get_facts(limit=200):
                    content = str(getattr(item, "content", "") or "").lower()
                    if not content:
                        continue
                    if query.lower() in content:
                        facts.append(item)
                        continue
                    overlap = sum(1 for tok in query_tokens if tok in content)
                    if overlap >= max(1, min(2, len(query_tokens))):
                        facts.append(item)

        if facts:
            specificity_tokens = _query_tokens(query)
            if specificity_tokens:
                filtered_facts = []
                for item in facts:
                    content_low = str(getattr(item, "content", "") or "").lower()
                    if any(tok in content_low for tok in specificity_tokens):
                        filtered_facts.append(item)
                facts = filtered_facts

        if facts:
            # Deduplicate by normalized semantic key.
            seen = set()
            unique_facts = []
            for f in facts:
                if _is_noisy_memory_line(f.content):
                    continue
                key = _memory_dedupe_key(f.content)
                if not key or key in seen:
                    continue
                seen.add(key)
                unique_facts.append(f)
            if not unique_facts:
                # If retrieved rows were noisy, retry against raw fact storage.
                query_tokens = _query_tokens(query)
                recovered = []
                for item in memory.get_facts(limit=200):
                    content = str(getattr(item, "content", "") or "").lower()
                    if not content or _is_noisy_memory_line(content):
                        continue
                    if query.lower() in content:
                        recovered.append(item)
                        continue
                    overlap = sum(1 for tok in query_tokens if tok in content)
                    if query_tokens and overlap >= max(1, min(2, len(query_tokens))):
                        recovered.append(item)
                if recovered:
                    fact_lines = _render_fact_lines(recovered, limit=5)
                    if not fact_lines:
                        return ActionResult.ok(
                            f"I don't have any specific memories about '{query}'.",
                            capability="recall_facts",
                        )
                    fact_list = "\n".join(fact_lines)
                    return ActionResult.ok(
                        f"Here's what I remember about '{query}':\n{fact_list}",
                        capability="recall_facts",
                    )
                return ActionResult.ok(f"I don't have any specific memories about '{query}'.", capability="recall_facts")
            
            # Format with timestamp for temporal context
            fact_lines = _render_fact_lines(unique_facts, limit=5)
            if not fact_lines:
                return ActionResult.ok(
                    f"I don't have any specific memories about '{query}'.",
                    capability="recall_facts",
                )
            fact_list = "\n".join(fact_lines)
            return ActionResult.ok(f"Here's what I remember about '{query}':\n{fact_list}", capability="recall_facts")
        
        # Double fallback - suggest remembering
        return ActionResult.ok(f"I don't have any specific memories about '{query}'. You can tell me to 'remember that...' and I'll save it.", capability="recall_facts")
    
    # Get all facts
    facts = memory.get_facts(limit=20)
    if not facts:
        return ActionResult.ok("I don't have any facts stored yet. Say 'remember that...' to teach me.", capability="recall_facts")
    
    # Deduplicate
    seen = set()
    unique_facts = []
    for f in facts:
        if _is_noisy_memory_line(f.content):
            continue
        key = _memory_dedupe_key(f.content)
        if not key or key in seen:
            continue
        seen.add(key)
        unique_facts.append(f)
    if not unique_facts:
        return ActionResult.ok("I don't have any facts stored yet. Say 'remember that...' to teach me.", capability="recall_facts")
            
    fact_lines = _render_fact_lines(unique_facts, limit=len(unique_facts))
    if not fact_lines:
        return ActionResult.ok("I don't have any facts stored yet. Say 'remember that...' to teach me.", capability="recall_facts")
    fact_list = "\n".join(fact_lines)
    return ActionResult.ok(
        f"Here's what I remember about you:\n{fact_list}",
        {"facts": [_normalize_memory_text(f.content) or f.content for f in unique_facts]},
        "recall_facts",
    )


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
    
    return ActionResult.fail("Say 'forget everything' to clear all memories, or 'forget my [topic]' to forget specific facts.", "forget")


def handle_forget_specific(text: str, context: Dict[str, Any]) -> ActionResult:
    """Forget specific memories about a topic."""
    memory = get_memory_store()
    text_lower = text.lower()
    
    # Extract what to forget
    patterns = [
        r"forget (?:about )?my (.+?)(?:\.|$)",
        r"forget (?:that )?my (.+?)(?:\.|$)",
        r"delete (?:the )?memory (?:about|of) (?:my )?(.+?)(?:\.|$)",
        r"remove (?:the )?memory (?:about|of) (?:my )?(.+?)(?:\.|$)",
        r"erase (?:my )?(.+?) (?:memory|info|information)(?:\.|$)",
    ]
    
    topic = None
    for pattern in patterns:
        match = re.search(pattern, text_lower)
        if match:
            topic = match.group(1).strip()
            break
    
    if not topic:
        return ActionResult.fail(
            "What should I forget? Try: 'forget my favorite color' or 'forget about my birthday'.",
            "forget_specific"
        )
    
    # Search for matching facts
    try:
        candidates = [topic]
        candidates.append(topic.replace("'s", ""))
        candidates.append(topic.replace("'", ""))
        candidates = [c.strip() for c in candidates if c and c.strip()]

        facts_by_id: Dict[int, Any] = {}
        for candidate in candidates:
            for fact in memory.search_facts(candidate):
                if getattr(fact, "id", None) is not None:
                    facts_by_id[int(fact.id)] = fact

        # Fallback: broaden matching against stored facts when keyword intersection is too strict.
        if not facts_by_id:
            topic_words = [
                w for w in re.findall(r"[a-z0-9]+", topic.lower())
                if w not in {"my", "the", "about", "that", "is", "name"}
            ]
            for fact in memory.get_facts(limit=200):
                content = str(getattr(fact, "content", "") or "").lower()
                if not content:
                    continue
                if topic.lower() in content:
                    facts_by_id[int(fact.id)] = fact
                    continue
                if topic_words and sum(1 for w in topic_words if w in content) >= max(1, min(2, len(topic_words))):
                    facts_by_id[int(fact.id)] = fact

        facts = list(facts_by_id.values())
        if not facts:
            return ActionResult.ok(
                f"I don't have any memories about '{topic}'.",
                {"topic": topic, "deleted": 0},
                "forget_specific"
            )
        
        # Delete matching facts
        deleted_count = 0
        for fact in facts:
            try:
                memory.delete_fact(fact.id)
                deleted_count += 1
            except Exception as e:
                logger.warning(f"Failed to delete fact {fact.id}: {e}")
        
        if deleted_count > 0:
            return ActionResult.ok(
                f"Done! I've forgotten {deleted_count} memory(ies) about '{topic}'.",
                {"topic": topic, "deleted": deleted_count},
                "forget_specific"
            )
        else:
            return ActionResult.fail(
                f"I found memories about '{topic}' but couldn't delete them.",
                "forget_specific"
            )
            
    except Exception as e:
        logger.error(f"Error forgetting specific memory: {e}")
        return ActionResult.fail(f"I had trouble forgetting that: {e}", "forget_specific")


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


def handle_task_history_lookup(text: str, context: Dict[str, Any]) -> ActionResult:
    """Answer task-history questions from indexed run dossiers with provenance."""
    try:
        from ...core.task_history import get_task_history_manager

        manager = get_task_history_manager()
        session_id = str((context or {}).get("session_id") or "")
        answer = manager.answer_history_question(text, limit=3, session_id=session_id)
        matches = answer.get("matches") if isinstance(answer, dict) else []
        return ActionResult.ok(
            str(answer.get("message") or ""),
            {
                "matches": matches if isinstance(matches, list) else [],
            },
            "task_history_lookup",
        )
    except Exception as exc:
        logger.error("Task history lookup failed: %s", exc)
        return ActionResult.fail("I couldn't query task history right now.", "task_history_lookup")




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

    # Update Mental Model
    registry.register(Capability(
        name="update_mental_model",
        triggers=[
            "set role", "update mental model", "set values", "values are", "product focus",
            "focus on", "act as", "be my cofounder", "be my manager", "be my advisor",
        ],
        handler=handle_update_mental_model,
        requires_confirmation=False,
        description="update your mental model (role, values, focus, communication style)",
        capability_type=CapabilityType.MEMORY,
        examples=["Set role to cofounder", "Values: clarity, speed, quality", "Focus on developer tools"],
    ))
    

    # Remember Fact
    registry.register(Capability(
        name="remember_fact",
        triggers=["remember that", "remember this", "remember", "note that", "save the fact that"],
        handler=handle_remember_fact,
        requires_confirmation=False,
        description="remember a fact about the user",
        capability_type=CapabilityType.MEMORY,
        examples=["Remember that I love emerald green", "Remember that my birthday is January 1st"]
    ))
    
    # Recall Facts
    registry.register(Capability(
        name="recall_facts",
        triggers=["what do you remember", "what do you know about me", 
                  "recall", "my facts", "what did i tell you", "what is my",
                  "do you know my", "do i like", "list my memories", "list all my memories", "all my memories"],
        handler=handle_recall_facts,
        requires_confirmation=False,
        description="recall facts about you",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=["What do you remember about me?", "Recall my preferences", "What color do I like?"]
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
    
    # Forget Specific - forget specific memories about a topic
    registry.register(Capability(
        name="forget_specific",
        triggers=["forget my", "forget about my", "delete memory about", 
                  "remove memory about", "erase my"],
        handler=handle_forget_specific,
        requires_confirmation=False,
        description="forget specific memories about a topic",
        capability_type=CapabilityType.SYSTEM,
        examples=["Forget my favorite color", "Forget about my birthday"]
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

    # Task History Lookup
    registry.register(Capability(
        name="task_history_lookup",
        triggers=[
            "task history",
            "run history",
            "execution history",
            "last run",
            "previous run",
            "previous task",
            "show run dossiers",
            "what happened in my last task",
            "what did you do earlier",
        ],
        handler=handle_task_history_lookup,
        requires_confirmation=False,
        description="answer task-history questions with dossier provenance",
        capability_type=CapabilityType.MEMORY,
        examples=["What happened in my last task?", "Show task history with evidence"],
    ))
    
    logger.info("Registered memory capabilities")
