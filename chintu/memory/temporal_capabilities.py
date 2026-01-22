"""Temporal Memory Capabilities.

Voice commands for temporal queries and memory management.
"""

import logging
import re
from typing import Dict, Any
from datetime import datetime, timedelta

from ..core.capabilities import ActionResult

logger = logging.getLogger(__name__)


def handle_what_did_i_say(text: str, context: Dict[str, Any]) -> ActionResult:
    """Recall what user said about a topic.
    
    Examples:
    - "What did I say about coffee?"
    - "What did I mention yesterday about work?"
    """
    from .temporal_graph import get_temporal_graph
    
    graph = get_temporal_graph()
    text_lower = text.lower()
    
    # Extract topic
    patterns = [
        r"what did i (?:say|mention|talk) about (.+?)(?:\?|$)",
        r"what (?:have i|did i) (?:say|said) about (.+?)(?:\?|$)",
    ]
    
    topic = None
    for pattern in patterns:
        match = re.search(pattern, text_lower)
        if match:
            topic = match.group(1).strip()
            break
    
    if not topic:
        return ActionResult.fail("What topic should I look for?", "temporal_recall")
    
    # Check for time modifier
    period = None
    if "yesterday" in text_lower:
        period = "yesterday"
    elif "last week" in text_lower:
        period = "last_week"
    elif "today" in text_lower:
        period = "today"
    
    statements = graph.what_did_i_say_about(topic, period)
    
    if not statements:
        if period:
            return ActionResult.ok(
                f"I don't have any record of you mentioning '{topic}' {period.replace('_', ' ')}.",
                {"topic": topic, "period": period},
                "temporal_recall"
            )
        return ActionResult.ok(
            f"I don't have any record of you mentioning '{topic}'.",
            {"topic": topic},
            "temporal_recall"
        )
    
    # Format response
    if len(statements) == 1:
        response = f"You said: \"{statements[0]}\""
    else:
        response = f"You mentioned '{topic}' {len(statements)} times:\n"
        for stmt in statements[:5]:
            response += f"  • \"{stmt[:100]}...\"\n" if len(stmt) > 100 else f"  • \"{stmt}\"\n"
    
    return ActionResult.ok(response, {"statements": statements[:5]}, "temporal_recall")


def handle_when_did_i_mention(text: str, context: Dict[str, Any]) -> ActionResult:
    """Find when a topic was last mentioned.
    
    Examples:
    - "When did I mention the project?"
    - "When did I talk about vacation?"
    """
    from .temporal_graph import get_temporal_graph
    
    graph = get_temporal_graph()
    
    # Extract topic
    match = re.search(r"when did i (?:mention|say|talk about) (.+?)(?:\?|$)", text.lower())
    if not match:
        return ActionResult.fail("What topic should I look for?", "temporal_when")
    
    topic = match.group(1).strip()
    timestamp = graph.when_did_i_mention(topic)
    
    if not timestamp:
        return ActionResult.ok(
            f"I don't have any record of you mentioning '{topic}'.",
            {"topic": topic},
            "temporal_when"
        )
    
    # Format time naturally
    now = datetime.now()
    diff = now - timestamp
    
    if diff.days == 0:
        time_str = f"today at {timestamp.strftime('%I:%M %p')}"
    elif diff.days == 1:
        time_str = f"yesterday at {timestamp.strftime('%I:%M %p')}"
    elif diff.days < 7:
        time_str = f"{diff.days} days ago"
    else:
        time_str = f"on {timestamp.strftime('%B %d')}"
    
    return ActionResult.ok(
        f"You mentioned '{topic}' {time_str}.",
        {"topic": topic, "timestamp": timestamp.isoformat()},
        "temporal_when"
    )


def handle_conversation_history(text: str, context: Dict[str, Any]) -> ActionResult:
    """Show recent conversation history.
    
    Examples:
    - "What did we discuss today?"
    - "Show our conversation history"
    """
    from .temporal_graph import get_temporal_graph
    
    graph = get_temporal_graph()
    text_lower = text.lower()
    
    # Determine time range
    if "today" in text_lower:
        since = datetime.now().replace(hour=0, minute=0, second=0)
    elif "yesterday" in text_lower:
        since = (datetime.now() - timedelta(days=1)).replace(hour=0, minute=0)
    elif "this week" in text_lower:
        since = datetime.now() - timedelta(days=7)
    else:
        since = None
    
    conversations = graph.get_conversations(since=since, limit=10)
    
    if not conversations:
        return ActionResult.ok(
            "No conversation history found for that period.",
            {},
            "conversation_history"
        )
    
    response = f"Here are {len(conversations)} recent exchanges:\n\n"
    for conv in conversations[:5]:
        time_str = conv.timestamp.strftime("%I:%M %p")
        snippet = conv.user_input[:60] + "..." if len(conv.user_input) > 60 else conv.user_input
        response += f"• [{time_str}] You: \"{snippet}\"\n"
    
    return ActionResult.ok(response, {"count": len(conversations)}, "conversation_history")


