"""Discord gateway (Interactions webhook)."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import requests
from fastapi import Request

from chintu_backend.core.config import get_config
from .policy import ChannelPolicyManager

logger = logging.getLogger(__name__)


@dataclass
class DiscordConfig:
    enabled: bool
    application_id: str
    public_key: str
    bot_token: str
    allowed_channels: str
    allowed_users: str


class DiscordGateway:
    """Discord interactions handler (slash commands + components)."""

    def __init__(self, command_handler):
        self.config = get_config()
        self.command_handler = command_handler
        self.policy = ChannelPolicyManager()
        self._cfg = self._build_config()

    def _build_config(self) -> Optional[DiscordConfig]:
        enabled = bool(getattr(self.config, "discord_enabled", False))
        application_id = str(getattr(self.config, "discord_application_id", "") or "").strip()
        public_key = str(getattr(self.config, "discord_public_key", "") or "").strip()
        bot_token = str(getattr(self.config, "discord_bot_token", "") or "").strip()
        if not enabled or not application_id or not public_key:
            return None
        return DiscordConfig(
            enabled=enabled,
            application_id=application_id,
            public_key=public_key,
            bot_token=bot_token,
            allowed_channels=str(getattr(self.config, "discord_allowed_channels", "") or ""),
            allowed_users=str(getattr(self.config, "discord_allowed_users", "") or ""),
        )

    def is_enabled(self) -> bool:
        return self._cfg is not None

    async def handle_webhook(self, request: Request) -> Tuple[int, Any]:
        if not self._cfg:
            return 503, {"status": "disabled"}

        raw_body = await request.body()
        if not self._verify_request(request.headers, raw_body):
            return 401, {"error": "invalid signature"}

        try:
            payload = json.loads(raw_body.decode("utf-8") or "{}")
        except Exception:
            payload = {}

        if payload.get("type") == 1:  # PING
            return 200, {"type": 1}

        if payload.get("type") in {2, 3, 4}:  # COMMAND / COMPONENT
            user_id = _extract_discord_user(payload)
            channel_id = str(payload.get("channel_id") or "")
            if not self._is_allowed(user_id, channel_id):
                if getattr(self.config, "channel_pairing_enabled", False):
                    code = self.policy.request_pairing_code("discord", user_id)
                    return 200, _discord_message(f"Pairing code: {code}", ephemeral=True)
                return 403, _discord_message("Not allowed.", ephemeral=True)

            text = _discord_payload_to_text(payload)
            asyncio.create_task(self._process_message(text, user_id, channel_id, payload))
            return 200, {"type": 5}  # DEFERRED response

        return 200, {"status": "ignored"}

    def _verify_request(self, headers: Dict[str, Any], body: bytes) -> bool:
        cfg = self._cfg
        if not cfg:
            return False
        signature = headers.get("x-signature-ed25519") or headers.get("X-Signature-Ed25519")
        timestamp = headers.get("x-signature-timestamp") or headers.get("X-Signature-Timestamp")
        if not signature or not timestamp:
            return False
        try:
            from nacl.signing import VerifyKey
            from nacl.exceptions import BadSignatureError

            key = VerifyKey(bytes.fromhex(cfg.public_key))
            try:
                key.verify(timestamp.encode("utf-8") + body, bytes.fromhex(signature))
                return True
            except BadSignatureError:
                return False
        except Exception:
            logger.warning("Discord signature verification requires pynacl")
            return False

    def _is_allowed(self, user_id: str, channel_id: str) -> bool:
        cfg = self._cfg
        if not cfg:
            return False
        allow_users = [u.strip() for u in cfg.allowed_users.split(",") if u.strip()]
        allow_channels = [c.strip() for c in cfg.allowed_channels.split(",") if c.strip()]
        if allow_users and user_id not in allow_users:
            return False
        if allow_channels and channel_id not in allow_channels:
            return False
        if getattr(self.config, "channel_pairing_enabled", False):
            return self.policy.is_allowed("discord", user_id)
        return True

    async def _process_message(self, text: str, user_id: str, channel_id: str, payload: Dict[str, Any]) -> None:
        try:
            from chintu_backend.agents.agent_directory import get_agent_directory

            agent_key, agent_role = self.policy.get_agent_profile(
                "discord",
                user_id,
                default_role=getattr(self.config, "agent_default_role", "primary"),
            )
            directory = get_agent_directory()
            runtime = directory.get_or_create(agent_key, role=agent_role)
            agent_context = directory.build_context(
                runtime,
                agent_key,
                channel="discord",
                user_id=user_id,
            )
            response = await asyncio.to_thread(
                self.command_handler.handle,
                text,
                "discord",
                agent_context,
            )
            self._send_followup(payload, response)
        except Exception as exc:
            logger.warning("Discord handling failed: %s", exc)

    def _send_followup(self, payload: Dict[str, Any], text: str) -> None:
        cfg = self._cfg
        if not cfg:
            return
        token = payload.get("token")
        app_id = payload.get("application_id") or cfg.application_id
        if not token or not app_id:
            return
        url = f"https://discord.com/api/v10/webhooks/{app_id}/{token}"
        payload_out = {"content": text}
        try:
            requests.post(url, json=payload_out, timeout=10)
        except Exception as exc:
            logger.warning("Discord follow-up failed: %s", exc)


def _extract_discord_user(payload: Dict[str, Any]) -> str:
    member = payload.get("member") or {}
    user = member.get("user") or payload.get("user") or {}
    return str(user.get("id") or "")


def _discord_payload_to_text(payload: Dict[str, Any]) -> str:
    data = payload.get("data") or {}
    name = str(data.get("name") or "").strip()
    options = data.get("options") or []
    parts = [name] if name else []
    for opt in options:
        if isinstance(opt, dict):
            parts.append(f"{opt.get('name')}={opt.get('value')}")
    return " ".join([p for p in parts if p]).strip()


def _discord_message(content: str, ephemeral: bool = False) -> Dict[str, Any]:
    data = {"content": content}
    if ephemeral:
        data["flags"] = 64
    return {"type": 4, "data": data}
