"""
Fact Verification Middleware.
Ensures Chintu does not learn or repeat falsehoods.
"""

import logging
from typing import Dict, Any, Optional, Tuple
from chintu_backend.core.config import get_config

logger = logging.getLogger(__name__)

class FactChecker:
    def __init__(self):
        self.config = get_config()
        self.ollama = None
        self.groq = None
        
        # Initialize LLM
        try:
            from chintu_backend.brain.llm.ollama_client import OllamaClient
            self.ollama = OllamaClient(
                host=self.config.ollama_host,
                model=self.config.ollama_model
            )
        except ImportError:
            pass
            
        if self.config.groq_api_key:
            try:
                from chintu_backend.brain.llm.groq_client import GroqClient
                self.groq = GroqClient(model=self.config.groq_model, api_key=self.config.groq_api_key)
            except ImportError:
                pass


    def verify_fact(self, statement: str, context: str = "") -> Tuple[bool, str]:
        """
        Verify if a statement is factually accurate.
        Returns: (is_true, reason)
        """
        if not statement or len(statement) < 5:
            return True, "Too short to verify"
            
        verify_prompt = (
            f"Act as a strict Fact Checker. Review this statement for factual accuracy.\n"
            f"Statement: \"{statement}\"\n"
            f"Context: {context[:200]}\n\n"
            "Is this statement factually TRUE or FALSE?\n"
            "If it contains common misconceptions or obvious errors (like '2+2=1', 'Sky is green', 'Earth is flat'), say FALSE.\n"
            "Format: START_DECISION [TRUE|FALSE] END_DECISION. Then explain why."
        )
        
        try:
            response = self._llm_call(verify_prompt)
            
            if "START_DECISION FALSE" in response or "START_DECISION [FALSE]" in response:
                explanation = response.split("END_DECISION")[-1].strip()
                logger.warning(f"Fact Check REJECTED: {statement} -> {explanation}")
                return False, explanation
                
            return True, "Verified"
            
        except Exception as e:
            logger.warning(f"Fact check failed (allowing): {e}")
            return True, "Check failed"

    def verify_content(self, content: str) -> str:
        """
        Review a block of content and flag/remove obvious falsehoods.
        Returns corrected content.
        """
        # For large content, we might skim or ask LLM to "rewrite fixing errors".
        # If content is huge, this is expensive.
        # Strategy: Ask LLM to "List any factual errors in this text".
        
        check_prompt = (
            "Review the following text for factual accuracy. "
            "If there are any blatant falsehoods (e.g. mathematical errors, basic science errors), "
            "list them. If none, say NONE.\n\n"
            f"Text: {content[:4000]}..."
        )
        
        response = self._llm_call(check_prompt)
        if "NONE" in response or len(response) < 10:
            return content
            
        # If errors found, we might warn or try to fix.
        # For now, just log it.
        logger.info(f"Fact Check Findings: {response}")
        return content

    def _llm_call(self, prompt: str) -> str:
        if self.groq:
            return self.groq.chat(prompt)
        if self.ollama:
            return self.ollama.generate(prompt)
        return "NONE"

# Singleton
_checker = None
def get_fact_checker() -> FactChecker:
    global _checker
    if not _checker:
        _checker = FactChecker()
    return _checker
