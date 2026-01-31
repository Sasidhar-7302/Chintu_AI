"""Centralized capability registration and wiring helpers."""

from __future__ import annotations

import logging
from typing import Any, Dict

from .capability_handlers import register_core_capabilities, register_enhancement_capabilities
from .help_capabilities import register_help_capabilities
from ..capabilities.news_capability import register_news_capabilities
from ..brain.memory.memory_capabilities import register_memory_capabilities
from ..brain.memory.temporal_capabilities import register_temporal_capabilities
from ..tasks.task_capabilities import register_task_capabilities
from ..vision.app_listing import register_app_listing_capabilities

logger = logging.getLogger(__name__)


def register_all_capabilities(registry, config) -> Dict[str, Any]:
    """Register all capability modules in a consistent order."""
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

    register_core_capabilities()
    register_memory_capabilities()
    register_temporal_capabilities()
    register_task_capabilities()
    register_help_capabilities()
    register_app_listing_capabilities()

    # Device & Phone capabilities (New)
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
        loaded = skill_registry.load_sources(sources)
        registered = skill_registry.register_capabilities(registry)
        logger.info("Skills loaded: %s, registered: %s", loaded, registered)
    except Exception as exc:  # noqa: BLE001
        _warn("Skill registry", exc)

    # Automation
    try:
        from ..automation import register_automation_capabilities

        register_automation_capabilities(registry)
    except Exception as exc:  # noqa: BLE001
        _warn("Automation capabilities", exc)

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

    # Goals
    try:
        from ..brain.goals import register_goal_capabilities

        register_goal_capabilities()
    except Exception as exc:  # noqa: BLE001
        _warn("Goal capabilities", exc)

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

    summary["total"] = len(registry.list_capabilities())
    return summary
