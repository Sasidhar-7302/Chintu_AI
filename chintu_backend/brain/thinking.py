"""
Thinking manager for deliberate multi-step reasoning.

This module provides a bounded "think -> verify -> refine" loop that can be
used when a task needs deeper reasoning than the default fast path.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

try:
    from ..core.config import get_config
except ImportError:
    from chintu_backend.core.config import get_config

logger = logging.getLogger(__name__)


class ThinkingManager:
    """Runs a bounded deep-thinking loop with optional sandbox verification."""

    def __init__(self, llm_client):
        self.llm = llm_client
        self.config = get_config()
        self.sandbox = None
        try:
            from ..coding.sandbox import get_sandbox_manager

            self.sandbox = get_sandbox_manager()
        except ImportError:
            logger.warning("Sandbox not available for ThinkingManager")

    def think(self, user_query: str, system_context: str = "") -> str:
        """Execute the deep-thinking loop and return the final user response."""
        logger.info("System-2 thinking activated for query: %s", user_query[:80])

        prompt = self._build_thinking_prompt(user_query=user_query, system_context=system_context)
        response = ""
        max_iterations = 3

        for iteration in range(max_iterations):
            raw = self.llm.generate_content(prompt)
            response = str(raw or "").strip()
            if not response:
                logger.warning("Thinking mode received empty response (iteration=%d)", iteration + 1)
                break

            verified_text, needs_fix, verification_log = self._process_verification(response)
            if not needs_fix:
                return self._parse_thought_output(verified_text)

            logger.info("Verification failed during deep-thinking (attempt=%d)", iteration + 1)
            prompt += (
                "\n\nSYSTEM: Verification Output:\n"
                f"{verification_log}\n\n"
                "Please fix the code based on the error and provide the final answer."
            )

        if response:
            return self._parse_thought_output(response)
        return "I could not complete deep reasoning right now. I will continue with standard routing."

    @staticmethod
    def _build_thinking_prompt(*, user_query: str, system_context: str) -> str:
        return f"""
You are an AI assistant in Deep Thinking Mode.

Goal: solve the user's request with explicit reasoning and a high-quality final answer.

SYSTEM CONTEXT:
{system_context}

USER REQUEST:
{user_query}

INSTRUCTIONS:
1. Analyze the request inside <thought> tags (step-by-step reasoning, edge cases).
2. If code needs validation, include checks inside <verify language="python"> ... </verify>.
3. Provide the final polished response inside <answer> tags.

Format:
<thought>
[internal reasoning]

<verify language="python">
print("verification")
</verify>
</thought>

<answer>
[final response shown to user]
</answer>
""".strip()

    def _parse_thought_output(self, raw_text: str) -> str:
        """Extract <answer> content; fallback to cleaned raw text."""
        raw_text = str(raw_text or "")

        answer_match = re.search(r"<answer>(.*?)</answer>", raw_text, re.DOTALL | re.IGNORECASE)
        thought_match = re.search(r"<thought>(.*?)</thought>", raw_text, re.DOTALL | re.IGNORECASE)

        if answer_match:
            final_answer = answer_match.group(1).strip()
            if thought_match:
                logger.debug("Thinking trace: %s", thought_match.group(1).strip())
            return final_answer

        logger.warning("Thinking mode output tags missing/malformed; returning cleaned raw output.")
        return (
            raw_text.replace("<thought>", "")
            .replace("</thought>", "")
            .replace("<answer>", "")
            .replace("</answer>", "")
            .strip()
        )

    def _process_verification(self, text: str) -> tuple[str, bool, str]:
        """
        Run inline python verification blocks.

        Returns:
            (original_text, needs_fix, verification_log)
        """
        text = str(text or "")
        if not self.sandbox:
            return text, False, ""

        pattern = r'<verify language="python">(.*?)</verify>'
        matches = re.finditer(pattern, text, re.DOTALL | re.IGNORECASE)

        needs_fix = False
        logs = []
        for match in matches:
            code = match.group(1).strip()
            stdout, stderr, exit_code = self.sandbox.run_python(code)
            logs.append(
                "Code Execution Result:\n"
                f"Stdout: {stdout}\n"
                f"Stderr: {stderr}\n"
                f"Exit Code: {exit_code}"
            )
            logger.info("Thinking sandbox execution completed (exit_code=%s)", exit_code)
            if exit_code != 0:
                needs_fix = True

        return text, needs_fix, "\n".join(logs)


_thinker: Optional[ThinkingManager] = None


def get_thinking_manager(llm_client) -> ThinkingManager:
    global _thinker
    if _thinker is None:
        _thinker = ThinkingManager(llm_client)
    return _thinker

