"""
Rule Engine: Evaluates signals against strict logic to generate suggestions.
"""

import logging
import time
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass
from .signals import get_signal_manager

logger = logging.getLogger(__name__)

@dataclass
class Suggestion:
    text: str
    action_type: str  # e.g., "suggestion"
    priority: int     # 1 (low) to 10 (high)
    rule_id: str
    payload: Optional[Dict[str, Any]] = None

@dataclass
class Rule:
    id: str
    name: str
    condition: Callable[[Dict[str, Any]], bool]
    suggestion_text: str
    priority: int = 5
    cooldown_seconds: float = 3600.0  # Default 1 hour cooldown per rule

class RuleEngine:
    """
    Evaluates a set of Rules against the current Signals.
    """
    
    def __init__(self):
        self.rules: List[Rule] = []
        self._last_triggered: Dict[str, float] = {}  # rule_id -> timestamp
        
    def add_rule(self, rule: Rule):
        """Register a new rule."""
        self.rules.append(rule)
        
    def evaluate(self) -> List[Suggestion]:
        """
        Check all rules against current signals.
        Returns a list of Suggestions to be presented to the user.
        """
        signals = get_signal_manager().get_signals()
        suggestions = []
        now = time.time()
        
        for rule in self.rules:
            # Check cooldown
            last_run = self._last_triggered.get(rule.id, 0)
            if now - last_run < rule.cooldown_seconds:
                continue
                
            try:
                # Evaluate condition
                if rule.condition(signals):
                    logger.info(f"Rule triggered: {rule.name}")
                    self._last_triggered[rule.id] = now
                    
                    suggestions.append(Suggestion(
                        text=rule.suggestion_text,
                        action_type="suggestion",
                        priority=rule.priority,
                        rule_id=rule.id
                    ))
            except Exception as e:
                logger.error(f"Error evaluating rule {rule.id}: {e}")
                
        # Sort by priority (highest first)
        suggestions.sort(key=lambda s: s.priority, reverse=True)
        return suggestions

# Singleton
_rule_engine = None

def get_rule_engine():
    global _rule_engine
    if _rule_engine is None:
        _rule_engine = RuleEngine()
    return _rule_engine
