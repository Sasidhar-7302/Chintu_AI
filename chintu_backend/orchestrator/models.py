"""Persistent orchestration models for long-running projects."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class ProjectStatus(str, Enum):
    """Lifecycle status of an orchestrated project."""

    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    """Execution status of a project step."""

    PENDING = "pending"
    RUNNABLE = "runnable"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_INPUT = "waiting_input"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class OrchestratorProject:
    """A long-running project managed by the orchestrator."""

    id: str
    name: str
    description: str
    status: ProjectStatus = ProjectStatus.ACTIVE
    run_start_hour: int = 9
    run_end_hour: int = 21
    daily_budget_minutes: int = 120
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    last_run_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OrchestratorStep:
    """A single step in a project plan."""

    id: str
    project_id: str
    order_index: int
    title: str
    command: str
    capability: Optional[str] = None
    depends_on: List[str] = field(default_factory=list)
    required_inputs: List[str] = field(default_factory=list)
    risk_level: str = "low"
    status: StepStatus = StepStatus.PENDING
    assigned_agent: Optional[str] = None
    attempts: int = 0
    max_attempts: int = 2
    last_run_at: Optional[datetime] = None
    next_eligible_at: Optional[datetime] = None
    last_error: str = ""
    estimated_minutes: int = 10
    auto_retry: bool = True
    approval_required: bool = False


@dataclass
class ApprovalRequest:
    """A request for user approval before a step can run."""

    id: str
    project_id: str
    step_id: str
    reason: str
    status: str = "pending"  # pending, approved, rejected
    created_at: datetime = field(default_factory=datetime.utcnow)
    decided_at: Optional[datetime] = None
    decided_by: Optional[str] = None


@dataclass
class StepRun:
    """Execution record for a step run attempt."""

    id: str
    project_id: str
    step_id: str
    started_at: datetime
    finished_at: datetime
    success: bool
    result: str = ""
    error: str = ""
    duration_seconds: float = 0.0

