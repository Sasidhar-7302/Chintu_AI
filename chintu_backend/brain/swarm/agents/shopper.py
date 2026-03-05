
"""
Shopping Agent: Autonomous Product Scout.
Uses Browser Controller to find, compare, and recommend products.
"""

import logging
import json
from typing import Dict, Any, Optional, List
from chintu_backend.brain.swarm.base_agent import BaseAgent, AgentState
from chintu_backend.core.config import get_config
from chintu_backend.brain.llm.ollama_client import OllamaClient
from chintu_backend.brain.llm.groq_client import GroqClient
from chintu_backend.brain.swarm.browser_controller import BrowserController

logger = logging.getLogger(__name__)

class ShoppingAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="ShoppingAgent", description="searches for products, compares prices, finds deals")
        self.config = get_config()
        self.browser = BrowserController()
        self._init_llm()
        
    def _init_llm(self):
        # Reasoning LLM for comparison
        self.llm = None
        if self.config.groq_api_key:
             try: self.llm = GroqClient(model=self.config.groq_model, api_key=self.config.groq_api_key)
             except: pass
        if not self.llm:
             try: self.llm = OllamaClient(host=self.config.ollama_host, model="llama3.1:8b") 
             except: pass

    def run(self, goal: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Execute Shopping Task.
        1. Plan: Extract search keywords.
        2. Search: Get product list.
        3. Evaluate: Compare items.
        4. Result: Return best option.
        """
        self.update_state(AgentState.PLANNING)
        self.log_step("Planning", goal)
        
        # 1. Keywords
        search_query = self._extract_query(goal)
        self.log_step("Searching", search_query)
        
        # 2. Search
        self.update_state(AgentState.EXECUTING)
        products = self.browser.search(search_query) # List of dicts
        
        if not products:
             return {"success": False, "error": "No products found."}
             
        # 3. Analyze & Filter (Top 3)
        top_picks = products[:3]
        
        # 4. Deep Dive (Simulated Navigation)
        comparison_data = []
        for p in top_picks:
            link = p.get('link')
            if link:
                self.log_step("Visiting", link)
                content = self.browser.navigate(link)
                price = self.browser.extract_price(content) or p.get('price', 'N/A')
                comparison_data.append({
                    "title": p.get('title'),
                    "price": price,
                    "link": link,
                    "summary": content[:200]
                })

        # 5. Recommendation
        recommendation = self._recommend(goal, comparison_data)
        
        return {
            "success": True, 
            "picked": recommendation, 
            "comparison": comparison_data
        }

    def _extract_query(self, goal: str) -> str:
        # Simple extraction or LLM
        if "buy" in goal or "find" in goal:
             return goal.replace("buy", "").replace("find", "").strip()
        return goal

    def _recommend(self, goal: str, items: List[Dict]) -> str:
        prompt = (
            f"Goal: {goal}\n"
            f"Items: {json.dumps(items)}\n"
            "Recommend the best item. Return a short reasoning."
        )
        try:
             return self.llm.chat(prompt) if hasattr(self.llm, 'chat') else self.llm.generate(prompt)
        except:
             return "Check the comparison table."

    def stop(self):
        self.update_state(AgentState.IDLE)
