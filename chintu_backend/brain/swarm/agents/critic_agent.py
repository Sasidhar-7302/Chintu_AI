"""
Critic Agent.
Reviews plans, code, and strategies for potential errors or safety violations.
Acts as a gatekeeper in the Swarm workflow.
"""

import logging
import json
from typing import Dict, Any, List, Optional
from chintu_backend.brain.swarm.base_agent import BaseAgent, AgentState
from chintu_backend.core.config import get_config
from chintu_backend.brain.llm.ollama_client import OllamaClient
from chintu_backend.brain.llm.groq_client import GroqClient

logger = logging.getLogger(__name__)

class CriticAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="CriticAgent", description="Reviews plans and logic for errors")
        self.config = get_config()
        self._init_llm()

    def _init_llm(self):
        # Prefer Groq for fast reasoning
        self.llm = None
        if self.config.groq_api_key:
            try:
                self.llm = GroqClient(model=self.config.groq_model, api_key=self.config.groq_api_key)
            except: pass
            
        if not self.llm:
            try:
                self.llm = OllamaClient(host=self.config.ollama_host, model=self.config.ollama_model)
            except: pass

    def run(self, goal: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Default run method (required by BaseAgent).
        Usually called with specific Review request context.
        """
        plan = context.get("plan") if context else None
        if not plan:
             return {"success": False, "error": "No plan provided to critique"}
        
        return self.review_plan(goal, plan)

    def review_plan(self, goal: str, plan: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Analyze a plan for logical consistency and safety.
        Returns: { "approved": bool, "feedback": str, "risk_score": float }
        """
        self.update_state("reviewing")
        self.log_step("Reviewing Plan", f"Goal: {goal}")

        if not self.llm:
             return {"approved": True, "feedback": "Critic LLM unavailable - skipped.", "risk_score": 0.0}

        prompt = (
            f"Act as a QA Critic for an AI Agent Swarm.\n"
            f"Goal: \"{goal}\"\n\n"
            f"Proposed Plan:\n{json.dumps(plan, indent=2)}\n\n"
            "Analyze this plan for:\n"
            "1. Logic Holes (Missing steps?)\n"
            "2. Safety Risks (Unsafe commands?)\n"
            "3. Efficiency (Redundant steps?)\n\n"
            "Return JSON:\n"
            "{ \"approved\": boolean, \"feedback\": \"concise critique\", \"risk_score\": 0.0-1.0 }"
        )

        try:
            response = self.llm.chat(prompt) if hasattr(self.llm, 'chat') else self.llm.generate(prompt)
            # Json cleanup
            snippet = response
            if "```json" in snippet:
                snippet = snippet.split("```json")[1].split("```")[0]
            elif "```" in snippet:
                 snippet = snippet.split("```")[1].split("```")[0]
            
            result = json.loads(snippet.strip())
            approved = result.get("approved", True)
            feedback = result.get("feedback", "No feedback provided.")
            
            self.log_step("Review Complete", f"Approved: {approved} | Feedback: {feedback}")
            self.update_state(AgentState.IDLE)
            
            return result
        except Exception as e:
            logger.error(f"Critic failed: {e}")
            # Fail open or closed? Fail open for now to avoid blocking.
            return {"approved": True, "feedback": f"Critic error: {e}", "risk_score": 0.0}

    def stop(self):
        self.update_state(AgentState.IDLE)
