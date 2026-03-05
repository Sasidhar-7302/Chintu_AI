"""Basic swarm engine with router and worker roles."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional, List
from concurrent.futures import ThreadPoolExecutor, as_completed

from chintu_backend.core.config import get_config

from .model_manager import ModelManager
from .arbitration import select_agents, AgentSpec
from .agent_runtime import create_agent_runtime, AgentSessionStore
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
        runtime = create_agent_runtime("planner")
        return self._chat(self.config.swarm_planner_model, prompt, context, system, decision, "planner", runtime=runtime)

    def _run_coder(self, prompt: str, context: str, decision: RouterDecision) -> SwarmResult:
        system = "You are the Coder. Produce correct, tested code with brief explanations."
        runtime = create_agent_runtime("coder")
        return self._chat(self.config.swarm_coder_model, prompt, context, system, decision, "coder", runtime=runtime)

    def _run_researcher(self, prompt: str, context: str, decision: RouterDecision) -> SwarmResult:
        system = "You are the Researcher. Summarize findings with sources and caveats."
        runtime = create_agent_runtime("researcher")
        return self._chat(self.config.swarm_researcher_model, prompt, context, system, decision, "researcher", runtime=runtime)

    def _run_complex(self, prompt: str, context: str, decision: RouterDecision) -> SwarmResult:
        if (
            self.config.browser_fallback_enabled
            and decision.complexity_score >= self.config.browser_fallback_threshold
            and not os.environ.get("PYTEST_CURRENT_TEST")
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
        plan = select_agents(prompt, decision)
        agent_runs: List[AgentSpec] = plan.agents

        if getattr(self.config, "swarm_trace_enabled", True):
            try:
                from chintu_backend.brain.orchestration.trace import log_event
                log_event(
                    {
                        "event": "swarm_arbitration",
                        "intent": decision.intent.value,
                        "complexity": decision.complexity_score,
                        "agents": [a.role for a in agent_runs],
                        "reason": plan.reason,
                    }
                )
            except Exception:
                pass

        outputs = []
        runtimes = {spec.role: create_agent_runtime(spec.role) for spec in agent_runs}
        if getattr(self.config, "swarm_parallel_enabled", True):
            worker_count = max(1, min(3, len(agent_runs)))
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = {
                    executor.submit(
                        self._chat,
                        spec.model,
                        prompt,
                        context,
                        spec.system_prompt,
                        decision,
                        spec.role,
                        spec.timeout_seconds,
                        runtimes.get(spec.role),
                    ): spec.role
                    for spec in agent_runs
                }
                total_timeout = float(getattr(self.config, "swarm_total_timeout_seconds", 120.0))
                try:
                    iterator = as_completed(futures, timeout=total_timeout)
                except TypeError:
                    iterator = as_completed(futures)
                try:
                    for fut in iterator:
                        try:
                            outputs.append(fut.result())
                        except Exception as exc:
                            logger.warning("Swarm sub-agent failed: %s", exc)
                except TimeoutError:
                    logger.warning("Swarm parallel run timed out")
        else:
            for spec in agent_runs:
                try:
                    outputs.append(
                        self._chat(
                            spec.model,
                            prompt,
                            context,
                            spec.system_prompt,
                            decision,
                            spec.role,
                            spec.timeout_seconds,
                            runtimes.get(spec.role),
                        )
                    )
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
            float(getattr(self.config, "swarm_agent_timeout_seconds", 45.0)),
            create_agent_runtime("orchestrator"),
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
        runtime = create_agent_runtime("router")
        return self._chat(self.config.swarm_router_model, prompt, context, system, decision, "router", runtime=runtime)

    def _chat(
        self,
        model: str,
        prompt: str,
        context: str,
        system_prompt: str,
        decision: RouterDecision,
        source: str,
        timeout: Optional[float] = None,
        runtime: Optional[object] = None,
    ) -> SwarmResult:
        messages = [{"role": "system", "content": system_prompt}]
        if context:
            messages.append({"role": "system", "content": f"Context:\n{context}"})
        messages.append({"role": "user", "content": prompt})
        if runtime is not None:
            try:
                AgentSessionStore(runtime.session_dir).append_event(
                    {
                        "event": "agent_request",
                        "agent_id": getattr(runtime, "agent_id", ""),
                        "role": source,
                        "model": model,
                        "prompt_chars": len(prompt or ""),
                        "context_chars": len(context or ""),
                    }
                )
            except Exception:
                pass
        try:
            content, _raw = self.model_manager.chat(model=model, messages=messages, timeout=timeout)
        except TypeError:
            content, _raw = self.model_manager.chat(model=model, messages=messages)
        if runtime is not None:
            try:
                AgentSessionStore(runtime.session_dir).append_event(
                    {
                        "event": "agent_response",
                        "agent_id": getattr(runtime, "agent_id", ""),
                        "role": source,
                        "model": model,
                        "response_chars": len(content or ""),
                    }
                )
            except Exception:
                pass
        if getattr(self.config, "swarm_trace_enabled", True):
            try:
                from chintu_backend.brain.orchestration.trace import log_event
                log_event(
                    {
                        "event": "swarm_agent_complete",
                        "agent": source,
                        "chars": len(content or ""),
                        "model": model,
                        "agent_id": getattr(runtime, "agent_id", ""),
                        "workspace_dir": str(getattr(runtime, "workspace_dir", "")),
                    }
                )
            except Exception:
                pass
        return SwarmResult(content=content, source=source, decision=decision)
