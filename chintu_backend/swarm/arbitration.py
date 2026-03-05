"""Agent arbitration for swarm multi-agent runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from chintu_backend.core.config import get_config
from .router import RouterDecision, RouterIntent


@dataclass
class AgentSpec:
    role: str
    model: str
    system_prompt: str
    timeout_seconds: float


@dataclass
class SwarmPlan:
    agents: List[AgentSpec]
    reason: str


def select_agents(prompt: str, decision: RouterDecision) -> SwarmPlan:
    config = get_config()
    text = (prompt or "").lower()

    code_keywords = ["code", "debug", "fix", "implement", "function", "class", "error", "stack trace"]
    research_keywords = ["research", "compare", "analyze", "summarize", "sources", "citations", "explain"]
    plan_keywords = ["plan", "roadmap", "phases", "steps", "milestone", "workflow"]

    want_planner = decision.intent in {RouterIntent.PLAN, RouterIntent.COMPLEX} or any(k in text for k in plan_keywords)
    want_coder = decision.intent in {RouterIntent.CODE, RouterIntent.COMPLEX} or any(k in text for k in code_keywords)
    want_researcher = decision.intent in {RouterIntent.RESEARCH, RouterIntent.COMPLEX} or any(k in text for k in research_keywords)

    if decision.intent == RouterIntent.CHAT and not (want_planner or want_coder or want_researcher):
        want_planner = True

    agents: List[AgentSpec] = []
    timeout = float(getattr(config, "swarm_agent_timeout_seconds", 45.0))
    if want_planner:
        agents.append(
            AgentSpec(
                role="planner",
                model=config.swarm_planner_model,
                system_prompt="You are the Planner. Produce a structured plan with clear steps.",
                timeout_seconds=timeout,
            )
        )
    if want_researcher:
        agents.append(
            AgentSpec(
                role="researcher",
                model=config.swarm_researcher_model,
                system_prompt="You are the Researcher. Summarize findings with sources and caveats.",
                timeout_seconds=timeout,
            )
        )
    if want_coder:
        agents.append(
            AgentSpec(
                role="coder",
                model=config.swarm_coder_model,
                system_prompt="You are the Coder. Produce correct, tested code with brief explanations.",
                timeout_seconds=timeout,
            )
        )

    max_agents = int(getattr(config, "swarm_max_agents", 3))
    if max_agents > 0:
        agents = agents[:max_agents]

    if not agents:
        agents.append(
            AgentSpec(
                role="planner",
                model=config.swarm_planner_model,
                system_prompt="You are the Planner. Produce a structured plan with clear steps.",
                timeout_seconds=timeout,
            )
        )

    reason = f"intent={decision.intent.value}, selected={[a.role for a in agents]}"
    return SwarmPlan(agents=agents, reason=reason)

