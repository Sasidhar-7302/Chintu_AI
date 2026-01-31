"""WhatsApp gateway via Twilio webhook integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Tuple

import requests
from fastapi import Request

from chintu_backend.core.config import get_config
from .policy import ChannelPolicyManager

logger = logging.getLogger(__name__)


@dataclass
class WhatsAppConfig:
    enabled: bool
    account_sid: str
    auth_token: str
    from_number: str
    allowlist: str


class WhatsAppGateway:
    """Inbound webhook handler + outbound sender (Twilio)."""

    def __init__(self, command_handler):
        self.config = get_config()
        self.command_handler = command_handler
        self.policy = ChannelPolicyManager()
        self._cfg = self._build_config()

    def _build_config(self) -> Optional[WhatsAppConfig]:
        if not getattr(self.config, "whatsapp_enabled", False):
            return None
        account_sid = getattr(self.config, "whatsapp_account_sid", "")
        auth_token = getattr(self.config, "whatsapp_auth_token", "")
        from_number = getattr(self.config, "whatsapp_from_number", "")
        allowlist = getattr(self.config, "whatsapp_allowed_numbers", "")
        if not account_sid or not auth_token or not from_number:
            return None
        return WhatsAppConfig(
            enabled=True,
            account_sid=account_sid,
            auth_token=auth_token,
            from_number=from_number,
            allowlist=allowlist,
        )

    def is_enabled(self) -> bool:
        return self._cfg is not None

    async def handle_webhook(self, request: Request) -> Tuple[int, str]:
        if not self._cfg:
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
            response = self.command_handler.handle(
                body,
                source="whatsapp",
                context={"channel": "whatsapp", "user_id": from_number},
            )
            self._send_message(from_number, response)
        except Exception as exc:
            logger.warning("WhatsApp handling failed: %s", exc)
        return 200, "OK"

    def _is_allowed(self, from_number: str) -> bool:
        if getattr(self.config, "channel_pairing_enabled", False):
            # For WhatsApp, allowlist must include number
            return self.policy.is_allowed("whatsapp", from_number)
        if not self._cfg:
            return False
        allowlist = [n.strip() for n in self._cfg.allowlist.split(",") if n.strip()]
        if not allowlist:
            return True
        return from_number in allowlist

    def _send_message(self, to_number: str, body: str) -> None:
        if not self._cfg:
            return
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self._cfg.account_sid}/Messages.json"
        data = {
            "From": f"whatsapp:{self._cfg.from_number}",
            "To": f"whatsapp:{to_number}",
            "Body": body,
        }
        try:
            requests.post(url, data=data, auth=(self._cfg.account_sid, self._cfg.auth_token), timeout=10)
        except Exception as exc:
            logger.warning("WhatsApp send failed: %s", exc)
