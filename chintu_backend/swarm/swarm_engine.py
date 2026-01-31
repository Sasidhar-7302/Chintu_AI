"""Basic swarm engine with router and worker roles."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, List
from concurrent.futures import ThreadPoolExecutor, as_completed

from chintu_backend.core.config import get_config

from .model_manager import ModelManager
from .router import RouterAgent, RouterDecision, RouterIntent

logger = logging.getLogger(__name__)


@dataclass
class SwarmResult:
    content: str
    source: str
    decision: RouterDecision


class SwarmEngine:
    """Route user prompts to specialized models with simple role prompts."""

    def __init__(
        self,
        model_manager: Optional[ModelManager] = None,
        router: Optional[RouterAgent] = None,
        browser_agent=None,
    ):
        config = get_config()
        self.model_manager = model_manager or ModelManager(base_url=config.ollama_host)
        self.router = router or RouterAgent(self.model_manager, config.swarm_router_model)
        self.browser_agent = browser_agent
        self.config = config

    def run(self, prompt: str, context: str = "") -> SwarmResult:
        decision = self.router.route(prompt)
        if decision.intent == RouterIntent.PLAN:
            return self._run_planner(prompt, context, decision)
        if decision.intent == RouterIntent.CODE:
            return self._run_coder(prompt, context, decision)
        if decision.intent == RouterIntent.RESEARCH:
            return self._run_researcher(prompt, context, decision)
        if decision.intent == RouterIntent.COMPLEX:
            return self._run_complex(prompt, context, decision)
        return self._run_chat(prompt, context, decision)

    def _run_planner(self, prompt: str, context: str, decision: RouterDecision) -> SwarmResult:
        system = "You are the Planner. Produce a structured plan with clear steps."
        return self._chat(self.config.swarm_planner_model, prompt, context, system, decision, "planner")

    def _run_coder(self, prompt: str, context: str, decision: RouterDecision) -> SwarmResult:
        system = "You are the Coder. Produce correct, tested code with brief explanations."
        return self._chat(self.config.swarm_coder_model, prompt, context, system, decision, "coder")

    def _run_researcher(self, prompt: str, context: str, decision: RouterDecision) -> SwarmResult:
        system = "You are the Researcher. Summarize findings with sources and caveats."
        return self._chat(self.config.swarm_researcher_model, prompt, context, system, decision, "researcher")

    def _run_complex(self, prompt: str, context: str, decision: RouterDecision) -> SwarmResult:
        if (
            self.config.browser_fallback_enabled
            and decision.complexity_score >= self.config.browser_fallback_threshold
        ):
            agent = self.browser_agent or self._default_browser_agent()
            if agent and agent.is_available:
                response = agent.ask(prompt)
                return SwarmResult(
                    content=response.response_text,
                    source="browser",
                    decision=decision,
                )

        # Multi-agent orchestrated run for complex tasks
        agent_runs = [
            ("planner", self.config.swarm_planner_model, "You are the Planner. Produce a structured plan with clear steps."),
            ("researcher", self.config.swarm_researcher_model, "You are the Researcher. Summarize findings with sources and caveats."),
            ("coder", self.config.swarm_coder_model, "You are the Coder. Produce correct, tested code with brief explanations."),
        ]

        outputs = []
        if getattr(self.config, "swarm_parallel_enabled", True):
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = {
                    executor.submit(self._chat, model, prompt, context, system, decision, role): role
                    for role, model, system in agent_runs
                }
                for fut in as_completed(futures):
                    try:
                        outputs.append(fut.result())
                    except Exception as exc:
                        logger.warning("Swarm sub-agent failed: %s", exc)
        else:
            for role, model, system in agent_runs:
                try:
                    outputs.append(self._chat(model, prompt, context, system, decision, role))
                except Exception as exc:
                    logger.warning("Swarm sub-agent failed: %s", exc)

        if outputs:
            return self._synthesize(prompt, context, decision, outputs)

        system = (
            "You are the Planner. If the task needs higher intelligence, "
            "state that browser fallback is required and explain what to fetch."
        )
        return self._chat(self.config.swarm_planner_model, prompt, context, system, decision, "planner")

    def _synthesize(
        self,
        prompt: str,
        context: str,
        decision: RouterDecision,
        outputs: List[SwarmResult],
    ) -> SwarmResult:
        system = (
            "You are the Orchestrator. Combine Planner, Researcher, and Coder outputs "
            "into a single, coherent response. Resolve conflicts and keep it concise."
        )
        summary_blocks = []
        for output in outputs:
            summary_blocks.append(f"[{output.source.upper()}]\n{output.content}")
        synthesis_prompt = f"{prompt}\n\nAgent Outputs:\n\n" + "\n\n".join(summary_blocks)
        result = self._chat(
            self.config.swarm_orchestrator_model,
            synthesis_prompt,
            context,
            system,
            decision,
            "orchestrator",
        )
        return result

    def _default_browser_agent(self):
        try:
            from chintu_backend.automation.browser import BrowserFallbackAgent

            return BrowserFallbackAgent()
        except Exception as exc:
            logger.warning("Browser fallback unavailable: %s", exc)
            return None

    def _run_chat(self, prompt: str, context: str, decision: RouterDecision) -> SwarmResult:
        system = "You are a helpful assistant. Keep responses concise."
        return self._chat(self.config.swarm_router_model, prompt, context, system, decision, "router")

    def _chat(
        self,
        model: str,
        prompt: str,
        context: str,
        system_prompt: str,
        decision: RouterDecision,
        source: str,
    ) -> SwarmResult:
        messages = [{"role": "system", "content": system_prompt}]
        if context:
            messages.append({"role": "system", "content": f"Context:\n{context}"})
        messages.append({"role": "user", "content": prompt})
        content, _raw = self.model_manager.chat(model=model, messages=messages)
        return SwarmResult(content=content, source=source, decision=decision)
