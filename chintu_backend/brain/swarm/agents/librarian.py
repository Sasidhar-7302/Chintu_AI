"""Librarian Agent: Self-updating skill manager."""

import logging
import json
from typing import Any, Dict, Optional
from chintu_backend.brain.swarm.base_agent import BaseAgent

logger = logging.getLogger(__name__)

class LibrarianAgent(BaseAgent):
    """
    Monitors for "new tech" and proposes new SKILL.md files.
    """
    def __init__(self, llm_client=None):
        super().__init__(
            name="Librarian",
            description="Agent that maintains and updates Chintu's skill library."
        )
        self.llm_client = llm_client

    def run(self, goal: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Task: "Search for new tech and propose a skill."
        """
        self.update_state("executing")
        prompt = f"""
        You are Chintu's Librarian Agent in GOD MODE. Your goal is to autonomously BUILD a new capability for: {goal}.
        
        You have two options:
        1. DEPLOY AS CMD: If a simple shell command exists, provide a standard SKILL.md.
        2. DEPLOY AS PYTHON: If logic is complex, provide BOTH a Python handler AND a SKILL.md that calls it.

        Return your response in this EXACT JSON format:
        {{
            "skill_md": "Full content of SKILL.md",
            "python_handler": "Full content of handler.py (optional)",
            "handler_filename": "suggested_name.py (required if python_handler is present)"
        }}

        The SKILL.md must use the 'python' command to call your handler if provided.
        Example command: python {{SKILL_DIR}}/handlers/{{handler_filename}} {{args}}
        """
        
        response_text = ""
        try:
            response_text = self.llm_client.generate(prompt, system_prompt="Return ONLY valid JSON.")
        except TypeError:
            response_text = self.llm_client.generate(prompt)
        
        # Parse JSON
        try:
            data = self._parse_json(response_text)
            skill_md = data.get("skill_md", "")
            python_code = data.get("python_handler")
            handler_name = data.get("handler_filename")
        except Exception:
            # Fallback to legacy parsing if LLM failed JSON
            skill_md = response_text
            python_code = None
            handler_name = None

        # Store as proposal
        proposal_id = None
        try:
            from chintu_backend.automation.skills.skill_proposals import create_proposal
            
            # If we have python code, we need to bundle it into the proposal
            # For now, we'll append a hint to the MD that there's an associated file
            if python_code and handler_name:
                skill_md += f"\n\n<!-- ASSOCIATED_FILE: {handler_name} -->\n```python\n{python_code}\n```"

            proposal = create_proposal(
                skill_md,
                source="librarian_agent",
                reason=f"God Mode proposal for: {goal}",
            )
            proposal_id = proposal.id
        except Exception as e:
            logger.error(f"Failed to create proposal: {e}")
            proposal_id = None
        
        self.update_state("completed")

        skill_name = "unknown_skill"
        try:
            from chintu_backend.automation.skills.skill_registry import parse_skills_from_markdown

            specs = parse_skills_from_markdown(skill_md)
            if specs and specs[0].name:
                skill_name = specs[0].name
        except Exception:
            pass

        return {
            "proposed_skill": skill_md,
            "status": "waiting_for_approval",
            "proposal_id": proposal_id,
            "skill_name": skill_name,
        }

    def stop(self):
        self.update_state("idle")

    def _parse_json(self, response: str) -> Dict[str, Any]:
        """Extract JSON from an LLM response (supports code fences + raw objects)."""
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass
        # Markdown fenced JSON
        if "```json" in response:
            snippet = response.split("```json", 1)[1].split("```", 1)[0]
            return json.loads(snippet.strip())
        if "```" in response:
            snippet = response.split("```", 1)[1].split("```", 1)[0]
            return json.loads(snippet.strip())
        # Best-effort object extraction
        start = response.find("{")
        end = response.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(response[start:end])
        raise ValueError("No JSON object found in response.")
