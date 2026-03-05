"""Channel policy manager for allowlists and pairing codes."""

from __future__ import annotations

import json
import logging
import random
import string
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from chintu_backend.core.config import get_config

logger = logging.getLogger(__name__)


class ChannelPolicyManager:
    def __init__(self, allowlist_path: Optional[Path] = None):
        self.config = get_config()
        self.path = Path(
            allowlist_path
            or getattr(self.config, "channel_allowlist_path", None)
            or (self.config.data_dir / "channel_allowlist.json")
        )
        self._data: Dict[str, Dict[str, object]] = {}
        self._load()

    def _load(self) -> None:
        try:
            if self.path.exists():
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to load channel allowlist: %s", exc)
            self._data = {}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to save channel allowlist: %s", exc)

    def _ensure_channel(self, channel: str) -> Dict[str, object]:
        channel = channel.lower()
        if channel not in self._data:
            self._data[channel] = {"allowlist": [], "pending_codes": {}, "agents": {}, "tool_policies": {}}
        entry = self._data[channel]
        if "agents" not in entry:
            entry["agents"] = {}
        if "tool_policies" not in entry:
            entry["tool_policies"] = {}
        return entry

    def get_agent_profile(self, channel: str, user_id, default_role: Optional[str] = None) -> Tuple[str, str]:
        entry = self._ensure_channel(channel)
        agents = entry.get("agents", {}) or {}
        key = str(user_id)
        profile = agents.get(key)
        if isinstance(profile, dict):
            agent_key = str(profile.get("key") or "primary")
            role = str(profile.get("role") or (default_role or "primary"))
            return agent_key, role
        # Default mapping (auto-register)
        agent_key = "primary"
        role = str(default_role or "primary")
        agents[key] = {"key": agent_key, "role": role}
        entry["agents"] = agents
        self._save()
        return agent_key, role

    def set_agent_profile(self, channel: str, user_id, agent_key: str, role: Optional[str] = None) -> None:
        entry = self._ensure_channel(channel)
        agents = entry.get("agents", {}) or {}
        agents[str(user_id)] = {
            "key": agent_key,
            "role": role or agent_key,
        }
        entry["agents"] = agents
        self._save()

    def clear_agent_profile(self, channel: str, user_id) -> None:
        entry = self._ensure_channel(channel)
        agents = entry.get("agents", {}) or {}
        if str(user_id) in agents:
            agents.pop(str(user_id))
            entry["agents"] = agents
            self._save()

    def get_tool_policy(self, channel: str, user_id=None) -> Dict[str, List[str]]:
        entry = self._ensure_channel(channel)
        policies = entry.get("tool_policies", {}) or {}
        policy = {"allow": [], "deny": []}
        if user_id is not None:
            user_policy = policies.get(str(user_id), {})
            policy["allow"] = list(user_policy.get("allow", []) or [])
            policy["deny"] = list(user_policy.get("deny", []) or [])
        default_policy = policies.get("default", {}) if isinstance(policies, dict) else {}
        if not policy["allow"] and default_policy:
            policy["allow"] = list(default_policy.get("allow", []) or [])
        if not policy["deny"] and default_policy:
            policy["deny"] = list(default_policy.get("deny", []) or [])
        return policy

    def set_tool_policy(self, channel: str, allow: Optional[List[str]] = None, deny: Optional[List[str]] = None, user_id=None) -> None:
        entry = self._ensure_channel(channel)
        policies = entry.get("tool_policies", {}) or {}
        key = "default" if user_id is None else str(user_id)
        policies[key] = {
            "allow": list(allow or []),
            "deny": list(deny or []),
        }
        entry["tool_policies"] = policies
        self._save()

    def is_allowed(self, channel: str, user_id) -> bool:
        entry = self._ensure_channel(channel)
        allowlist = entry.get("allowlist", [])
        return str(user_id) in [str(x) for x in allowlist]

    def add_allowed(self, channel: str, user_id) -> None:
        entry = self._ensure_channel(channel)
        allowlist = entry.get("allowlist", [])
        if str(user_id) not in [str(x) for x in allowlist]:
            allowlist.append(str(user_id))
            entry["allowlist"] = allowlist
            self._save()

    def request_pairing_code(self, channel: str, user_id) -> str:
        entry = self._ensure_channel(channel)
        pending = entry.get("pending_codes", {})
        code = _random_code(6)
        pending[code] = str(user_id)
        entry["pending_codes"] = pending
        self._save()
        return code

    def approve_code(self, channel: str, code: str):
        entry = self._ensure_channel(channel)
        pending = entry.get("pending_codes", {})
        user_id = pending.pop(code, None)
        if user_id is None:
            return None
        allowlist = entry.get("allowlist", [])
        if str(user_id) not in [str(x) for x in allowlist]:
            allowlist.append(str(user_id))
        entry["allowlist"] = allowlist
        entry["pending_codes"] = pending
        self._save()
        return user_id

    def clear_pending(self, channel: str, user_id) -> None:
        entry = self._ensure_channel(channel)
        pending = entry.get("pending_codes", {})
        pending = {k: v for k, v in pending.items() if str(v) != str(user_id)}
        entry["pending_codes"] = pending
        self._save()


def _random_code(length: int) -> str:
    return "".join(random.choice(string.digits) for _ in range(length))
