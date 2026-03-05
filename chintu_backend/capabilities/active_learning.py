"""
Active Learning: Enables Chintu to Research -> Learn -> Synthesize new skills.
"""

import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import List, Tuple

from ..core.config import get_config

logger = logging.getLogger(__name__)

class ActiveLearner:
    """
    Research a topic and save it as a persistent skill/memory.
    """
    
    def __init__(self):
        self.config = get_config()
        self.skills_dir = str(self.config.skills_proposals_dir)
        os.makedirs(self.skills_dir, exist_ok=True)
        self.last_research_time = 0

    def _sanitize_topic(self, topic: str) -> str:
        cleaned = re.sub(r"\s+", " ", str(topic or "").strip())
        return cleaned[:160]

    def _rate_limited(self) -> bool:
        cooldown_seconds = int(getattr(self.config, "learning_active_cooldown_seconds", 300))
        return (time.time() - self.last_research_time) < max(10, cooldown_seconds)

    def _cpu_too_high(self) -> bool:
        max_cpu = int(getattr(self.config, "learning_active_max_cpu_percent", 50))
        try:
            import psutil

            return bool(psutil.cpu_percent(interval=0.1) > max_cpu)
        except Exception:
            return False

    def _research_topic(self, topic: str, max_results: int = 5) -> Tuple[str, List[str]]:
        """Collect best-effort web evidence for a topic."""
        from chintu_backend.search.search_capabilities import search_web

        search_query = f"{topic} how-to best practices"
        raw_results, formatted = search_web(search_query, max_results=max_results)
        sources: List[str] = []
        for item in raw_results or []:
            url = getattr(item, "url", None)
            if url:
                sources.append(str(url))
        return str(formatted or "").strip(), sources

    def _build_skill_markdown(self, topic: str, summary: str, sources: List[str]) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-") or "learned-skill"
        trigger_a = topic.lower().strip()
        trigger_b = f"help with {trigger_a}"
        trigger_c = f"automate {trigger_a}"
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        lines = [
            f"# {slug}",
            f"Description: Learned skill draft for {topic}.",
            f"Triggers: {trigger_a}, {trigger_b}, {trigger_c}",
            "Type: instruction",
            "",
            f"## Learned: {ts}",
            "",
            "## Purpose",
            f"This skill helps with requests related to {topic}.",
            "",
            "## Research Summary",
            summary or f"Web research was limited. Use this as a starter for {topic}.",
            "",
            "## Source Links",
        ]
        if sources:
            for src in sources[:10]:
                lines.append(f"- {src}")
        else:
            lines.append("- (No external sources were available in this run.)")
        return "\n".join(lines).strip() + "\n"
        
    def learn_skill(self, topic: str) -> str:
        """
        Research a topic and save a skill file.
        Returns: Path to the new skill file.
        """
        topic = self._sanitize_topic(topic)
        if not topic:
            return "Tell me what capability to learn."

        # 1. Rate Limiting (1 research task per cooldown window)
        if self._rate_limited():
            return "Thinking too hard! Please wait a few minutes before asking me to research a new skill."
            
        # 2. CPU Guard (Don't research if system is busy, e.g. gaming)
        if self._cpu_too_high():
            return "System is under heavy load (Gaming?). I'll skip deep research for now to save FPS."
            
        self.last_research_time = time.time()

        logger.info("Active Learning: researching '%s'...", topic)

        # 1. Search web evidence
        summary = ""
        sources: List[str] = []
        try:
            summary, sources = self._research_topic(topic, max_results=5)
        except Exception as exc:
            logger.warning("Active learning web research failed for '%s': %s", topic, exc)

        # 2. Save to learning memory for future fine-tuning
        try:
            from chintu_backend.brain.learning.learning_engine import get_learning_engine

            get_learning_engine().record_web_learning(
                query=f"learn skill: {topic}",
                response=summary or f"Drafted skill from limited evidence for topic: {topic}.",
                sources=sources,
            )
        except Exception:
            pass

        # 3. Synthesize skill proposal content
        skill_content = self._build_skill_markdown(topic, summary=summary, sources=sources)

        # 3. Save as Proposal (requires approval)
        try:
            from chintu_backend.automation.skills.skill_proposals import create_proposal
            proposal = create_proposal(
                skill_content,
                source="active_learning",
                reason=f"Auto-learned from topic: {topic}",
            )
            logger.info(f"✅ Proposed new skill: {proposal.id}")
            return (
                f"I've drafted a new skill for '{topic}' and queued it for approval "
                f"(proposal: {proposal.id}). Say 'approve skill {proposal.id}' to enable it."
            )
        except Exception as e:
            logger.error(f"Failed to create skill proposal: {e}")
            return "I learned the skill but couldn't save it for approval."

# Global
_learner = None

def get_active_learner() -> ActiveLearner:
    global _learner
    if not _learner:
        _learner = ActiveLearner()
    return _learner
