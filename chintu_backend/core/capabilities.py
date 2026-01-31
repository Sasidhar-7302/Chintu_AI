"""
Capability Registry System for Chintu Assistant.
Provides a formal, auditable skill registry instead of implicit if/else.

Integrates with PolicyEngine for safety guardrails.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Any, TYPE_CHECKING
from enum import Enum

# Import policy engine for safety checks
try:
    from .policy import get_policy_engine, PolicyDecision
    HAS_POLICY = True
except ImportError:
    HAS_POLICY = False

# Import degraded mode for offline/quiet checks
try:
    from .degraded_mode import get_degraded_mode, SystemMode
    HAS_DEGRADED = True
except ImportError:
    HAS_DEGRADED = False

logger = logging.getLogger(__name__)


class CapabilityType(Enum):
    """Types of capabilities for categorization."""
    SYSTEM = "system"        # OS-level actions (open app, system info)
    COMMUNICATION = "comm"   # Chat, questions
    PRODUCTIVITY = "prod"    # Notes, tasks, reminders
    AUTOMATION = "auto"      # Scripts, workflows
    MEMORY = "memory"        # Recall, facts, history
    AI_AGENT = "ai_agent"    # Deep reasoning, autonomous tasks


@dataclass
class ActionResult:
    """Result of a capability execution."""
    success: bool
    message: str
    data: Optional[Any] = None
    requires_confirmation: bool = False
    pending_action: Optional[Callable] = None
    capability_name: str = ""
    
    @staticmethod
    def ok(message: str, data: Any = None, capability: str = "") -> "ActionResult":
        return ActionResult(success=True, message=message, data=data, capability_name=capability)
    
    @staticmethod
    def fail(message: str, capability: str = "") -> "ActionResult":
        return ActionResult(success=False, message=message, capability_name=capability)
    
    @staticmethod
    def confirm(message: str, pending_action: Callable, capability: str = "") -> "ActionResult":
        return ActionResult(
            success=True, 
            message=message, 
            requires_confirmation=True,
            pending_action=pending_action,
            capability_name=capability
        )


@dataclass
class Capability:
    """
    A registered capability that Chintu can execute.
    
    Attributes:
        name: Unique identifier for this capability
        triggers: List of phrases/keywords that trigger this capability
        handler: Function to execute the action
        requires_confirmation: Whether to ask user before executing
        description: Human-readable description of what this does
        capability_type: Category of capability
        examples: Example phrases for this capability
    """
    name: str
    triggers: List[str]
    handler: Callable[[str, Dict[str, Any]], ActionResult]
    requires_confirmation: bool = False
    description: str = ""
    capability_type: CapabilityType = CapabilityType.SYSTEM
    examples: List[str] = field(default_factory=list)
    # Metadata for Intent-based routing
    intent_type: Optional[Any] = None
    complexity: Optional[Any] = None
    
    def matches(self, text: str) -> bool:
        """
        Check if text matches any trigger.
        
        Smart matching rules:
        - Allow question-based triggers like "what time", "what do you remember"
        - Block action triggers when phrased as exploratory questions
        - Handle "can you X" and "please X" as action intents (strip and match)
        """
        text_lower = text.lower().strip()
        
        # Normalize polite prefixes - treat "can you open" as "open"
        polite_prefixes = ["can you ", "could you ", "please ", "would you ", "will you "]
        normalized = text_lower
        polite_request = False
        for prefix in polite_prefixes:
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix):]
                polite_request = True
                break
        
        question_starters = ("what", "why", "how", "when", "where", "who", "which")
        is_question = text_lower.endswith("?") or text_lower.startswith(question_starters)
        exploratory_patterns = [
            "how do i ", "how can i ", "how to ", "how would i ",
            "what is ", "what's ", "who is ", "where is ", "when is ", "why is ",
            "what is the way to ", "tell me how to ", "tell me about ",
            "explain ", "define ", "definition of ", "meaning of ",
            "write a ", "tell me a ", "tell a ", "draft a ", "create a "
        ]
        
        # Check if text contains a URL/domain but is an informational question
        url_extensions = [".com", ".org", ".io", ".net", ".edu", ".gov"]
        has_url = any(ext in text_lower for ext in url_extensions)
        is_url_question = has_url and any(text_lower.startswith(p) for p in exploratory_patterns)
        
        # Check for trigger matches
        for trigger in self.triggers:
            trigger_lower = trigger.lower()
            # Use word-boundary matching for single-word triggers to avoid
            # false positives like "open" matching "opened".
            def _trigger_match(needle: str, haystack: str) -> bool:
                if not needle:
                    return False
                # Check if it looks like a regex pattern (special characters present)
                if any(c in needle for c in "()[]?*+^$|"):
                    try:
                        return re.search(needle, haystack) is not None
                    except re.error:
                        pass
                # Word boundary check for simple keywords
                if " " not in needle and needle.replace("_", "").isalnum():
                    pattern = r"\b" + re.escape(needle) + r"\b"
                    return re.search(pattern, haystack) is not None
                # Standard substring fallback
                return needle in haystack

            # Check both original and normalized text
            if _trigger_match(trigger_lower, text_lower) or _trigger_match(trigger_lower, normalized):
                # If trigger itself is a question phrase (like "what time"), always allow
                if trigger_lower.startswith(("what ", "how much", "my ", "show ")):
                    return True

                action_prefixes = (
                    "open", "go to", "visit", "browse", "launch", "start", "run",
                    "remind", "set ", "cancel", "delete", "clear"
                )
                action_keywords = (".com", ".org", ".io", ".net", "website")
                is_action_trigger = (
                    trigger_lower.startswith(action_prefixes)
                    or trigger_lower in action_keywords
                )

                # Block URL-question (e.g., "what is github.com") from triggering actions
                if is_action_trigger and is_url_question:
                    return False
                
                # For action triggers, block exploratory questions unless it's a polite request
                if is_action_trigger and ((is_question and not polite_request) or any(text_lower.startswith(p) for p in exploratory_patterns)):
                    return False
                
                return True
        
        return False
    
    def get_match_score(self, text: str) -> float:
        """Get a match score (0-1) based on trigger matches."""
        import re
        text_lower = text.lower().strip()
        best_score = 0.0
        
        # Priority mapping for capability types
        TYPE_PRIORITY = {
            CapabilityType.SYSTEM: 0.1,      # Core system commands should be stable
            CapabilityType.AI_AGENT: 0.05,
            CapabilityType.MEMORY: 0.05,
            CapabilityType.PRODUCTIVITY: 0.0,
            CapabilityType.COMMUNICATION: -0.1
        }
        
        def _trigger_match_info(needle: str, haystack: str) -> Optional[float]:
            if not needle:
                return None
            
            # regex check
            if any(c in needle for c in "()[]?*+^$|"):
                try:
                    match = re.search(needle, haystack)
                    if match:
                        # Score based on how big a chunk of the text the regex explained
                        return len(match.group(0)) / len(haystack)
                except re.error:
                    pass
            
            # Keyword boundary check
            if " " not in needle and needle.replace("_", "").isalnum():
                pattern = r"\b" + re.escape(needle) + r"\b"
                match = re.search(pattern, haystack)
                if match:
                    return len(needle) / len(haystack)
            
            # Substring check
            if needle in haystack:
                return len(needle) / len(haystack)
            
            return None

        for trigger in self.triggers:
            match_score = _trigger_match_info(trigger.lower(), text_lower)
            if match_score is not None:
                # Add type-based priority
                priority = TYPE_PRIORITY.get(self.capability_type, 0.0)
                final_score = match_score + priority
                
                # Bonus for long triggers (more specific)
                if len(trigger) > 10:
                    final_score += 0.05
                    
                if final_score > best_score:
                    best_score = final_score
                    
        return best_score


class CapabilityRegistry:
    """
    Central registry for all Chintu capabilities.
    Ensures no LLM executes OS actions directly - all go through registered handlers.
    """
    
    def __init__(self):
        self._capabilities: Dict[str, Capability] = {}
        self._pending_confirmation: Optional[ActionResult] = None
        logger.info("CapabilityRegistry initialized")
    
    @staticmethod
    def get_instance() -> "CapabilityRegistry":
        """Singleton access for legacy/compatibility callers."""
        return get_registry()

    def register(self, capability: Optional[Capability] = None, **kwargs) -> None:
        """Register a new capability. 
        Supports both Capability objects and raw arguments for compatibility.
        """
        if capability is None:
            # Create from kwargs if passed separately (legacy/alternate API)
            name = kwargs.get("name")
            handler = kwargs.get("handler")
            triggers = kwargs.get("triggers", kwargs.get("patterns", []))
            description = kwargs.get("description", "")
            
            if not name or not handler:
                logger.error("Registry.register: name and handler are required")
                return

            capability = Capability(
                name=name,
                handler=handler,
                triggers=triggers,
                description=description,
                capability_type=kwargs.get("capability_type", CapabilityType.SYSTEM),
                examples=kwargs.get("examples", [])
            )

        if capability.name in self._capabilities:
            logger.info(f"Overwriting existing capability: {capability.name}")
        self._capabilities[capability.name] = capability
        logger.debug(f"Registered capability: {capability.name} with triggers {capability.triggers}")
    
    def get(self, name: str) -> Optional[Capability]:
        """Get a capability by name."""
        return self._capabilities.get(name)
    
    def match(self, text: str) -> Optional[Capability]:
        """
        Find the best matching capability for the given text.
        Returns None if no capability matches (should route to LLM conversation).
        """
        if not text:
            return None
        
        # Score all capabilities
        scored = []
        for cap in self._capabilities.values():
            if cap.matches(text):
                score = cap.get_match_score(text)
                scored.append((score, cap))
        
        if not scored:
            return None
        
        # Return highest scoring match
        scored.sort(key=lambda x: x[0], reverse=True)
        best = scored[0][1]
        logger.debug(f"Matched capability: {best.name} for text: '{text[:50]}...'")
        return best
    
    def execute(self, capability: Capability, text: str, context: Dict[str, Any] = None) -> ActionResult:
        """
        Execute a capability's handler.
        
        Flow:
        1. Check policy engine for safety/risk
        2. If denied, return error
        3. If confirmation required, prompt user
        4. Execute handler
        """
        context = context or {}
        
        # === Degraded Mode Check ===
        if HAS_DEGRADED and not context.get("_degraded_checked"):
            try:
                degraded = get_degraded_mode()
                availability = degraded.is_available(capability.name)
                if not availability.available:
                    msg = availability.reason or "This capability is unavailable right now."
                    if availability.alternative:
                        msg += f" Try: {availability.alternative}"
                    return ActionResult.fail(msg, capability.name)
                if availability.degraded and availability.reason:
                    context["_degraded_reason"] = availability.reason
                context["_degraded_checked"] = True
            except Exception as e:
                logger.warning(f"Degraded mode check failed, allowing execution: {e}")

        # === Policy Check ===
        if HAS_POLICY and not context.get("_policy_checked"):
            try:
                policy_engine = get_policy_engine()
                # Refresh policy system state from degraded mode and battery status
                if HAS_DEGRADED:
                    try:
                        degraded = get_degraded_mode()
                        mode = degraded.get_mode()
                        has_internet = degraded.check_internet()
                        policy_engine.update_system_state(
                            has_internet=bool(has_internet),
                            is_offline_mode=mode == SystemMode.OFFLINE,
                            is_quiet_mode=mode == SystemMode.QUIET,
                        )
                    except Exception as e:
                        logger.debug(f"Policy system state update (degraded) failed: {e}")

                try:
                    import psutil
                    battery = psutil.sensors_battery()
                    if battery:
                        policy_engine.update_system_state(
                            battery_percent=int(battery.percent)
                        )
                except Exception:
                    pass
                policy = policy_engine.evaluate(capability.name, context)
                
                # DENY - block execution
                if policy.decision == PolicyDecision.DENY:
                    logger.warning(f"Policy DENIED capability: {capability.name} - {policy.reason}")
                    msg = f"I can't do that right now. {policy.reason}"
                    if policy.suggested_alternative:
                        msg += f" Try: {policy.suggested_alternative}"
                    return ActionResult.fail(msg, capability.name)
                
                # REQUIRE_PLAN - show plan preview first
                if policy.decision == PolicyDecision.REQUIRE_PLAN:
                    logger.info(f"Policy requires PLAN for: {capability.name}")
                    plan_summary = None
                    # Attempt to get a plan preview from the capability handler
                    try:
                        plan_ctx = context.copy()
                        plan_ctx["_policy_checked"] = True
                        plan_ctx["_plan_only"] = True
                        plan_result = capability.handler(text, plan_ctx)
                        if plan_result and not plan_result.success:
                            return plan_result
                        if plan_result and plan_result.message:
                            plan_summary = plan_result.message
                    except Exception as e:
                        logger.warning(f"Plan preview failed, falling back: {e}")

                    if not plan_summary:
                        try:
                            from .executive import get_executive_brain
                            plan = get_executive_brain().create_plan(text)
                            plan_summary = plan.get_summary()
                        except Exception:
                            plan_summary = "This is a multi-step action."

                    def pending_with_plan():
                        ctx = context.copy()
                        ctx["_policy_checked"] = True
                        ctx["_confirmed"] = True
                        return capability.handler(text, ctx)
                    result = ActionResult.confirm(
                        f"{plan_summary}\n\nProceed?",
                        pending_with_plan,
                        capability.name,
                    )
                    self._pending_confirmation = result
                    return result
                
                # REQUIRE_CONFIRMATION - ask before executing
                if policy.decision == PolicyDecision.REQUIRE_CONFIRMATION:
                    if not context.get("_confirmed"):
                        logger.info(f"Policy requires CONFIRMATION for: {capability.name}")
                        def pending_confirmed():
                            ctx = context.copy()
                            ctx["_policy_checked"] = True
                            ctx["_confirmed"] = True
                            return capability.handler(text, ctx)
                        result = ActionResult.confirm(
                            f"I need your confirmation. {policy.reason}",
                            pending_confirmed,
                            capability.name
                        )
                        self._pending_confirmation = result
                        return result
                
                # ALLOW - mark as checked and continue
                context["_policy_checked"] = True
                
            except Exception as e:
                logger.warning(f"Policy check failed, allowing execution: {e}")
        
        try:
            # Legacy confirmation check (if capability.requires_confirmation is True)
            if capability.requires_confirmation and not context.get("_confirmed"):
                def pending():
                    ctx = context.copy()
                    ctx["_confirmed"] = True
                    return capability.handler(text, ctx)
                result = ActionResult.confirm(
                    f"I'm about to {capability.description}. Do you want me to proceed?",
                    pending,
                    capability.name
                )
                self._pending_confirmation = result
                return result
            
            # Execute the handler
            result = capability.handler(text, context)
            result.capability_name = capability.name

            degraded_reason = context.get("_degraded_reason")
            if degraded_reason and result.success:
                result.message = f"{result.message}\n\nNote: {degraded_reason}"
            
            # If handler itself returned a confirmation request, store it
            if result.requires_confirmation and result.pending_action:
                self._pending_confirmation = result
            
            return result
            
        except Exception as e:
            logger.error(f"Capability execution failed: {capability.name} - {e}")
            return ActionResult.fail(f"Sorry, I couldn't complete that action: {e}", capability.name)
    
    def confirm_pending(self) -> Optional[ActionResult]:
        """Execute a pending action that was waiting for confirmation."""
        if not self._pending_confirmation or not self._pending_confirmation.pending_action:
            return None
        
        try:
            result = self._pending_confirmation.pending_action()
            self._pending_confirmation = None
            if result and result.requires_confirmation and result.pending_action:
                self._pending_confirmation = result
            return result
        except Exception as e:
            logger.error(f"Confirmed action failed: {e}")
            self._pending_confirmation = None
            return ActionResult.fail(f"Action failed: {e}")
    
    def cancel_pending(self) -> None:
        """Cancel a pending action."""
        if self._pending_confirmation:
            logger.info("Pending action cancelled")
            self._pending_confirmation = None
    
    def has_pending(self) -> bool:
        """Check if there's a pending confirmation."""
        return self._pending_confirmation is not None
    
    def list_capabilities(self) -> List[Dict[str, Any]]:
        """List all registered capabilities for debugging/UI."""
        return [
            {
                "name": cap.name,
                "description": cap.description,
                "type": cap.capability_type.value,
                "requires_confirmation": cap.requires_confirmation,
                "triggers": cap.triggers,
                "examples": cap.examples,
            }
            for cap in self._capabilities.values()
        ]
    
    def explain_action(self, capability_name: str, text: str) -> str:
        """Explain why an action was taken (for explainability mode)."""
        cap = self.get(capability_name)
        if not cap:
            return "Unknown action."
        
        matched_triggers = [t for t in cap.triggers if t.lower() in text.lower()]
        trigger_str = ", ".join(matched_triggers) if matched_triggers else "context"
        
        return f"I detected '{trigger_str}' in your request, which triggered the {cap.name} capability. {cap.description}"


# Global registry instance
_registry: Optional[CapabilityRegistry] = None


def get_registry() -> CapabilityRegistry:
    """Get or create the global capability registry."""
    global _registry
    if _registry is None:
        _registry = CapabilityRegistry()
    return _registry
