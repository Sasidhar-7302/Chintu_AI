"""Agent factory with role templates and scoped policies."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from chintu_backend.core.config import get_config
from chintu_backend.agents.agent_directory import get_agent_directory, AgentRuntime
from chintu_backend.channels.policy import ChannelPolicyManager

logger = logging.getLogger(__name__)


@dataclass
class AgentTemplate:
    role: str
    description: str
    tool_allow: List[str]
    tool_deny: List[str]
    sandbox_network_mode: str = "none"


TEMPLATES: Dict[str, AgentTemplate] = {
    "founder": AgentTemplate(
        role="founder",
        description="Founder/CEO agent. Strategy, prioritization, approvals.",
        tool_allow=["group:runtime", "group:memory", "group:sessions", "group:canvas", "group:browser", "group:web"],
        tool_deny=["tools.exec.run"],
        sandbox_network_mode="none",
    ),
    "pm": AgentTemplate(
        role="pm",
        description="Product manager. Plans, specs, user stories.",
        tool_allow=["group:memory", "group:sessions", "group:canvas", "group:web", "group:browser"],
        tool_deny=["tools.exec.run"],
        sandbox_network_mode="none",
    ),
    "dev": AgentTemplate(
        role="dev",
        description="Developer agent. Code changes, tests, automation.",
        tool_allow=["group:runtime", "group:memory", "group:sessions", "group:browser"],
        tool_deny=[],
        sandbox_network_mode="none",
    ),
    "growth": AgentTemplate(
        role="growth",
        description="Growth/marketing agent. Research, copy, experiments.",
        tool_allow=["group:memory", "group:web", "group:browser", "group:canvas"],
        tool_deny=["tools.exec.run"],
        sandbox_network_mode="none",
    ),
    "ops": AgentTemplate(
        role="ops",
        description="Operations agent. Monitoring, deploys, integrations.",
        tool_allow=["group:runtime", "group:memory", "group:sessions"],
        tool_deny=[],
        sandbox_network_mode="none",
    ),
    "research": AgentTemplate(
        role="research",
        description="Deep research agent. Sources, summaries, analysis.",
        tool_allow=["group:web", "group:memory", "group:browser"],
        tool_deny=["tools.exec.run"],
        sandbox_network_mode="none",
    ),
}


def _load_policy_data(path: Path) -> Dict[str, object]:
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {"default": {}, "roles": {}}


def ensure_templates() -> None:
    """Ensure agent policy templates exist in the policy store."""
    config = get_config()
    policy_path = Path(config.agent_policies_path)
    data = _load_policy_data(policy_path)
    roles = data.get("roles") or {}
    updated = False
    for key, template in TEMPLATES.items():
        if key in roles:
            continue
        roles[key] = {
            "allow": list(template.tool_allow),
            "deny": list(template.tool_deny),
            "sandbox_network_mode": template.sandbox_network_mode,
            "description": template.description,
        }
        updated = True
    if updated:
        data["roles"] = roles
        policy_path.parent.mkdir(parents=True, exist_ok=True)
        policy_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        logger.info("Agent templates added to policy store.")


def create_agent(
    agent_key: str,
    role: str,
    *,
    channel: Optional[str] = None,
    user_id: Optional[str] = None,
    workspace_mode: Optional[str] = None,
    workspace_dir: Optional[Path] = None,
) -> AgentRuntime:
    """Create agent with template role and optional channel routing."""
    ensure_templates()
    directory = get_agent_directory()
    runtime = directory.get_or_create(
        agent_key=agent_key,
        role=role,
        workspace_mode=workspace_mode,
        workspace_dir=workspace_dir,
    )
    if channel and user_id:
        try:
            ChannelPolicyManager().set_agent_profile(channel, user_id, agent_key, role)
        except Exception:
            pass
    return runtime
