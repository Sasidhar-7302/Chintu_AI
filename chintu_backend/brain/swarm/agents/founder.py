"""
Founder Agent - The Product Manager / CEO Agent

Workflow:
1. RESEARCH: Deep research on the task/problem domain
2. PLAN: Create detailed execution plan with time estimates
3. GATHER: Collect ALL required permissions/credentials upfront
4. BUDGET: Analyze costs and feasibility
5. EXECUTE: Work autonomously after approval (no step-by-step interrupts)
6. REPORT: Deliver results with summary
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum

from chintu_backend.brain.swarm.base_agent import BaseAgent, AgentState
from chintu_backend.swarm.agent_runtime import create_agent_runtime
from chintu_backend.core.config import get_config
from chintu_backend.brain.llm.ollama_client import OllamaClient
from chintu_backend.brain.llm.groq_client import GroqClient

logger = logging.getLogger(__name__)


class TaskPhase(Enum):
    RESEARCH = "research"
    PLANNING = "planning"
    GATHERING = "gathering"
    BUDGETING = "budgeting"
    EXECUTING = "executing"
    REPORTING = "reporting"


@dataclass
class RequiredResource:
    """A resource/permission needed from the user."""
    id: str
    type: str  # credential, approval, budget, file, input
    description: str
    required: bool = True
    provided: bool = False
    value: Any = None


@dataclass
class TaskEstimate:
    """Time and resource estimate for a task."""
    hours_estimated: float
    confidence: float  # 0-1
    breakdown: List[Dict[str, Any]] = field(default_factory=list)
    budget_usd: float = 0.0
    budget_breakdown: List[Dict[str, Any]] = field(default_factory=list)
    requires_from_user: List[RequiredResource] = field(default_factory=list)


@dataclass
class ExecutionPlan:
    """The full plan for task execution."""
    task_id: str
    original_request: str
    research_summary: str
    plan_steps: List[Dict[str, Any]]
    estimate: TaskEstimate
    created_at: datetime = field(default_factory=datetime.now)
    approved: bool = False
    status: str = "pending"


class FounderAgent(BaseAgent):
    """
    High-level strategist agent that acts like a Product Manager / Founder.
    
    Takes vague business requests and:
    1. Researches the problem
    2. Creates a detailed plan with estimates
    3. Gathers ALL permissions upfront
    4. Executes autonomously after approval
    5. Reports results
    """
    
    def __init__(self):
        super().__init__(
            name="Founder",
            description="Product Manager / CEO - researches, plans, estimates, and executes business tasks"
        )
        try:
            runtime = create_agent_runtime("founder")
            self.attach_runtime(runtime)
        except Exception:
            pass
        
        self.config = get_config()
        self.llm = None
        self._init_llm()
        
        self.current_phase = TaskPhase.RESEARCH
        self.current_plan: Optional[ExecutionPlan] = None
        self.sub_agents: Dict[str, BaseAgent] = {}
        
    def _init_llm(self):
        """Initialize LLM - prefer fast models for planning."""
        # Try NVIDIA Kimi K2 first, then Groq, then Ollama
        try:
            from chintu_backend.core.model_router import NvidiaClient
            nvidia_key = getattr(self.config, 'nvidia_api_key', None)
            if nvidia_key:
                self.llm = NvidiaClient(api_key=nvidia_key)
                logger.info("Founder using NVIDIA Kimi K2")
                return
        except Exception:
            pass
            
        if getattr(self.config, 'groq_api_key', None):
            try:
                self.llm = GroqClient(
                    model=getattr(self.config, 'groq_model', 'llama-3.1-70b-versatile'),
                    api_key=self.config.groq_api_key
                )
                logger.info("Founder using Groq")
                return
            except Exception:
                pass
        
        try:
            self.llm = OllamaClient(
                host=getattr(self.config, 'ollama_host', 'http://localhost:11434'),
                model=getattr(self.config, 'ollama_model', 'qwen2.5:3b')
            )
            logger.info("Founder using Ollama")
        except Exception:
            logger.warning("No LLM available for Founder")

    def run(self, goal: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Execute the Founder workflow:
        Research → Plan → Gather Requirements → Budget → Execute → Report
        """
        self.update_state(AgentState.PLANNING)
        self.log_step("Starting", f"Goal: {goal}")
        
        # Phase 1: Research
        self.current_phase = TaskPhase.RESEARCH
        research_result = self._research(goal)
        
        # Phase 2: Plan with estimates
        self.current_phase = TaskPhase.PLANNING
        plan = self._create_plan(goal, research_result)
        self.current_plan = plan
        
        # Phase 3: Gather all requirements upfront
        self.current_phase = TaskPhase.GATHERING
        requirements = self._gather_requirements(plan)
        
        # Phase 4: Budget analysis
        self.current_phase = TaskPhase.BUDGETING
        budget = self._analyze_budget(goal, plan, context)
        plan.estimate.budget_usd = budget.get("total_usd", 0)
        plan.estimate.budget_breakdown = budget.get("breakdown", [])
        
        # Return the plan for user approval (execution happens after approval)
        return {
            "success": True,
            "phase": "awaiting_approval",
            "plan": self._plan_to_dict(plan),
            "requires_approval": True,
            "requirements": [self._resource_to_dict(r) for r in requirements],
            "estimate": {
                "hours": plan.estimate.hours_estimated,
                "confidence": plan.estimate.confidence,
                "budget_usd": plan.estimate.budget_usd,
            },
            "message": self._generate_approval_message(plan)
        }
    
    def execute_approved_plan(self, plan_id: str, approvals: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a plan after user approval.
        Called when user approves the plan and provides required resources.
        """
        if not self.current_plan or self.current_plan.task_id != plan_id:
            return {"success": False, "error": "Plan not found"}
        
        self.current_plan.approved = True
        self.current_phase = TaskPhase.EXECUTING
        self.update_state(AgentState.EXECUTING)
        
        # Apply user-provided approvals
        for resource in self.current_plan.estimate.requires_from_user:
            if resource.id in approvals:
                resource.provided = True
                resource.value = approvals[resource.id]
        
        # Execute each step
        results = []
        for step in self.current_plan.plan_steps:
            self.log_step("Executing", step.get("description", "Step"))
            step_result = self._execute_step(step)
            results.append(step_result)
            
            if not step_result.get("success", False) and step.get("critical", True):
                self.current_plan.status = "failed"
                return {
                    "success": False,
                    "error": step_result.get("error", "Step failed"),
                    "completed_steps": results
                }
        
        # Phase 6: Report
        self.current_phase = TaskPhase.REPORTING
        self.current_plan.status = "completed"
        self.update_state(AgentState.COMPLETED)
        
        return {
            "success": True,
            "results": results,
            "summary": self._generate_summary(results)
        }
    
    def _research(self, goal: str) -> Dict[str, Any]:
        """
        Deep research on the task/problem domain.
        Uses web search, memory, and analysis.
        """
        self.log_step("Research", "Analyzing problem domain")
        
        prompt = f"""You are a Product Manager researching a task. Analyze this request:

REQUEST: {goal}

Provide a comprehensive research summary:
1. What exactly is being asked?
2. What are the key challenges?
3. What technologies/tools are needed?
4. What are similar products/solutions?
5. What are potential risks?
6. What's the minimum viable approach?

Be specific and practical. Output as JSON:
{{
    "understanding": "clear description of what's needed",
    "challenges": ["list of challenges"],
    "technologies": ["required tech stack"],
    "similar_solutions": ["existing similar products"],
    "risks": ["potential risks"],
    "mvp_approach": "minimum viable approach"
}}"""

        try:
            response = self._llm_generate(prompt)
            return self._parse_json(response)
        except Exception as e:
            logger.error(f"Research failed: {e}")
            return {"understanding": goal, "challenges": [], "technologies": []}
    
    def _create_plan(self, goal: str, research: Dict[str, Any]) -> ExecutionPlan:
        """Create detailed execution plan with time estimates."""
        self.log_step("Planning", "Creating execution plan")
        
        prompt = f"""You are a Product Manager creating an execution plan.

GOAL: {goal}

RESEARCH FINDINGS:
{json.dumps(research, indent=2)}

Create a detailed execution plan. Consider:
- I work 24/7 without breaks
- Be realistic about time estimates
- Break down into small, parallel-able steps
- Identify what I need from the user UPFRONT (credentials, decisions, files)

Output as JSON:
{{
    "steps": [
        {{
            "id": 1,
            "description": "step description",
            "agent": "which agent does this (Coder/Ops/etc)",
            "hours_estimate": 0.5,
            "depends_on": [],
            "deliverable": "what this produces",
            "critical": true
        }}
    ],
    "total_hours": 5.0,
    "confidence": 0.8,
    "parallel_possible": true,
    "requires_from_user": [
        {{
            "id": "hosting_creds",
            "type": "credential",
            "description": "Vercel/Railway API key for deployment",
            "required": true
        }}
    ]
}}"""

        try:
            response = self._llm_generate(prompt)
            plan_data = self._parse_json(response)
            
            # Build estimate
            requires = [
                RequiredResource(
                    id=r["id"],
                    type=r.get("type", "input"),
                    description=r.get("description", ""),
                    required=r.get("required", True)
                )
                for r in plan_data.get("requires_from_user", [])
            ]
            
            estimate = TaskEstimate(
                hours_estimated=plan_data.get("total_hours", 8.0),
                confidence=plan_data.get("confidence", 0.7),
                breakdown=[
                    {"step": s["description"], "hours": s.get("hours_estimate", 1)}
                    for s in plan_data.get("steps", [])
                ],
                requires_from_user=requires
            )
            
            import uuid
            return ExecutionPlan(
                task_id=str(uuid.uuid4())[:8],
                original_request=goal,
                research_summary=json.dumps(research),
                plan_steps=plan_data.get("steps", []),
                estimate=estimate
            )
            
        except Exception as e:
            logger.error(f"Planning failed: {e}")
            import uuid
            return ExecutionPlan(
                task_id=str(uuid.uuid4())[:8],
                original_request=goal,
                research_summary="",
                plan_steps=[{"description": goal, "agent": "Coder", "hours_estimate": 8}],
                estimate=TaskEstimate(hours_estimated=8.0, confidence=0.5)
            )
    
    def _gather_requirements(self, plan: ExecutionPlan) -> List[RequiredResource]:
        """Collect all requirements from plan."""
        return plan.estimate.requires_from_user
    
    def _analyze_budget(self, goal: str, plan: ExecutionPlan, context: Optional[Dict]) -> Dict[str, Any]:
        """Analyze budget requirements and feasibility."""
        self.log_step("Budget", "Analyzing costs")
        
        user_budget = context.get("budget_usd", 0) if context else 0
        
        prompt = f"""Analyze the budget for this project:

GOAL: {goal}
PLAN STEPS: {len(plan.plan_steps)} steps
ESTIMATED HOURS: {plan.estimate.hours_estimated}
USER BUDGET: ${user_budget}

Estimate costs:
- Hosting (estimate monthly cost)
- APIs (if any external services needed)
- Domain (if needed)
- One-time setup costs

Output JSON:
{{
    "total_usd": 50.0,
    "monthly_recurring": 10.0,
    "breakdown": [
        {{"item": "Hosting (Vercel)", "cost": 0, "note": "Free tier"}}
    ],
    "within_budget": true,
    "recommendations": "Cost optimization suggestions"
}}"""

        try:
            response = self._llm_generate(prompt)
            budget = self._parse_json(response)
            
            # Add feasibility assessment
            if user_budget > 0:
                budget["within_budget"] = budget.get("total_usd", 0) <= user_budget
            
            return budget
        except Exception as e:
            logger.error(f"Budget analysis failed: {e}")
            return {"total_usd": 0, "breakdown": [], "within_budget": True}
    
    def _execute_step(self, step: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a single step from the plan."""
        agent_name = step.get("agent", "Coder")
        description = step.get("description", "")
        
        self.log_step("Step", f"{agent_name}: {description}")
        
        # Get or create agent
        agent = self.sub_agents.get(agent_name)
        if not agent:
            agent = self._get_or_create_agent(agent_name)
            if agent:
                self.sub_agents[agent_name] = agent
        
        if not agent:
            return {"success": False, "error": f"Agent {agent_name} not available"}
        
        try:
            result = agent.run(description, {"parent_plan": self.current_plan})
            return {"success": True, "output": result}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _get_or_create_agent(self, agent_name: str) -> Optional[BaseAgent]:
        """Get an agent by name, creating if needed."""
        try:
            # Try importing known agents
            agent_map = {
                "Coder": "chintu_backend.brain.swarm.agents.coder",
                "Shopper": "chintu_backend.brain.swarm.agents.shopper",
                "TaskMaster": "chintu_backend.brain.swarm.agents.task_master",
            }
            
            if agent_name in agent_map:
                module = __import__(agent_map[agent_name], fromlist=[agent_name])
                agent_class = getattr(module, agent_name)
                return agent_class()
        except Exception as e:
            logger.warning(f"Could not create agent {agent_name}: {e}")
        
        return None
    
    def _generate_approval_message(self, plan: ExecutionPlan) -> str:
        """Generate a user-friendly approval message."""
        est = plan.estimate
        hours = est.hours_estimated
        
        # Calculate completion time
        completion = datetime.now() + timedelta(hours=hours)
        
        msg_parts = [
            f"📋 **Project Plan Ready**",
            f"",
            f"**Task:** {plan.original_request}",
            f"",
            f"**Estimate:**",
            f"- ⏱️ Time: ~{hours:.1f} hours",
            f"- 📅 Done by: {completion.strftime('%Y-%m-%d %H:%M')}",
            f"- 💰 Budget: ${est.budget_usd:.2f}",
            f"- 📊 Confidence: {est.confidence*100:.0f}%",
            f"",
            f"**Steps:** {len(plan.plan_steps)}",
        ]
        
        for step in plan.plan_steps[:5]:
            msg_parts.append(f"  {step.get('id', '-')}. {step.get('description', 'Step')}")
        
        if len(plan.plan_steps) > 5:
            msg_parts.append(f"  ... and {len(plan.plan_steps) - 5} more")
        
        if est.requires_from_user:
            msg_parts.append("")
            msg_parts.append("**I need from you:**")
            for req in est.requires_from_user:
                msg_parts.append(f"  - {req.description}")
        
        msg_parts.append("")
        msg_parts.append("Reply 'approve' to start, or provide feedback to adjust.")
        
        return "\n".join(msg_parts)
    
    def _plan_to_dict(self, plan: ExecutionPlan) -> Dict[str, Any]:
        """Convert plan to dictionary for serialization."""
        return {
            "task_id": plan.task_id,
            "original_request": plan.original_request,
            "research_summary": plan.research_summary,
            "steps": plan.plan_steps,
            "created_at": plan.created_at.isoformat(),
            "status": plan.status
        }
    
    def _resource_to_dict(self, resource: RequiredResource) -> Dict[str, Any]:
        """Convert resource to dictionary."""
        return {
            "id": resource.id,
            "type": resource.type,
            "description": resource.description,
            "required": resource.required,
            "provided": resource.provided
        }
    
    def _generate_summary(self, results: List[Dict]) -> str:
        """Generate execution summary."""
        successful = sum(1 for r in results if r.get("success"))
        total = len(results)
        return f"Completed {successful}/{total} steps successfully."
    
    def _llm_generate(self, prompt: str) -> str:
        """Generate response from LLM."""
        if not self.llm:
            raise RuntimeError("No LLM available")
        
        if hasattr(self.llm, 'chat'):
            return self.llm.chat(prompt)
        elif hasattr(self.llm, 'generate'):
            return self.llm.generate(prompt)
        else:
            raise RuntimeError("LLM has no generate method")
    
    def _parse_json(self, response: str) -> Dict[str, Any]:
        """Extract JSON from LLM response."""
        try:
            # Try direct parse
            return json.loads(response)
        except json.JSONDecodeError:
            # Try extracting from markdown
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
                return json.loads(json_str.strip())
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0]
                return json.loads(json_str.strip())
            # Try finding JSON object
            start = response.find("{")
            end = response.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(response[start:end])
            return {}
    
    def stop(self):
        """Stop execution."""
        for agent in self.sub_agents.values():
            try:
                agent.stop()
            except Exception:
                pass
        self.update_state(AgentState.IDLE)
