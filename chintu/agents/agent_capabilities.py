"""
Agent capability handlers for Chintu AI Assistant.
Provides voice commands for multi-step workflow execution.
"""

import logging
from typing import Dict, Any

from ..core.capabilities import Capability, CapabilityType, ActionResult

logger = logging.getLogger(__name__)


def handle_execute_workflow(text: str, context: Dict[str, Any]) -> ActionResult:
    """
    Execute a multi-step workflow based on user request.
    
    Examples:
        "Find the best laptop under $1000 and save the results"
        "Research Python frameworks and make a comparison"
        "Go to Google, search for news, and summarize the top stories"
    """
    from .task_planner import get_task_planner
    from .workflow_engine import get_workflow_engine
    
    # Extract the task description
    query = text.strip()
    prefixes = [
        "execute ", "run workflow ", "do this: ", "perform ",
        "automate ", "multi-step ", "workflow: "
    ]
    
    task_description = query
    for prefix in prefixes:
        if query.lower().startswith(prefix):
            task_description = query[len(prefix):].strip()
            break
    
    if not task_description or len(task_description) < 5:
        return ActionResult.fail(
            "What would you like me to do? Describe the task.",
            "execute_workflow"
        )
    
    try:
        # Plan the workflow
        planner = get_task_planner()
        plan = planner.plan(task_description, context)
        
        if not plan.steps:
            return ActionResult.fail(
                "I couldn't create a plan for that task. Could you be more specific?",
                "execute_workflow"
            )

        if context.get("_plan_only"):
            lines = [f"Plan: {plan.goal}", ""]
            for step in plan.steps:
                lines.append(f"- Step {step.id}: {step.description}")
                if step.parameters:
                    lines.append(f"  Parameters: {step.parameters}")
            return ActionResult.ok("\n".join(lines), capability="execute_workflow")
        
        # Execute the workflow
        engine = get_workflow_engine()
        result = engine.execute(plan)
        
        # Format the response
        if result.success:
            response = f"**Workflow Complete!** ({result.duration_seconds:.1f}s)\n\n"
            response += f"{result.steps_completed}/{result.steps_total} steps completed.\n\n"
            response += f"**Result:**\n{result.final_result}"
        else:
            response = f"**Workflow Partially Complete**\n\n"
            response += f"{result.steps_completed}/{result.steps_total} steps completed.\n\n"
            if result.errors:
                response += f"**Errors:**\n- " + "\n- ".join(result.errors)
            if result.final_result:
                response += f"\n\n**Last Result:**\n{result.final_result}"
        
        return ActionResult.ok(
            response,
            {
                "steps_completed": result.steps_completed,
                "steps_total": result.steps_total,
                "success": result.success,
                "duration": result.duration_seconds
            },
            "execute_workflow"
        )
        
    except Exception as e:
        logger.error(f"Workflow execution failed: {e}")
        return ActionResult.fail(
            f"Workflow failed: {e}",
            "execute_workflow"
        )


def handle_plan_task(text: str, context: Dict[str, Any]) -> ActionResult:
    """
    Plan a task without executing (preview mode).
    
    Examples:
        "Plan: research AI trends"
        "Show me the steps to find a restaurant"
    """
    from .task_planner import get_task_planner
    
    # Extract the task description
    query = text.strip()
    prefixes = [
        "plan: ", "plan ", "show me the steps to ", "how would you ",
        "what steps to ", "break down "
    ]
    
    task_description = query
    for prefix in prefixes:
        if query.lower().startswith(prefix):
            task_description = query[len(prefix):].strip()
            break
    
    if not task_description or len(task_description) < 5:
        return ActionResult.fail(
            "What would you like me to plan?",
            "plan_task"
        )
    
    try:
        planner = get_task_planner()
        plan = planner.plan(task_description, context)
        
        if not plan.steps:
            return ActionResult.fail(
                "I couldn't create a plan for that. Could you be more specific?",
                "plan_task"
            )
        
        response = f"**Plan: {plan.goal}**\n\n"
        for step in plan.steps:
            response += f"[ ] **Step {step.id}:** {step.description}\n"
            if step.parameters:
                response += f"    Parameters: {step.parameters}\n"
        
        response += f"\n*Say \"execute this\" to run the workflow.*"
        
        return ActionResult.ok(
            response,
            {"goal": plan.goal, "steps": len(plan.steps)},
            "plan_task"
        )
        
    except Exception as e:
        logger.error(f"Task planning failed: {e}")
        return ActionResult.fail(
            f"Planning failed: {e}",
            "plan_task"
        )


