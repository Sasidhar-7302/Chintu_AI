"""
Task Planner for Chintu AI Assistant.
Uses LLM to break down complex requests into executable steps.
"""

import json
import logging
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class StepType(Enum):
    """Types of steps that can be executed."""
    SEARCH = "search"           # Web search
    BROWSE = "browse"           # Open URL in browser
    CLICK = "click"             # Click element
    FILL = "fill"               # Fill form field
    SCREENSHOT = "screenshot"   # Take screenshot
    READ = "read"               # Read page content
    EXTRACT = "extract"         # Extract specific data
    REMEMBER = "remember"       # Save to memory
    NOTIFY = "notify"           # Notify user
    WAIT = "wait"               # Wait for condition
    CUSTOM = "custom"           # Custom action


@dataclass
class Step:
    """A single step in a workflow."""
    id: int
    action: StepType
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[int] = field(default_factory=list)
    status: str = "pending"  # pending, running, completed, failed
    result: Optional[str] = None
    error: Optional[str] = None


@dataclass
class Plan:
    """A complete execution plan."""
    goal: str
    steps: List[Step]
    created_at: str = ""
    status: str = "pending"  # pending, running, completed, failed
    current_step: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "steps": [
                {
                    "id": s.id,
                    "action": s.action.value,
                    "description": s.description,
                    "parameters": s.parameters,
                    "status": s.status
                }
                for s in self.steps
            ],
            "status": self.status,
            "current_step": self.current_step
        }
    
    def __str__(self) -> str:
        lines = [f"**Plan: {self.goal}**\n"]
        for step in self.steps:
            status_icon = {
                "pending": "[ ]",
                "running": "[~]", 
                "completed": "[x]",
                "failed": "[!]"
            }.get(step.status, "[ ]")
            lines.append(f"{status_icon} Step {step.id}: {step.description}")
        return "\n".join(lines)


class TaskPlanner:
    """
    Plans multi-step tasks using LLM.
    Breaks down complex requests into executable steps.
    """
    
    def __init__(self):
        self._available_actions = list(StepType)
    
    def plan(self, request: str, context: Dict[str, Any] = None) -> Plan:
        """
        Create an execution plan for the given request.
        
        Args:
            request: The user's complex request
            context: Optional context (current page, user preferences, etc.)
            
        Returns:
            A Plan with steps to execute
        """
        from datetime import datetime
        
        # Use LLM to generate plan
        steps = self._generate_plan_with_llm(request, context)
        
        return Plan(
            goal=request,
            steps=steps,
            created_at=datetime.now().isoformat(),
            status="pending"
        )
    
    def _generate_plan_with_llm(self, request: str, context: Dict[str, Any] = None) -> List[Step]:
        """Use LLM to generate execution steps."""
        try:
            from ..core.model_router import get_router
            router = get_router()

            prompt = self._build_planning_prompt(request, context)

            # Use route_and_execute to get response
            response, source = router.route_and_execute(prompt)

            if response and source != "none":
                parsed_steps = self._parse_plan_response(response)
                if parsed_steps:
                    return parsed_steps

            # If LLM returned nothing useful, fall back to heuristics
            logger.warning("LLM plan was empty, using heuristics")
            return self._heuristic_plan(request)

        except Exception as e:
            logger.error(f"LLM planning failed: {e}")
            # Fallback to simple heuristic planning
            return self._heuristic_plan(request)
    
    def _build_planning_prompt(self, request: str, context: Dict[str, Any] = None) -> str:
        """Build the prompt for the LLM planner."""
        available_actions = ", ".join([a.value for a in StepType])
        
        prompt = f"""You are a task planner. Break down the user's request into executable steps.

Available actions: {available_actions}

User request: "{request}"

Respond with a JSON array of steps. Each step should have:
- "action": one of the available actions
- "description": what this step does
- "parameters": dict of parameters (url, query, selector, text, etc.)

Example response:
[
  {{"action": "search", "description": "Search for restaurants", "parameters": {{"query": "best restaurants near me"}}}},
  {{"action": "browse", "description": "Open top result", "parameters": {{"url": "result_url"}}}},
  {{"action": "extract", "description": "Get restaurant details", "parameters": {{"selector": ".restaurant-info"}}}}
]

Important:
- Keep steps simple and atomic
- Maximum 10 steps
- Be practical and focused

Generate the plan:"""
        
        return prompt
    
    def _parse_plan_response(self, response: str) -> List[Step]:
        """Parse LLM response into steps."""
        try:
            # Extract JSON from response
            json_match = re.search(r'\[[\s\S]*\]', response)
            if not json_match:
                logger.warning("No JSON found in plan response")
                return []
            
            steps_data = json.loads(json_match.group())
            steps = []
            
            for i, step_data in enumerate(steps_data[:10], 1):  # Max 10 steps
                action_str = step_data.get("action", "custom")
                try:
                    action = StepType(action_str)
                except ValueError:
                    action = StepType.CUSTOM
                
                steps.append(Step(
                    id=i,
                    action=action,
                    description=step_data.get("description", f"Step {i}"),
                    parameters=step_data.get("parameters", {})
                ))
            
            return steps
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse plan JSON: {e}")
            return []
    
    def _heuristic_plan(self, request: str) -> List[Step]:
        """Create a simple plan using heuristics (fallback)."""
        request_lower = request.lower()
        steps = []
        step_id = 1
        
        # Search-based tasks
        if any(word in request_lower for word in ["find", "search", "look for", "research"]):
            # Extract what to search for
            search_query = request
            for prefix in ["find ", "search for ", "look for ", "research "]:
                if prefix in request_lower:
                    search_query = request[request_lower.find(prefix) + len(prefix):]
                    break
            
            steps.append(Step(
                id=step_id,
                action=StepType.SEARCH,
                description=f"Search for: {search_query}",
                parameters={"query": search_query}
            ))
            step_id += 1
            
            steps.append(Step(
                id=step_id,
                action=StepType.NOTIFY,
                description="Report search results",
                parameters={},
                depends_on=[step_id - 1]
            ))
        
        # Browse-based tasks
        elif any(word in request_lower for word in ["go to", "open", "visit", "browse"]):
            url_match = re.search(r'(https?://\S+|[\w.-]+\.(com|org|net|io)\S*)', request)
            url = url_match.group() if url_match else ""
            
            steps.append(Step(
                id=step_id,
                action=StepType.BROWSE,
                description=f"Open: {url}",
                parameters={"url": url}
            ))
            step_id += 1
            
            steps.append(Step(
                id=step_id,
                action=StepType.READ,
                description="Read page content",
                parameters={},
                depends_on=[step_id - 1]
            ))
        
        # Default: just notify
        if not steps:
            steps.append(Step(
                id=1,
                action=StepType.NOTIFY,
                description="Could not determine specific steps",
                parameters={"message": f"Request: {request}"}
            ))
        
        return steps
    
    def replan(self, plan: Plan, error: str, step: int) -> Plan:
        """
        Create a new plan after a step failure.
        
        Args:
            plan: The original plan
            error: The error that occurred
            step: The step that failed
            
        Returns:
            A revised plan
        """
        # Simple retry logic - mark failed step and continue
        if step < len(plan.steps):
            plan.steps[step - 1].status = "failed"
            plan.steps[step - 1].error = error
        
        return plan


# Global instance
_task_planner: Optional[TaskPlanner] = None


def get_task_planner() -> TaskPlanner:
    """Get the global task planner instance."""
    global _task_planner
    if _task_planner is None:
        _task_planner = TaskPlanner()
    return _task_planner
