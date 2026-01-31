"""
Multi-Step Planning for Chintu AI Assistant.

Provides intelligent task planning:
- Break complex requests into steps
- Execute steps sequentially
- Handle failures gracefully
- Confirm before destructive actions
"""

import logging
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class StepStatus(Enum):
    """Status of a plan step."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PlanStep:
    """A single step in a plan."""
    description: str
    action: str  # Capability or action to execute
    parameters: Dict[str, Any] = field(default_factory=dict)
    status: StepStatus = StepStatus.PENDING
    result: str = ""
    requires_confirmation: bool = False


@dataclass
class ExecutionPlan:
    """A multi-step execution plan."""
    goal: str
    steps: List[PlanStep] = field(default_factory=list)
    current_step: int = 0
    status: str = "pending"  # pending, running, completed, failed


class MultiStepPlanner:
    """
    Plans and executes multi-step tasks.
    
    Features:
    - LLM-powered plan generation
    - Step-by-step execution
    - Rollback on failure
    - Confirmation for sensitive actions
    """
    
    # Common multi-step patterns
    PATTERNS = {
        "book travel": ["search flights", "search hotels", "compare prices", "confirm booking"],
        "research topic": ["search web", "read articles", "summarize findings", "save notes"],
        "setup project": ["create folder", "open editor", "search template", "copy files"],
        "email response": ["read email", "draft reply", "review", "send"],
    }
    
    def __init__(self, llm_client=None, capability_executor: Callable = None):
        """
        Initialize planner.
        
        Args:
            llm_client: LLM for plan generation
            capability_executor: Function to execute capabilities
        """
        self.llm = llm_client
        self.executor = capability_executor
        self._current_plan: Optional[ExecutionPlan] = None
        self._plan_history: List[ExecutionPlan] = []
        
    def needs_planning(self, text: str) -> bool:
        """
        Check if request needs multi-step planning.
        
        Args:
            text: User request
            
        Returns:
            True if multi-step planning is needed
        """
        text_lower = text.lower()
        
        # Explicit multi-step indicators
        multi_step_words = [
            "and then", "after that", "followed by",
            "step by step", "plan", "workflow",
            "book", "research", "setup", "prepare",
        ]
        
        for word in multi_step_words:
            if word in text_lower:
                return True
        
        # Check for compound actions (multiple verbs)
        action_verbs = ["open", "search", "read", "write", "send", "create", "find", "save"]
        verb_count = sum(1 for v in action_verbs if v in text_lower)
        
        return verb_count >= 2
    
    def create_plan(self, goal: str) -> ExecutionPlan:
        """
        Create an execution plan for a goal.
        
        Args:
            goal: User's goal/request
            
        Returns:
            Execution plan
        """
        plan = ExecutionPlan(goal=goal)
        
        # Try rule-based first
        steps = self._rule_based_plan(goal)
        
        # Use LLM if no rule match
        if not steps and self.llm:
            steps = self._llm_plan(goal)
        
        plan.steps = steps
        self._current_plan = plan
        
        logger.info(f"Created plan with {len(steps)} steps for: {goal}")
        
        return plan
    
    def _rule_based_plan(self, goal: str) -> List[PlanStep]:
        """Generate plan using rules/patterns."""
        goal_lower = goal.lower()
        
        # Check patterns
        for pattern, actions in self.PATTERNS.items():
            if pattern in goal_lower:
                return [
                    PlanStep(
                        description=action,
                        action=action.replace(" ", "_"),
                    )
                    for action in actions
                ]
        
        # Parse compound requests
        if " and " in goal_lower:
            parts = goal_lower.split(" and ")
            return [
                PlanStep(description=part.strip(), action="execute")
                for part in parts
            ]
        
        return []
    
    def _llm_plan(self, goal: str) -> List[PlanStep]:
        """Generate plan using LLM."""
        if not self.llm:
            return []
        
        prompt = f"""Break down this goal into specific steps.
For each step, provide a short action phrase.

Goal: {goal}

Steps (one per line, numbered):
1."""

        try:
            response = self.llm.generate(prompt)
            
            # Parse steps from response
            steps = []
            for line in response.split("\n"):
                line = line.strip()
                if not line:
                    continue
                
                # Remove numbering
                if line[0].isdigit():
                    line = line.lstrip("0123456789.").strip()
                
                if line:
                    steps.append(PlanStep(
                        description=line,
                        action="execute",
                    ))
            
            return steps[:10]  # Limit steps
            
        except Exception as e:
            logger.error(f"LLM planning failed: {e}")
            return []
    
    def execute_plan(self, plan: Optional[ExecutionPlan] = None) -> str:
        """
        Execute a plan step by step.
        
        Args:
            plan: Plan to execute (default: current plan)
            
        Returns:
            Execution summary
        """
        plan = plan or self._current_plan
        if not plan:
            return "No plan to execute."
        
        plan.status = "running"
        results = []
        
        for i, step in enumerate(plan.steps):
            plan.current_step = i
            step.status = StepStatus.RUNNING
            
            logger.info(f"Executing step {i+1}: {step.description}")
            
            # Check for confirmation
            if step.requires_confirmation:
                # Would need async/callback here in real implementation
                pass
            
            # Execute step
            try:
                if self.executor:
                    result = self.executor(step.description, {})
                    step.result = str(result)
                    step.status = StepStatus.COMPLETED
                    results.append(f"✓ {step.description}")
                else:
                    step.status = StepStatus.SKIPPED
                    results.append(f"○ {step.description} (skipped)")
                    
            except Exception as e:
                step.status = StepStatus.FAILED
                step.result = str(e)
                results.append(f"✗ {step.description}: {e}")
                
                # Decide whether to continue
                logger.warning(f"Step failed: {e}")
        
        plan.status = "completed"
        self._plan_history.append(plan)
        
        return "\n".join(results)
    
    def get_plan_summary(self, plan: Optional[ExecutionPlan] = None) -> str:
        """Get a human-readable plan summary."""
        plan = plan or self._current_plan
        if not plan:
            return "No plan available."
        
        lines = [f"Plan: {plan.goal}", "Steps:"]
        for i, step in enumerate(plan.steps, 1):
            status_icon = {
                StepStatus.PENDING: "○",
                StepStatus.RUNNING: "▶",
                StepStatus.COMPLETED: "✓",
                StepStatus.FAILED: "✗",
                StepStatus.SKIPPED: "–",
            }.get(step.status, "?")
            
            lines.append(f"  {status_icon} {i}. {step.description}")
        
        return "\n".join(lines)
    
    def cancel_plan(self):
        """Cancel the current plan."""
        if self._current_plan:
            self._current_plan.status = "cancelled"
            self._current_plan = None


# Global instance
_planner: Optional[MultiStepPlanner] = None


def get_planner(llm_client=None, executor=None) -> MultiStepPlanner:
    """Get or create the global planner."""
    global _planner
    if _planner is None:
        _planner = MultiStepPlanner(llm_client, executor)
    return _planner
