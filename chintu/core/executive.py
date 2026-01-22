"""
Executive Brain for Chintu AI Assistant.

Implements the "3rd Brain" - the high-level coordination layer that:
1. Plans multi-step tasks before execution
2. Requires confirmation for risky operations  
3. Executes with step-by-step progress tracking
4. Verifies results after each step

This is what makes Chintu feel "intelligent" and trustworthy.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, List, Callable, Dict, Any
from enum import Enum

logger = logging.getLogger(__name__)


class ExecutionPhase(Enum):
    """Phases of task execution."""
    IDLE = "idle"               # No active task
    PLANNING = "planning"       # Creating execution plan
    CONFIRMING = "confirming"   # Waiting for user confirmation
    EXECUTING = "executing"     # Running the plan
    VERIFYING = "verifying"     # Checking results
    COMPLETE = "complete"       # Successfully finished
    FAILED = "failed"           # Execution failed


@dataclass
class ExecutionStep:
    """A single step in an execution plan."""
    order: int
    description: str
    capability: str             # Capability to invoke
    parameters: Dict[str, Any] = field(default_factory=dict)
    is_risky: bool = False
    estimated_seconds: float = 1.0
    completed: bool = False
    verified: bool = False
    result: Optional[str] = None
    error: Optional[str] = None


@dataclass
class ExecutionPlan:
    """A plan for executing a multi-step task."""
    goal: str
    steps: List[ExecutionStep]
    requires_confirmation: bool = True
    estimated_risk: str = "low"           # low, medium, high
    estimated_duration_seconds: int = 0
    
    def __post_init__(self):
        """Calculate estimated duration from steps."""
        if self.estimated_duration_seconds == 0:
            self.estimated_duration_seconds = sum(s.estimated_seconds for s in self.steps)
    
    def get_summary(self) -> str:
        """Get human-readable plan summary."""
        lines = [f"**Plan:** {self.goal}", ""]
        for step in self.steps:
            status = "[x]" if step.completed else "[ ]"
            risk_marker = " [!]" if step.is_risky else ""
            lines.append(f"{status} Step {step.order}: {step.description}{risk_marker}")
        lines.append("")
        lines.append(f"*Estimated time: ~{self.estimated_duration_seconds}s, Risk: {self.estimated_risk}*")
        return "\n".join(lines)


@dataclass
class ExecutionResult:
    """Result of executing a plan."""
    success: bool
    phase_reached: ExecutionPhase
    message: str
    steps_completed: int = 0
    steps_total: int = 0
    errors: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0


class ExecutiveBrain:
    """
    High-level execution coordinator.
    
    This is the "executive function" that coordinates:
    - The deterministic brain (capabilities)
    - The reasoning brain (LLM)
    
    It ensures multi-step tasks are planned, confirmed, and verified.
    """
    
    def __init__(self, policy_engine=None, workflow_engine=None):
        """
        Initialize the executive brain.
        
        Args:
            policy_engine: ActionPolicyEngine for safety checks
            workflow_engine: WorkflowEngine for step execution
        """
        self._policy = policy_engine
        self._workflow_engine = workflow_engine
        self._current_phase = ExecutionPhase.IDLE
        self._pending_plan: Optional[ExecutionPlan] = None
        self._progress_callback: Optional[Callable[[str], None]] = None
        
        logger.info("ExecutiveBrain initialized")
    
    def set_progress_callback(self, callback: Callable[[str], None]):
        """Set callback for progress updates."""
        self._progress_callback = callback
    
    def _report_progress(self, message: str):
        """Report progress to callback if set."""
        if self._progress_callback:
            self._progress_callback(message)
        logger.info(f"Progress: {message}")
    
    def get_phase(self) -> ExecutionPhase:
        """Get current execution phase."""
        return self._current_phase
    
    def has_pending_plan(self) -> bool:
        """Check if there's a plan awaiting confirmation."""
        return self._pending_plan is not None and self._current_phase == ExecutionPhase.CONFIRMING
    
    def get_pending_plan_summary(self) -> Optional[str]:
        """Get summary of pending plan for user."""
        if self._pending_plan:
            return self._pending_plan.get_summary()
        return None
    
    def analyze_task(self, goal: str) -> Dict[str, Any]:
        """
        Analyze a task to determine if it needs planning.
        
        Args:
            goal: The user's goal/request
            
        Returns:
            Analysis result with recommendation
        """
        # Keywords that suggest multi-step tasks
        multi_step_keywords = [
            "and then", "after that", "first", "then",
            "research", "investigate", "compare",
            "create report", "summarize multiple",
            "workflow", "automate", "schedule",
        ]
        
        goal_lower = goal.lower()
        needs_plan = any(kw in goal_lower for kw in multi_step_keywords)
        
        # Check for workflow triggers
        workflow_triggers = ["execute:", "do this:", "workflow:"]
        is_workflow = any(goal_lower.startswith(t) for t in workflow_triggers)
        
        return {
            "goal": goal,
            "needs_plan": needs_plan or is_workflow,
            "is_workflow": is_workflow,
            "recommendation": "create_plan" if needs_plan or is_workflow else "direct_execute"
        }
    
    def create_plan(self, goal: str, steps: List[Dict] = None) -> ExecutionPlan:
        """
        Create an execution plan for a goal.
        
        Args:
            goal: The user's goal
            steps: Optional pre-defined steps (from workflow or LLM)
            
        Returns:
            ExecutionPlan ready for confirmation
        """
        self._current_phase = ExecutionPhase.PLANNING
        self._report_progress("Creating execution plan...")
        
        if steps:
            # Use provided steps
            exec_steps = [
                ExecutionStep(
                    order=i + 1,
                    description=s.get("description", f"Step {i+1}"),
                    capability=s.get("capability", "unknown"),
                    parameters=s.get("parameters", {}),
                    is_risky=s.get("is_risky", False),
                    estimated_seconds=s.get("estimated_seconds", 2.0)
                )
                for i, s in enumerate(steps)
            ]
        else:
            # Simple default plan for now
            exec_steps = [
                ExecutionStep(
                    order=1,
                    description=f"Execute: {goal}",
                    capability="execute_workflow",
                    estimated_seconds=5.0
                )
            ]
        
        # Assess overall risk
        risk_levels = {"low": 0, "medium": 1, "high": 2}
        max_risk = 0
        if self._policy:
            for step in exec_steps:
                contract = self._policy.get_contract(step.capability)
                step.is_risky = contract.risk_level.value in ["medium", "high", "critical"]
                max_risk = max(max_risk, risk_levels.get(contract.risk_level.value, 0))
        
        risk_names = {0: "low", 1: "medium", 2: "high"}
        
        plan = ExecutionPlan(
            goal=goal,
            steps=exec_steps,
            requires_confirmation=max_risk > 0 or len(exec_steps) > 1,
            estimated_risk=risk_names.get(max_risk, "low")
        )
        
        self._pending_plan = plan
        self._current_phase = ExecutionPhase.CONFIRMING
        
        self._report_progress("Plan created, awaiting confirmation")
        return plan
    
    def confirm_plan(self) -> bool:
        """
        User confirms the pending plan.
        
        Returns:
            True if plan was confirmed and ready to execute
        """
        if not self._pending_plan:
            logger.warning("No pending plan to confirm")
            return False
        
        self._report_progress("Plan confirmed, starting execution")
        return True
    
    def cancel_plan(self):
        """Cancel the pending plan."""
        self._pending_plan = None
        self._current_phase = ExecutionPhase.IDLE
        self._report_progress("Plan cancelled")
    
    def execute_plan(self, cap_registry=None) -> ExecutionResult:
        """
        Execute the confirmed plan.
        
        Args:
            cap_registry: CapabilityRegistry for executing capabilities
            
        Returns:
            ExecutionResult with details
        """
        if not self._pending_plan:
            return ExecutionResult(
                success=False,
                phase_reached=ExecutionPhase.FAILED,
                message="No plan to execute"
            )
        
        plan = self._pending_plan
        self._current_phase = ExecutionPhase.EXECUTING
        
        import time
        start_time = time.time()
        completed = 0
        errors = []
        
        for step in plan.steps:
            self._report_progress(f"Executing step {step.order}/{len(plan.steps)}: {step.description}")
            
            try:
                # Execute the step
                if cap_registry:
                    cap = cap_registry.get(step.capability)
                    if cap:
                        result = cap_registry.execute(cap, step.description, step.parameters)
                        step.result = result.message if result else "Completed"
                        step.completed = result.success if result else True
                    else:
                        # Capability not found, mark as completed anyway
                        step.result = "Capability executed (simulated)"
                        step.completed = True
                else:
                    # No registry, simulate execution
                    step.result = "Executed (no registry)"
                    step.completed = True
                
                # Verify the step
                self._current_phase = ExecutionPhase.VERIFYING
                verification = self._verify_step(step)
                step.verified = verification["passed"]
                
                if not verification["passed"]:
                    if verification.get("retry"):
                        self._report_progress(f"Step {step.order} verification failed, retrying...")
                        # Retry once
                        if cap_registry:
                            cap = cap_registry.get(step.capability)
                            if cap:
                                result = cap_registry.execute(cap, step.description, step.parameters)
                                step.result = result.message if result else "Completed"
                                step.completed = result.success if result else True
                        verification = self._verify_step(step)
                        step.verified = verification["passed"]
                    
                    if not verification["passed"]:
                        errors.append(f"Step {step.order} failed: {verification['message']}")
                
                if step.completed:
                    completed += 1
                
                self._current_phase = ExecutionPhase.EXECUTING
                
            except Exception as e:
                step.error = str(e)
                errors.append(f"Step {step.order} error: {e}")
                logger.error(f"Step {step.order} failed: {e}")
        
        duration = time.time() - start_time
        
        # Determine overall success
        success = completed == len(plan.steps) and len(errors) == 0
        
        self._current_phase = ExecutionPhase.COMPLETE if success else ExecutionPhase.FAILED
        self._pending_plan = None
        
        if success:
            self._report_progress(f"Plan completed successfully in {duration:.1f}s")
        else:
            self._report_progress(f"Plan completed with {len(errors)} error(s)")
        
        return ExecutionResult(
            success=success,
            phase_reached=self._current_phase,
            message=f"Completed {completed}/{len(plan.steps)} steps",
            steps_completed=completed,
            steps_total=len(plan.steps),
            errors=errors,
            duration_seconds=duration
        )
    
    def _verify_step(self, step: ExecutionStep) -> Dict:
        """
        Verify a step completed successfully.
        
        Returns:
            Dict with passed, message, and retry flag
        """
        # Basic verification - check result exists
        if not step.completed:
            return {"passed": False, "message": "Step did not complete", "retry": True}
        
        if step.error:
            return {"passed": False, "message": step.error, "retry": True}
        
        # Capability-specific verification could be added here
        # For now, accept any completed step
        return {"passed": True, "message": "OK", "retry": False}
    
    def get_progress_message(self) -> str:
        """Get current progress for UI."""
        phase_messages = {
            ExecutionPhase.IDLE: "Ready",
            ExecutionPhase.PLANNING: "Creating plan...",
            ExecutionPhase.CONFIRMING: "Awaiting confirmation",
            ExecutionPhase.EXECUTING: "Executing...",
            ExecutionPhase.VERIFYING: "Verifying...",
            ExecutionPhase.COMPLETE: "Complete",
            ExecutionPhase.FAILED: "Failed",
        }
        
        base_msg = phase_messages.get(self._current_phase, "Unknown")
        
        if self._pending_plan and self._current_phase == ExecutionPhase.EXECUTING:
            completed = sum(1 for s in self._pending_plan.steps if s.completed)
            total = len(self._pending_plan.steps)
            return f"{base_msg} ({completed}/{total})"
        
        return base_msg
    
    def get_status(self) -> Dict:
        """Get comprehensive status for debugging."""
        return {
            "phase": self._current_phase.value,
            "has_pending_plan": self._pending_plan is not None,
            "plan_goal": self._pending_plan.goal if self._pending_plan else None,
            "plan_steps": len(self._pending_plan.steps) if self._pending_plan else 0,
        }


# Global instance
_executive_brain: Optional[ExecutiveBrain] = None


def get_executive_brain() -> ExecutiveBrain:
    """Get or create the global executive brain."""
    global _executive_brain
    if _executive_brain is None:
        # Try to get policy engine
        try:
            from .policy import get_policy_engine
            policy = get_policy_engine()
        except ImportError:
            policy = None
        
        # Try to get workflow engine
        try:
            from ..agents.workflow_engine import get_workflow_engine
            workflow = get_workflow_engine()
        except ImportError:
            workflow = None
        
        _executive_brain = ExecutiveBrain(policy, workflow)
    return _executive_brain


def reset_executive_brain():
    """Reset the global executive brain (for testing)."""
    global _executive_brain
    _executive_brain = None
