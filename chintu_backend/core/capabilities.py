"""
Capability Registry System for Chintu Assistant.
Provides a formal, auditable skill registry instead of implicit if/else.

Integrates with PolicyEngine for safety guardrails.
"""

import logging
import re
import os
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Any, TYPE_CHECKING, Type
from enum import Enum
from pydantic import BaseModel, ValidationError

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

# Allow submodule imports like chintu_backend.core.capabilities.memory_tool
# by treating this module as a namespace package when a sibling directory exists.
try:
    from pathlib import Path as _Path

    _cap_pkg_dir = _Path(__file__).with_name("capabilities")
    if _cap_pkg_dir.is_dir():
        __path__ = [str(_cap_pkg_dir)]
except Exception:
    pass


class CapabilityType(Enum):
    """Types of capabilities for categorization."""
    SYSTEM = "system"        # OS-level actions (open app, system info)
    COMMUNICATION = "comm"   # Chat, questions
    PRODUCTIVITY = "prod"    # Notes, tasks, reminders
    AUTOMATION = "auto"      # Scripts, workflows
    MEMORY = "memory"        # Recall, facts, history
    AI_AGENT = "ai_agent"    # Deep reasoning, autonomous tasks
    ADMIN = "admin"          # Admin-level restricted actions
    DEVELOPER = "developer"  # Coding and debugging tools


