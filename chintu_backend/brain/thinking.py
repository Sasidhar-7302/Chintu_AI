"""
ThinkingManager: Implements System 2 "Thinking Mode" for complex tasks.
Inspired by Chain-of-Thought and Agentic Reasoning patterns.
"""

import logging
from typing import Dict, Any, Optional, List
try:
    from ..core.config import get_config
except ImportError:
    from chintu_backend.core.config import get_config

logger = logging.getLogger(__name__)

class ThinkingManager:
    """
    Manages the 'Deep Thinking' process for complex queries.
    Uses an internal LLM loop to plan, critique, and refine answers.
    """
    
    def __init__(self, llm_client):
        self.llm = llm_client
        self.config = get_config()
        
        # Connect to Sandbox
        try:
            from ..coding.sandbox import get_sandbox_manager
            self.sandbox = get_sandbox_manager()
        except ImportError:
            self.sandbox = None
            logger.warning("Sandbox not available for Thinking Manager")
        
    def think(self, user_query: str, system_context: str = "") -> str:
        """
        Execute the System 2 Thinking Loop.
        
        Steps:
        1. Contextualize: Understand the core request.
        2. Plan: Breakdown the steps.
        3. Reason: Talk through the logic (CoT).
        4. Synthesize: Create the final answer.
        """
        logger.info(f"🤔 System 2 Activated for: {user_query[:50]}...")
        
        # 1. The Thinking Prompt
        # We force the LLM to output its internal monologue inside <thought> tags
        # and the final answer inside <answer> tags.
        thinking_prompt = f"""
        You are an Advanced AI Agent in 'Deep Thinking Mode'.
        
        Your Goal: Solve the user's complex request by thinking step-by-step.
        
        SYSTEM CONTEXT:
        {system_context}
        
        USER REQUEST:
        {user_query}
        
        INSTRUCTIONS:
        1. First, analyze the request inside <thought> tags. Break it down. Anticipate edge cases. Check your knowledge.
        2. If you need to plan code, write the plan inside <thought>.
        3. Finally, provide the refined, high-quality response inside <answer> tags. Only the <answer> part will be shown to the user immediately, but your thoughts help you get there.
        
        Format:
        <thought>
        [Your internal reasoning]
        
        To verify code, use:
        <verify language="python">
        print("Hello from Sandbox")
        </verify>
        </thought>
        
        <answer>
        [Your final response]
        </answer>
        """
        
        # 2. Execute Prediction loop (Thinking -> Verifying -> Thinking)
        MAX_ITERATIONS = 3
        current_prompt = thinking_prompt
        
        for i in range(MAX_ITERATIONS):
            response = self.llm.generate_content(current_prompt)
            
            # Check for verification requests
            verified_response, needs_fix, verification_log = self._process_verification(response)
            
            if not needs_fix:
                return self._parse_thought_output(verified_response)
                
            # If verification failed, feed it back to the model
            logger.info(f"🔧 Verification failed (Attempt {i+1}). Retrying...")
            current_prompt += f"\n\nSYSTEM: Verification Output:\n{verification_log}\n\nPlease fix the code based on the error and provide the final answer."
            
        # If we ran out of iterations, just return what we have (best effort)
        return self._parse_thought_output(response)

    def _parse_thought_output(self, raw_text: str) -> str:
        """Extract valid answer from the raw XML-like output."""
        import re
        
        # Try to extract <answer> content
        answer_match = re.search(r"<answer>(.*?)</answer>", raw_text, re.DOTALL | re.IGNORECASE)
        thought_match = re.search(r"<thought>(.*?)</thought>", raw_text, re.DOTALL | re.IGNORECASE)
        
        if answer_match:
            final_answer = answer_match.group(1).strip()
            
            # Optionally log thoughts for transparency/debugging
            if thought_match:
                thoughts = thought_match.group(1).strip()
                logger.debug(f"💭 Thoughts:\n{thoughts}")
                
            return final_answer
        
        # Fallback: If model didn't use tags properly, return whole text
        # (This happens with smaller models sometimes)
        logger.warning("Thinking Mode: XML tags not found/malformed. Returning raw output.")
        return raw_text.replace("<thought>", "").replace("</thought>", "").replace("<answer>", "").replace("</answer>", "").strip()

    def _process_verification(self, text: str) -> tuple[str, bool, str]:
        """
        Scan text for <verify> tags, execute code, and return (text, needs_fix, log).
        """
        import re
        
        if not self.sandbox:
            return text, False, ""
            
        # Simple regex for python verification
        # <verify language="python">...</verify>
        pattern = r'<verify language="python">(.*?)</verify>'
        matches = re.finditer(pattern, text, re.DOTALL | re.IGNORECASE)
        
        needs_fix = False
        logs = []
        
        for match in matches:
            code = match.group(1).strip()
            stdout, stderr, exit_code = self.sandbox.run_python(code)
            
            log = f"Code Execution Result:\nStdout: {stdout}\nStderr: {stderr}\nExit Code: {exit_code}"
            logs.append(log)
            logger.info(f"Sandbox Exec: Exit {exit_code}")
            
            if exit_code != 0:
                needs_fix = True
                
        return text, needs_fix, "\n".join(logs)

# Factory
_thinker = None

def get_thinking_manager(llm_client) -> ThinkingManager:
    global _thinker
    if not _thinker:
        _thinker = ThinkingManager(llm_client)
    return _thinker
