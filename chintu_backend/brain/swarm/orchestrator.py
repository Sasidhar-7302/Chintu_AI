"""
Swarm Orchestrator ("The Manager")
Interprets goals, decomposes tasks, and assigns them to specialized agents.
"""

import logging
import json
from typing import Dict, Any, List, Optional
from chintu_backend.brain.swarm.base_agent import BaseAgent, AgentState
from chintu_backend.swarm.agent_runtime import create_agent_runtime
from chintu_backend.core.config import get_config
from chintu_backend.brain.llm.ollama_client import OllamaClient
from chintu_backend.brain.llm.groq_client import GroqClient
from chintu_backend.brain.swarm.agents.critic_agent import CriticAgent

logger = logging.getLogger(__name__)

class SwarmOrchestrator(BaseAgent):
    def __init__(self):
        super().__init__(name="SwarmOrchestrator", description="High-level planner and task delegator")
        try:
            runtime = create_agent_runtime("orchestrator")
            self.attach_runtime(runtime)
        except Exception:
            pass
        self.agents: Dict[str, BaseAgent] = {}
        self.config = get_config()
        self._init_llm()
        try:
            self.critic = CriticAgent()
        except:
            self.critic = None
        
    def _init_llm(self):
        # Prefer Groq for fast planning
        self.llm = None
        if self.config.groq_api_key:
            try:
                self.llm = GroqClient(model=self.config.groq_model, api_key=self.config.groq_api_key)
            except: pass
            
        if not self.llm:
            try:
                self.llm = OllamaClient(host=self.config.ollama_host, model=self.config.ollama_model)
            except: pass

    def register_agent(self, agent: BaseAgent):
        """Register a worker agent to the swarm."""
        try:
            runtime = create_agent_runtime(agent.name.lower())
            agent.attach_runtime(runtime)
        except Exception:
            pass
        self.agents[agent.name] = agent
        logger.info(f"Registered agent: {agent.name}")

    def run(self, goal: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Orchestrate the execution of a high-level goal.
        1. Decompose goal.
        2. Assign agents.
        3. Execute and Aggregate.
        """
        self.update_state(AgentState.PLANNING)
        self.log_step("Planning", f"Goal: {goal}")
        
        # 1. Plan
        plan = self._create_plan(goal)
        if not plan:
            return {"success": False, "error": "Planning failed"}
            
        # 2. Critique (Self-Correction)
        if self.critic:
            try:
                review = self.critic.review_plan(goal, plan)
                if not review.get("approved"):
                    self.log_step("Critic Rejected", review.get("feedback"))
                    # Simple retry logic: Append feedback to goal and replan
                    refined_goal = f"{goal} (Constraint: {review.get('feedback')})"
                    plan = self._create_plan(refined_goal)
                    self.log_step("Re-Planned", "Generated new plan based on critique")
            except Exception as e:
                logger.warning(f"Critic loop failed: {e}")

        results = []
        
        # 3. Execute steps
        self.update_state(AgentState.EXECUTING)
        for step in plan:
            agent_name = step.get("agent")
            task_desc = step.get("task")
            
            self.log_step("Delegating", f"Task: {task_desc} -> Agent: {agent_name}")
            
            agent = self.agents.get(agent_name)
            if not agent:
                logger.warning(f"Agent {agent_name} not found. Skipping step.")
                results.append({"step": task_desc, "status": "skipped", "error": "Agent not found"})
                continue
                
            try:
                step_result = agent.run(task_desc, context)
                results.append({"step": task_desc, "status": "completed", "output": step_result})
            except Exception as e:
                logger.error(f"Step failed: {e}")
                results.append({"step": task_desc, "status": "failed", "error": str(e)})
                
        self.update_state(AgentState.COMPLETED)
        return {"success": True, "plan": plan, "results": results}

    def _create_plan(self, goal: str) -> List[Dict[str, Any]]:
        """Use LLM to decompose goal into steps for available agents."""
        available_agents = ", ".join([f"{a.name} ({a.description})" for a in self.agents.values()])
        
        prompt = (
            f"Act as a Project Manager for a Swarm of AI Agents.\n"
            f"Goal: \"{goal}\"\n\n"
            f"Available Agents:\n{available_agents}\n\n"
            "Create a JSON execution plan. Return generic 'BaseAgent' if no specialist fits.\n"
            "Format: json list of { \"agent\": \"AgentName\", \"task\": \"specific instruction\" }"
        )
        
        try:
            response = self.llm.chat(prompt) if hasattr(self.llm, 'chat') else self.llm.generate(prompt)
            # Basic json cleanup
            clean_json = response
            if "```json" in clean_json:
                clean_json = clean_json.split("```json")[1].split("```")[0]
            elif "```" in clean_json:
                 clean_json = clean_json.split("```")[1].split("```")[0]
                 
            return json.loads(clean_json.strip())
        except Exception as e:
            logger.error(f"Planning failed: {e}")
            return []

    def stop(self):
        for agent in self.agents.values():
            agent.stop()
        self.update_state(AgentState.IDLE)
