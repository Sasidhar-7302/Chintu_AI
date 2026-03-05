"""Agent runtime isolation: workspace, session, and policy context."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional
import uuid

from chintu_backend.core.config import get_config
from .agent_policy import AgentPolicyStore, AgentToolPolicy, AgentSandboxConfig


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class AgentRuntime:
    agent_id: str
    role: str
    workspace_dir: Path
    state_dir: Path
    session_dir: Path
    logs_dir: Path
    memory_dir: Path
    skills_dir: Path
    policy: AgentToolPolicy
    sandbox: AgentSandboxConfig
    created_at: str

    def ensure_dirs(self) -> None:
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    def as_context(self) -> Dict[str, object]:
        return {
            "_agent_id": self.agent_id,
            "_agent_role": self.role,
            "_agent_runtime": self,
            "_agent_policy": self.policy,
            "_agent_sandbox": self.sandbox,
            "_agent_workspace": str(self.workspace_dir),
            "_agent_state_dir": str(self.state_dir),
            "_agent_session_dir": str(self.session_dir),
            "_agent_logs_dir": str(self.logs_dir),
            "_agent_memory_dir": str(self.memory_dir),
            "_agent_skills_dir": str(self.skills_dir),
        }


class AgentSessionStore:
    """Persist per-agent session state (traceability + isolation)."""

    def __init__(self, session_dir: Path):
        self.session_dir = session_dir
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.session_path = self.session_dir / "session.json"
        self.log_path = self.session_dir / "events.jsonl"

    def touch(self, metadata: Dict[str, object]) -> None:
        data = dict(metadata)
        data["updated_at"] = _utc_now()
        self.session_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def append_event(self, event: Dict[str, object]) -> None:
        record = dict(event)
        record["ts"] = _utc_now()
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")


def create_agent_runtime(role: str) -> AgentRuntime:
    config = get_config()
    agent_id = f"{role}-{uuid.uuid4().hex[:8]}"
    base_dir = Path(config.data_dir) / "agents" / role
    workspace_dir = base_dir / agent_id / "workspace"
    state_dir = base_dir / agent_id / "state"
    session_dir = base_dir / agent_id / "session"
    logs_dir = base_dir / agent_id / "logs"
    memory_dir = base_dir / agent_id / "memory"
    skills_dir = base_dir / agent_id / "skills"

    store = AgentPolicyStore()
    profile = store.get_profile(role)
    policy = profile.to_tool_policy()
    sandbox = profile.to_sandbox()

    runtime = AgentRuntime(
        agent_id=agent_id,
        role=role,
        workspace_dir=workspace_dir,
        state_dir=state_dir,
        session_dir=session_dir,
        logs_dir=logs_dir,
        memory_dir=memory_dir,
        skills_dir=skills_dir,
        policy=policy,
        sandbox=sandbox,
        created_at=_utc_now(),
    )
    runtime.ensure_dirs()
    AgentSessionStore(session_dir).touch(
        {
            "agent_id": agent_id,
            "role": role,
            "created_at": runtime.created_at,
            "workspace_dir": str(workspace_dir),
            "state_dir": str(state_dir),
            "session_dir": str(session_dir),
            "logs_dir": str(logs_dir),
            "memory_dir": str(memory_dir),
            "skills_dir": str(skills_dir),
            "policy": {
                "allow": policy.allowlist,
                "deny": policy.denylist,
                "description": policy.description,
            },
            "sandbox": {
                "network_mode": sandbox.network_mode,
                "workspace_dir": str(sandbox.workspace_dir) if sandbox.workspace_dir else "",
            },
        }
    )
    return runtime
