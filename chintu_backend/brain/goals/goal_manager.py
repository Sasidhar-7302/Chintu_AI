"""
Persistent Goals System for Chintu v5.1

This module implements a smart goal/task management system that can handle:
- Recurring tasks (daily news at 9 AM, weekly reports)
- Long-running projects (monitor web apps, track metrics)
- Multi-day workflows (week-long research, 365-day habits)
- Automated monitoring and reporting

Key Features:
- SQLite persistence for goals and progress
- Natural language goal parsing
- Automatic scheduling and execution
- Progress tracking and reporting
- Integration with swarm for complex goal execution
"""

import logging
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass, field
from enum import Enum

from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean, Float, Enum as SAEnum
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger(__name__)

Base = declarative_base()


class GoalType(str, Enum):
    """Types of goals."""
    RECURRING = "recurring"      # Daily/weekly/monthly tasks
    PROJECT = "project"          # Multi-step projects with milestones
    MONITORING = "monitoring"    # Watch something and report
    HABIT = "habit"              # Long-term habit tracking
    ONE_TIME = "one_time"        # Single execution goal


class GoalStatus(str, Enum):
    """Goal status."""
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class RecurrencePattern(str, Enum):
    """Recurrence patterns for recurring goals."""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    HOURLY = "hourly"
    CUSTOM = "custom"  # Custom cron-like pattern


class Goal(Base):
    """SQLAlchemy model for persistent goals."""
    __tablename__ = "goals"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    goal_type = Column(SAEnum(GoalType), default=GoalType.ONE_TIME)
    status = Column(SAEnum(GoalStatus), default=GoalStatus.ACTIVE)
    
    # Scheduling
    recurrence = Column(SAEnum(RecurrencePattern), nullable=True)
    schedule_time = Column(String(10), nullable=True)  # HH:MM format
    schedule_days = Column(Text, nullable=True)  # JSON array of days
    custom_cron = Column(String(100), nullable=True)
    
    # Execution
    action_command = Column(Text, nullable=False)  # Command to execute
    action_params = Column(Text, nullable=True)  # JSON params
    
    # Tracking
    last_run = Column(DateTime, nullable=True)
    next_run = Column(DateTime, nullable=True)
    run_count = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    failure_count = Column(Integer, default=0)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)  # For time-limited goals
    
    # Progress (for projects)
    progress_percent = Column(Float, default=0.0)
    milestones = Column(Text, nullable=True)  # JSON array of milestones
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "goal_type": self.goal_type.value if self.goal_type else None,
            "status": self.status.value if self.status else None,
            "recurrence": self.recurrence.value if self.recurrence else None,
            "schedule_time": self.schedule_time,
            "action_command": self.action_command,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "next_run": self.next_run.isoformat() if self.next_run else None,
            "run_count": self.run_count,
            "success_count": self.success_count,
            "progress_percent": self.progress_percent,
        }


class GoalExecution(Base):
    """Track individual goal executions."""
    __tablename__ = "goal_executions"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    goal_id = Column(String(36), nullable=False, index=True)
    executed_at = Column(DateTime, default=datetime.utcnow)
    success = Column(Boolean, default=True)
    result = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    duration_seconds = Column(Float, nullable=True)


class GoalReport(Base):
    """Store generated reports for monitoring goals."""
    __tablename__ = "goal_reports"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    goal_id = Column(String(36), nullable=False, index=True)
    report_date = Column(DateTime, default=datetime.utcnow)
    report_type = Column(String(50), nullable=True)  # daily, weekly, monthly
    content = Column(Text, nullable=False)
    metrics = Column(Text, nullable=True)  # JSON metrics data


