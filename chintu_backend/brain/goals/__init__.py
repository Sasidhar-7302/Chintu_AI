"""
Chintu Goals System - Persistent Goal and Task Management

This module provides a smart goal management system for:
- Recurring tasks (daily, weekly, monthly)
- Long-running projects with milestones
- Monitoring and reporting
- Habit tracking

Example usage:
    from chintu_backend.goals import get_goal_manager, GoalType, RecurrencePattern
    
    manager = get_goal_manager()
    
    # Daily news at 9 AM
    manager.create_goal(
        name="Morning News",
        action_command="search latest tech news and summarize",
        goal_type=GoalType.RECURRING,
        recurrence=RecurrencePattern.DAILY,
        schedule_time="09:00"
    )
    
    # Monitor web app every hour
    manager.create_goal(
        name="App Health Check",
        action_command="check https://myapp.com/health and report",
        goal_type=GoalType.MONITORING,
        recurrence=RecurrencePattern.HOURLY
    )
"""

from .goal_manager import (
    GoalManager,
    Goal,
    GoalType,
    GoalStatus,
    RecurrencePattern,
    GoalExecution,
    GoalReport,
    get_goal_manager,
)
from .goal_parser import parse_goal_from_text
from .goal_capabilities import register_goal_capabilities

__all__ = [
    "GoalManager",
    "Goal",
    "GoalType",
    "GoalStatus",
    "RecurrencePattern",
    "GoalExecution",
    "GoalReport",
    "get_goal_manager",
    "parse_goal_from_text",
    "register_goal_capabilities",
]

