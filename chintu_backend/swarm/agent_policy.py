"""Per-agent tool and sandbox policy profiles."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Dict, List, Optional

from chintu_backend.core.config import get_config


@dataclass
class AgentToolPolicy:
    allowlist: List[str] = field(default_factory=list)
    denylist: List[str] = field(default_factory=list)
    description: str = ""

    def allows(self, capability_name: str) -> bool:
        name = (capability_name or "").lower()
        for pattern in self.denylist:
            if fnmatch(name, pattern.lower()):
                return False
        if self.allowlist:
            return any(fnmatch(name, pattern.lower()) for pattern in self.allowlist)
        return True


@dataclass
class AgentSandboxConfig:
    network_mode: str = "none"
    workspace_dir: Optional[Path] = None


@dataclass
class AgentPolicyProfile:
    tool_allowlist: List[str] = field(default_factory=list)
    tool_denylist: List[str] = field(default_factory=list)
    sandbox_network_mode: Optional[str] = None
    sandbox_workspace: Optional[str] = None
    description: str = ""

    def to_tool_policy(self) -> AgentToolPolicy:
        return AgentToolPolicy(
            allowlist=list(self.tool_allowlist or []),
            denylist=list(self.tool_denylist or []),
            description=self.description or "",
        )

    def to_sandbox(self) -> AgentSandboxConfig:
        workspace = Path(self.sandbox_workspace) if self.sandbox_workspace else None
        return AgentSandboxConfig(
            network_mode=self.sandbox_network_mode or "none",
            workspace_dir=workspace,
        )


class AgentPolicyStore:
    """Load per-agent policies from a JSON file."""

    def __init__(self, path: Optional[Path] = None):
        config = get_config()
        self.path = Path(path or config.agent_policies_path)
        self._data: Optional[Dict[str, object]] = None

    def _load(self) -> Dict[str, object]:
        if self._data is not None:
            return self._data
        if self.path and self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self._data = raw
                    return raw
            except Exception:
                pass
        self._data = {"default": {}, "roles": {}}
        return self._data

    def get_profile(self, role: str) -> AgentPolicyProfile:
        data = self._load()
        role_key = (role or "default").lower()
        default = data.get("default") or {}
        roles = data.get("roles") or {}
        override = roles.get(role_key) or {}

        def _list(value):
            if not value:
                return []
            if isinstance(value, list):
                return [str(v) for v in value if str(v)]
            return [str(value)]

        return AgentPolicyProfile(
            tool_allowlist=_list(override.get("allow") or default.get("allow")),
            tool_denylist=_list(override.get("deny") or default.get("deny")),
            sandbox_network_mode=(override.get("sandbox_network_mode") or default.get("sandbox_network_mode")),
            sandbox_workspace=(override.get("sandbox_workspace") or default.get("sandbox_workspace")),
            description=str(override.get("description") or default.get("description") or ""),
        )
