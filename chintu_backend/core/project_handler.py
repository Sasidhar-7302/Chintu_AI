"""
Project Handler - Routes project/build requests to Founder agent.

This handler intercepts BUILD intent commands and delegates to the
Founder agent for the PM workflow: Research → Plan → Gather → Execute.
"""

import asyncio
import logging
import re
from typing import Dict, Any, Optional, Tuple

from chintu_backend.brain.swarm.agents.founder import FounderAgent
from chintu_backend.brain.swarm.agent_factory import get_agent_factory, AgentRole

logger = logging.getLogger(__name__)


class ProjectHandler:
    """
    Handles project/build requests using the Founder agent.
    
    Workflow:
    1. Detect if request is a project/build task
    2. Extract budget and other constraints
    3. Delegate to Founder for PM workflow
    4. Return plan for approval
    5. Execute after approval
    """
    
    # Patterns for detecting project requests
    PROJECT_PATTERNS = [
        r"build\s+(me\s+)?(a|an)?\s*(.+)",
        r"create\s+(me\s+)?(a|an)?\s*(.+)app",
        r"make\s+(me\s+)?(a|an)?\s*(.+)that",
        r"develop\s+(a|an)?\s*(.+)",
        r"deploy\s+(.+)",
        r"host\s+(.+)",
        r"launch\s+(a|an)?\s*(.+)",
    ]
    
    # Budget extraction patterns
    BUDGET_PATTERNS = [
        r"\$\s*(\d+(?:,\d{3})*(?:\.\d{2})?)",
        r"(\d+(?:,\d{3})*(?:\.\d{2})?)\s*(?:dollars|usd)",
        r"budget\s*(?:is|of)?\s*\$?\s*(\d+)",
    ]
    
    def __init__(self):
        self.founder: Optional[FounderAgent] = None
        self.pending_plans: Dict[str, Dict[str, Any]] = {}
        self.factory = get_agent_factory()
    
    def is_project_request(self, text: str) -> bool:
        """Check if text is a project/build request."""
        text_lower = text.lower()
        
        # Check for project keywords + context
        project_keywords = ["build", "develop", "deploy", "host", "launch", "ship"]
        product_keywords = ["app", "application", "website", "site", "product", 
                          "saas", "platform", "project", "dashboard", "api", "service"]
        
        has_project_verb = any(kw in text_lower for kw in project_keywords)
        has_product_noun = any(kw in text_lower for kw in product_keywords)
        
        # Also check for business keywords
        business_keywords = ["passive income", "make money", "revenue", "monetize", "budget"]
        has_business = any(kw in text_lower for kw in business_keywords)
        
        return (has_project_verb and has_product_noun) or has_business
    
    def extract_budget(self, text: str) -> Optional[float]:
        """Extract budget from text."""
        for pattern in self.BUDGET_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                budget_str = match.group(1).replace(",", "")
                try:
                    return float(budget_str)
                except ValueError:
                    continue
        return None
    
    async def handle(self, text: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Handle a project request.
        
        Args:
            text: User's request
            context: Additional context (user preferences, etc.)
            
        Returns:
            Result with plan requiring approval, or execution result
        """
        context = context or {}
        
        # Extract budget if mentioned
        budget = self.extract_budget(text)
        if budget:
            context["budget_usd"] = budget
            logger.info(f"Detected budget: ${budget}")
        
        # Initialize Founder if needed
        if not self.founder:
            self.founder = FounderAgent()
        
        # Run Founder workflow
        logger.info(f"Delegating to Founder: {text[:100]}...")
        result = self.founder.run(text, context)
        
        # Store pending plan for approval
        if result.get("requires_approval"):
            plan = result.get("plan", {})
            task_id = plan.get("task_id", "unknown")
            self.pending_plans[task_id] = {
                "plan": plan,
                "requirements": result.get("requirements", []),
                "estimate": result.get("estimate", {}),
            }
            
            return {
                "type": "approval_required",
                "task_id": task_id,
                "message": result.get("message", ""),
                "plan": plan,
                "requirements": result.get("requirements", []),
                "estimate": result.get("estimate", {}),
            }
        
        return result
    
    async def approve_and_execute(
        self, 
        task_id: str, 
        approvals: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Approve a plan and execute it.
        
        Args:
            task_id: ID of the task to approve
            approvals: User-provided credentials/approvals
            
        Returns:
            Execution result
        """
        if task_id not in self.pending_plans:
            return {"success": False, "error": f"Task {task_id} not found"}
        
        if not self.founder:
            return {"success": False, "error": "Founder not initialized"}
        
        approvals = approvals or {}
        
        # Execute the approved plan
        result = self.founder.execute_approved_plan(task_id, approvals)
        
        # Clean up
        self.pending_plans.pop(task_id, None)
        
        return result
    
    def get_pending_plans(self) -> Dict[str, Dict[str, Any]]:
        """Get all pending plans awaiting approval."""
        return self.pending_plans.copy()
    
    def reject_plan(self, task_id: str, reason: str = "") -> bool:
        """Reject a pending plan."""
        if task_id in self.pending_plans:
            self.pending_plans.pop(task_id)
            logger.info(f"Rejected plan {task_id}: {reason}")
            return True
        return False


# Singleton instance
_project_handler: Optional[ProjectHandler] = None


def get_project_handler() -> ProjectHandler:
    """Get or create the project handler singleton."""
    global _project_handler
    if _project_handler is None:
        _project_handler = ProjectHandler()
    return _project_handler


async def handle_build_intent(text: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Convenience function to handle BUILD intent commands.
    
    Called from the main command router when BUILD intent is detected.
    """
    handler = get_project_handler()
    return await handler.handle(text, context)