class GoalManager:
    """
    Manages persistent goals with scheduling and execution.

    This is the "smart system" that can:
    - Read news every morning at 9 AM
    - Monitor web applications and generate reports
    - Track long-running projects over weeks/months
    - Execute recurring tasks automatically
    """

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            from chintu_backend.core.config import get_config
            config = get_config()
            db_path = config.data_dir / "goals.db"

        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.engine = create_engine(f"sqlite:///{self.db_path}")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

        self._command_callback: Optional[Callable[[str], str]] = None
        self._running = False
        self._check_thread = None

        logger.info(f"GoalManager initialized with db: {self.db_path}")

    def set_command_callback(self, callback: Callable[[str], str]):
        """Set callback for executing goal commands."""
        self._command_callback = callback

    def create_goal(
        self,
        name: str,
        action_command: str,
        goal_type: GoalType = GoalType.ONE_TIME,
        description: str = "",
        recurrence: Optional[RecurrencePattern] = None,
        schedule_time: str = "09:00",
        schedule_days: Optional[List[str]] = None,
        expires_at: Optional[datetime] = None,
        action_params: Optional[Dict] = None,
    ) -> Goal:
        """
        Create a new goal.

        Examples:
            # Daily news at 9 AM
            create_goal("Morning News", "search latest tech news and summarize",
                       goal_type=GoalType.RECURRING, recurrence=RecurrencePattern.DAILY,
                       schedule_time="09:00")

            # Monitor web app every hour
            create_goal("App Monitor", "check https://myapp.com/health and report status",
                       goal_type=GoalType.MONITORING, recurrence=RecurrencePattern.HOURLY)

            # Week-long research project
            create_goal("AI Research", "research latest AI developments",
                       goal_type=GoalType.PROJECT)
        """
        goal = Goal(
            name=name,
            description=description,
            goal_type=goal_type,
            action_command=action_command,
            action_params=json.dumps(action_params) if action_params else None,
            recurrence=recurrence,
            schedule_time=schedule_time,
            schedule_days=json.dumps(schedule_days) if schedule_days else None,
            expires_at=expires_at,
        )

        # Calculate next run time
        goal.next_run = self._calculate_next_run(goal)

        with self.Session() as session:
            session.add(goal)
            session.commit()
            session.refresh(goal)

        logger.info(f"Created goal: {name} (type={goal_type.value}, next_run={goal.next_run})")
        return goal

    def _calculate_next_run(self, goal: Goal) -> Optional[datetime]:
        """Calculate the next run time for a goal."""
        now = datetime.now()

        if goal.goal_type == GoalType.ONE_TIME:
            return None  # Manual execution

        if not goal.recurrence:
            return None

        try:
            hour, minute = map(int, (goal.schedule_time or "09:00").split(':'))
        except:
            hour, minute = 9, 0

        if goal.recurrence == RecurrencePattern.DAILY:
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            return target

        elif goal.recurrence == RecurrencePattern.HOURLY:
            target = now.replace(minute=minute, second=0, microsecond=0)
            if target <= now:
                target += timedelta(hours=1)
            return target

        elif goal.recurrence == RecurrencePattern.WEEKLY:
            # Default to Monday if no days specified
            days = json.loads(goal.schedule_days) if goal.schedule_days else ["monday"]
            days_map = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                       "friday": 4, "saturday": 5, "sunday": 6}

            target_day = days_map.get(days[0].lower(), 0)
            days_ahead = target_day - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7

            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            target += timedelta(days=days_ahead)
            return target

        elif goal.recurrence == RecurrencePattern.MONTHLY:
            # Run on the 1st of each month
            if now.day == 1 and now.hour < hour:
                target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            else:
                # Next month
                if now.month == 12:
                    target = now.replace(year=now.year + 1, month=1, day=1,
                                        hour=hour, minute=minute, second=0, microsecond=0)
                else:
                    target = now.replace(month=now.month + 1, day=1,
                                        hour=hour, minute=minute, second=0, microsecond=0)
            return target

        return None

    def list_goals(self, status: Optional[GoalStatus] = None) -> List[Goal]:
        """List all goals, optionally filtered by status."""
        with self.Session() as session:
            query = session.query(Goal)
            if status:
                query = query.filter(Goal.status == status)
            return query.order_by(Goal.created_at.desc()).all()

    def get_goal(self, goal_id: str) -> Optional[Goal]:
        """Get a specific goal by ID."""
        with self.Session() as session:
            return session.query(Goal).filter(Goal.id == goal_id).first()

    def update_goal_status(self, goal_id: str, status: GoalStatus) -> bool:
        """Update a goal's status."""
        with self.Session() as session:
            goal = session.query(Goal).filter(Goal.id == goal_id).first()
            if goal:
                goal.status = status
                session.commit()
                return True
            return False

    def delete_goal(self, goal_id: str) -> bool:
        """Delete a goal."""
        with self.Session() as session:
            goal = session.query(Goal).filter(Goal.id == goal_id).first()
            if goal:
                session.delete(goal)
                session.commit()
                logger.info(f"Deleted goal: {goal.name}")
                return True
            return False

    def execute_goal(self, goal: Goal) -> GoalExecution:
        """Execute a goal and record the result."""
        import time
        start_time = time.time()

        execution = GoalExecution(goal_id=goal.id)

        try:
            if self._command_callback:
                result = self._command_callback(goal.action_command)
                execution.result = result
                execution.success = True
            else:
                execution.result = "No command callback configured"
                execution.success = False
                execution.error = "No callback"

        except Exception as e:
            execution.success = False
            execution.error = str(e)
            logger.error(f"Goal execution failed: {goal.name} - {e}")

        execution.duration_seconds = time.time() - start_time

        # Update goal stats
        with self.Session() as session:
            db_goal = session.query(Goal).filter(Goal.id == goal.id).first()
            if db_goal:
                db_goal.last_run = datetime.now()
                db_goal.run_count += 1
                if execution.success:
                    db_goal.success_count += 1
                else:
                    db_goal.failure_count += 1
                db_goal.next_run = self._calculate_next_run(db_goal)
                session.add(execution)
                session.commit()

        logger.info(f"Executed goal: {goal.name} (success={execution.success})")
        return execution

    def check_due_goals(self) -> List[Goal]:
        """Check for goals that are due for execution."""
        now = datetime.now()
        due_goals = []

        with self.Session() as session:
            goals = session.query(Goal).filter(
                Goal.status == GoalStatus.ACTIVE,
                Goal.next_run <= now
            ).all()

            for goal in goals:
                # Check if expired
                if goal.expires_at and goal.expires_at < now:
                    goal.status = GoalStatus.COMPLETED
                    session.commit()
                    continue

                due_goals.append(goal)

        return due_goals

    def start_background_checker(self, interval_seconds: int = 60):
        """Start background thread to check and execute due goals."""
        import threading

        if self._running:
            return

        self._running = True

        def check_loop():
            while self._running:
                try:
                    due_goals = self.check_due_goals()
                    for goal in due_goals:
                        self.execute_goal(goal)
                except Exception as e:
                    logger.error(f"Goal checker error: {e}")

                import time
                time.sleep(interval_seconds)

        self._check_thread = threading.Thread(target=check_loop, daemon=True)
        self._check_thread.start()
        logger.info("Goal background checker started")

    def stop_background_checker(self):
        """Stop the background checker."""
        self._running = False
        if self._check_thread:
            self._check_thread.join(timeout=5)
        logger.info("Goal background checker stopped")

    def get_goal_report(self, goal_id: str, days: int = 7) -> Dict[str, Any]:
        """Generate a report for a goal's recent executions."""
        with self.Session() as session:
            goal = session.query(Goal).filter(Goal.id == goal_id).first()
            if not goal:
                return {"error": "Goal not found"}

            since = datetime.now() - timedelta(days=days)
            executions = session.query(GoalExecution).filter(
                GoalExecution.goal_id == goal_id,
                GoalExecution.executed_at >= since
            ).order_by(GoalExecution.executed_at.desc()).all()

            return {
                "goal": goal.to_dict(),
                "period_days": days,
                "total_executions": len(executions),
                "successful": sum(1 for e in executions if e.success),
                "failed": sum(1 for e in executions if not e.success),
                "avg_duration": sum(e.duration_seconds or 0 for e in executions) / len(executions) if executions else 0,
                "last_result": executions[0].result if executions else None,
            }

    def get_summary(self) -> str:
        """Get a human-readable summary of all active goals."""
        goals = self.list_goals(status=GoalStatus.ACTIVE)

        if not goals:
            return "You have no active goals."

        lines = [f"You have {len(goals)} active goal(s):"]
        for goal in goals:
            next_run = goal.next_run.strftime("%Y-%m-%d %H:%M") if goal.next_run else "manual"
            lines.append(f"  - {goal.name} ({goal.goal_type.value}) - next: {next_run}")

        return "\n".join(lines)


# Global instance
_goal_manager: Optional[GoalManager] = None


def get_goal_manager() -> GoalManager:
    """Get or create the global goal manager instance."""
    global _goal_manager
    if _goal_manager is None:
        _goal_manager = GoalManager()
    return _goal_manager
