"""Centralized capability registration and wiring helpers."""

from __future__ import annotations

import logging
from typing import Any, Dict
from pathlib import Path

from .capability_handlers import register_core_capabilities, register_enhancement_capabilities
from .help_capabilities import register_help_capabilities
from ..capabilities.news_capability import register_news_capabilities
from ..brain.memory.memory_capabilities import register_memory_capabilities
from ..brain.memory.temporal_capabilities import register_temporal_capabilities
from ..tasks.task_capabilities import register_task_capabilities
try:
    from ..vision.app_listing import register_app_listing_capabilities
except ImportError:
    pass

register_developer_capabilities = None
try:
    from ..tools.developer_tools import register_developer_capabilities
except ImportError:
    register_developer_capabilities = None

from ..brain.swarm.swarm_capabilities import register_swarm_capabilities

logger = logging.getLogger(__name__)

_CAPABILITIES_REGISTERED_ONCE = False


def register_all_capabilities(registry, config) -> Dict[str, Any]:
    """Register all capability modules in a consistent order."""
    global _CAPABILITIES_REGISTERED_ONCE

    # Idempotence: Chintu is heavily singleton-driven (most registrars call get_registry()
    # internally), so re-running registration in-process is both noisy and can trip the
    # duplicate-name guard. Once we've registered once, treat subsequent calls as no-ops.
    if _CAPABILITIES_REGISTERED_ONCE:
        try:
            total = len(registry.list_capabilities())
        except Exception:
            total = 0
        return {"errors": [], "skipped": True, "total": total}

    summary: Dict[str, Any] = {"errors": []}

    def _warn(context: str, exc: Exception) -> None:
        summary["errors"].append(f"{context}: {exc}")
        logger.warning("%s not available: %s", context, exc)
        try:
            from .error_reporter import report_error, ErrorSeverity

            report_error(
                exc,
                severity=ErrorSeverity.WARNING,
                component="capabilities",
                user_message=f"{context} unavailable: {exc}",
            )
        except Exception:
            pass

    def _safe_register(func, label: str) -> None:
        if not callable(func):
            return
        try:
            try:
                func(registry)
            except TypeError:
                # Some registrars use the global registry singleton and take no args.
                func()
        except Exception as exc:
            _warn(label, exc)

    try:
        register_core_capabilities()
    except Exception as exc:
        _warn("Core capabilities", exc)

    # Help/explainability (what can you do, why, etc.)
    _safe_register(register_help_capabilities, "Help capabilities")

    # Memory + temporal memory (facts/preferences + time-based recall)
    _safe_register(register_memory_capabilities, "Memory capabilities")
    _safe_register(register_temporal_capabilities, "Temporal capabilities")

    # Tasks (todos/reminders)
    _safe_register(register_task_capabilities, "Task capabilities")
    _safe_register(register_app_listing_capabilities, "App listing capabilities")

    try:
        from ..device import register_mobile_capabilities, register_phone_capabilities
        if register_mobile_capabilities:
            register_mobile_capabilities()
        if register_phone_capabilities:
            register_phone_capabilities()
    except Exception as exc:
        _warn("Phone/Mobile capabilities", exc)

    # News capability (tech news)
    try:
        register_news_capabilities()
    except Exception as exc:  # noqa: BLE001
        _warn("News capabilities", exc)

    # Enhancement capabilities (screenshot, clipboard, context, repeat)
    try:
        register_enhancement_capabilities()
    except Exception as exc:  # noqa: BLE001
        _warn("Enhancement capabilities", exc)

    # Search
    try:
        from ..search import register_search_capabilities

        register_search_capabilities(registry)
    except Exception as exc:  # noqa: BLE001
        _warn("Search capabilities", exc)

    # Files
    try:
        from ..files import register_file_capabilities

        register_file_capabilities(registry)
    except Exception as exc:  # noqa: BLE001
        _warn("File capabilities", exc)

    # Repo indexing (incremental codebase search)
    try:
        from ..coding.repo_index_capabilities import register_repo_index_capabilities

        register_repo_index_capabilities(registry)
    except Exception as exc:  # noqa: BLE001
        _warn("Repo index capabilities", exc)

    # Browser
    try:
        from ..automation.browser import register_browser_capabilities

        register_browser_capabilities(registry)
    except Exception as exc:  # noqa: BLE001
        _warn("Browser capabilities", exc)

    # Agents
    try:
        from ..agents import register_agent_capabilities

        register_agent_capabilities(registry)
    except Exception as exc:  # noqa: BLE001
        _warn("Agent capabilities", exc)

    # Research
    try:
        from ..research import register_research_capabilities

        register_research_capabilities(registry)
    except Exception as exc:  # noqa: BLE001
        _warn("Research capabilities", exc)

    # LLM-in-browser research profiles (Phase 23)
    try:
        from ..research.browser_profile_capabilities import register_browser_profile_capabilities

        register_browser_profile_capabilities(registry)
    except Exception as exc:  # noqa: BLE001
        _warn("Research browser profile capabilities", exc)

    # Finance (watchlist + analysis)
    try:
        from ..finance import register_finance_capabilities

        register_finance_capabilities(registry)
    except Exception as exc:  # noqa: BLE001
        _warn("Finance capabilities", exc)

    # Communications/calls (Phase 24)
    try:
        from ..communications import register_communications_capabilities

        register_communications_capabilities(registry)
    except Exception as exc:  # noqa: BLE001
        _warn("Communications capabilities", exc)

    # Reporting / Dashboard Studio
    try:
        from ..reporting import register_dashboard_capabilities

        register_dashboard_capabilities(registry)
    except Exception as exc:  # noqa: BLE001
        _warn("Dashboard capabilities", exc)

    # Weather
    try:
        from ..weather import register_weather_capabilities
 
        register_weather_capabilities()
    except Exception as exc:  # noqa: BLE001
        _warn("Weather capabilities", exc)

    # Skills (SKILL.md)
    try:
        from ..automation.skills.skill_proposal_capabilities import register_skill_proposal_capabilities

        register_skill_proposal_capabilities(registry)
    except Exception as exc:  # noqa: BLE001
        _warn("Skill proposal capabilities", exc)

    # Skills (SKILL.md)
    try:
        from ..automation.skills.skill_registry import SkillRegistry

        skill_registry = SkillRegistry()
        sources = [
            (config.skills_bundled_dir, "bundled"),
            (config.skills_learned_dir, "learned"),
            (config.skills_user_dir, "user"),
            (config.skills_dir, "workspace"),
        ]
        sources = [(path, label) for path, label in sources if path]
        # Some configs point multiple entries at the same underlying folder.
        # De-duplicate to avoid noisy "Overwriting skill" logs and needless re-parsing.
        deduped = []
        seen = set()
        for path, label in sources:
            try:
                p = Path(path).expanduser().resolve()
            except Exception:
                p = Path(path)
            key = str(p).lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append((p, label))
        sources = deduped
        loaded = skill_registry.load_sources(sources)
        registered = skill_registry.register_capabilities(registry)
        logger.info("Skills loaded: %s, registered: %s", loaded, registered)
        if getattr(config, "skills_watch_enabled", False):
            skill_registry.start_watcher(registry, sources)
    except Exception as exc:  # noqa: BLE001
        _warn("Skill registry", exc)

    # Automation
    try:
        from ..automation import register_automation_capabilities

        register_automation_capabilities(registry)
    except Exception as exc:  # noqa: BLE001
        _warn("Automation capabilities", exc)

    # Process control
    try:
        from ..automation.process_capabilities import register_process_capabilities
 
        register_process_capabilities()
    except Exception as exc:  # noqa: BLE001
        _warn("Process capabilities", exc)

    # Workflows (deterministic pipeline runner)
    try:
        from ..workflows import register_workflow_capabilities

        register_workflow_capabilities(registry)
    except Exception as exc:  # noqa: BLE001
        _warn("Workflow capabilities", exc)

    # Learning
    try:
        from ..brain.learning import register_learning_capabilities

        register_learning_capabilities(registry)
    except Exception as exc:  # noqa: BLE001
        _warn("Learning capabilities", exc)

    # Curiosity scheduler (Phase 22)
    try:
        from ..brain.learning.curiosity_capabilities import register_curiosity_capabilities

        register_curiosity_capabilities(registry)
    except Exception as exc:  # noqa: BLE001
        _warn("Curiosity capabilities", exc)

    # Library (Curated knowledge)
    try:
        from ..brain.knowledge.library_capabilities import register_library_capabilities

        register_library_capabilities(registry)
    except Exception as exc:  # noqa: BLE001
        _warn("Library capabilities", exc)

    # Knowledge updater (Phase 13.5 local RAG)
    try:
        from ..brain.knowledge.knowledge_updater_capabilities import register_knowledge_updater_capabilities

        register_knowledge_updater_capabilities(registry)
    except Exception as exc:  # noqa: BLE001
        _warn("Knowledge updater capabilities", exc)

    # Telegram inbox intake/query (Phase 21)
    try:
        from ..channels.telegram_inbox_capabilities import register_telegram_inbox_capabilities

        register_telegram_inbox_capabilities(registry)
    except Exception as exc:  # noqa: BLE001
        _warn("Telegram inbox capabilities", exc)

    # Evaluation
    try:
        from ..eval.eval_capabilities import register_eval_capabilities

        register_eval_capabilities(registry)
    except Exception as exc:  # noqa: BLE001
        _warn("Eval capabilities", exc)

    # Goals
    try:
        from ..brain.goals import register_goal_capabilities
 
        register_goal_capabilities()
    except Exception as exc:  # noqa: BLE001
        _warn("Goal capabilities", exc)

    # Swarm (multi-agent routing)
    _safe_register(register_swarm_capabilities, "Swarm capabilities")

    # MCP
    try:
        from ..interfaces.mcp.mcp_capabilities import register_mcp_capabilities

        register_mcp_capabilities(registry)
    except Exception as exc:  # noqa: BLE001
        _warn("MCP capabilities", exc)

    # Security
    try:
        from ..security import register_identity_capabilities, register_login_capabilities

        register_identity_capabilities(registry)
        register_login_capabilities(registry)
    except Exception as exc:  # noqa: BLE001
        _warn("Security capabilities", exc)

    # Tooling
    try:
        from ..automation.tools.tool_capabilities import register_tool_capabilities

        register_tool_capabilities(registry)
    except Exception as exc:  # noqa: BLE001
        _warn("Tool capabilities", exc)

    # Watchdog
    try:
        from ..watchdog import register_watchdog_capabilities

        register_watchdog_capabilities(registry)
    except Exception as exc:  # noqa: BLE001
        _warn("Watchdog capabilities", exc)

    # Orchestrator
    try:
        from ..orchestrator import register_orchestrator_capabilities

        register_orchestrator_capabilities(registry)
    except Exception as exc:  # noqa: BLE001
        _warn("Orchestrator capabilities", exc)

    # Developer Tools (Autonomous Mode)
    _safe_register(register_developer_capabilities, "developer_tools")
    summary["total"] = len(registry.list_capabilities())
    _CAPABILITIES_REGISTERED_ONCE = True

    return summary