def handle_remember_fact(text: str, context: Dict[str, Any]) -> ActionResult:
    """Store a fact in temporal memory.
    
    Examples:
    - "Remember that my birthday is May 15"
    - "Remember I like coffee"
    """
    from .temporal_graph import get_temporal_graph
    
    graph = get_temporal_graph()
    
    # Extract fact
    patterns = [
        r"remember (?:that )?(.+)",
        r"note (?:that )?(.+)",
        r"save (?:that )?(.+)",
    ]
    
    fact = None
    for pattern in patterns:
        match = re.search(pattern, text.lower())
        if match:
            fact = match.group(1).strip()
            break
    
    if not fact:
        return ActionResult.fail("What should I remember?", "remember_fact")
    
    # Parse into subject-predicate-object (simple approach)
    # "my birthday is May 15" -> user, birthday, May 15
    # "I like coffee" -> user, likes, coffee
    
    if " is " in fact:
        parts = fact.split(" is ", 1)
        subject = parts[0].replace("my ", "user_")
        predicate = "is"
        obj = parts[1]
    elif " like " in fact:
        subject = "user"
        predicate = "likes"
        obj = fact.split(" like ", 1)[1]
    else:
        subject = "user"
        predicate = "stated"
        obj = fact
    
    graph.add_fact(subject, predicate, obj, source="user_stated")
    
    return ActionResult.ok(
        f"I'll remember that: {fact}",
        {"subject": subject, "predicate": predicate, "object": obj},
        "remember_fact"
    )


def handle_what_do_you_know(text: str, context: Dict[str, Any]) -> ActionResult:
    """List facts known about user or topic.
    
    Examples:
    - "What do you know about me?"
    - "What do you remember?"
    """
    from .temporal_graph import get_temporal_graph
    
    graph = get_temporal_graph()
    
    # Get facts about user
    facts = graph.get_facts_about("user")
    
    if not facts:
        return ActionResult.ok(
            "I don't have any facts stored yet. Tell me something to remember!",
            {},
            "what_do_you_know"
        )
    
    response = f"Here's what I know ({len(facts)} facts):\n\n"
    for fact in facts[:10]:
        response += f"• {fact.subject} {fact.predicate} {fact.object_value}\n"
    
    return ActionResult.ok(response, {"count": len(facts)}, "what_do_you_know")


def register_temporal_capabilities():
    """Register temporal memory capabilities."""
    from ..core.capabilities import get_registry, Capability, CapabilityType
    
    registry = get_registry()
    
    # What did I say about...
    registry.register(Capability(
        name="what_did_i_say",
        triggers=[
            "what did i say about",
            "what did i mention",
            "what was i talking about",
        ],
        handler=handle_what_did_i_say,
        description="Recall past statements about a topic",
        capability_type=CapabilityType.MEMORY,
        examples=["What did I say about coffee?", "What did I mention yesterday?"],

    ))
    
    # When did I mention...
    registry.register(Capability(
        name="temporal_when",
        handler=handle_when_did_i_mention,
        triggers=[
            "when did i mention",
            "when did i say",
            "when did i talk about",
        ],
        description="Find when you mentioned a topic",
        capability_type=CapabilityType.MEMORY,
        examples=["When did I mention the project?"],

    ))
    
    # Conversation history
    registry.register(Capability(
        name="conversation_history",
        handler=handle_conversation_history,
        triggers=[
            "our conversation history",
            "my conversation history",
            "what did we discuss",
            "what did we talk about",
            "show recent conversations",
            "show conversations",
        ],
        description="Show conversation history",
        capability_type=CapabilityType.MEMORY,
        examples=["What did we discuss today?", "Show conversation history"],

    ))
    
    # Remember that...
    registry.register(Capability(
        name="remember_fact",
        handler=handle_remember_fact,
        triggers=[
            "remember that",
            "remember i",
            "note that",
            "save that",
        ],
        description="Store a fact in memory",
        capability_type=CapabilityType.MEMORY,
        examples=["Remember that my birthday is May 15"],

    ))
    
    # What do you know...
    registry.register(Capability(
        name="what_do_you_know",
        handler=handle_what_do_you_know,
        triggers=[
            "what do you know",
            "what do you remember",
            "what facts do you have",
        ],
        description="List stored facts",
        capability_type=CapabilityType.MEMORY,
        examples=["What do you know about me?"],

    ))
    
    logger.info("Registered temporal memory capabilities")
