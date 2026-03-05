"""
Goal Capabilities for Chintu v5.1

Registers goal-related capabilities for the capability registry:
- create_goal: Create recurring/scheduled goals from natural language
- list_goals: Show all active goals
- delete_goal: Remove a goal
- goal_report: Get a report on goal performance

Examples:
    "Read me news every morning at 9 AM" -> create_goal
    "Monitor my website every hour" -> create_goal
    "Show my active goals" -> list_goals
    "How are my goals doing?" -> goal_report
"""

import logging
import re
from typing import Dict, Any, Optional

from chintu_backend.core.capabilities import ActionResult, Capability, get_registry

logger = logging.getLogger(__name__)


def register_goal_capabilities():
    """Register all goal-related capabilities."""
    registry = get_registry()

    # Create Goal capability
    registry.register(Capability(
        name="create_goal",
        triggers=[
            r"(?:remind me to|remind|set goal|schedule).+(?:every|daily|weekly|hourly)",
            r"(?:read|tell|send|check|monitor|track).+(?:every morning|every day|every hour|every week|every month|daily|weekly)",
            r"(?:every morning|every day|every hour).+(?:read|tell|send|check|remind)",
        ],
        handler=_handle_create_goal,
        description="Create a recurring or scheduled goal",
    ))

    # List Goals capability
    registry.register(Capability(
        name="list_goals",
        triggers=[
            r"(?:show|list|what are|display).*(?:goals?|scheduled tasks?|recurring|monitors?)",
            r"my (?:active )?goals",
            r"what(?:'s| is) scheduled",
        ],
        handler=_handle_list_goals,
        description="List all active goals",
    ))

    # Delete Goal capability
    registry.register(Capability(
        name="delete_goal",
        triggers=[
            r"(?:delete|remove|cancel|stop).*(?:goal|scheduled|recurring|monitor)",
            r"stop (?:monitoring|tracking|reminding)",
        ],
        handler=_handle_delete_goal,
        description="Delete a goal",
        requires_confirmation=True,
    ))

    # Goal Report capability
    registry.register(Capability(
        name="goal_report",
        triggers=[
            r"(?:how|what).*(?:goals?|scheduled|recurring).+(?:doing|performing|status)",
            r"goal(?:s)? (?:report|status|summary)",
            r"(?:report|status) (?:on|for) (?:my )?goals?",
        ],
        handler=_handle_goal_report,
        description="Get a report on goal performance",
    ))

    logger.info("Goal capabilities registered")


def _handle_create_goal(text: str, context: Dict[str, Any]) -> ActionResult:
    """Handle creating a goal from natural language."""
    try:
        from . import get_goal_manager, parse_goal_from_text
        
        manager = get_goal_manager()
        parsed = parse_goal_from_text(text)
        
        if not parsed:
            return ActionResult(
                success=False,
                message="I couldn't understand that goal. Try something like 'Read me news every morning at 9 AM'.",
            )
        
        goal = manager.create_goal(
            name=parsed["name"],
            action_command=parsed["action_command"],
            goal_type=parsed["goal_type"],
            recurrence=parsed["recurrence"],
            schedule_time=parsed["schedule_time"],
            schedule_days=parsed["schedule_days"],
            description=parsed["description"],
        )
        
        next_run = goal.next_run.strftime("%Y-%m-%d %H:%M") if goal.next_run else "when triggered"
        return ActionResult(
            success=True,
            message=f"Goal created: '{goal.name}'\nType: {goal.goal_type.value}\nNext run: {next_run}",
            data={"goal_id": goal.id, "goal": goal.to_dict()},
        )
        
    except Exception as e:
        logger.error(f"Failed to create goal: {e}")
        return ActionResult(success=False, message=f"Failed to create goal: {e}")


def _handle_list_goals(text: str, context: Dict[str, Any]) -> ActionResult:
    """Handle listing all active goals."""
    try:
        from . import get_goal_manager
        
        manager = get_goal_manager()
        summary = manager.get_summary()
        
        return ActionResult(success=True, message=summary)
        
    except Exception as e:
        logger.error(f"Failed to list goals: {e}")
        return ActionResult(success=False, message=f"Failed to list goals: {e}")


def _handle_delete_goal(text: str, context: Dict[str, Any]) -> ActionResult:
    """Handle deleting a goal (placeholder - needs goal ID)."""
    return ActionResult(
        success=False,
        message="To delete a goal, first list your goals with 'show my goals', then tell me which one to delete by name or number.",
    )


def _handle_goal_report(text: str, context: Dict[str, Any]) -> ActionResult:
    """Handle generating a goal performance report."""
    try:
        from . import get_goal_manager, GoalStatus
        
        manager = get_goal_manager()
        goals = manager.list_goals(status=GoalStatus.ACTIVE)
        
        if not goals:
            return ActionResult(success=True, message="You have no active goals to report on.")
        
        lines = [f"Goal Performance Report ({len(goals)} active goals):\n"]
        for goal in goals:
            success_rate = (goal.success_count / goal.run_count * 100) if goal.run_count > 0 else 0
            last = goal.last_run.strftime("%m/%d %H:%M") if goal.last_run else "never"
            lines.append(f"- {goal.name}: {goal.run_count} runs, {success_rate:.0f}% success, last: {last}")
        
        return ActionResult(success=True, message="\n".join(lines))
        
    except Exception as e:
        logger.error(f"Failed to generate goal report: {e}")
        return ActionResult(success=False, message=f"Failed to generate report: {e}")