@dataclass
class ActionResult:
    """Result of a capability execution."""
    success: bool
    message: str
    data: Optional[Any] = None
    requires_confirmation: bool = False
    confirmation_type: Optional[str] = None
    pending_action: Optional[Callable] = None
    capability_name: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": bool(self.success),
            "message": str(self.message),
            "data": self.data,
            "requires_confirmation": bool(self.requires_confirmation),
            "confirmation_type": self.confirmation_type,
            "capability_name": self.capability_name,
        }
    
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
    # Pydantic Schema for strict validation (Phase 4)
    schema: Optional[Type[BaseModel]] = None
    
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

            prefix_boost = 0.6  # Strong signal that user explicitly invoked a capability.
            # If the user starts their request with a specific multi-word trigger
            # (e.g. "my downloads folder is a mess ..."), treat it as a near-certain
            # match even if the full text is long (paths/extra instructions dilute
            # length-based ratios).
            is_specific_phrase = (" " in needle) and (len(needle) >= 10)
            
            # regex check
            if any(c in needle for c in "()[]?*+^$|"):
                try:
                    match = re.search(needle, haystack)
                    if match:
                        # Score based on how big a chunk of the text the regex explained
                        base = len(match.group(0)) / len(haystack)
                        if match.start() == 0:
                            if is_specific_phrase:
                                return 1.0
                            base += prefix_boost
                        return min(base, 1.0)
                except re.error:
                    pass
            
            # Keyword boundary check
            if " " not in needle and needle.replace("_", "").isalnum():
                pattern = r"\b" + re.escape(needle) + r"\b"
                match = re.search(pattern, haystack)
                if match:
                    base = len(needle) / len(haystack)
                    if match.start() == 0:
                        base += prefix_boost
                    return min(base, 1.0)
            
            # Substring check
            if needle in haystack:
                base = len(needle) / len(haystack)
                if haystack.startswith(needle):
                    if is_specific_phrase:
                        return 1.0
                    base += prefix_boost
                return min(base, 1.0)
            
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

                if final_score > 1.0:
                    final_score = 1.0
                    
                if final_score > best_score:
                    best_score = final_score
                     
        return min(best_score, 1.0)


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
                examples=kwargs.get("examples", []),
                schema=kwargs.get("schema")  # Phase 4: Schema Support
            )

        if capability.name in self._capabilities and not kwargs.get("allow_override", False):
            raise ValueError(f"Capability '{capability.name}' is already registered. Silent overrides are blocked for security.")
            
        if capability.name in self._capabilities:
            logger.warning(f"Overwriting existing capability: {capability.name} (Force allowed)")
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
        best, _ = self.match_with_score(text)
        return best

    def match_with_score(self, text: str) -> tuple[Optional[Capability], float]:
        """Return best matching capability and score (0-1)."""
        if not text:
            return None, 0.0

        scored = []
        for cap in self._capabilities.values():
            if cap.matches(text):
                score = cap.get_match_score(text)
                scored.append((score, cap))

        if not scored:
            return None, 0.0

        scored.sort(key=lambda x: x[0], reverse=True)
        best_score, best = scored[0]
        logger.debug(f"Matched capability: {best.name} (score={best_score:.3f}) for text: '{text[:50]}...'")
        return best, float(best_score)

    def _unknown_capability_requires_confirmation(self, capability: Capability, text: str) -> bool:
        """Heuristic safety check for capabilities that have no policy contract yet."""
        if capability.requires_confirmation:
            return True
        if capability.capability_type in {
            CapabilityType.ADMIN,
            CapabilityType.DEVELOPER,
            CapabilityType.AI_AGENT,
        }:
            return True

        risky_terms = {
            "delete",
            "remove",
            "reset",
            "erase",
            "format",
            "shutdown",
            "restart",
            "kill",
            "terminate",
            "execute",
            "command",
            "shell",
            "script",
            "write",
            "modify",
            "install",
            "uninstall",
            "submit",
            "purchase",
            "transfer",
            "login",
            "token",
            "secret",
            "password",
        }
        combined = " ".join(
            [
                capability.name or "",
                capability.description or "",
                " ".join(capability.triggers or []),
                text or "",
            ]
        ).lower()
        return any(term in combined for term in risky_terms)
    
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
        if "_request_text" not in context:
            context["_request_text"] = text
        agent_policy = context.get("_agent_policy")
        if agent_policy and hasattr(agent_policy, "allows"):
            try:
                if not agent_policy.allows(capability.name):
                    return ActionResult.fail(
                        f"Agent policy blocked tool: {capability.name}",
                        capability.name,
                    )
            except Exception:
                pass
        contract = None
        if HAS_POLICY:
            try:
                contract = get_policy_engine().get_contract(capability.name)
            except Exception:
                contract = None
        
        # If no contract exists, use a conservative heuristic:
        # confirm only risky/important actions, allow clearly safe ones.
        if not contract:
            needs_confirm = self._unknown_capability_requires_confirmation(capability, text)
            logger.warning(
                "No policy contract found for '%s'. Using unknown-capability heuristic (confirm=%s).",
                capability.name,
                needs_confirm,
            )
            if needs_confirm and not context.get("_confirmed"):
                def pending_closed():
                    ctx = context.copy()
                    ctx["_confirmed"] = True
                    ctx["_policy_checked"] = True
                    _maybe_record_action_approval(ctx)
                    return capability.handler(text, ctx)
                
                return ActionResult.confirm(
                    f"{capability.name} is not yet classified for safety. Confirm to run it this time.",
                    pending_closed,
                    capability.name
                )
            context["_policy_checked"] = True

        def _requires_system_lock() -> bool:
            if not contract:
                return False
            try:
                from .system_control import SYSTEM_CONTROL_SIDE_EFFECTS
                return any(effect in SYSTEM_CONTROL_SIDE_EFFECTS for effect in (contract.side_effects or []))
            except Exception:
                return False

        def _wrap_with_system_lock(func: Callable[[], ActionResult]) -> Callable[[], ActionResult]:
            if not _requires_system_lock():
                return func

            def guarded() -> ActionResult:
                try:
                    from .system_control import get_system_control_arbiter
                    arbiter = get_system_control_arbiter()
                    if not arbiter.acquire(capability.name):
                        return ActionResult.fail("System control is busy. Please try again.", capability.name)
                    try:
                        return func()
                    finally:
                        arbiter.release()
                except Exception as exc:
                    return ActionResult.fail(f"System control arbitration failed: {exc}", capability.name)

            return guarded

        def _maybe_record_exec_approval(ctx: Dict[str, Any]) -> None:
            """Record an exec approval when confirmations happen outside the handler.

            Some confirmations occur in the policy/legacy wrappers before the handler runs,
            which would otherwise bypass the handler-level ExecApprovalLedger recording.
            """
            try:
                if str(capability.name or "") != "terminal_exec":
                    return
                from chintu_backend.core.config import get_config
                from chintu_backend.policy.exec_approvals import get_exec_approval_ledger

                cfg = get_config()
                if not getattr(cfg, "exec_approval_enabled", True):
                    return

                params = ctx.get("_validated_params") or ctx.get("_extracted_params") or {}
                command = None
                cwd = None
                if isinstance(params, dict):
                    command = params.get("command")
                    cwd = params.get("cwd")
                else:
                    command = getattr(params, "command", None)
                    cwd = getattr(params, "cwd", None)
                command = str(command or "").strip()
                cwd_str = str(cwd or "").strip() or None
                if not command:
                    return

                ledger = get_exec_approval_ledger()
                ttl = int(getattr(cfg, "exec_approval_ttl_minutes", 10))
                ledger.record_approval(command, cwd_str, ttl_minutes=ttl)
            except Exception:
                return

        def _maybe_record_action_approval(ctx: Dict[str, Any]) -> None:
            """Record sensitive-action approvals for policy replay/audit (Phase 8)."""
            try:
                from chintu_backend.core.config import get_config
                from chintu_backend.policy.action_approvals import get_action_approval_ledger
                from chintu_backend.policy.action_risk import build_action_scope

                cfg = get_config()
                if not bool(getattr(cfg, "action_approval_enabled", True)):
                    return
                request_text = str(ctx.get("_request_text") or text or "").strip()
                scope = build_action_scope(capability.name, request_text, ctx)
                if not scope.categories:
                    return
                ledger = get_action_approval_ledger()
                ttl = int(getattr(cfg, "action_approval_ttl_minutes", 20))
                ledger.record_approval(
                    scope_hash=scope.scope_hash,
                    capability_name=capability.name,
                    categories=list(scope.categories),
                    ttl_minutes=ttl,
                    note=f"confirmed:{capability.name}",
                )
            except Exception:
                return
        
        # === Schema Validation (Phase 4) ===
        if capability.schema:
            try:
                # If we have extracted parameters in context (from ActionDispatcher), validate them
                params = context.get("_extracted_params", {})
                # If params is empty/None, we might skip validation if handler parses text manually
                # But if schema is strict, we should probably warn or try.
                # For now: Only validate if params are present OR if we want to enforce it.
                if params:
                    validated = capability.schema(**params)
                    # Update context with validated object for handler to use
                    context["_validated_params"] = validated
            except ValidationError as e:
                logger.warning(f"Schema validation failed for {capability.name}: {e}")
                return ActionResult.fail(f"Invalid parameters: {e}", capability.name)

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
                contract = policy_engine.get_contract(capability.name)
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
                        # Potentially call internal planning here if available, 
                        # but for now we just check if a plan is already present.
                    except Exception:
                        pass

                    plan_summary = context.get("_plan_summary")
                    if not plan_summary:
                        try:
                            # Use new LLMToolRouter for planning instead of stale ExecutiveBrain
                            from .llm_tool_router import LLMToolRouter
                            from .config import get_config
                            config = context.get("config") or get_config()
                            # Pass 'self' as registry if needed, though Router usually takes registry
                            router = LLMToolRouter(self, context.get("llm"), config)
                            steps = router.decompose(text)
                            
                            plan_summary = "**Proposed Plan:**\n"
                            for i, s in enumerate(steps):
                                plan_summary += f"{i+1}. {s.text}\n"
                            
                        except Exception as e:
                            logger.error(f"Planning failed: {e}")
                            plan_summary = "Could not generate plan preview."
                            logger.warning(f"Unified planning failed: {e}")
                            plan_summary = f"Multi-step execution required for: {text}"
                    
                    if not context.get("_confirmed"):
                        def pending_plan_confirmed():
                            ctx = context.copy()
                            ctx["_policy_checked"] = True
                            ctx["_confirmed"] = True
                            _maybe_record_action_approval(ctx)
                            return capability.handler(text, ctx)

                        pending_plan_confirmed = _wrap_with_system_lock(pending_plan_confirmed)
                        result = ActionResult.confirm(
                            f"{plan_summary}\n\nReply 'yes' to execute this plan.",
                            pending_plan_confirmed,
                            capability.name,
                        )
                        result.confirmation_type = "plan"
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
                            _maybe_record_exec_approval(ctx)
                            _maybe_record_action_approval(ctx)
                            return capability.handler(text, ctx)
                        pending_confirmed = _wrap_with_system_lock(pending_confirmed)
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

        # === Dry Run (Test/Validation Mode) ===
        if context.get("dry_run"):
            mode = str(context.get("dry_run_mode") or "side_effects").lower()
            should_dry_run = False
            if mode == "all":
                should_dry_run = True
            elif mode == "side_effects":
                if contract and getattr(contract, "side_effects", None):
                    should_dry_run = True
                if capability.capability_type in {CapabilityType.SYSTEM, CapabilityType.AUTOMATION}:
                    should_dry_run = True
            if should_dry_run:
                return ActionResult.ok(
                    f"[DRY RUN] Would execute capability: {capability.name}",
                    {"dry_run": True},
                    capability.name,
                )
        
        try:
            # Legacy confirmation check (if capability.requires_confirmation is True)
            if capability.requires_confirmation and not context.get("_confirmed"):
                def pending():
                    ctx = context.copy()
                    ctx["_confirmed"] = True
                    _maybe_record_exec_approval(ctx)
                    _maybe_record_action_approval(ctx)
                    return capability.handler(text, ctx)
                pending = _wrap_with_system_lock(pending)
                result = ActionResult.confirm(
                    f"I'm about to {capability.description}. Do you want me to proceed?",
                    pending,
                    capability.name
                )
                self._pending_confirmation = result
                return result
            
            # Execute the handler
            if _requires_system_lock():
                from .system_control import get_system_control_arbiter
                arbiter = get_system_control_arbiter()
                if not arbiter.acquire(capability.name):
                    return ActionResult.fail("System control is busy. Please try again.", capability.name)
                try:
                    result = capability.handler(text, context)
                finally:
                    arbiter.release()
            else:
                result = capability.handler(text, context)
            result.capability_name = capability.name

            degraded_reason = context.get("_degraded_reason")
            if degraded_reason and result.success:
                result.message = f"{result.message}\n\nNote: {degraded_reason}"
            
            # If handler itself returned a confirmation request, store it
            if result.requires_confirmation and result.pending_action:
                original_pending = _wrap_with_system_lock(result.pending_action)

                def pending_with_approval_record() -> ActionResult:
                    ctx = context.copy()
                    ctx["_confirmed"] = True
                    _maybe_record_exec_approval(ctx)
                    _maybe_record_action_approval(ctx)
                    return original_pending()

                result.pending_action = pending_with_approval_record
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

    def pending_snapshot(self) -> Dict[str, Any]:
        """Return a non-sensitive snapshot of the pending confirmation (if any)."""
        pending = self._pending_confirmation
        if not pending:
            return {}
        return {
            "pending": True,
            "capability": pending.capability_name or "",
            "message": pending.message or "",
            "confirmation_type": pending.confirmation_type or "",
        }
    
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

    def unregister(self, name: str) -> None:
        """Remove a capability by name."""
        if name in self._capabilities:
            self._capabilities.pop(name, None)

    def unregister_prefix(self, prefix: str) -> int:
        """Remove all capabilities with a given prefix."""
        to_remove = [k for k in self._capabilities if k.startswith(prefix)]
        for key in to_remove:
            self._capabilities.pop(key, None)
        return len(to_remove)
    
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
