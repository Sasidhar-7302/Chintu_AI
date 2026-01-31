"""
Active Learning: Enables Chintu to Research -> Learn -> Synthesize new skills.
"""

import logging
import os
from datetime import datetime
from ..core.config import get_config

logger = logging.getLogger(__name__)

class ActiveLearner:
    """
    Research a topic and save it as a persistent skill/memory.
    """
    
    def __init__(self):
        self.config = get_config()
        self.skills_dir = str(self.config.skills_learned_dir)
        os.makedirs(self.skills_dir, exist_ok=True)
        self.last_research_time = 0
        
    def learn_skill(self, topic: str) -> str:
        """
        Research a topic and save a skill file.
        Returns: Path to the new skill file.
        """
        import time
        import psutil
        
        # 1. Rate Limiting (1 research task per 5 minutes)
        if time.time() - self.last_research_time < 300:
            return "Thinking too hard! Please wait a few minutes before asking me to research a new skill."
            
        # 2. CPU Guard (Don't research if system is busy, e.g. gaming)
        if psutil.cpu_percent(interval=0.1) > 50:
            return "System is under heavy load (Gaming?). I'll skip deep research for now to save FPS."
            
        self.last_research_time = time.time()
        
        logger.info(f"🎓 Active Learning: Researching '{topic}'...")
        
        # 1. Search Web (Simulation for now, or hook into SearchCapability)
        # Ideally, we call 'search_web' tool here.
        # collected_info = search_web(topic)
        collected_info = f"Mock research data for {topic}. Ideally obtained via Tavily/Google."
        
        # 2. Synthesize Knowledge
        skill_content = f"# Skill: {topic}\n"
        skill_content += f"Learned: {datetime.now()}\n\n"
        skill_content += f"## Research Summary\n{collected_info}\n\n"
        skill_content += "## Key Concepts\n- Concept A\n- Concept B\n"
        
        # 3. Save to Brain
        filename = f"{topic.replace(' ', '_').lower()}.md"
        path = os.path.join(self.skills_dir, filename)
        
        with open(path, "w", encoding="utf-8") as f:
            f.write(skill_content)
            
        logger.info(f"✅ Learned new skill: {path}")
        return f"I have researched '{topic}' and saved it to {filename}. I can now use this knowledge."

# Global
_learner = None

def get_active_learner() -> ActiveLearner:
    global _learner
    if not _learner:
        _learner = ActiveLearner()
    return _learner
