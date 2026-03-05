from enum import Enum
from typing import List, Dict, Any, Optional
import re
import logging

logger = logging.getLogger("PolicyEngine")

class Decision(Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK_USER = "ask_user"

class PolicyRule:
    def __init__(self, pattern: str, decision: Decision, description: str = ""):
        self.pattern = pattern
        self.regex = re.compile(pattern)
        self.decision = decision
        self.description = description

    def matches(self, action_type: str) -> bool:
        return bool(self.regex.match(action_type))

class PolicyEngine:
    """
    Evaluates actions against a set of rules to determine if they should be
    Allowed, Denied, or require User Approval.
    """
    def __init__(self):
        # Default Rules
        # Order matters: First match wins.
        self.rules: List[PolicyRule] = [
            # 1. System/Internal events are always allowed
            PolicyRule(r"^connect$", Decision.ALLOW),
            PolicyRule(r"^disconnect$", Decision.ALLOW),
            PolicyRule(r"^state_update$", Decision.ALLOW),
            PolicyRule(r"^transcript$", Decision.ALLOW),
            PolicyRule(r"^response$", Decision.ALLOW),
            PolicyRule(r"^audio_level$", Decision.ALLOW),
            PolicyRule(r"^log_event$", Decision.ALLOW),
            PolicyRule(r"^heartbeat$", Decision.ALLOW),
            
            # 2. UI Actions (Input) are allowed
            PolicyRule(r"^ui_action$", Decision.ALLOW),
            PolicyRule(r"^push_to_talk$", Decision.ALLOW),
            PolicyRule(r"^text_input$", Decision.ALLOW),
            
            # 3. Dangerous / Sensitive Actions -> ASK USER
            PolicyRule(r"^shell_exec$", Decision.ASK_USER, "Execute Shell Command"),
            PolicyRule(r"^file_write$", Decision.ASK_USER, "Write to File"),
            PolicyRule(r"^browser_control$", Decision.ASK_USER, "Control Browser"),
            
            # 4. Unknown/Generic events -> ALLOW (for now, to avoid breaking legacy)
            # In a strict mode, this would be DENY.
            PolicyRule(r".*", Decision.ALLOW, "Default Allow"),
        ]
        
    def evaluate(self, node_id: str, action_type: str, payload: Dict[str, Any]) -> Decision:
        """
        Evaluate an action.
        
        Args:
            node_id: Source Node ID.
            action_type: Event type or Command name.
            payload: Full message payload.
            
        Returns:
            Decision enum.
        """
        # Specific check: If wrapper "event" type, look inside
        check_type = action_type
        if action_type == "event" and "payload" in payload:
            inner_event = payload.get("payload", {}).get("event")
            if inner_event:
                check_type = inner_event
                
        for rule in self.rules:
            if rule.matches(check_type):
                logger.debug(f"Rule Match: {rule.pattern} -> {rule.decision.value}")
                return rule.decision
                
        return Decision.ALLOW
