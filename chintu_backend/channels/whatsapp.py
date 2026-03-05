"""WhatsApp gateway via Twilio or Baileys bridge integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Tuple, Any, Dict

import requests
from fastapi import Request

from chintu_backend.core.config import get_config
from .policy import ChannelPolicyManager

logger = logging.getLogger(__name__)


@dataclass
class TwilioConfig:
    enabled: bool
    account_sid: str
    auth_token: str
    from_number: str
    allowlist: str


@dataclass
class BaileysConfig:
    enabled: bool
    base_url: str
    token: str
    send_path: str
    webhook_secret: str
    allowlist: str


class WhatsAppGateway:
    """Inbound webhook handler + outbound sender (Twilio)."""

    def __init__(self, command_handler):
        self.config = get_config()
        self.command_handler = command_handler
        self.policy = ChannelPolicyManager()
        self._provider = (getattr(self.config, "whatsapp_provider", "twilio") or "twilio").lower()
        self._twilio = None
        self._baileys = None
        self._build_config()

    def _build_config(self) -> None:
        if not getattr(self.config, "whatsapp_enabled", False):
            return
        allowlist = getattr(self.config, "whatsapp_allowed_numbers", "")
        if self._provider == "baileys":
            base_url = str(getattr(self.config, "whatsapp_baileys_url", "") or "").strip()
            token = str(getattr(self.config, "whatsapp_baileys_token", "") or "").strip()
            send_path = str(getattr(self.config, "whatsapp_baileys_send_path", "send") or "send").strip("/")
            webhook_secret = str(getattr(self.config, "whatsapp_baileys_webhook_secret", "") or "")
            if not base_url:
                return
            self._baileys = BaileysConfig(
                enabled=True,
                base_url=base_url.rstrip("/"),
                token=token,
                send_path=send_path or "send",
                webhook_secret=webhook_secret,
                allowlist=allowlist,
            )
            return

        account_sid = getattr(self.config, "whatsapp_account_sid", "")
        auth_token = getattr(self.config, "whatsapp_auth_token", "")
        from_number = getattr(self.config, "whatsapp_from_number", "")
        if not account_sid or not auth_token or not from_number:
            return
        self._twilio = TwilioConfig(
            enabled=True,
            account_sid=account_sid,
            auth_token=auth_token,
            from_number=from_number,
            allowlist=allowlist,
        )

    def is_enabled(self) -> bool:
        if self._provider == "baileys":
            return self._baileys is not None
        return self._twilio is not None

    async def handle_webhook(self, request: Request) -> Tuple[int, str]:
        if self._provider == "baileys":
            return await self._handle_baileys_webhook(request)
        if not self._twilio:
            return 503, "WhatsApp not configured"
        form = await request.form()
        from_number = str(form.get("From", "")).replace("whatsapp:", "")
        body = str(form.get("Body", "")).strip()
        if body.lower().startswith("pair ") or body.lower().startswith("/pair"):
            code = body.split()[-1].strip()
            if self.policy.approve_code("whatsapp", code) is not None:
                self._send_message(from_number, "Paired successfully. You can now send commands.")
                return 200, "OK"
            self._send_message(from_number, "Invalid pairing code.")
            return 200, "OK"
        if not self._is_allowed(from_number):
            if getattr(self.config, "channel_pairing_enabled", False):
                code = self.policy.request_pairing_code("whatsapp", from_number)
                self._send_message(
                    from_number,
                    f"You're not paired. Reply with: pair {code}",
                )
            return 403, "Not allowed"
        if not body:
            return 200, "OK"
        try:
            agent_context = self._build_agent_context(from_number)
            response = self.command_handler.handle(
                body,
                source="whatsapp",
                context=agent_context,
            )
            self._send_message(from_number, response)
        except Exception as exc:
            logger.warning("WhatsApp handling failed: %s", exc)
        return 200, "OK"

    def _is_allowed(self, from_number: str) -> bool:
        if getattr(self.config, "channel_pairing_enabled", False):
            # For WhatsApp, allowlist must include number
            return self.policy.is_allowed("whatsapp", from_number)
        if self._provider == "baileys":
            cfg = self._baileys
        else:
            cfg = self._twilio
        if not cfg:
            return False
        allowlist = [n.strip() for n in cfg.allowlist.split(",") if n.strip()]
        if not allowlist:
            return True
        return from_number in allowlist

    def _send_message(self, to_number: str, body: str) -> None:
        if self._provider == "baileys":
            self._send_baileys(to_number, body)
            return
        if not self._twilio:
            return
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self._twilio.account_sid}/Messages.json"
        data = {
            "From": f"whatsapp:{self._twilio.from_number}",
            "To": f"whatsapp:{to_number}",
            "Body": body,
        }
        try:
            requests.post(url, data=data, auth=(self._twilio.account_sid, self._twilio.auth_token), timeout=10)
        except Exception as exc:
            logger.warning("WhatsApp send failed: %s", exc)

    async def _handle_baileys_webhook(self, request: Request) -> Tuple[int, str]:
        if not self._baileys:
            return 503, "WhatsApp not configured"
        try:
            token = request.headers.get("x-whatsapp-token") or request.headers.get("x-baileys-token")
            if self._baileys.webhook_secret and token != self._baileys.webhook_secret:
                return 403, "Invalid token"
        except Exception:
            pass

        try:
            payload = await request.json()
        except Exception:
            payload = {}

        from_number = _extract_baileys_sender(payload)
        body = _extract_baileys_body(payload)
        if not from_number or not body:
            return 200, "OK"

        if body.lower().startswith("pair ") or body.lower().startswith("/pair"):
            code = body.split()[-1].strip()
            if self.policy.approve_code("whatsapp", code) is not None:
                self._send_message(from_number, "Paired successfully. You can now send commands.")
                return 200, "OK"
            self._send_message(from_number, "Invalid pairing code.")
            return 200, "OK"

        if not self._is_allowed(from_number):
            if getattr(self.config, "channel_pairing_enabled", False):
                code = self.policy.request_pairing_code("whatsapp", from_number)
                self._send_message(
                    from_number,
                    f"You're not paired. Reply with: pair {code}",
                )
            return 403, "Not allowed"

        try:
            agent_context = self._build_agent_context(from_number)
            response = self.command_handler.handle(
                body,
                source="whatsapp",
                context=agent_context,
            )
            self._send_message(from_number, response)
        except Exception as exc:
            logger.warning("WhatsApp handling failed: %s", exc)
        return 200, "OK"

    def _send_baileys(self, to_number: str, body: str) -> None:
        if not self._baileys:
            return
        url = f"{self._baileys.base_url}/{self._baileys.send_path}"
        payload = {"to": to_number, "message": body}
        headers = {}
        if self._baileys.token:
            headers["Authorization"] = f"Bearer {self._baileys.token}"
            headers["X-Api-Key"] = self._baileys.token
        try:
            requests.post(url, json=payload, headers=headers, timeout=10)
        except Exception as exc:
            logger.warning("Baileys send failed: %s", exc)

    def _build_agent_context(self, user_id: str) -> Dict[str, Any]:
        try:
            from chintu_backend.agents.agent_directory import get_agent_directory
            from .policy import ChannelPolicyManager

            policy = ChannelPolicyManager()
            agent_key, agent_role = policy.get_agent_profile(
                "whatsapp",
                user_id,
                default_role=getattr(self.config, "agent_default_role", "primary"),
            )
            directory = get_agent_directory()
            runtime = directory.get_or_create(agent_key, role=agent_role)
            return directory.build_context(
                runtime,
                agent_key,
                channel="whatsapp",
                user_id=str(user_id),
            )
        except Exception:
            return {"channel": "whatsapp", "user_id": user_id}


def _extract_baileys_sender(payload: Dict[str, Any]) -> str:
    sender = (
        payload.get("from")
        or payload.get("sender")
        or payload.get("remoteJid")
        or payload.get("chatId")
        or ""
    )
    sender = str(sender)
    sender = sender.replace("whatsapp:", "")
    if "@" in sender:
        sender = sender.split("@", 1)[0]
    return sender.strip()


def _extract_baileys_body(payload: Dict[str, Any]) -> str:
    body = payload.get("body") or payload.get("text") or payload.get("message") or payload.get("msg")
    if isinstance(body, dict):
        body = body.get("text") or body.get("body") or body.get("message")
    if not body and isinstance(payload.get("messages"), list) and payload.get("messages"):
        msg = payload.get("messages")[0]
        if isinstance(msg, dict):
            body = msg.get("text") or msg.get("body") or msg.get("message")
            sender = msg.get("from") or msg.get("remoteJid")
            if sender and not payload.get("from"):
                payload["from"] = sender
    return str(body or "").strip()
