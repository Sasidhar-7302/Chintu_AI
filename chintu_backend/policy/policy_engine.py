"""Action policy engine for Chintu AI Assistant."""

import logging
from enum import Enum
from dataclasses import dataclass
from typing import Dict, Optional, Set

from .capability_contracts import RiskLevel, CapabilityContract
from .unified_resolver import ResolverDecision, UnifiedPolicyResolver

logger = logging.getLogger(__name__)


# ActionHistory import moved to evaluate() to avoid circular import with chintu_backend.core



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
        "execute_workflow",
        "transfer_data",
        "schedule_workflow",
        # High-level agentic executor: always require a plan preview.
        "autonomous_swarm",
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
        "screen_query": CapabilityContract(RiskLevel.LOW, requires_confirmation=False, side_effects=["capture_screen"]),
        "whats_on_screen": CapabilityContract(RiskLevel.LOW, requires_confirmation=False, side_effects=["capture_screen"]),
        "read_screen_text": CapabilityContract(RiskLevel.LOW, requires_confirmation=False, side_effects=["capture_screen"]),
        "context_query": CapabilityContract(RiskLevel.NONE),  # Read-only context info
        "time": CapabilityContract(RiskLevel.NONE),  # Just returns time
        "get_last_opened_app": CapabilityContract(RiskLevel.NONE),  # Read-only
        "list_apps": CapabilityContract(RiskLevel.NONE),  # Read-only app listing
        "clipboard": CapabilityContract(RiskLevel.NONE),  # Read clipboard - safe

        # Read operations - Low risk
        "get_system_specs": CapabilityContract(RiskLevel.LOW),
        "get_preferences": CapabilityContract(RiskLevel.LOW),
        "recall_facts": CapabilityContract(RiskLevel.LOW),
        "memory_stats": CapabilityContract(RiskLevel.LOW),
        "list_files": CapabilityContract(RiskLevel.LOW),
        "read_file": CapabilityContract(RiskLevel.LOW),
        "clipboard_read": CapabilityContract(RiskLevel.LOW),
        "list_reminders": CapabilityContract(RiskLevel.LOW),
        "task_status": CapabilityContract(RiskLevel.LOW),
        "list_calendar": CapabilityContract(RiskLevel.LOW),
        "buying_guide": CapabilityContract(RiskLevel.LOW),
        # Keep briefing available even when connectivity checks are flaky; handlers
        # already degrade gracefully when live sources are unavailable.
        "morning_briefing": CapabilityContract(RiskLevel.LOW, requires_internet=False),
        "morning_briefing_detail": CapabilityContract(RiskLevel.LOW, requires_internet=False),
        "morning_briefing_feedback": CapabilityContract(RiskLevel.LOW, requires_internet=False),
        "followup_detail": CapabilityContract(RiskLevel.LOW, requires_internet=False),
        "list_scheduled": CapabilityContract(RiskLevel.LOW),
        "check_tasks": CapabilityContract(RiskLevel.LOW),
        "list_tasks": CapabilityContract(RiskLevel.LOW),
        "recall": CapabilityContract(RiskLevel.LOW),
        "read_document": CapabilityContract(RiskLevel.LOW),
        "find_file": CapabilityContract(RiskLevel.LOW),
        "repo_search": CapabilityContract(RiskLevel.LOW),
        "repo_index_build": CapabilityContract(RiskLevel.LOW, requires_confirmation=False),
        "repo_index_search": CapabilityContract(RiskLevel.LOW, requires_confirmation=False),
        "repo_index_status": CapabilityContract(RiskLevel.LOW, requires_confirmation=False),
        "dependency_summary": CapabilityContract(RiskLevel.LOW),
        "curiosity_status": CapabilityContract(RiskLevel.LOW),
        "telegram_inbox_status": CapabilityContract(RiskLevel.LOW),
        "telegram_inbox_recent": CapabilityContract(RiskLevel.LOW),
        "telegram_inbox_search": CapabilityContract(RiskLevel.LOW),
        "research_browser_capture": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_internet=True,
            requires_confirmation=False,
            side_effects=["browser_action", "capture_screen"],
        ),
        "communications_owner_status": CapabilityContract(RiskLevel.LOW),
        "identity": CapabilityContract(RiskLevel.NONE), # Allow simple "Who are you?"
        "identity_provider": CapabilityContract(RiskLevel.LOW),
        "setup_guide": CapabilityContract(RiskLevel.NONE), # Static text guide - no risk
        "get_system_specs": CapabilityContract(RiskLevel.LOW, requires_confirmation=False), # Explicitly safe
        "live_search": CapabilityContract(RiskLevel.LOW, requires_internet=True),
        "browse_url": CapabilityContract(RiskLevel.LOW, requires_internet=True),
        "weather": CapabilityContract(RiskLevel.LOW, requires_internet=True),
        "conversation": CapabilityContract(RiskLevel.NONE),
        "repeat_command": CapabilityContract(RiskLevel.LOW),
        "mcp_list_tools": CapabilityContract(RiskLevel.LOW),
        "watchdog_list": CapabilityContract(RiskLevel.LOW),
        "watchdog_check": CapabilityContract(RiskLevel.LOW),
        "eval_run": CapabilityContract(RiskLevel.LOW),
        "reliability_gate_run": CapabilityContract(RiskLevel.LOW),
        "orchestrator_project_status": CapabilityContract(RiskLevel.LOW),
        "orchestrator_missing_inputs": CapabilityContract(RiskLevel.LOW),
        "orchestrator_list_inputs": CapabilityContract(RiskLevel.LOW),
        "finance_watch_list": CapabilityContract(RiskLevel.LOW),
        "finance_watch_profile": CapabilityContract(RiskLevel.LOW),
        "finance_brief": CapabilityContract(RiskLevel.MEDIUM, requires_internet=True),
        "finance_news_pulse": CapabilityContract(RiskLevel.MEDIUM, requires_internet=True),
        "finance_candidates_list": CapabilityContract(RiskLevel.LOW),
        "finance_candidate_add": CapabilityContract(RiskLevel.LOW, side_effects=["modify_watchlist"]),
        "finance_portfolio_summary": CapabilityContract(RiskLevel.LOW),
        "finance_portfolio_rebalance_plan": CapabilityContract(RiskLevel.LOW),

        # Local actions - Low risk
        "open_app": CapabilityContract(RiskLevel.LOW, side_effects=["open_application"]),
        "open_url": CapabilityContract(RiskLevel.LOW, requires_internet=True, side_effects=["open_browser"]),
        "close_app": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_confirmation=False,
            side_effects=["close_application"],
        ),
        "volume_control": CapabilityContract(
            RiskLevel.LOW,
            requires_confirmation=False,
            side_effects=["audio_control"],
        ),
        "control_window": CapabilityContract(RiskLevel.LOW, side_effects=["window_control"]),
        "switch_window": CapabilityContract(RiskLevel.LOW, side_effects=["window_control"]),
        "clipboard_copy": CapabilityContract(RiskLevel.LOW, side_effects=["modify_clipboard"]),
        "timer": CapabilityContract(RiskLevel.LOW, side_effects=["create_timer"]),
        "add_task": CapabilityContract(RiskLevel.LOW, side_effects=["create_task"]),
        "complete_task": CapabilityContract(RiskLevel.LOW, side_effects=["modify_task"]),
        "add_calendar_event": CapabilityContract(
            RiskLevel.LOW,
            requires_confirmation=False,
            side_effects=["create_calendar_event"],
        ),
        "set_reminder": CapabilityContract(RiskLevel.LOW, side_effects=["create_task"]),
        "note_taking": CapabilityContract(RiskLevel.LOW, side_effects=["modify_notes"]),
        "set_preference": CapabilityContract(RiskLevel.LOW, side_effects=["modify_preferences"]),
        "remember_fact": CapabilityContract(RiskLevel.LOW, side_effects=["modify_memory"]),
        "forget_specific": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_confirmation=False,
            side_effects=["modify_memory"],
        ),
        "write_file": CapabilityContract(RiskLevel.MEDIUM, requires_confirmation=False, side_effects=["modify_files"]),
        "modify_file": CapabilityContract(RiskLevel.MEDIUM, requires_confirmation=False, side_effects=["modify_files"]),
        "file_info": CapabilityContract(RiskLevel.LOW),
        "organize_downloads": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_confirmation=False,  # Handler provides preview + user confirmation.
            side_effects=["move_files"],
        ),
        "watchdog_add": CapabilityContract(RiskLevel.LOW, side_effects=["create_monitor"]),
        "watchdog_remove": CapabilityContract(RiskLevel.LOW, side_effects=["remove_monitor"]),
        "telegram_inbox_process": CapabilityContract(
            RiskLevel.LOW,
            requires_confirmation=False,
            side_effects=["process_queue", "modify_knowledge"],
        ),
        "telegram_inbox_cancel": CapabilityContract(
            RiskLevel.LOW,
            requires_confirmation=False,
            side_effects=["modify_queue"],
        ),
        "telegram_inbox_resume": CapabilityContract(
            RiskLevel.LOW,
            requires_confirmation=False,
            side_effects=["modify_queue"],
        ),
        "curiosity_run_cycle": CapabilityContract(
            RiskLevel.LOW,
            requires_confirmation=False,
            side_effects=["process_queue", "refresh_knowledge"],
        ),
        "curiosity_start": CapabilityContract(
            RiskLevel.LOW,
            requires_confirmation=False,
            side_effects=["background_execution"],
        ),
        "curiosity_stop": CapabilityContract(
            RiskLevel.LOW,
            requires_confirmation=False,
            side_effects=["background_execution"],
        ),
        "research_browser_draft": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_internet=True,
            requires_confirmation=False,
            side_effects=["browser_action", "draft_content"],
        ),
        "research_browser_send": CapabilityContract(
            RiskLevel.HIGH,
            requires_internet=True,
            requires_confirmation=True,
            side_effects=["browser_action", "form_submit"],
        ),
        "communications_set_owner": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_confirmation=False,
            side_effects=["store_secret", "modify_config"],
        ),
        "communications_call": CapabilityContract(
            RiskLevel.HIGH,
            requires_confirmation=False,
            side_effects=["browser_action", "call_action"],
        ),
        "communications_reservation": CapabilityContract(
            RiskLevel.HIGH,
            requires_confirmation=False,
            side_effects=["browser_action", "call_action"],
        ),
        "orchestrator_create_project": CapabilityContract(RiskLevel.LOW, side_effects=["create_project"]),
        "orchestrator_set_input": CapabilityContract(RiskLevel.LOW, side_effects=["store_input"]),
        "orchestrator_pause_project": CapabilityContract(RiskLevel.LOW, side_effects=["pause_project"]),
        "orchestrator_resume_project": CapabilityContract(RiskLevel.LOW, side_effects=["resume_project"]),
        "orchestrator_cancel_project": CapabilityContract(RiskLevel.LOW, side_effects=["cancel_project"]),
        "generate_thumbnail": CapabilityContract(RiskLevel.LOW, side_effects=["create_image"]),
        "finance_watch_add": CapabilityContract(RiskLevel.LOW, side_effects=["modify_watchlist"]),
        "finance_watch_remove": CapabilityContract(RiskLevel.LOW, side_effects=["modify_watchlist"]),
        "finance_portfolio_import": CapabilityContract(
            RiskLevel.LOW,
            side_effects=["read_file", "modify_finance_data"],
        ),
        "finance_portfolio_manual_entry": CapabilityContract(
            RiskLevel.LOW,
            side_effects=["modify_finance_data"],
        ),
        "job_apply": CapabilityContract(RiskLevel.MEDIUM, requires_internet=True, requires_confirmation=True, side_effects=["browser_action", "form_submit"]),
        "job_apply_list": CapabilityContract(RiskLevel.LOW),
        "figma_automation": CapabilityContract(RiskLevel.MEDIUM, requires_internet=True, requires_confirmation=True, side_effects=["browser_action", "create_image"]),
        "set_config": CapabilityContract(RiskLevel.MEDIUM, requires_confirmation=True, side_effects=["modify_config"]),
        "image_analyze": CapabilityContract(RiskLevel.LOW),
        "video_summarize": CapabilityContract(RiskLevel.MEDIUM, requires_confirmation=False, side_effects=["read_file"]),
        "news_video": CapabilityContract(RiskLevel.MEDIUM, requires_internet=True, requires_confirmation=True, side_effects=["create_media"]),
        "youtube_short": CapabilityContract(RiskLevel.LOW, side_effects=["create_project"]),
        "youtube_short_generate_assets": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_internet=True,
            can_run_background=True,
            side_effects=["create_media"],
        ),
        "social_content_pipeline": CapabilityContract(
            RiskLevel.LOW,
            requires_confirmation=False,
            side_effects=["create_media", "create_files"],
        ),
        "social_youtube_channel_setup": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_internet=True,
            requires_confirmation=False,
            side_effects=["browser_action", "account_setup"],
        ),
        "social_stage_upload": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_internet=True,
            requires_confirmation=False,
            side_effects=["browser_action", "draft_content"],
        ),
        "social_publish_post": CapabilityContract(
            RiskLevel.HIGH,
            # This capability captures approval only; final submit stays manual.
            requires_internet=False,
            requires_confirmation=True,
            side_effects=["browser_action", "publish_content"],
        ),
        "app_builder": CapabilityContract(RiskLevel.LOW, side_effects=["create_project"]),
        "app_builder_generate_docs": CapabilityContract(
            RiskLevel.MEDIUM,
            can_run_background=True,
            side_effects=["create_files"],
        ),
        "app_builder_scaffold_backend": CapabilityContract(
            RiskLevel.HIGH,
            requires_confirmation=True,
            side_effects=["modify_files"],
        ),
        "app_builder_execute_build": CapabilityContract(
            RiskLevel.HIGH,
            requires_confirmation=True,
            side_effects=["modify_files", "install_dependencies", "run_tests"],
        ),
        "code_interpreter": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_confirmation=False,
            side_effects=["sandbox_exec"],
        ),
        # Synthetic capability name used to aggregate multi-step execution results.
        "compound_command": CapabilityContract(RiskLevel.LOW),
        "autonomous_swarm": CapabilityContract(
            RiskLevel.HIGH,
            requires_confirmation=True,
            side_effects=["multi_step_action"],
        ),

        # Web operations - Medium risk
        "web_search": CapabilityContract(RiskLevel.MEDIUM, requires_internet=True),
        "news_search": CapabilityContract(RiskLevel.MEDIUM, requires_internet=True),
        "deep_search": CapabilityContract(RiskLevel.MEDIUM, requires_internet=True),
        "open_browser": CapabilityContract(RiskLevel.MEDIUM, requires_internet=True, side_effects=["browser_action"]),
        "browser_search": CapabilityContract(RiskLevel.MEDIUM, requires_internet=True, side_effects=["browser_action"]),
        "screenshot": CapabilityContract(RiskLevel.MEDIUM, side_effects=["capture_screen"]),
        "page_content": CapabilityContract(RiskLevel.MEDIUM, requires_internet=True),
        "browser_snapshot_refs": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_internet=True,
            requires_confirmation=False,
            side_effects=["browser_action", "capture_screen"],
        ),
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
        "browser_act_ref": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_internet=True,
            requires_confirmation=False,
            side_effects=["browser_click"],
        ),
        "browser_pilot": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_internet=True,
            requires_confirmation=False,
            side_effects=["browser_action"],
        ),
        "close_browser": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_confirmation=False,
            side_effects=["close_browser"]
        ),

        # Workflows - Medium risk (require plan preview)
        "execute_workflow": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_confirmation=False,  # plan-preview gate covers interactive usage
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
        # Screen Click (vision/native) - Medium risk (guarded by payment guard when needed)
        "screen_click": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_confirmation=False,
            side_effects=["mouse_keyboard_action"],
        ),

        # GCC (long-horizon context) - read-only
        "gcc_context": CapabilityContract(RiskLevel.LOW),

        # Automation - Medium risk
        "schedule_workflow": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_confirmation=False,  # plan-preview gate covers interactive usage
            side_effects=["create_scheduled_task"],
        ),
        "finance_schedule_brief": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_confirmation=True,
            side_effects=["create_scheduled_task"],
        ),
        "finance_schedule_pulse": CapabilityContract(
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
            requires_confirmation=False,  # plan-preview gate covers interactive usage
            side_effects=["cross_app_transfer"],
        ),
        "sandbox_data_task": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_confirmation=False,
            requires_internet=True,
            side_effects=["sandbox_execution", "file_output"],
        ),
        "autonomy_workflow": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_confirmation=False,
            requires_internet=True,
            side_effects=["workflow_execution", "file_output", "scheduler_write"],
        ),
        "sandbox_run": CapabilityContract(
            RiskLevel.HIGH,
            requires_confirmation=True,
            side_effects=["sandbox_execution"],
        ),
        "file_management": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_confirmation=False,
            side_effects=["modify_files"],
        ),
        "web_research": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_internet=True,
            requires_confirmation=False,
            side_effects=["browser_action"],
        ),
        "skill_propose": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_confirmation=False,
            side_effects=["propose_capability"],
        ),
        "terminal_exec": CapabilityContract(
            RiskLevel.CRITICAL,
            requires_confirmation=True,
            side_effects=["shell_execution"],
        ),
        "cancel_scheduled": CapabilityContract(RiskLevel.LOW, side_effects=["remove_scheduled_task"]),
        "cancel_reminder": CapabilityContract(RiskLevel.LOW, side_effects=["remove_task"]),

        # Daily-driver parity capabilities
        "email_inbox_triage": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_internet=True,
            requires_confirmation=False,  # Read-only; privacy boundaries handled by configuration.
            side_effects=["read_email"],
        ),
        "focus_mode": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_confirmation=False,  # Handler asks for a single confirmation with a clear plan.
            side_effects=["close_application", "open_application", "window_control"],
        ),
        "file_hunter": CapabilityContract(
            RiskLevel.LOW,
            requires_confirmation=False,
            side_effects=["read_files", "open_application"],
        ),
        "youtube_digest": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_internet=True,
            requires_confirmation=False,
            side_effects=["browser_action"],
        ),
        "deal_finder": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_internet=True,
            requires_confirmation=False,
        ),
        "deal_watch_add": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_internet=True,
            requires_confirmation=False,
            side_effects=["create_scheduled_task"],
        ),
        "deal_watch_list": CapabilityContract(
            RiskLevel.LOW,
            requires_confirmation=False,
        ),
        "deal_watch_remove": CapabilityContract(
            RiskLevel.LOW,
            requires_confirmation=False,
            side_effects=["remove_scheduled_task"],
        ),
        "deal_watch_run": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_internet=True,
            requires_confirmation=False,
        ),
        "hardware_health": CapabilityContract(
            RiskLevel.LOW,
            requires_confirmation=False,
        ),
        "smart_shutdown_after_download": CapabilityContract(
            RiskLevel.MEDIUM,
            requires_confirmation=False,  # Handler asks for confirmation and can be cancelled.
            side_effects=["system_shutdown"],
        ),
        "cancel_smart_shutdown": CapabilityContract(
            RiskLevel.LOW,
            requires_confirmation=False,
        ),

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
            side_effects=["list_passwords"],
        ),
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
        try:
            from chintu_backend.core.config import get_config

            self._config = get_config()
        except Exception:
            self._config = None
        self._resolver = UnifiedPolicyResolver(self._config)
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
        # Robust fallback: unknown capabilities must never crash policy evaluation.
        # Treat unknown capabilities as medium risk and require a user confirmation by default.
        logger.warning("No predefined contract found for capability: %s", capability_name)
        return CapabilityContract(
            risk_level=RiskLevel.MEDIUM,
            requires_confirmation=True,
            can_run_background=False,
            side_effects=["unknown_capability"],
        )

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

        if "has_internet" in kwargs:
            self._system_state.is_offline_mode = not bool(kwargs["has_internet"])

        logger.debug(
            "System state updated: internet=%s, battery=%s%%, quiet=%s",
            self._system_state.has_internet,
            self._system_state.battery_percent,
            self._system_state.is_quiet_mode,
        )

    def _allow_browser_fallback_when_offline(
        self,
        capability_name: str,
        contract: CapabilityContract,
        context: Optional[Dict],
    ) -> bool:
        """Allow safe internet tasks to attempt browser fallback even when offline check is flaky."""
        cfg = self._config
        if not bool(getattr(cfg, "browser_fallback_enabled", False)):
            return False
        if contract.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
            return False

        blocked_caps = {
            "social_publish_post",
            "job_apply",
            "terminal_exec",
            "sandbox_run",
            "identity_get_secret",
            "login_to",
        }
        if capability_name in blocked_caps:
            return False

        blocked_effects = {
            "publish_content",
            "form_submit",
            "shell_execution",
            "read_secret",
            "store_secret",
            "payment",
            "transaction",
        }
        if any(effect in blocked_effects for effect in (contract.side_effects or [])):
            return False

        if isinstance(context, dict) and bool(context.get("_force_strict_offline", False)):
            return False
        return True

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
            if self._allow_browser_fallback_when_offline(capability_name, contract, context):
                return ActionPolicy(
                    decision=PolicyDecision.ALLOW,
                    reason=(
                        f"Internet check is currently offline; allowing '{capability_name}' to attempt "
                        "browser-based fallback."
                    ),
                    risk_level=contract.risk_level,
                    requires_internet=True,
                )
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
            # Orchestrator steps already come with a structured plan and their own approval gates.
            # Avoid prompting the user for redundant plan confirmations in background projects.
            if not (context and context.get("_orchestrator")):
                return ActionPolicy(
                    decision=PolicyDecision.REQUIRE_PLAN,
                    reason=f"'{capability_name}' is a multi-step action that needs plan preview",
                    risk_level=contract.risk_level,
                )

        # Dynamic confirmation override via ActionHistory
        # Check close_app/close_browser
        if capability_name in ["close_app", "close_browser"]:
            try:
                from chintu_backend.core.action_history import get_action_history
                history = get_action_history()
                app_name = context.get("app_name") if context else None
                
                # If we know we opened it, we can safely close it
                if app_name and history.did_i_open_app(app_name):
                     return ActionPolicy(
                        decision=PolicyDecision.ALLOW,
                        reason=f"Safe to close '{app_name}' (I opened it)",
                        risk_level=contract.risk_level,
                        requires_internet=contract.requires_internet,
                    )
            except ImportError:
                 pass # History not available

        if capability_name in ["delete_file", "modify_file", "write_file"]:
            try:
                from chintu_backend.core.action_history import get_action_history
                history = get_action_history()
                file_path = context.get("file_path") if context else None
                
                if file_path:
                    # 1. Check if we created it
                    if history.did_i_create_file(file_path):
                         return ActionPolicy(
                            decision=PolicyDecision.ALLOW,
                            reason=f"Safe to modify '{file_path}' (I created it)",
                            risk_level=contract.risk_level,
                        )
                    
                    # 2. Check strict folder boundaries (Simulated)
                    import os
                    # Get current working dir or project root
                    safe_dir = os.getcwd().lower() 
                    if file_path.lower().startswith(safe_dir):
                        # Inside safe directory -> Allow
                        pass # Fall through to default contract
                    else:
                        # Outside safe directory -> REQUIRE CONFIRMATION
                        return ActionPolicy(
                            decision=PolicyDecision.REQUIRE_CONFIRMATION,
                            reason=f"File '{file_path}' is outside the assistant folder.",
                            risk_level=RiskLevel.HIGH, # Elevate risk for external files
                        )
            except ImportError:
                pass


        # Exec approvals: if the exact command+cwd was approved recently,
        # skip the confirmation prompt within the TTL window.
        if capability_name == "terminal_exec":
            try:
                from chintu_backend.core.config import get_config
                from chintu_backend.policy.exec_approvals import get_exec_approval_ledger

                cfg = get_config()
                if getattr(cfg, "exec_approval_enabled", True):
                    params = None
                    if context and isinstance(context, dict):
                        params = context.get("_validated_params") or context.get("_extracted_params") or {}
                    command = None
                    cwd = None
                    if isinstance(params, dict):
                        command = params.get("command")
                        cwd = params.get("cwd")
                    else:
                        command = getattr(params, "command", None)
                        cwd = getattr(params, "cwd", None)
                    command = str(command or "").strip()
                    cwd = str(cwd or "").strip() or None
                    if command:
                        ledger = get_exec_approval_ledger()
                        if ledger.is_approved(command, cwd):
                            try:
                                if context and isinstance(context, dict):
                                    context["_confirmed"] = True
                            except Exception:
                                pass
                            return ActionPolicy(
                                decision=PolicyDecision.ALLOW,
                                reason="Command previously approved (within TTL).",
                                risk_level=contract.risk_level,
                                requires_internet=contract.requires_internet,
                            )
            except Exception:
                pass

        # Phase 8 unified resolver: tool profile + agent profile + context risk + runtime profile.
        try:
            if bool(getattr(self._config, "security_unified_policy_enabled", True)):
                resolution = self._resolver.resolve(
                    capability_name=capability_name,
                    contract=contract,
                    context=context if isinstance(context, dict) else {},
                )
                if isinstance(context, dict):
                    context["_policy_resolution"] = resolution.to_dict()
                if resolution.decision == ResolverDecision.deny:
                    return ActionPolicy(
                        decision=PolicyDecision.DENY,
                        reason=resolution.reason,
                        risk_level=resolution.risk_level,
                        requires_internet=contract.requires_internet,
                    )
                if resolution.decision == ResolverDecision.confirm:
                    return ActionPolicy(
                        decision=PolicyDecision.REQUIRE_CONFIRMATION,
                        reason=resolution.reason,
                        risk_level=resolution.risk_level,
                        requires_internet=contract.requires_internet,
                    )
                if resolution.decision == ResolverDecision.allow:
                    return ActionPolicy(
                        decision=PolicyDecision.ALLOW,
                        reason=resolution.reason,
                        risk_level=resolution.risk_level,
                        requires_internet=contract.requires_internet,
                    )
        except Exception as exc:
            logger.debug("Unified policy resolver failed: %s", exc)

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
