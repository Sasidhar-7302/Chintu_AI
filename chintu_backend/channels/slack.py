"""Slack gateway (Events + Slash Command webhook)."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import requests
from fastapi import Request

from chintu_backend.core.config import get_config
from .policy import ChannelPolicyManager

logger = logging.getLogger(__name__)


@dataclass
class SlackConfig:
    enabled: bool
    bot_token: str
    signing_secret: str
    allowed_channels: str
    allowed_users: str


class SlackGateway:
    """Slack Events API + slash command handler."""

    def __init__(self, command_handler):
        self.config = get_config()
        self.command_handler = command_handler
        self.policy = ChannelPolicyManager()
        self._cfg = self._build_config()

    def _build_config(self) -> Optional[SlackConfig]:
        enabled = bool(getattr(self.config, "slack_enabled", False))
        bot_token = str(getattr(self.config, "slack_bot_token", "") or "").strip()
        signing_secret = str(getattr(self.config, "slack_signing_secret", "") or "").strip()
        if not enabled or not bot_token or not signing_secret:
            return None
        return SlackConfig(
            enabled=enabled,
            bot_token=bot_token,
            signing_secret=signing_secret,
            allowed_channels=str(getattr(self.config, "slack_allowed_channels", "") or ""),
            allowed_users=str(getattr(self.config, "slack_allowed_users", "") or ""),
        )

    def is_enabled(self) -> bool:
        return self._cfg is not None

    async def handle_webhook(self, request: Request) -> Tuple[int, Any]:
        if not self._cfg:
            return 503, {"status": "disabled"}

        raw_body = await request.body()
        if not self._verify_request(request.headers, raw_body):
            return 403, {"status": "invalid_signature"}

        content_type = request.headers.get("content-type", "")
        if "application/x-www-form-urlencoded" in content_type:
            form = await request.form()
            text = str(form.get("text", "")).strip()
            user_id = str(form.get("user_id", "")).strip()
            channel_id = str(form.get("channel_id", "")).strip()
            response_url = str(form.get("response_url", "")).strip()
            if not text:
                return 200, {"status": "ok"}
            if not self._is_allowed(user_id, channel_id):
                if getattr(self.config, "channel_pairing_enabled", False):
                    code = self.policy.request_pairing_code("slack", user_id)
                    self._post_response_url(response_url, f"Pairing code: {code}")
                return 403, {"status": "denied"}
            asyncio.create_task(self._process_message(text, user_id, channel_id, response_url=response_url))
            return 200, {"status": "ok"}

        try:
            payload = json.loads(raw_body.decode("utf-8") or "{}")
        except Exception:
            payload = {}

        if payload.get("type") == "url_verification":
            return 200, {"challenge": payload.get("challenge")}

        if payload.get("type") == "event_callback":
            event = payload.get("event", {}) or {}
            if event.get("type") != "message":
                return 200, {"status": "ignored"}
            if event.get("bot_id") or event.get("subtype") == "bot_message":
                return 200, {"status": "ignored"}
            text = str(event.get("text", "")).strip()
            user_id = str(event.get("user", "")).strip()
            channel_id = str(event.get("channel", "")).strip()
            if not text:
                return 200, {"status": "ok"}
            if not self._is_allowed(user_id, channel_id):
                if getattr(self.config, "channel_pairing_enabled", False):
                    code = self.policy.request_pairing_code("slack", user_id)
                    self._send_message(channel_id, f"Pairing code: {code}")
                return 403, {"status": "denied"}
            asyncio.create_task(self._process_message(text, user_id, channel_id))
            return 200, {"status": "ok"}

        return 200, {"status": "ignored"}

    def _verify_request(self, headers: Dict[str, Any], body: bytes) -> bool:
        cfg = self._cfg
        if not cfg:
            return False
        timestamp = headers.get("x-slack-request-timestamp") or headers.get("X-Slack-Request-Timestamp")
        signature = headers.get("x-slack-signature") or headers.get("X-Slack-Signature")
        if not timestamp or not signature:
            return False
        try:
            ts = int(timestamp)
            if abs(time.time() - ts) > 60 * 5:
                return False
        except Exception:
            return False

        base = f"v0:{timestamp}:{body.decode('utf-8')}".encode("utf-8")
        digest = hmac.new(cfg.signing_secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
        expected = f"v0={digest}"
        return hmac.compare_digest(expected, signature)

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
            return self.policy.is_allowed("slack", user_id)
        return True

    async def _process_message(
        self,
        text: str,
        user_id: str,
        channel_id: str,
        response_url: Optional[str] = None,
    ) -> None:
        try:
            from chintu_backend.agents.agent_directory import get_agent_directory

            agent_key, agent_role = self.policy.get_agent_profile(
                "slack",
                user_id,
                default_role=getattr(self.config, "agent_default_role", "primary"),
            )
            directory = get_agent_directory()
            runtime = directory.get_or_create(agent_key, role=agent_role)
            agent_context = directory.build_context(
                runtime,
                agent_key,
                channel="slack",
                user_id=user_id,
            )
            response = await asyncio.to_thread(
                self.command_handler.handle,
                text,
                "slack",
                agent_context,
            )
            if response_url:
                self._post_response_url(response_url, response)
            else:
                self._send_message(channel_id, response)
        except Exception as exc:
            logger.warning("Slack handling failed: %s", exc)

    def _send_message(self, channel_id: str, text: str) -> None:
        cfg = self._cfg
        if not cfg:
            return
        url = "https://slack.com/api/chat.postMessage"
        headers = {"Authorization": f"Bearer {cfg.bot_token}", "Content-Type": "application/json"}
        payload = {"channel": channel_id, "text": text}
        try:
            requests.post(url, headers=headers, json=payload, timeout=10)
        except Exception as exc:
            logger.warning("Slack send failed: %s", exc)

    def _post_response_url(self, url: str, text: str) -> None:
        if not url:
            return
        try:
            requests.post(url, json={"text": text}, timeout=10)
        except Exception as exc:
            logger.warning("Slack response_url send failed: %s", exc)
