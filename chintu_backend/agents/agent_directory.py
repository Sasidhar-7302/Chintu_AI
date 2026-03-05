"""Persistent agent directory and channel routing helpers."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple

from chintu_backend.core.config import get_config
from chintu_backend.swarm.agent_policy import AgentPolicyStore
from chintu_backend.swarm.agent_runtime import AgentRuntime, AgentSessionStore

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _slug(value: str) -> str:
    raw = "".join(ch.lower() if ch.isalnum() or ch in "-_" else "-" for ch in value.strip())
    return raw.strip("-") or "agent"


@dataclass
class AgentProfile:
    key: str
    agent_id: str
    role: str
    workspace_dir: Path
    state_dir: Path
    session_dir: Path
    logs_dir: Path
    memory_dir: Path
    skills_dir: Path
    created_at: str
    updated_at: str


class AgentDirectory:
    """Maintain persistent agent identities and workspaces."""

    def __init__(self, path: Optional[Path] = None):
        self.config = get_config()
        self.path = Path(path or self.config.agent_registry_path)
        self._data: Dict[str, Dict[str, str]] = {}
        self._load()

    def _load(self) -> None:
        try:
            if self.path.exists():
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self._data = raw
        except Exception as exc:
            logger.warning("Failed to load agent registry: %s", exc)
            self._data = {}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to save agent registry: %s", exc)

    def list_profiles(self) -> Dict[str, AgentProfile]:
        profiles: Dict[str, AgentProfile] = {}
        for key, data in self._data.items():
            profiles[key] = self._profile_from_data(key, data)
        return profiles

    def get_or_create(
        self,
        agent_key: str,
        role: Optional[str] = None,
        workspace_mode: Optional[str] = None,
        workspace_dir: Optional[Path] = None,
    ) -> AgentRuntime:
        agent_key = agent_key or "primary"
        role = (role or self.config.agent_default_role or "primary").lower()
        record = self._data.get(agent_key)
        if record:
            profile = self._profile_from_data(agent_key, record)
        else:
            profile = self._create_profile(agent_key, role, workspace_mode, workspace_dir)

        runtime = self._build_runtime(profile)
        try:
            runtime.ensure_dirs()
        except Exception:
            pass
        runtime.session_store = AgentSessionStore(runtime.session_dir)
        runtime.session_store.touch(
            {
                "agent_id": runtime.agent_id,
                "role": runtime.role,
                "workspace_dir": str(runtime.workspace_dir),
                "state_dir": str(runtime.state_dir),
                "session_dir": str(runtime.session_dir),
                "logs_dir": str(runtime.logs_dir),
                "memory_dir": str(runtime.memory_dir),
                "skills_dir": str(runtime.skills_dir),
                "created_at": runtime.created_at,
                "updated_at": _utc_now(),
            }
        )
        return runtime

    def build_context(
        self,
        runtime: AgentRuntime,
        agent_key: str,
        *,
        channel: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, object]:
        context = runtime.as_context()
        context.update(
            {
                "_agent_id": runtime.agent_id,
                "agent_key": agent_key,
                "agent_role": runtime.role,
                "workspace_dir": str(runtime.workspace_dir),
                "_agent_session_store": getattr(runtime, "session_store", None),
            }
        )
        if channel:
            context["channel"] = channel
        if user_id:
            context["user_id"] = user_id
        return context

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _profile_from_data(self, key: str, data: Dict[str, str]) -> AgentProfile:
        base_dir = Path(self.config.data_dir) / "agents" / _slug(str(data.get("role") or self.config.agent_default_role or "primary")) / _slug(str(data.get("agent_id") or key))
        return AgentProfile(
            key=key,
            agent_id=str(data.get("agent_id") or _slug(key)),
            role=str(data.get("role") or self.config.agent_default_role or "primary"),
            workspace_dir=Path(str(data.get("workspace_dir") or Path.cwd())),
            state_dir=Path(str(data.get("state_dir") or (base_dir / "state"))),
            session_dir=Path(str(data.get("session_dir") or (base_dir / "session"))),
            logs_dir=Path(str(data.get("logs_dir") or (base_dir / "logs"))),
            memory_dir=Path(str(data.get("memory_dir") or (base_dir / "memory"))),
            skills_dir=Path(str(data.get("skills_dir") or (base_dir / "skills"))),
            created_at=str(data.get("created_at") or _utc_now()),
            updated_at=str(data.get("updated_at") or _utc_now()),
        )

    def _create_profile(
        self,
        agent_key: str,
        role: str,
        workspace_mode: Optional[str],
        workspace_dir: Optional[Path],
    ) -> AgentProfile:
        agent_id = f"{_slug(agent_key)}-{_slug(role)}"
        now = _utc_now()
        mode = (workspace_mode or self.config.agent_default_workspace_mode or "shared").lower()
        if agent_key != "primary" and workspace_mode is None:
            mode = "isolated"

        if workspace_dir:
            workspace_root = Path(workspace_dir)
        elif mode == "shared":
            workspace_root = Path(self.config.agent_primary_workspace or Path.cwd())
        else:
            workspace_root = Path(self.config.agent_workspace_root or (self.config.data_dir / "agents"))

        base_dir = Path(self.config.data_dir) / "agents" / role / agent_id
        if mode == "isolated" and not workspace_dir:
            workspace_path = base_dir / "workspace"
        else:
            workspace_path = workspace_root

        profile = AgentProfile(
            key=agent_key,
            agent_id=agent_id,
            role=role,
            workspace_dir=workspace_path,
            state_dir=base_dir / "state",
            session_dir=base_dir / "session",
            logs_dir=base_dir / "logs",
            memory_dir=base_dir / "memory",
            skills_dir=base_dir / "skills",
            created_at=now,
            updated_at=now,
        )
        self._data[agent_key] = {
            "agent_id": profile.agent_id,
            "role": profile.role,
            "workspace_dir": str(profile.workspace_dir),
            "state_dir": str(profile.state_dir),
            "session_dir": str(profile.session_dir),
            "logs_dir": str(profile.logs_dir),
            "memory_dir": str(profile.memory_dir),
            "skills_dir": str(profile.skills_dir),
            "created_at": profile.created_at,
            "updated_at": profile.updated_at,
        }
        self._save()
        return profile

    def _build_runtime(self, profile: AgentProfile) -> AgentRuntime:
        store = AgentPolicyStore()
        policy_profile = store.get_profile(profile.role)
        policy = policy_profile.to_tool_policy()
        sandbox = policy_profile.to_sandbox()
        if sandbox.workspace_dir is None:
            sandbox.workspace_dir = profile.workspace_dir
        return AgentRuntime(
            agent_id=profile.agent_id,
            role=profile.role,
            workspace_dir=profile.workspace_dir,
            state_dir=profile.state_dir,
            session_dir=profile.session_dir,
            logs_dir=profile.logs_dir,
            memory_dir=profile.memory_dir,
            skills_dir=profile.skills_dir,
            policy=policy,
            sandbox=sandbox,
            created_at=profile.created_at,
        )


_directory: Optional[AgentDirectory] = None


def get_agent_directory() -> AgentDirectory:
    global _directory
    if _directory is None:
        _directory = AgentDirectory()
    return _directory
