"""Runtime path/default initialization helpers for Config."""

from __future__ import annotations

from pathlib import Path


def initialize_runtime_paths(config) -> None:
    """Apply filesystem-backed runtime defaults and ensure required paths exist."""
    config.data_dir.mkdir(parents=True, exist_ok=True)
    if config.models_dir is None:
        config.models_dir = config.data_dir / "models"
        config.models_dir.mkdir(parents=True, exist_ok=True)
    if config.learning_adapter_dir is None:
        config.learning_adapter_dir = config.models_dir / "adapters"
    config.learning_adapter_dir.mkdir(parents=True, exist_ok=True)
    if config.persona_registry_path is None:
        config.persona_registry_path = config.data_dir / "personas" / "registry.json"
    config.persona_registry_path.parent.mkdir(parents=True, exist_ok=True)
    if config.wake_word_samples_dir is None:
        config.wake_word_samples_dir = config.data_dir / "wakeword"
    config.wake_word_samples_dir.mkdir(parents=True, exist_ok=True)
    (config.wake_word_samples_dir / "positive").mkdir(parents=True, exist_ok=True)
    (config.wake_word_samples_dir / "negative").mkdir(parents=True, exist_ok=True)
    if config.wake_word_verifier_path is None:
        config.wake_word_verifier_path = config.wake_word_samples_dir / "verifier.pkl"

    if config.wake_word_model_path is None:
        custom_onnx = config.wake_word_samples_dir / "hey_chintu.onnx"
        if custom_onnx.exists():
            config.wake_word_model_path = str(custom_onnx)
        else:
            repo_onnx = Path.cwd() / "_Hey_Chintu_.onnx"
            if repo_onnx.exists():
                config.wake_word_model_path = str(repo_onnx)
            else:
                project_root = Path(__file__).resolve().parents[2]
                root_onnx = project_root / "_Hey_Chintu_.onnx"
                if root_onnx.exists():
                    config.wake_word_model_path = str(root_onnx)

    if config.memory_store_path is None:
        config.memory_store_path = config.data_dir / "memory_db"
    config.memory_store_path.mkdir(parents=True, exist_ok=True)

    if config.memory_sqlite_path is None:
        config.memory_sqlite_path = config.data_dir / "memory_hybrid.db"

    if config.memory_markdown_dir is None:
        config.memory_markdown_dir = config.data_dir / "brain_md"
    if getattr(config, "obsidian_vault_dir", None):
        config.memory_markdown_dir = Path(config.obsidian_vault_dir)
    if getattr(config, "workflows_dir", None) is None:
        config.workflows_dir = config.data_dir / "workflows"
    if getattr(config, "repo_index_dir", None) is None:
        config.repo_index_dir = config.data_dir / "repo_index"
    if getattr(config, "airllm_cache_dir", None) is None:
        config.airllm_cache_dir = config.data_dir / "airllm_cache"
    if config.finance_watchlist_path is None:
        config.finance_watchlist_path = config.data_dir / "finance" / "watchlist.json"
    if config.finance_brief_dir is None:
        config.finance_brief_dir = config.data_dir / "finance" / "briefs"
    if config.finance_portfolio_store_path is None:
        config.finance_portfolio_store_path = config.data_dir / "finance" / "portfolio.json"
    if config.finance_receipts_dir is None:
        config.finance_receipts_dir = config.data_dir / "finance" / "receipts"
    config.memory_markdown_dir.mkdir(parents=True, exist_ok=True)
    config.workflows_dir.mkdir(parents=True, exist_ok=True)
    config.repo_index_dir.mkdir(parents=True, exist_ok=True)
    config.airllm_cache_dir.mkdir(parents=True, exist_ok=True)

    config.finance_watchlist_path.parent.mkdir(parents=True, exist_ok=True)
    config.finance_brief_dir.mkdir(parents=True, exist_ok=True)
    config.finance_portfolio_store_path.parent.mkdir(parents=True, exist_ok=True)
    config.finance_receipts_dir.mkdir(parents=True, exist_ok=True)

    if config.training_log_path is None:
        config.training_log_path = config.data_dir / "training" / "interactions.jsonl"
    config.training_log_path.parent.mkdir(parents=True, exist_ok=True)

    if config.training_exports_dir is None:
        config.training_exports_dir = config.data_dir / "training" / "exports"
    config.training_exports_dir.mkdir(parents=True, exist_ok=True)
    if config.learning_pending_activation_path is None:
        config.learning_pending_activation_path = config.data_dir / "training" / "pending_adapter_activation.json"
    config.learning_pending_activation_path.parent.mkdir(parents=True, exist_ok=True)
    if config.learning_phase29_reports_dir is None:
        config.learning_phase29_reports_dir = Path.cwd() / "generated_reports"
    config.learning_phase29_reports_dir.mkdir(parents=True, exist_ok=True)

    if config.history_event_store_path is None:
        config.history_event_store_path = config.data_dir / "history" / "events.jsonl"
    if config.task_dossiers_dir is None:
        config.task_dossiers_dir = config.data_dir / "history" / "dossiers"
    if config.task_history_index_path is None:
        config.task_history_index_path = config.data_dir / "history" / "dossier_index.sqlite3"
    config.history_event_store_path.parent.mkdir(parents=True, exist_ok=True)
    config.task_dossiers_dir.mkdir(parents=True, exist_ok=True)
    config.task_history_index_path.parent.mkdir(parents=True, exist_ok=True)

    if config.gcc_root_dir is None:
        config.gcc_root_dir = Path.cwd() / ".GCC"
    if config.gcc_enabled:
        config.gcc_root_dir.mkdir(parents=True, exist_ok=True)

    if config.swarm_db_path is None:
        config.swarm_db_path = config.data_dir / "swarm.db"

    if config.agent_policies_path is None:
        config.agent_policies_path = config.data_dir / "agent_policies.json"
    if config.agent_registry_path is None:
        config.agent_registry_path = config.data_dir / "agent_registry.json"
    if config.agent_workspace_root is None:
        config.agent_workspace_root = config.data_dir / "agents"
    if config.agent_primary_workspace is None:
        config.agent_primary_workspace = Path.cwd()
    if config.workspace_root_dir is None:
        config.workspace_root_dir = Path(config.agent_primary_workspace or Path.cwd())
    if config.workspace_receipts_dir is None:
        config.workspace_receipts_dir = config.data_dir / "workspace" / "receipts"
    if config.workspace_checkpoints_dir is None:
        config.workspace_checkpoints_dir = config.data_dir / "workspace" / "checkpoints"
    config.workspace_receipts_dir.mkdir(parents=True, exist_ok=True)
    config.workspace_checkpoints_dir.mkdir(parents=True, exist_ok=True)
    config.workspace_root_dir.mkdir(parents=True, exist_ok=True)

    if config.docker_sandbox_workspace is None:
        config.docker_sandbox_workspace = Path.cwd()

    if config.watchdog_db_path is None:
        config.watchdog_db_path = config.data_dir / "watchdogs.db"

    if config.skills_dir is None:
        config.skills_dir = Path.cwd() / "skills"
    if config.skills_user_dir is None:
        config.skills_user_dir = config.data_dir / "skills"
    if config.skills_bundled_dir is None:
        config.skills_bundled_dir = (
            Path(__file__).resolve().parent.parent / "automation" / "skills" / "bundled"
        )
    if config.skills_learned_dir is None:
        project_learned = Path.cwd() / "brain_md" / "skills"
        config.skills_learned_dir = (
            project_learned if project_learned.exists() else (config.data_dir / "skills_learned")
        )
    if config.skills_proposals_dir is None:
        config.skills_proposals_dir = config.data_dir / "skills_proposals"
    if config.skills_supply_chain_receipts_dir is None:
        config.skills_supply_chain_receipts_dir = config.data_dir / "skill_supply_chain" / "receipts"
    config.skills_dir.mkdir(parents=True, exist_ok=True)
    config.skills_user_dir.mkdir(parents=True, exist_ok=True)
    config.skills_bundled_dir.mkdir(parents=True, exist_ok=True)
    config.skills_learned_dir.mkdir(parents=True, exist_ok=True)
    config.skills_proposals_dir.mkdir(parents=True, exist_ok=True)
    config.skills_supply_chain_receipts_dir.mkdir(parents=True, exist_ok=True)

    if config.channel_allowlist_path is None:
        config.channel_allowlist_path = config.data_dir / "channel_allowlist.json"

    if config.orchestrator_db_path is None:
        config.orchestrator_db_path = config.data_dir / "orchestrator.db"

    if config.thumbnail_output_dir is None:
        config.thumbnail_output_dir = config.data_dir / "thumbnails"
    config.thumbnail_output_dir.mkdir(parents=True, exist_ok=True)

    if config.coding_agent_change_log_dir is None:
        config.coding_agent_change_log_dir = config.data_dir / "changes"
    config.coding_agent_change_log_dir.mkdir(parents=True, exist_ok=True)

    if config.audit_log_path is None:
        config.audit_log_path = config.data_dir / "audit" / "audit_log.jsonl"
    if config.exec_approval_path is None:
        config.exec_approval_path = config.data_dir / "exec_approvals.json"
    if config.action_approval_path is None:
        config.action_approval_path = config.data_dir / "action_approvals.json"
    if config.phase9_reports_dir is None:
        config.phase9_reports_dir = Path.cwd() / "generated_reports"
    if config.phase9_history_path is None:
        config.phase9_history_path = config.data_dir / "governance" / "benchmark_history.jsonl"
    if config.phase9_alerts_path is None:
        config.phase9_alerts_path = config.data_dir / "governance" / "alerts.jsonl"
    if config.phase9_monthly_review_dir is None:
        config.phase9_monthly_review_dir = config.data_dir / "governance" / "monthly_reviews"
    config.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
    config.phase9_reports_dir.mkdir(parents=True, exist_ok=True)
    config.phase9_history_path.parent.mkdir(parents=True, exist_ok=True)
    config.phase9_alerts_path.parent.mkdir(parents=True, exist_ok=True)
    config.phase9_monthly_review_dir.mkdir(parents=True, exist_ok=True)
    if config.phase15_dir is None:
        config.phase15_dir = config.data_dir / "self_improvement"
    if config.phase15_gap_plans_dir is None:
        config.phase15_gap_plans_dir = config.phase15_dir / "gap_plans"
    if config.phase15_change_reports_dir is None:
        config.phase15_change_reports_dir = config.phase15_dir / "change_reports"
    if config.phase15_routing_reports_dir is None:
        config.phase15_routing_reports_dir = config.phase15_dir / "routing_reports"
    config.phase15_dir.mkdir(parents=True, exist_ok=True)
    config.phase15_gap_plans_dir.mkdir(parents=True, exist_ok=True)
    config.phase15_change_reports_dir.mkdir(parents=True, exist_ok=True)
    config.phase15_routing_reports_dir.mkdir(parents=True, exist_ok=True)

    if config.dependency_bootstrap_receipts_dir is None:
        config.dependency_bootstrap_receipts_dir = config.data_dir / "dependency_receipts"
    config.dependency_bootstrap_receipts_dir.mkdir(parents=True, exist_ok=True)

    if config.arbiter_telemetry_path is None:
        config.arbiter_telemetry_path = config.data_dir / "telemetry" / "arbiter_routing.jsonl"
    config.arbiter_telemetry_path.parent.mkdir(parents=True, exist_ok=True)
    if config.catalog_model_path is None:
        config.catalog_model_path = config.data_dir / "knowledge" / "model_catalog.json"
    config.catalog_model_path.parent.mkdir(parents=True, exist_ok=True)
    if config.knowledge_store_dir is None:
        config.knowledge_store_dir = config.data_dir / "knowledge_updater"
    config.knowledge_store_dir.mkdir(parents=True, exist_ok=True)

    if config.browser_profiles_dir is None:
        config.browser_profiles_dir = config.data_dir / "browser_profiles"
    config.browser_profiles_dir.mkdir(parents=True, exist_ok=True)
    if config.research_browser_capture_dir is None:
        config.research_browser_capture_dir = config.data_dir / "research_browser" / "captures"
    config.research_browser_capture_dir.mkdir(parents=True, exist_ok=True)

    if config.telegram_inbox_media_dir is None:
        config.telegram_inbox_media_dir = config.data_dir / "telegram_inbox" / "media"
    if config.telegram_inbox_items_dir is None:
        config.telegram_inbox_items_dir = config.data_dir / "telegram_inbox" / "items"
    if config.telegram_inbox_db_path is None:
        config.telegram_inbox_db_path = config.data_dir / "telegram_inbox" / "inbox.sqlite3"
    config.telegram_inbox_media_dir.mkdir(parents=True, exist_ok=True)
    config.telegram_inbox_items_dir.mkdir(parents=True, exist_ok=True)
    config.telegram_inbox_db_path.parent.mkdir(parents=True, exist_ok=True)

    if config.curiosity_state_path is None:
        config.curiosity_state_path = config.data_dir / "curiosity" / "state.json"
    if config.curiosity_runs_dir is None:
        config.curiosity_runs_dir = config.data_dir / "curiosity" / "runs"
    config.curiosity_state_path.parent.mkdir(parents=True, exist_ok=True)
    config.curiosity_runs_dir.mkdir(parents=True, exist_ok=True)

    if config.agent_workspace_root is not None:
        try:
            config.agent_workspace_root.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    if config.eval_cases_path is None:
        config.eval_cases_path = Path(__file__).resolve().parent.parent / "eval" / "cases.jsonl"

    if config.library_root_dir is None:
        config.library_root_dir = Path.cwd() / "Chintus_Library"
    config.library_root_dir.mkdir(parents=True, exist_ok=True)

    if config.identity_vault_key_path is None:
        config.identity_vault_key_path = config.data_dir / "identity.key"
    config.identity_vault_key_path.parent.mkdir(parents=True, exist_ok=True)

    if config.identity_vault_meta_path is None:
        config.identity_vault_meta_path = config.data_dir / "identity_meta.json"
    config.identity_vault_meta_path.parent.mkdir(parents=True, exist_ok=True)
    if config.integrations_receipts_dir is None:
        config.integrations_receipts_dir = config.data_dir / "integrations" / "receipts"
    config.integrations_receipts_dir.mkdir(parents=True, exist_ok=True)
    if config.communications_owner_profile_path is None:
        config.communications_owner_profile_path = config.data_dir / "communications" / "owner_profile.json"
    if config.communications_receipts_dir is None:
        config.communications_receipts_dir = config.data_dir / "communications" / "receipts"
    config.communications_owner_profile_path.parent.mkdir(parents=True, exist_ok=True)
    config.communications_receipts_dir.mkdir(parents=True, exist_ok=True)


