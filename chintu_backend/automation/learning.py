"""
Learning Engine for Chintu AI Assistant.
Analyses interaction history to suggest new skills or optimizations.
"""

import os
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from chintu_backend.core.config import get_config

logger = logging.getLogger(__name__)

class LearningEngine:
    """
    Analyzes past actions and interactions to evolve Chintu's brain.
    """
    def __init__(self, llm_client=None):
        self.config = get_config()
        self.llm = llm_client
        if not self.llm:
            try:
                from ..brain.llm.ollama_client import OllamaClient
                self.llm = OllamaClient()
            except Exception:
                self.llm = None
        
        self.history_path = self.config.training_log_path
        self.proposals_dir = self.config.skills_proposals_dir

    def run_daily_learning(self):
        """Perform the daily growth analysis."""
        logger.info("🧬 Starting Daily Learning Hour...")
        
        if not self.history_path or not self.history_path.exists():
            logger.warning("No interaction history found for learning.")
            return
            
        # 1. Load recent history (last 100 entries)
        history = self._load_recent_history(limit=100)
        if not history:
            return

        # 2. Analyze for skill gaps
        gaps = self._analyze_for_gaps(history)
        
        # 3. Propose new skills for gaps
        for gap in gaps:
            self._propose_new_skill(gap)
            
        logger.info(f"🧬 Learning complete. Identified {len(gaps)} potential growth areas.")

    def _load_recent_history(self, limit: int) -> List[Dict]:
        """Load recent interaction records."""
        history = []
        try:
            with open(self.history_path, 'r', encoding='utf-8') as f:
                # Read last lines efficiently
                lines = f.readlines()
                for line in lines[-limit:]:
                    try:
                        history.append(json.loads(line))
                    except:
                        continue
        except Exception as e:
            logger.error(f"Failed to load history: {e}")
        return history

    def _analyze_for_gaps(self, history: List[Dict]) -> List[str]:
        """Use LLM to identify goals that were complex or partially failed."""
        if not self.llm or not self.llm.is_available:
            return []

        # Summarize history for LLM
        history_summary = []
        for h in history:
            goal = h.get("input") or h.get("goal")
            success = h.get("success", True)
            if goal:
                history_summary.append(f"Goal: {goal} | Success: {success}")

        history_text = "\n".join(history_summary)
        
        prompt = f"""
        Analyze the following Chintu AI interaction history:
        {history_text}

        Identify 1-2 repetitive tasks or complex goals that would benefit from a dedicated, high-performance Skill.
        Focused on: OS automation, browser tasks, or calculations.
        
        Return ONLY a comma-separated list of short goal descriptions.
        Example: search for latest AI news and summarize, automate job application on LinkedIn
        """
        
        try:
            response = self.llm.generate(prompt, system_prompt="You are Chintu's Metacognitive Learning Engine.")
            gaps = [g.strip() for g in response.split(",") if g.strip()]
            return gaps
        except Exception as e:
            logger.error(f"Gap analysis failed: {e}")
            return []

    def _propose_new_skill(self, goal: str):
        """Invoke the LibrarianAgent to draft a new skill."""
        logger.info(f"🧬 Distilling new skill for: {goal}")
        try:
            from ..brain.swarm.agents.librarian import LibrarianAgent
            librarian = LibrarianAgent(llm_client=self.llm)
            result = librarian.run(goal)
            logger.info(f"🧬 Proposed new skill: {result.get('skill_name', 'Unknown')}")
        except Exception as e:
            logger.error(f"Failed to propose skill for {goal}: {e}")

def get_learning_engine():
    """Get global learning engine instance."""
    return LearningEngine()
