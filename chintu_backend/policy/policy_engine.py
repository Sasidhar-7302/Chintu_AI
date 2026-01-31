"""Action policy engine for Chintu AI Assistant."""

import logging
from enum import Enum
from dataclasses import dataclass
from typing import Dict, Optional, Set

from .capability_contracts import RiskLevel, CapabilityContract

logger = logging.getLogger(__name__)


class PolicyDecision(Enum):
    """Policy decisions for action execution."""

    ALLOW = "allow"                      # Execute immediately
    REQUIRE_CONFIRMATION = "confirm"     # Ask user to confirm
    REQUIRE_PLAN = "plan"                # Show plan before execution
    DENY = "deny"                        # Block execution


@dataclass
class ActionPolicy:
    """Result of policy evaluation for an action."""

    decision: PolicyDecision
    reason: str
    risk_level: RiskLevel
    requires_internet: bool = False
    suggested_alternative: Optional[str] = None


@dataclass
class SystemState:
    """Current system state for policy decisions."""

    has_internet: bool = True
    battery_percent: int = 100
    is_low_battery: bool = False
    is_quiet_mode: bool = False    # No TTS, minimal interactions
    is_offline_mode: bool = False  # Force offline operation
    rate_limited: bool = False     # API rate limits hit


class ActionPolicyEngine:
    """
    Evaluates policies for capability executions.

    This is the guardrails layer that decides what is safe to do and when
    to ask for confirmation. It considers:
    - Capability risk level
    - System state (battery, network, etc.)
    - User preferences
    """

    # Capabilities that always need confirmation regardless of preferences
    ALWAYS_CONFIRM: Set[str] = {
        "forget", "reset_preferences", "clear_notes"
    }

    # Capabilities that need plan preview for multi-step operations
    NEEDS_PLAN_PREVIEW: Set[str] = {
        "execute_workflow", "transfer_data", "schedule_workflow"
    }

    # Capabilities safe even in degraded modes
    ALWAYS_SAFE: Set[str] = {
        "help", "what_can_you_do", "status", "system_info",
        "get_preferences", "recall_facts", "memory_stats"
    }

    # Default contracts for known capabilities (fallback if not declared)
    DEFAULT_CONTRACTS: Dict[str, CapabilityContract] = {
        # System - No risk (READ ONLY - NO CONFIRMATION NEEDED)
        "help": CapabilityContract(RiskLevel.NONE),
        "what_can_you_do": CapabilityContract(RiskLevel.NONE),
        "status": CapabilityContract(RiskLevel.NONE),
        "system_info": CapabilityContract(RiskLevel.NONE),
        "why": CapabilityContract(RiskLevel.NONE),
        "history": CapabilityContract(RiskLevel.NONE),
        "read_response": CapabilityContract(RiskLevel.NONE),
        "list_windows": CapabilityContract(RiskLevel.NONE),  # Read-only - no confirmation
        "screenshot": CapabilityContract(RiskLevel.NONE),  # Just captures screen
        "context_query": CapabilityContract(RiskLevel.NONE),  # Read-only context info
        "time": CapabilityContract(RiskLevel.NONE),  # Just returns time
        "get_last_opened_app": CapabilityContract(RiskLevel.NONE),  # Read-only
        "list_apps": CapabilityContract(RiskLevel.NONE),  # Read-only app listing
        "clipboard": CapabilityContract(RiskLevel.NONE),  # Read clipboard - safe

        # Read operations - Low risk
        "get_preferences": CapabilityContract(RiskLevel.LOW),
        "recall_facts": CapabilityContract(RiskLevel.LOW),
        "memory_stats": CapabilityContract(RiskLevel.LOW),
        "list_files": CapabilityContract(RiskLevel.LOW),
        "read_file": CapabilityContract(RiskLevel.LOW),
        "clipboard_read": CapabilityContract(RiskLevel.LOW),
        "list_reminders": CapabilityContract(RiskLevel.LOW),
        "task_status": CapabilityContract(RiskLevel.LOW),
        "list_scheduled": CapabilityContract(RiskLevel.LOW),
        "check_tasks": CapabilityContract(RiskLevel.LOW),
        "list_tasks": CapabilityContract(RiskLevel.LOW),
        "recall": CapabilityContract(RiskLevel.LOW),
        "read_document": CapabilityContract(RiskLevel.LOW),
        "find_file": CapabilityContract(RiskLevel.LOW),
        "live_search": CapabilityContract(RiskLevel.LOW, requires_internet=True),
        "browse_url": CapabilityContract(RiskLevel.LOW, requires_internet=True),
        "repeat_command": CapabilityContract(RiskLevel.LOW),
        "mcp_list_tools": CapabilityContract(RiskLevel.LOW),
        "watchdog_list": CapabilityContract(RiskLevel.LOW),
        "watchdog_check": CapabilityContract(RiskLevel.LOW),
        "orchestrator_project_status": CapabilityContract(RiskLevel.LOW),
        "orchestrator_missing_inputs": CapabilityContract(RiskLevel.LOW),
        "orchestrator_list_inputs": CapabilityContract(RiskLevel.LOW),

        # Local actions - Low risk
        "open_app": CapabilityContract(RiskLevel.LOW, side_effects=["open_application"]),
        "open_url": CapabilityContract(RiskLevel.LOW, requires_internet=True, side_effects=["open_browser"]),
        "close_app": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_confirmation=False,
            side_effects=["close_application"],
        ),
        "control_window": CapabilityContract(RiskLevel.LOW, side_effects=["window_control"]),
        "switch_window": CapabilityContract(RiskLevel.LOW, side_effects=["window_control"]),
        "clipboard_copy": CapabilityContract(RiskLevel.LOW, side_effects=["modify_clipboard"]),
        "set_reminder": CapabilityContract(RiskLevel.LOW, side_effects=["create_task"]),
        "note_taking": CapabilityContract(RiskLevel.LOW, side_effects=["modify_notes"]),
        "set_preference": CapabilityContract(RiskLevel.LOW, side_effects=["modify_preferences"]),
        "remember_fact": CapabilityContract(RiskLevel.LOW, side_effects=["modify_memory"]),
        "file_info": CapabilityContract(RiskLevel.LOW),
        "watchdog_add": CapabilityContract(RiskLevel.LOW, side_effects=["create_monitor"]),
        "watchdog_remove": CapabilityContract(RiskLevel.LOW, side_effects=["remove_monitor"]),
        "orchestrator_create_project": CapabilityContract(RiskLevel.LOW, side_effects=["create_project"]),
        "orchestrator_set_input": CapabilityContract(RiskLevel.LOW, side_effects=["store_input"]),
        "orchestrator_pause_project": CapabilityContract(RiskLevel.LOW, side_effects=["pause_project"]),
        "orchestrator_resume_project": CapabilityContract(RiskLevel.LOW, side_effects=["resume_project"]),
        "orchestrator_cancel_project": CapabilityContract(RiskLevel.LOW, side_effects=["cancel_project"]),
        "generate_thumbnail": CapabilityContract(RiskLevel.LOW, side_effects=["create_image"]),

        # Web operations - Medium risk
        "web_search": CapabilityContract(RiskLevel.MEDIUM, requires_internet=True),
        "news_search": CapabilityContract(RiskLevel.MEDIUM, requires_internet=True),
        "deep_search": CapabilityContract(RiskLevel.MEDIUM, requires_internet=True),
        "open_browser": CapabilityContract(RiskLevel.MEDIUM, requires_internet=True, side_effects=["browser_action"]),
        "browser_search": CapabilityContract(RiskLevel.MEDIUM, requires_internet=True, side_effects=["browser_action"]),
        "screenshot": CapabilityContract(RiskLevel.MEDIUM, side_effects=["capture_screen"]),
        "page_content": CapabilityContract(RiskLevel.MEDIUM, requires_internet=True),
        "mcp_call_tool": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_confirmation=True,
            side_effects=["mcp_tool_call"],
        ),

        # Browser automation - Medium/High risk
        "click_link": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_internet=True,
            requires_confirmation=False,
            side_effects=["browser_click"],
        ),
        "close_browser": CapabilityContract(RiskLevel.MEDIUM, side_effects=["close_browser"]),

        # Workflows - Medium risk (require plan preview)
        "execute_workflow": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_confirmation=True,
            side_effects=["multi_step_action"],
        ),
        "plan_task": CapabilityContract(RiskLevel.LOW),
        "quick_action": CapabilityContract(RiskLevel.MEDIUM, requires_internet=True),

        # Screen Control - Medium risk (no confirmation for seamless typing)
        "screen_control": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_confirmation=False,
            side_effects=["mouse_keyboard_action"],
        ),

        # Automation - Medium risk
        "schedule_workflow": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_confirmation=True,
            side_effects=["create_scheduled_task"],
        ),
        "orchestrator_run": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_confirmation=False,
            side_effects=["run_project_steps"],
        ),
        "orchestrator_approve_step": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_confirmation=False,
            side_effects=["approve_project_step"],
        ),
        "background_task": CapabilityContract(
            RiskLevel.MEDIUM,
            can_run_background=True,
            side_effects=["background_execution"],
        ),
        "transfer_data": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_confirmation=True,
            side_effects=["cross_app_transfer"],
        ),
        "sandbox_run": CapabilityContract(
            RiskLevel.HIGH,
            requires_confirmation=True,
            side_effects=["sandbox_execution"],
        ),
        "cancel_scheduled": CapabilityContract(RiskLevel.LOW, side_effects=["remove_scheduled_task"]),
        "cancel_reminder": CapabilityContract(RiskLevel.LOW, side_effects=["remove_task"]),

        # Destructive - High risk
        "forget": CapabilityContract(
            RiskLevel.HIGH,
            requires_confirmation=True,
            side_effects=["delete_memory"],
        ),
        "reset_preferences": CapabilityContract(
            RiskLevel.HIGH,
            requires_confirmation=True,
            side_effects=["reset_settings"],
        ),
        "fix_code": CapabilityContract(
            RiskLevel.HIGH,
            requires_confirmation=True,
            side_effects=["modify_files", "sandbox_execution"],
        ),
        "email_read_codes": CapabilityContract(
            RiskLevel.HIGH,
            requires_confirmation=True,
            side_effects=["read_email"],
        ),
        "identity_store_secret": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_confirmation=False,
            side_effects=["store_secret"],
        ),
        "identity_list_secrets": CapabilityContract(
            RiskLevel.LOW,
            requires_confirmation=False,
            side_effects=["list_secrets"],
        ),
        "identity_get_secret": CapabilityContract(
            RiskLevel.CRITICAL,
            requires_confirmation=True,
            side_effects=["read_secret"],
        ),
        "identity_delete_secret": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_confirmation=True,
            side_effects=["delete_secret"],
        ),
        "login_to": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_confirmation=True,
            side_effects=["auto_login"],
        ),
        "save_login": CapabilityContract(
            RiskLevel.LOW,
            requires_confirmation=False,
            side_effects=["store_login"],
        ),
        "setup_vault": CapabilityContract(
            RiskLevel.LOW,
            requires_confirmation=False,
            side_effects=["setup_vault"],
        ),
        "unlock_vault": CapabilityContract(
            RiskLevel.LOW,
            requires_confirmation=False,
            side_effects=["unlock_vault"],
        ),
        "list_logins": CapabilityContract(
            RiskLevel.LOW,
            requires_confirmation=False,
            side_effects=["list_logins"],
        ),

        # LLM fallback - Low risk
        "conversation": CapabilityContract(RiskLevel.LOW, requires_internet=True),
    }

    def __init__(self, preferences=None):
        """
        Initialize the policy engine.

        Args:
            preferences: PreferenceManager instance for user prefs
        """
        self._preferences = preferences
        self._system_state = SystemState()
        self._custom_contracts: Dict[str, CapabilityContract] = {}
        logger.info("ActionPolicyEngine initialized")

    def register_contract(self, capability_name: str, contract: CapabilityContract):
        """Register a custom contract for a capability."""
        self._custom_contracts[capability_name] = contract
        logger.debug("Registered contract for %s: %s", capability_name, contract.risk_level.value)

    def get_contract(self, capability_name: str) -> CapabilityContract:
        """Get the contract for a capability."""
        if capability_name in self._custom_contracts:
            return self._custom_contracts[capability_name]
        if capability_name in self.DEFAULT_CONTRACTS:
            return self.DEFAULT_CONTRACTS[capability_name]
        logger.warning("No contract found for capability: %s, defaulting to confirmation-required", capability_name)
        return CapabilityContract(RiskLevel.MEDIUM, requires_confirmation=True)

    def update_system_state(self, **kwargs):
        """
        Update system state for policy decisions.

        Args:
            has_internet: Whether internet is available
            battery_percent: Current battery percentage
            is_quiet_mode: Whether in quiet/noise mode
            rate_limited: Whether API rate limits are hit
        """
        for key, value in kwargs.items():
            if hasattr(self._system_state, key):
                setattr(self._system_state, key, value)

        if "battery_percent" in kwargs:
            self._system_state.is_low_battery = kwargs["battery_percent"] < 20

        if "has_internet" in kwargs and not kwargs["has_internet"]:
            self._system_state.is_offline_mode = True

        logger.debug(
            "System state updated: internet=%s, battery=%s%%, quiet=%s",
            self._system_state.has_internet,
            self._system_state.battery_percent,
            self._system_state.is_quiet_mode,
        )

    def evaluate(self, capability_name: str, context: Optional[Dict] = None) -> ActionPolicy:
        """
        Evaluate policy for a capability execution.

        Args:
            capability_name: Name of the capability to evaluate
            context: Optional context (e.g., specific parameters)

        Returns:
            ActionPolicy with decision and reasoning
        """
        contract = self.get_contract(capability_name)

        if contract.requires_internet and not self._system_state.has_internet:
            return ActionPolicy(
                decision=PolicyDecision.DENY,
                reason=f"'{capability_name}' requires internet, but you're offline",
                risk_level=contract.risk_level,
                requires_internet=True,
                suggested_alternative=self._get_offline_alternative(capability_name),
            )

        if not contract.can_run_low_battery and self._system_state.is_low_battery:
            return ActionPolicy(
                decision=PolicyDecision.DENY,
                reason=f"'{capability_name}' is disabled in low battery mode",
                risk_level=contract.risk_level,
            )

        if capability_name in self.ALWAYS_CONFIRM:
            return ActionPolicy(
                decision=PolicyDecision.REQUIRE_CONFIRMATION,
                reason=f"'{capability_name}' always requires confirmation due to potential data loss",
                risk_level=contract.risk_level,
            )

        if capability_name in self.NEEDS_PLAN_PREVIEW:
            return ActionPolicy(
                decision=PolicyDecision.REQUIRE_PLAN,
                reason=f"'{capability_name}' is a multi-step action that needs plan preview",
                risk_level=contract.risk_level,
            )

        if contract.requires_confirmation:
            return ActionPolicy(
                decision=PolicyDecision.REQUIRE_CONFIRMATION,
                reason=f"'{capability_name}' has side effects: {', '.join(contract.side_effects)}",
                risk_level=contract.risk_level,
            )

        if contract.risk_level == RiskLevel.HIGH:
            return ActionPolicy(
                decision=PolicyDecision.REQUIRE_CONFIRMATION,
                reason=f"'{capability_name}' is a high-risk action",
                risk_level=contract.risk_level,
            )

        if contract.risk_level == RiskLevel.CRITICAL:
            return ActionPolicy(
                decision=PolicyDecision.DENY,
                reason=f"'{capability_name}' is a critical-risk action that's currently blocked",
                risk_level=contract.risk_level,
            )

        return ActionPolicy(
            decision=PolicyDecision.ALLOW,
            reason="Action is within normal risk parameters",
            risk_level=contract.risk_level,
            requires_internet=contract.requires_internet,
        )

    def _get_offline_alternative(self, capability_name: str) -> Optional[str]:
        """Suggest an offline alternative for an online-only capability."""
        alternatives = {
            "web_search": "Try 'recall facts' to check your saved knowledge",
            "news_search": "No offline alternative available",
            "deep_search": "Try 'read file' to search local documents",
            "browser_search": "Use 'open app' to launch a local application instead",
            "conversation": "Local model will be used for basic responses",
        }
        return alternatives.get(capability_name)

    def is_safe_for_background(self, capability_name: str) -> bool:
        """Check if a capability is safe to run in background."""
        contract = self.get_contract(capability_name)
        return contract.can_run_background and contract.risk_level.value in ["none", "low"]

    def get_risk_summary(self, capability_names):
        """Get a risk summary for multiple capabilities (e.g., workflow steps)."""
        risks = {level.value: 0 for level in RiskLevel}
        requires_confirmation = []
        requires_internet = []

        for name in capability_names:
            contract = self.get_contract(name)
            risks[contract.risk_level.value] += 1
            if contract.requires_confirmation:
                requires_confirmation.append(name)
            if contract.requires_internet:
                requires_internet.append(name)

        overall_risk = RiskLevel.NONE
        if risks["critical"] > 0:
            overall_risk = RiskLevel.CRITICAL
        elif risks["high"] > 0:
            overall_risk = RiskLevel.HIGH
        elif risks["medium"] > 0:
            overall_risk = RiskLevel.MEDIUM
        elif risks["low"] > 0:
            overall_risk = RiskLevel.LOW

        return {
            "overall_risk": overall_risk.value,
            "risk_breakdown": risks,
            "requires_confirmation": requires_confirmation,
            "requires_internet": requires_internet,
            "can_run_offline": len(requires_internet) == 0,
        }


_policy_engine: Optional[ActionPolicyEngine] = None


def get_policy_engine() -> ActionPolicyEngine:
    """Get or create the global policy engine instance."""
    global _policy_engine
    if _policy_engine is None:
        _policy_engine = ActionPolicyEngine()
    return _policy_engine


def reset_policy_engine():
    """Reset the global policy engine (for testing)."""
    global _policy_engine
    _policy_engine = None