def apply_fast_defaults(config) -> None:
    """Apply defaults without filesystem writes (used in tests)."""
    if config.models_dir is None:
        config.models_dir = config.data_dir / "models"
    if config.learning_adapter_dir is None:
        config.learning_adapter_dir = config.models_dir / "adapters"
    if config.persona_registry_path is None:
        config.persona_registry_path = config.data_dir / "personas" / "registry.json"
    if config.wake_word_samples_dir is None:
        config.wake_word_samples_dir = config.data_dir / "wakeword"
    if config.wake_word_verifier_path is None:
        config.wake_word_verifier_path = config.wake_word_samples_dir / "verifier.pkl"
    if config.memory_store_path is None:
        config.memory_store_path = config.data_dir / "memory_db"
    if config.memory_sqlite_path is None:
        config.memory_sqlite_path = config.data_dir / "memory_hybrid.db"
    if config.memory_markdown_dir is None:
        config.memory_markdown_dir = config.data_dir / "brain_md"
    if getattr(config, "obsidian_vault_dir", None):
        config.memory_markdown_dir = Path(config.obsidian_vault_dir)
    if getattr(config, "workflows_dir", None) is None:
        config.workflows_dir = config.data_dir / "workflows"
    if getattr(config, "repo_index_dir", None) is None:
        config.repo_index_dir = config.data_dir / "repo_index"
    if getattr(config, "airllm_cache_dir", None) is None:
        config.airllm_cache_dir = config.data_dir / "airllm_cache"
    if config.finance_watchlist_path is None:
        config.finance_watchlist_path = config.data_dir / "finance" / "watchlist.json"
    if config.finance_brief_dir is None:
        config.finance_brief_dir = config.data_dir / "finance" / "briefs"
    if config.finance_portfolio_store_path is None:
        config.finance_portfolio_store_path = config.data_dir / "finance" / "portfolio.json"
    if config.finance_receipts_dir is None:
        config.finance_receipts_dir = config.data_dir / "finance" / "receipts"
    if config.training_log_path is None:
        config.training_log_path = config.data_dir / "training" / "interactions.jsonl"
    if config.training_exports_dir is None:
        config.training_exports_dir = config.data_dir / "training" / "exports"
    if config.learning_pending_activation_path is None:
        config.learning_pending_activation_path = config.data_dir / "training" / "pending_adapter_activation.json"
    if config.learning_phase29_reports_dir is None:
        config.learning_phase29_reports_dir = Path.cwd() / "generated_reports"
    if config.history_event_store_path is None:
        config.history_event_store_path = config.data_dir / "history" / "events.jsonl"
    if config.task_dossiers_dir is None:
        config.task_dossiers_dir = config.data_dir / "history" / "dossiers"
    if config.task_history_index_path is None:
        config.task_history_index_path = config.data_dir / "history" / "dossier_index.sqlite3"
    if config.gcc_root_dir is None:
        config.gcc_root_dir = Path.cwd() / ".GCC"
    if config.swarm_db_path is None:
        config.swarm_db_path = config.data_dir / "swarm.db"
    if config.agent_policies_path is None:
        config.agent_policies_path = config.data_dir / "agent_policies.json"
    if config.agent_registry_path is None:
        config.agent_registry_path = config.data_dir / "agent_registry.json"
    if config.agent_workspace_root is None:
        config.agent_workspace_root = config.data_dir / "agents"
    if config.agent_primary_workspace is None:
        config.agent_primary_workspace = Path.cwd()
    if config.workspace_root_dir is None:
        config.workspace_root_dir = Path(config.agent_primary_workspace or Path.cwd())
    if config.workspace_receipts_dir is None:
        config.workspace_receipts_dir = config.data_dir / "workspace" / "receipts"
    if config.workspace_checkpoints_dir is None:
        config.workspace_checkpoints_dir = config.data_dir / "workspace" / "checkpoints"
    if config.docker_sandbox_workspace is None:
        config.docker_sandbox_workspace = Path.cwd()
    if config.watchdog_db_path is None:
        config.watchdog_db_path = config.data_dir / "watchdogs.db"
    if config.skills_dir is None:
        config.skills_dir = Path.cwd() / "skills"
    if config.skills_user_dir is None:
        config.skills_user_dir = config.data_dir / "skills"
    if config.skills_bundled_dir is None:
        config.skills_bundled_dir = (
            Path(__file__).resolve().parent.parent / "automation" / "skills" / "bundled"
        )
    if config.skills_learned_dir is None:
        config.skills_learned_dir = config.data_dir / "skills_learned"
    if config.skills_proposals_dir is None:
        config.skills_proposals_dir = config.data_dir / "skills_proposals"
    if config.skills_supply_chain_receipts_dir is None:
        config.skills_supply_chain_receipts_dir = config.data_dir / "skill_supply_chain" / "receipts"
    if config.channel_allowlist_path is None:
        config.channel_allowlist_path = config.data_dir / "channel_allowlist.json"
    if config.orchestrator_db_path is None:
        config.orchestrator_db_path = config.data_dir / "orchestrator.db"
    if config.thumbnail_output_dir is None:
        config.thumbnail_output_dir = config.data_dir / "thumbnails"
    if config.coding_agent_change_log_dir is None:
        config.coding_agent_change_log_dir = config.data_dir / "changes"
    if config.audit_log_path is None:
        config.audit_log_path = config.data_dir / "audit" / "audit_log.jsonl"
    if config.exec_approval_path is None:
        config.exec_approval_path = config.data_dir / "exec_approvals.json"
    if config.action_approval_path is None:
        config.action_approval_path = config.data_dir / "action_approvals.json"
    if config.phase9_reports_dir is None:
        config.phase9_reports_dir = Path.cwd() / "generated_reports"
    if config.phase9_history_path is None:
        config.phase9_history_path = config.data_dir / "governance" / "benchmark_history.jsonl"
    if config.phase9_alerts_path is None:
        config.phase9_alerts_path = config.data_dir / "governance" / "alerts.jsonl"
    if config.phase9_monthly_review_dir is None:
        config.phase9_monthly_review_dir = config.data_dir / "governance" / "monthly_reviews"
    if config.phase15_dir is None:
        config.phase15_dir = config.data_dir / "self_improvement"
    if config.phase15_gap_plans_dir is None:
        config.phase15_gap_plans_dir = config.phase15_dir / "gap_plans"
    if config.phase15_change_reports_dir is None:
        config.phase15_change_reports_dir = config.phase15_dir / "change_reports"
    if config.phase15_routing_reports_dir is None:
        config.phase15_routing_reports_dir = config.phase15_dir / "routing_reports"
    if config.dependency_bootstrap_receipts_dir is None:
        config.dependency_bootstrap_receipts_dir = config.data_dir / "dependency_receipts"
    if config.arbiter_telemetry_path is None:
        config.arbiter_telemetry_path = config.data_dir / "telemetry" / "arbiter_routing.jsonl"
    if config.catalog_model_path is None:
        config.catalog_model_path = config.data_dir / "knowledge" / "model_catalog.json"
    if config.knowledge_store_dir is None:
        config.knowledge_store_dir = config.data_dir / "knowledge_updater"
    if config.browser_profiles_dir is None:
        config.browser_profiles_dir = config.data_dir / "browser_profiles"
    if config.research_browser_capture_dir is None:
        config.research_browser_capture_dir = config.data_dir / "research_browser" / "captures"
    if config.telegram_inbox_media_dir is None:
        config.telegram_inbox_media_dir = config.data_dir / "telegram_inbox" / "media"
    if config.telegram_inbox_items_dir is None:
        config.telegram_inbox_items_dir = config.data_dir / "telegram_inbox" / "items"
    if config.telegram_inbox_db_path is None:
        config.telegram_inbox_db_path = config.data_dir / "telegram_inbox" / "inbox.sqlite3"
    if config.curiosity_state_path is None:
        config.curiosity_state_path = config.data_dir / "curiosity" / "state.json"
    if config.curiosity_runs_dir is None:
        config.curiosity_runs_dir = config.data_dir / "curiosity" / "runs"
    if config.eval_cases_path is None:
        config.eval_cases_path = Path(__file__).resolve().parent.parent / "eval" / "cases.jsonl"
    if config.library_root_dir is None:
        config.library_root_dir = Path.cwd() / "Chintus_Library"
    if config.identity_vault_key_path is None:
        config.identity_vault_key_path = config.data_dir / "identity.key"
    if config.identity_vault_meta_path is None:
        config.identity_vault_meta_path = config.data_dir / "identity_meta.json"
    if config.integrations_receipts_dir is None:
        config.integrations_receipts_dir = config.data_dir / "integrations" / "receipts"
    if config.communications_owner_profile_path is None:
        config.communications_owner_profile_path = config.data_dir / "communications" / "owner_profile.json"
    if config.communications_receipts_dir is None:
        config.communications_receipts_dir = config.data_dir / "communications" / "receipts"
