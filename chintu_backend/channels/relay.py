"""Generic relay webhook gateway (Signal/Teams/iMessage)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional, Tuple

import requests
from fastapi import Request

from chintu_backend.core.config import get_config
from .policy import ChannelPolicyManager

logger = logging.getLogger(__name__)


class RelayGateway:
    """Accepts webhook relays from external bridges."""

    def __init__(self, command_handler, channel: str):
        self.config = get_config()
        self.command_handler = command_handler
        self.channel = channel
        self.policy = ChannelPolicyManager()

    def is_enabled(self) -> bool:
        return bool(getattr(self.config, f"{self.channel}_enabled", False))

    async def handle_webhook(self, request: Request) -> Tuple[int, Any]:
        if not self.is_enabled():
            return 503, {"status": "disabled"}

        secret = str(getattr(self.config, f"{self.channel}_webhook_secret", "") or "")
        if secret:
            token = request.headers.get("x-relay-token") or request.headers.get(f"x-{self.channel}-token")
            if token != secret:
                return 403, {"status": "invalid_token"}

        try:
            payload = await request.json()
        except Exception:
            payload = {}

        text = str(payload.get("text") or payload.get("message") or "").strip()
        user_id = str(payload.get("user_id") or payload.get("from") or "")
        reply_url = str(payload.get("reply_url") or payload.get("response_url") or "")
        if not text:
            return 200, {"status": "ok"}

        if getattr(self.config, "channel_pairing_enabled", False):
            if not self.policy.is_allowed(self.channel, user_id):
                code = self.policy.request_pairing_code(self.channel, user_id)
                if reply_url:
                    self._post_reply(reply_url, f"Pairing code: {code}")
                return 403, {"status": "denied", "pairing_code": code}

        response = await self._run_command(text, user_id)
        if reply_url:
            self._post_reply(reply_url, response)
            return 200, {"status": "ok"}
        return 200, {"response": response}

    async def _run_command(self, text: str, user_id: str) -> str:
        try:
            from chintu_backend.agents.agent_directory import get_agent_directory

            agent_key, agent_role = self.policy.get_agent_profile(
                self.channel,
                user_id,
                default_role=getattr(self.config, "agent_default_role", "primary"),
            )
            directory = get_agent_directory()
            runtime = directory.get_or_create(agent_key, role=agent_role)
            agent_context = directory.build_context(
                runtime,
                agent_key,
                channel=self.channel,
                user_id=user_id,
            )
            return await asyncio.to_thread(
                self.command_handler.handle,
                text,
                self.channel,
                agent_context,
            )
        except Exception as exc:
            logger.warning("%s relay failed: %s", self.channel, exc)
            return f"Command failed: {exc}"

    def _post_reply(self, url: str, text: str) -> None:
        if not url:
            return
        try:
            requests.post(url, json={"text": text}, timeout=10)
        except Exception as exc:
            logger.warning("%s relay response failed: %s", self.channel, exc)