def handle_quick_action(text: str, context: Dict[str, Any]) -> ActionResult:
    """
    Handle quick multi-step actions with common patterns.
    
    Examples:
        "Search and summarize Python tutorials"
        "Find and compare laptops"
    """
    from .task_planner import get_task_planner, Step, StepType, Plan
    from .workflow_engine import get_workflow_engine
    from datetime import datetime
    
    query = text.lower().strip()
    
    # Pattern: Search and summarize
    if "search and summarize" in query or "find and summarize" in query:
        topic = query.replace("search and summarize", "").replace("find and summarize", "").strip()
        
        plan = Plan(
            goal=f"Search and summarize: {topic}",
            steps=[
                Step(1, StepType.SEARCH, f"Search for {topic}", {"query": topic}),
                Step(2, StepType.NOTIFY, "Present results summary", {}, depends_on=[1])
            ],
            created_at=datetime.now().isoformat()
        )
        
        engine = get_workflow_engine()
        result = engine.execute(plan)
        
        return ActionResult.ok(
            result.final_result,
            {"success": result.success, "steps": 2},
            "quick_action"
        )
    
    # Pattern: Find and compare
    if "find and compare" in query or "compare" in query:
        items = query.replace("find and compare", "").replace("compare", "").strip()
        
        plan = Plan(
            goal=f"Compare: {items}",
            steps=[
                Step(1, StepType.SEARCH, f"Search for {items} comparison", {"query": f"{items} comparison review"}),
                Step(2, StepType.NOTIFY, "Present comparison", {}, depends_on=[1])
            ],
            created_at=datetime.now().isoformat()
        )
        
        engine = get_workflow_engine()
        result = engine.execute(plan)
        
        return ActionResult.ok(
            result.final_result,
            {"success": result.success},
            "quick_action"
        )
    
    # Fall back to general workflow
    return handle_execute_workflow(text, context)


def register_agent_capabilities(registry) -> None:
    """Register all agent-related capabilities."""
    
    # Execute Workflow
    registry.register(Capability(
        name="execute_workflow",
        triggers=[
            "execute ", "run workflow", "do this:", "perform ",
            "automate ", "multi-step"
        ],
        handler=handle_execute_workflow,
        requires_confirmation=False,
        description="execute a multi-step workflow",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=[
            "Execute: find the best laptop and save results",
            "Do this: research Python and summarize"
        ]
    ))
    
    # Plan Task (Preview)
    registry.register(Capability(
        name="plan_task",
        triggers=[
            "plan:", "show me the steps", "how would you",
            "what steps", "break down"
        ],
        handler=handle_plan_task,
        requires_confirmation=False,
        description="plan a task without executing",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=[
            "Plan: research AI trends",
            "Show me the steps to find a restaurant"
        ]
    ))
    
    # Quick Actions
    registry.register(Capability(
        name="quick_action",
        triggers=[
            "search and summarize", "find and summarize",
            "find and compare", "compare "
        ],
        handler=handle_quick_action,
        requires_confirmation=False,
        description="quick multi-step actions",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=[
            "Search and summarize Python tutorials",
            "Find and compare laptops"
        ]
    ))
    
    logger.info("Registered agent capabilities")
