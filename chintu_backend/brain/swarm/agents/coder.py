"""
AutonCoder: The Autonomous Engineering Agent.
Implements Actor-Critic Loop for reliable code generation.
"""

import logging
import ast
import re
import json
from typing import Dict, Any, Optional
from chintu_backend.brain.swarm.base_agent import BaseAgent, AgentState
from chintu_backend.core.config import get_config
from chintu_backend.brain.llm.ollama_client import OllamaClient
from chintu_backend.brain.llm.groq_client import GroqClient

logger = logging.getLogger(__name__)

class AutonCoder(BaseAgent):
    def __init__(self):
        super().__init__(name="AutonCoder", description="writes file-based code, refactors, and fixes bugs")
        self.config = get_config()
        self._init_llm()
        
    def _init_llm(self):
        # Prefer High-Intelligence Model for Coding (Gemini or Qwen-Coder via Ollama)
        self.llm = None
        # Try local Coder first if available
        try:
             # Fallback to 1.5b if 7b is missing to ensure it runs out of box
             self.llm = OllamaClient(host=self.config.ollama_host, model="qwen2.5:1.5b") 
        except: pass
        
        if not self.llm and self.config.groq_api_key:
             try:
                 self.llm = GroqClient(model=self.config.groq_model, api_key=self.config.groq_api_key)
             except: pass

    def run(self, goal: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Execute coding task with reflection.
        1. Think: Generate Code.
        2. Act: Prepare file write.
        3. Reflect: Static Analysis (Syntax Check).
        4. Commit: Save file.
        """
        self.update_state(AgentState.PLANNING)
        self.log_step("Analyzing", goal)
        
        # 1. Generate Logic
        code_data = self._generate_code(goal)
        if not code_data:
            return {"success": False, "error": "Code generation failed"}
            
        filename = code_data.get("filename", "generated_script.py")
        content = code_data.get("content", "")
        
        # 2. Reflect (Syntax Check)
        self.update_state(AgentState.EXECUTING)
        is_valid, error = self._syntax_check(content)
        
        if not is_valid:
             self.log_step("Syntax Error Detected", error)
             # Self-Correction attempt
             content = self._fix_code(content, error)
             is_valid, error = self._syntax_check(content)
             if not is_valid:
                 return {"success": False, "error": f"Failed to fix syntax: {error}"}
        
        # 3. Commit
        try:
            # In a real tool-use scenario, we would call 'write_to_file' tool.
            # Here we simulate or write directly if allowed (we are backend).
            # Use per-agent workspace if available, else fallback to swarm_output.
            base_dir = self.workspace_dir or (self.config.data_dir / "swarm_output")
            output_path = base_dir / filename
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(content, encoding="utf-8")
            
            self.log_step("Success", f"Wrote to {output_path}")
            return {"success": True, "path": str(output_path), "code": content[:100] + "..."}
            
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _generate_code(self, goal: str) -> Dict[str, str]:
        prompt = (
            f"You are an Expert Python Engineer. Goal: \"{goal}\"\n"
            "Return JSON with 'filename' and 'content'.\n"
            "Example: { \"filename\": \"hello.py\", \"content\": \"print('Hello')\" }"
        )
        try:
            response = self.llm.chat(prompt) if hasattr(self.llm, 'chat') else self.llm.generate(prompt)
            # Json extraction
            clean = response
            if "```json" in clean: clean = clean.split("```json")[1].split("```")[0]
            elif "```" in clean: clean = clean.split("```")[1].split("```")[0]
            
            return json.loads(clean.strip())
        except Exception as e:
            logger.error(f"Gen failed: {e}")
            return {}

    def _fix_code(self, code: str, error: str) -> str:
        prompt = (
            f"Fix this python code which has a Syntax Error.\nError: {error}\nCode:\n{code}\n"
            "Return ONLY the fixed code."
        )
        try:
            res = self.llm.chat(prompt) if hasattr(self.llm, 'chat') else self.llm.generate(prompt)
            if "```python" in res: res = res.split("```python")[1].split("```")[0]
            return res.strip()
        except:
             return code

    def _syntax_check(self, code: str) -> tuple[bool, str]:
        try:
            ast.parse(code)
            return True, ""
        except SyntaxError as e:
            return False, str(e)

    def stop(self):
        self.update_state(AgentState.IDLE)
