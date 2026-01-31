"""
Fast LLM Router.
Replaces the rigid Regex-based IntentDetector.
Uses a fast, lightweight LLM call (Groq/Ollama) to classify user intent dynamically.
"""

import json
import logging
import re
from typing import Dict, Any, Optional
from chintu_backend.core.model_router import Intent, RoutingDecision, TaskComplexity

logger = logging.getLogger(__name__)

class FastLLMRouter:
    def __init__(self, llm_client):
        self.llm = llm_client

    def route(self, text: str) -> RoutingDecision:
        """
        Decide intent using LLM.
        """
        prompt = f"""You are the brain of an AI assistant. Classify the user's request.
RETURN ONLY JSON. No markdown.

Valid Intents:
- OPEN_APP (e.g. "Open Chrome", "Start Spotify")
- SEARCH_WEB (e.g. "Search for cats", "Google python")
- SYSTEM_CONTROL (e.g. "Mute volumen", "Shutdown")
- GENERAL_CHAT (e.g. "Hi", "How are you", "Tell me a joke")
- COMPLEX_TASK (e.g. "Write a blog post", "Analyze this file")
- CODING (e.g. "Write python code")

User Request: "{text}"

JSON Format:
{{
    "intent": "IntentName",
    "complexity": "simple|complex",
    "params": {{ ...extracted entities... }}
}}
"""
        try:
            # We assume self.llm.generate or similar exists, adapting to OllamaClient
            response_text = self.llm.generate(prompt, system_prompt="You are a JSON classifier.")
            
            # Clean response
            json_str = self._extract_json(response_text)
            data = json.loads(json_str)
            
            intent_str = data.get("intent", "GENERAL_CHAT").upper()
            complexity_str = data.get("complexity", "simple").lower()
            params = data.get("params", {})

            # Map to Chintu Enums
            intent = self._map_intent(intent_str)
            complexity = TaskComplexity.COMPLEX if complexity_str == "complex" else TaskComplexity.SIMPLE
            
            # Logic: If Intent is CHAT, use LLM. If Intent is APP/SYSTEM, we might try to execute directly
            use_llm = (intent in [Intent.SIMPLE_CHAT, Intent.CODING, Intent.RESEARCH, Intent.REASONING])
            
            return RoutingDecision(
                intent=intent,
                complexity=complexity,
                use_llm=use_llm,
                prefer_cloud=(complexity == TaskComplexity.COMPLEX),
                extracted_params=params
            )

        except Exception as e:
            logger.error(f"Router LLM failed: {e}. Fallback to Chat.")
            return RoutingDecision(Intent.SIMPLE_CHAT, TaskComplexity.SIMPLE, True, False, {})

    def _extract_json(self, text: str) -> str:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return match.group(0)
        return text

    def _map_intent(self, intent_str: str) -> Intent:
        mapping = {
            "OPEN_APP": Intent.OPEN_APP,
            "SEARCH_WEB": Intent.SEARCH_WEB,
            "SYSTEM_CONTROL": Intent.SCREEN_CONTROL, # Mapping system to screen control for now or closer equivalent
            "GENERAL_CHAT": Intent.SIMPLE_CHAT,
            "CODING": Intent.CODING,
            "COMPLEX_TASK": Intent.REASONING
        }
        return mapping.get(intent_str, Intent.SIMPLE_CHAT)
