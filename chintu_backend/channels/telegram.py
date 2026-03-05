"""Telegram gateway for headless control and push notifications."""

from __future__ import annotations

import asyncio
import logging
import threading
import hmac
import hashlib
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
import uuid

from chintu_backend.core.config import get_config
from chintu_backend.core.events import Event, EventType, get_event_bus
from chintu_backend.core.state import get_state_manager

logger = logging.getLogger(__name__)


def _import_telegram():
    """Import telegram dependencies lazily to avoid hard failures."""
    try:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
        from telegram.ext import (
            Application,
            CallbackQueryHandler,
            CommandHandler,
            ContextTypes,
            MessageHandler,
            filters,
        )

        return {
            "InlineKeyboardButton": InlineKeyboardButton,
            "InlineKeyboardMarkup": InlineKeyboardMarkup,
            "WebAppInfo": WebAppInfo,
            "Update": Update,
            "Application": Application,
            "CallbackQueryHandler": CallbackQueryHandler,
            "CommandHandler": CommandHandler,
            "ContextTypes": ContextTypes,
            "MessageHandler": MessageHandler,
            "filters": filters,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Telegram dependencies not available: %s", exc)
        return None


@dataclass
class TelegramConfig:
    enabled: bool
    token: str
    allowed_user_id: int
    allow_orchestrator_approvals: bool
    allow_code_approvals: bool
    max_message_length: int


class TelegramGateway:
    """Headless gateway for Telegram control and notifications."""

    def __init__(self, command_handler) -> None:
        self.config = get_config()
        self.command_handler = command_handler
        self.event_bus = get_event_bus()
        self.state_manager = get_state_manager()

        self._deps = _import_telegram()
        self._tg: Optional[TelegramConfig] = self._build_config()

        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._app = None
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> Tuple[bool, str]:
        """Start the Telegram gateway in a background thread."""
        if not self._tg or not self._deps:
            self.state_manager.update_feature("telegram", enabled=False, status="inactive")
            return False, "Telegram not configured"
        if self._running:
            return True, "Telegram gateway already running"

        self._thread = threading.Thread(target=self._run, daemon=True, name="ChintuTelegram")
        self._thread.start()
        self._running = True
        self.state_manager.update_feature("telegram", enabled=True, status="active", error=None)
        return True, "Telegram gateway started"

    def stop(self) -> None:
        """Stop the Telegram gateway."""
        self._running = False
        loop = self._loop
        app = self._app
        if loop and loop.is_running() and app:
            try:
                asyncio.run_coroutine_threadsafe(app.stop(), loop)
            except Exception:
                pass
        try:
            self.state_manager.update_feature("telegram", status="inactive")
        except Exception:
            pass

    def _run(self) -> None:
        """Background thread entrypoint."""
        deps = self._deps
        tg = self._tg
        if not deps or not tg:
            return

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._async_run(deps, tg))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Telegram gateway crashed: %s", exc)
            try:
                self.state_manager.update_feature("telegram", status="testing", error=str(exc))
            except Exception:
                pass
        finally:
            self._running = False

    async def _async_run(self, deps: Dict[str, Any], tg: TelegramConfig) -> None:
        Application = deps["Application"]
        CallbackQueryHandler = deps["CallbackQueryHandler"]
        CommandHandler = deps["CommandHandler"]
        MessageHandler = deps["MessageHandler"]
        filters = deps["filters"]

        self._app = Application.builder().token(tg.token).build()

        # Handlers
        self._app.add_handler(CommandHandler("start", self._on_start))
        self._app.add_handler(CommandHandler("dashboard", self._on_dashboard))
        self._app.add_handler(CallbackQueryHandler(self._on_callback))
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_text))
        self._app.add_handler(MessageHandler(filters.PHOTO, self._on_photo))
        self._app.add_handler(MessageHandler(filters.VIDEO, self._on_video))
        self._app.add_handler(MessageHandler(filters.Document.ALL, self._on_document))

        # Subscribe to internal notifications.
        self.event_bus.subscribe(EventType.NOTIFICATION, self._on_notification_event, is_async=False)

        logger.info("Telegram gateway polling started")
        await self._app.initialize()
        await self._app.start()
        try:
            await self._app.updater.start_polling(drop_pending_updates=True)
            # Keep the loop alive while running.
            while self._running:
                await asyncio.sleep(0.25)
        finally:
            try:
                await self._app.updater.stop()
            except Exception:
                pass
            try:
                await self._app.stop()
            except Exception:
                pass
            try:
                await self._app.shutdown()
            except Exception:
                pass
            logger.info("Telegram gateway stopped")

    # ------------------------------------------------------------------
    # Telegram handlers
    # ------------------------------------------------------------------
    async def _on_start(self, update, _context) -> None:
        if not self._is_allowed(update):
            return
        await update.effective_message.reply_text(
            "Chintu Telegram gateway is connected. Send a command to begin."
        )

    async def _on_dashboard(self, update, _context) -> None:
        if not self._is_allowed(update):
            return
        if not bool(getattr(self.config, "telegram_mini_app_enabled", False)):
            await self._safe_reply(update, "Mini app control plane is disabled.")
            return
        url = self._build_mini_app_url(update)
        if not url:
            await self._safe_reply(
                update,
                "Mini app URL is not configured. Set `CHINTU_TELEGRAM_MINI_APP_URL`.",
            )
            return
        deps = self._deps or {}
        InlineKeyboardButton = deps.get("InlineKeyboardButton")
        InlineKeyboardMarkup = deps.get("InlineKeyboardMarkup")
        WebAppInfo = deps.get("WebAppInfo")
        if InlineKeyboardButton and InlineKeyboardMarkup and WebAppInfo:
            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton("Open Control Plane", web_app=WebAppInfo(url=url))]]
            )
            await update.effective_message.reply_text(
                "Open Chintu control plane:",
                reply_markup=keyboard,
            )
        else:
            await update.effective_message.reply_text(f"Control plane URL:\n{url}")

    async def _on_text(self, update, _context) -> None:
        # Allow pairing flow before access checks
        text = (update.effective_message.text or "").strip()
        if text.lower().startswith("/pair") or text.lower().startswith("pair "):
            await self._handle_pairing(update, text)
            return
        if not self._is_allowed(update):
            return
        if not text:
            return
        logger.info("Telegram command: %s", text[:120])
        self._maybe_store_text_inbox_item(update, text)
        try:
            agent_context = self._build_agent_context(update)
            response = self.command_handler.handle(
                text,
                source="telegram",
                context=agent_context,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Telegram command failed: %s", exc)
            response = f"Command failed: {exc}"
        await self._safe_reply(update, response)
        await self._maybe_send_news_feedback_keyboard(update, text=text, response=response)
        
        # Send voice note if enabled and response is not too long
        if self._should_send_voice(response):
            await self._send_voice_note(update.effective_chat.id, response)

    async def _on_photo(self, update, context) -> None:
        if not self._is_allowed(update):
            return
        message = getattr(update, "effective_message", None)
        photos = list(getattr(message, "photo", []) or [])
        if not photos:
            return
        file_id = str(getattr(photos[-1], "file_id", "") or "").strip()
        if not file_id:
            return
        media_path = await self._download_telegram_media(context, file_id, ".jpg")
        note = str(getattr(message, "caption", "") or "").strip()
        outcome = self._ingest_telegram_inbox_item(
            update,
            kind="photo",
            message_text=note,
            media_path=media_path,
            media_type="image/jpeg",
        )
        if outcome:
            await self._safe_reply(update, outcome)

    async def _on_video(self, update, context) -> None:
        if not self._is_allowed(update):
            return
        message = getattr(update, "effective_message", None)
        video = getattr(message, "video", None)
        if not video:
            return
        file_id = str(getattr(video, "file_id", "") or "").strip()
        if not file_id:
            return
        suffix = ".mp4"
        media_path = await self._download_telegram_media(context, file_id, suffix)
        note = str(getattr(message, "caption", "") or "").strip()
        outcome = self._ingest_telegram_inbox_item(
            update,
            kind="video",
            message_text=note,
            media_path=media_path,
            media_type="video/mp4",
        )
        if outcome:
            await self._safe_reply(update, outcome)

    async def _on_document(self, update, context) -> None:
        if not self._is_allowed(update):
            return
        message = getattr(update, "effective_message", None)
        document = getattr(message, "document", None)
        if not document:
            return
        file_id = str(getattr(document, "file_id", "") or "").strip()
        if not file_id:
            return
        file_name = str(getattr(document, "file_name", "") or "").strip()
        suffix = Path(file_name).suffix if file_name else ".bin"
        media_path = await self._download_telegram_media(context, file_id, suffix or ".bin")
        note = str(getattr(message, "caption", "") or "").strip()
        outcome = self._ingest_telegram_inbox_item(
            update,
            kind="document",
            message_text=note,
            media_path=media_path,
            media_type=str(getattr(document, "mime_type", "") or "application/octet-stream"),
        )
        if outcome:
            await self._safe_reply(update, outcome)

    async def _on_callback(self, update, _context) -> None:
        if not self._is_allowed(update):
            return
        query = update.callback_query
        if not query:
            return
        data = query.data or ""
        await query.answer()
        orch_payload = self._parse_orchestrator_callback_data(data)
        if orch_payload:
            step_id, approve, err = orch_payload
            if err:
                await self._safe_reply(update, err)
                return
            await self._handle_orchestrator_approval(step_id, approve=approve, update=update)
            return
        if data.startswith("news:"):
            await self._handle_news_feedback_callback(data=data, update=update)
            return
        await self._safe_reply(update, "I did not recognize that action.")

    async def _handle_orchestrator_approval(self, step_id: str, approve: bool, update) -> None:
        if not self._tg:
            return
        if not self._tg.allow_orchestrator_approvals:
            await self._safe_reply(update, "Approvals are disabled for Telegram.")
            return
        try:
            from chintu_backend.orchestrator import get_orchestrator_manager

            manager = get_orchestrator_manager()
            updated = manager.approve_step(step_id, approve=approve)
            if not updated:
                await self._safe_reply(update, "I could not update that step.")
                return
            status = updated.status.value
            action = "Approved" if approve else "Rejected"
            await self._safe_reply(update, f"{action} step {updated.id[:8]} ({status}).")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Telegram approval failed: %s", exc)
            await self._safe_reply(update, f"Approval failed: {exc}")

    async def _handle_news_feedback_callback(self, data: str, update) -> None:
        try:
            _, action, index_raw = data.split(":", 2)
            index = int(index_raw)
        except Exception:
            await self._safe_reply(update, "Invalid news action.")
            return

        if index <= 0:
            await self._safe_reply(update, "Invalid headline number.")
            return

        if action == "like":
            command = f"I like #{index}"
            quick = "Saved: like"
        elif action == "dislike":
            command = f"not interested in #{index}"
            quick = "Saved: not interested"
        elif action == "more":
            command = f"read more about #{index}"
            quick = "Opening details"
        else:
            await self._safe_reply(update, "Unknown news action.")
            return

        try:
            agent_context = self._build_agent_context(update)
            result = self.command_handler.handle(command, source="telegram", context=agent_context)
        except Exception as exc:  # noqa: BLE001
            await self._safe_reply(update, f"Action failed: {exc}")
            return

        response = str(result or "").strip() or quick
        await self._safe_reply(update, response)

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------
    def _on_notification_event(self, event: Event) -> None:
        """Sync event-bus handler that schedules async sends."""
        tg = self._tg
        loop = self._loop
        if not tg or not loop or not loop.is_running() or not self._app:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._send_notification(event.data), loop)
        except Exception:
            pass

    async def _send_notification(self, data: Dict[str, Any]) -> None:
        tg = self._tg
        app = self._app
        deps = self._deps
        if not tg or not app or not deps:
            return

        category = str(data.get("category") or "notification")
        severity = str(data.get("severity") or "info").lower()
        title = str(data.get("title") or "Chintu Notification")
        message = str(data.get("message") or "")
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}

        prefix = {
            "critical": "ðŸ›‘",
            "high": "âš ï¸",
            "medium": "â„¹ï¸",
            "low": "âœ…",
            "info": "â„¹ï¸",
        }.get(severity, "â„¹ï¸")

        text = f"{prefix} {title}\n{message}".strip()
        text = self._trim(text, tg.max_message_length)

        reply_markup = None
        if category == "orchestrator_approval" and tg.allow_orchestrator_approvals:
            step_id = str(metadata.get("step_id") or "")
            if step_id:
                InlineKeyboardButton = deps["InlineKeyboardButton"]
                InlineKeyboardMarkup = deps["InlineKeyboardMarkup"]
                reply_markup = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton("âœ… Approve", callback_data=self._build_orchestrator_callback_data(step_id=step_id, approve=True)),
                            InlineKeyboardButton("âŒ Reject", callback_data=self._build_orchestrator_callback_data(step_id=step_id, approve=False)),
                        ]
                    ]
                )

        try:
            await app.bot.send_message(
                chat_id=tg.allowed_user_id,
                text=text,
                reply_markup=reply_markup,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Telegram send failed: %s", exc)

    async def _maybe_send_news_feedback_keyboard(self, update, *, text: str, response: str) -> None:
        deps = self._deps
        tg = self._tg
        if not deps or not tg:
            return
        low_text = str(text or "").lower()
        low_response = str(response or "").lower()
        if "daily briefing" not in low_text and "[top 20 headlines]" not in low_response:
            return

        headline_numbers = []
        for line in str(response or "").splitlines():
            clean = str(line or "").strip()
            if not clean:
                continue
            if len(clean) >= 3 and clean[0:2].isdigit() and clean[2] == ".":
                headline_numbers.append(int(clean[0:2]))
            elif len(clean) >= 2 and clean[0].isdigit() and clean[1] == ".":
                headline_numbers.append(int(clean[0]))
        if not headline_numbers:
            return

        count = min(max(headline_numbers), 5)
        InlineKeyboardButton = deps["InlineKeyboardButton"]
        InlineKeyboardMarkup = deps["InlineKeyboardMarkup"]
        rows = []
        for idx in range(1, count + 1):
            rows.append(
                [
                    InlineKeyboardButton(f"Like #{idx}", callback_data=f"news:like:{idx}"),
                    InlineKeyboardButton(f"Less #{idx}", callback_data=f"news:dislike:{idx}"),
                    InlineKeyboardButton(f"More #{idx}", callback_data=f"news:more:{idx}"),
                ]
            )
        message = "Quick actions for top headlines:"
        try:
            await update.effective_message.reply_text(message, reply_markup=InlineKeyboardMarkup(rows))
        except Exception:
            return

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    async def _download_telegram_media(self, context, file_id: str, suffix: str) -> str:
        try:
            from chintu_backend.channels.telegram_inbox import get_telegram_inbox_manager

            manager = get_telegram_inbox_manager()
            target = Path(manager.media_dir) / f"tg_{uuid.uuid4().hex[:12]}{suffix}"
            tg_file = await context.bot.get_file(file_id)
            await tg_file.download_to_drive(custom_path=str(target))
            return str(target)
        except Exception as exc:
            logger.warning("Telegram media download failed: %s", exc)
            return ""

    def _build_inbox_provenance(self, update) -> Dict[str, Any]:
        message = getattr(update, "effective_message", None)
        provenance: Dict[str, Any] = {}
        if not message:
            return provenance
        forward_origin = getattr(message, "forward_origin", None)
        if forward_origin:
            provenance["forward_origin"] = str(forward_origin)
        if getattr(message, "forward_date", None):
            try:
                provenance["forward_date"] = message.forward_date.isoformat()
            except Exception:
                provenance["forward_date"] = str(message.forward_date)
        sender_chat = getattr(message, "sender_chat", None)
        if sender_chat is not None:
            provenance["sender_chat_id"] = str(getattr(sender_chat, "id", "") or "")
            provenance["sender_chat_title"] = str(getattr(sender_chat, "title", "") or "")
        return provenance

    def _source_timestamp_iso(self, update) -> str:
        message = getattr(update, "effective_message", None)
        date_value = getattr(message, "date", None)
        if not date_value:
            return ""
        try:
            return date_value.isoformat()
        except Exception:
            return str(date_value)

    def _ingest_telegram_inbox_item(
        self,
        update,
        *,
        kind: str,
        message_text: str = "",
        media_path: str = "",
        media_type: str = "",
    ) -> str:
        try:
            from chintu_backend.channels.telegram_inbox import get_telegram_inbox_manager

            manager = get_telegram_inbox_manager()
            if not manager.enabled:
                return ""
            message = getattr(update, "effective_message", None)
            chat = getattr(update, "effective_chat", None)
            user = getattr(update, "effective_user", None)
            queued = manager.enqueue_item(
                kind=kind,
                message_text=str(message_text or "").strip(),
                media_path=str(media_path or ""),
                media_type=str(media_type or ""),
                source_message_id=str(getattr(message, "message_id", "") or ""),
                source_chat_id=str(getattr(chat, "id", "") or ""),
                source_user_id=str(getattr(user, "id", "") or ""),
                source_timestamp=self._source_timestamp_iso(update),
                provenance=self._build_inbox_provenance(update),
            )
            if not bool(queued.get("ok")):
                return f"Inbox intake skipped: {queued.get('message') or 'not queued'}."
            intake_id = str(queued.get("intake_id") or "")
            if not bool(getattr(self.config, "telegram_inbox_auto_process", True)):
                return f"Saved to Telegram inbox queue ({intake_id})."
            processed = manager.process_pending(max_items=1)
            items = list(processed.get("items") or [])
            if not items:
                return f"Saved to Telegram inbox queue ({intake_id})."
            item = items[0]
            summary = str(item.get("summary") or "").strip()
            if len(summary) > 180:
                summary = summary[:177] + "..."
            return f"Saved and processed Telegram item ({intake_id}). {summary}"
        except Exception as exc:
            logger.warning("Telegram inbox ingest failed: %s", exc)
            return ""

    def _maybe_store_text_inbox_item(self, update, text: str) -> None:
        message = getattr(update, "effective_message", None)
        if not message:
            return
        low = str(text or "").lower()
        is_forwarded = bool(
            getattr(message, "forward_origin", None)
            or getattr(message, "forward_date", None)
            or getattr(message, "forward_from", None)
            or getattr(message, "forward_from_chat", None)
        )
        has_link = "http://" in low or "https://" in low or "www." in low
        if not (is_forwarded or has_link):
            return
        # Text intake is background-only to keep chat flow snappy.
        self._ingest_telegram_inbox_item(update, kind="text", message_text=text)

    def _build_config(self) -> Optional[TelegramConfig]:
        enabled = bool(getattr(self.config, "telegram_enabled", False))
        token = str(getattr(self.config, "telegram_bot_token", "") or "").strip()
        allowed_user_id = int(getattr(self.config, "telegram_allowed_user_id", 0) or 0)
        # Allow starting if token exists, even if allowed_user_id is 0 (will auto-register)
        if not enabled or not token:
            return None
        return TelegramConfig(
            enabled=enabled,
            token=token,
            allowed_user_id=allowed_user_id,
            allow_orchestrator_approvals=bool(
                getattr(self.config, "telegram_allow_orchestrator_approvals", True)
            ),
            allow_code_approvals=bool(getattr(self.config, "telegram_allow_code_approvals", False)),
            max_message_length=int(getattr(self.config, "telegram_max_message_length", 3000)),
        )

    def _build_agent_context(self, update) -> Dict[str, Any]:
        user_id = int(getattr(update.effective_user, "id", 0) or 0)
        from chintu_backend.agents.agent_directory import get_agent_directory
        from .policy import ChannelPolicyManager

        policy = ChannelPolicyManager()
        agent_key, agent_role = policy.get_agent_profile(
            "telegram",
            user_id,
            default_role=getattr(self.config, "agent_default_role", "primary"),
        )
        directory = get_agent_directory()
        runtime = directory.get_or_create(agent_key, role=agent_role)
        return directory.build_context(
            runtime,
            agent_key,
            channel="telegram",
            user_id=str(user_id),
        )

    def _orchestrator_signing_secret(self) -> str:
        explicit = str(getattr(self.config, "telegram_approval_signing_secret", "") or "").strip()
        if explicit:
            return explicit
        return str(getattr(self.config, "telegram_bot_token", "") or "").strip()

    def _build_owner_gate_signature(self, user_id: str, exp_ts: int) -> str:
        secret = self._orchestrator_signing_secret()
        if not secret:
            return ""
        message = f"uid:{user_id}|exp:{int(exp_ts)}"
        return hmac.new(secret.encode("utf-8", errors="ignore"), message.encode("utf-8"), hashlib.sha256).hexdigest()[:16]

    def _build_mini_app_url(self, update) -> str:
        base = str(getattr(self.config, "telegram_mini_app_url", "") or "").strip()
        if not base:
            return ""
        user_id = str(getattr(getattr(update, "effective_user", None), "id", "") or "").strip()
        if not user_id:
            return base
        ttl_s = int(getattr(self.config, "telegram_mini_app_token_ttl_seconds", 900) or 900)
        exp_ts = int(time.time()) + max(60, ttl_s)
        sig = self._build_owner_gate_signature(user_id, exp_ts)
        if not sig:
            return base

        parsed = urlparse(base)
        q = dict(parse_qsl(parsed.query, keep_blank_values=True))
        q["uid"] = user_id
        q["exp"] = str(exp_ts)
        q["sig"] = sig
        gateway_token = str(getattr(self.config, "gateway_auth_token", "") or "").strip()
        if gateway_token and "token" not in q:
            q["token"] = gateway_token
        return urlunparse(parsed._replace(query=urlencode(q)))

    def _build_orchestrator_callback_data(self, *, step_id: str, approve: bool) -> str:
        action = "approve" if approve else "reject"
        secret = self._orchestrator_signing_secret()
        if not secret:
            return f"orch:{action}:{step_id}"
        action_short = "a" if approve else "r"
        payload = f"{action}:{step_id}".encode("utf-8", errors="ignore")
        sig = hmac.new(
            secret.encode("utf-8", errors="ignore"),
            payload,
            hashlib.sha256,
        ).hexdigest()[:12]
        return f"orchv1:{action_short}:{step_id}:{sig}"

    def _parse_orchestrator_callback_data(self, data: str) -> Optional[Tuple[str, bool, str]]:
        raw = str(data or "").strip()
        require_signed = bool(getattr(self.config, "telegram_require_signed_approvals", True))
        secret = self._orchestrator_signing_secret()

        if raw.startswith("orchv1:"):
            parts = raw.split(":")
            if len(parts) != 4:
                return "", False, "Invalid approval payload."
            _, action_short, step_id, sig = parts
            if action_short not in {"a", "r"}:
                return "", False, "Invalid approval action."
            if not step_id:
                return "", False, "Missing approval step id."
            if not secret:
                return "", False, "Approval signing key is not configured."
            approve = action_short == "a"
            action = "approve" if approve else "reject"
            expected = hmac.new(
                secret.encode("utf-8", errors="ignore"),
                f"{action}:{step_id}".encode("utf-8", errors="ignore"),
                hashlib.sha256,
            ).hexdigest()[:12]
            if not hmac.compare_digest(expected, str(sig or "")):
                return "", False, "Approval payload signature check failed."
            return step_id, approve, ""

        if raw.startswith("orch:approve:"):
            if require_signed:
                return "", False, "Unsigned approval payloads are disabled."
            return raw.split(":", 2)[-1], True, ""
        if raw.startswith("orch:reject:"):
            if require_signed:
                return "", False, "Unsigned approval payloads are disabled."
            return raw.split(":", 2)[-1], False, ""
        return None

    def _is_allowed(self, update) -> bool:
        tg = self._tg
        if not tg:
            return False
        user = getattr(update, "effective_user", None)
        if not user:
            return False

        # Channel policy allowlist/pairing
        from .policy import ChannelPolicyManager

        policy = ChannelPolicyManager()
        user_id = int(user.id)
        if getattr(self.config, "telegram_dm_policy", "pairing") == "open":
            return True
        if policy.is_allowed("telegram", user_id):
            return True

        # If allowed_user_id is 0, auto-register the first user who messages
        if tg.allowed_user_id == 0:
            if getattr(self.config, "channel_pairing_enabled", False):
                code = policy.request_pairing_code("telegram", user_id)
                self._notify_pairing(update, code)
                return False
            logger.info(f"Auto-registering Telegram user: {user_id}")
            tg.allowed_user_id = user_id
            policy.add_allowed("telegram", user_id)
            self._persist_allowed_user(user_id)
            return True
        
        if int(user.id) != int(tg.allowed_user_id):
            if getattr(self.config, "channel_pairing_enabled", False):
                code = policy.request_pairing_code("telegram", user_id)
                self._notify_pairing(update, code)
            logger.warning("Telegram access denied for user_id=%s", getattr(user, "id", None))
            return False
        return True

    def _persist_allowed_user(self, user_id: int) -> None:
        try:
            from pathlib import Path
            env_path = Path.cwd() / ".env"
            if env_path.exists():
                content = env_path.read_text()
                if "TELEGRAM_ALLOWED_USER_ID" not in content:
                    with open(env_path, "a") as f:
                        f.write(f"\nTELEGRAM_ALLOWED_USER_ID={user_id}\n")
                    logger.info(f"Saved Telegram user ID to .env: {user_id}")
        except Exception as exc:
            logger.warning(f"Could not save user ID to .env: {exc}")

    def _notify_pairing(self, update, code: str) -> None:
        prompt = (
            "You're not paired yet. Use this code to pair:\n"
            f"{code}\n\nReply with `/pair {code}` to approve."
        )
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self._safe_reply(update, prompt))
        except Exception:
            pass

    async def _handle_pairing(self, update, text: str) -> None:
        from .policy import ChannelPolicyManager

        parts = text.strip().split()
        if len(parts) < 2:
            await self._safe_reply(update, "Usage: /pair <code>")
            return
        code = parts[1].strip()
        policy = ChannelPolicyManager()
        user_id = policy.approve_code("telegram", code)
        if user_id is None:
            await self._safe_reply(update, "Invalid or expired pairing code.")
            return
        await self._safe_reply(update, "Paired successfully. You can now send commands.")

    async def _safe_reply(self, update, text: str) -> None:
        msg = (text or "").strip() or "Done."
        msg = self._trim(msg, self._tg.max_message_length if self._tg else 3000)
        try:
            await update.effective_message.reply_text(msg)
        except Exception:
            pass

    @staticmethod
    def _trim(text: str, max_len: int) -> str:
        if len(text) <= max_len:
            return text
        return text[: max(0, max_len - 50)] + "\n\n[truncated]"

    # ------------------------------------------------------------------
    # Voice Notes (v6.0 Enhancement)
    # ------------------------------------------------------------------
    def _should_send_voice(self, text: str) -> bool:
        """Check if we should send a voice note for this response."""
        # Voice notes disabled - just send text messages
        return False

    async def _send_voice_note(self, chat_id: int, text: str) -> None:
        """Convert text to speech and send as voice note using Edge TTS."""
        import tempfile
        import os
        
        try:
            import edge_tts
        except ImportError:
            logger.debug("edge-tts not available for voice notes")
            return
            
        # Clean text for speech
        clean_text = text.replace("*", "").replace("_", "").replace("`", "")
        clean_text = clean_text[:450]  # Limit voice length
        
        voice = str(getattr(self.config, "telegram_voice", "en-US-AriaNeural"))
        
        try:
            communicate = edge_tts.Communicate(clean_text, voice)
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                temp_path = f.name
                
            await communicate.save(temp_path)
            
            if self._app and os.path.exists(temp_path):
                with open(temp_path, "rb") as audio_file:
                    await self._app.bot.send_voice(chat_id, audio_file)
                os.unlink(temp_path)
                logger.debug("Voice note sent to Telegram")
        except Exception as exc:
            logger.debug("Voice note failed: %s", exc)

    async def send_morning_briefing(self) -> None:
        """Push morning briefing to user's phone."""
        tg = self._tg
        if not tg or not self._app:
            return
            
        try:
            from datetime import datetime
            import calendar
            
            now = datetime.now()
            day_name = calendar.day_name[now.weekday()]
            date_str = now.strftime("%B %d, %Y")
            time_str = now.strftime("%I:%M %p")
            
            # Build briefing
            briefing_parts = [
                f"â˜€ï¸ Good morning! It's {day_name}, {date_str}.",
                f"Current time: {time_str}",
            ]
            
            # Add tasks due today
            try:
                from chintu_backend.tasks.task_manager import get_task_manager
                tm = get_task_manager()
                due_today = tm.get_tasks_due_today() if tm else []
                if due_today:
                    briefing_parts.append(f"\nðŸ“‹ Tasks due today: {len(due_today)}")
                    for task in due_today[:3]:
                        briefing_parts.append(f"  â€¢ {task.title}")
            except Exception:
                pass
            
            briefing = "\n".join(briefing_parts)
            
            # Send text briefing
            await self._app.bot.send_message(chat_id=tg.allowed_user_id, text=briefing)
            
            # Send voice briefing
            await self._send_voice_note(tg.allowed_user_id, briefing)
            logger.info("Morning briefing sent via Telegram")
            
        except Exception as exc:
            logger.warning("Morning briefing failed: %s", exc)

    async def request_credential(self, service: str, username: str) -> None:
        """Request credential approval via Telegram for Identity Vault."""
        tg = self._tg
        if not tg or not self._app or not self._deps:
            return
            
        InlineKeyboardButton = self._deps["InlineKeyboardButton"]
        InlineKeyboardMarkup = self._deps["InlineKeyboardMarkup"]
        
        text = f"ðŸ” Chintu needs credentials for:\n**{service}** / {username}\n\nReply with 'approve' to use stored password, or send the new password."
        
        reply_markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("âœ… Use Stored", callback_data=f"cred:approve:{service}:{username}"),
                InlineKeyboardButton("âŒ Cancel", callback_data="cred:cancel"),
            ]
        ])
        
        try:
            await self._app.bot.send_message(
                chat_id=tg.allowed_user_id,
                text=text,
                reply_markup=reply_markup,
            )
        except Exception as exc:
            logger.warning("Credential request failed: %s", exc)


_gateway: Optional[TelegramGateway] = None


def get_telegram_gateway(command_handler=None) -> TelegramGateway:
    """Get or create the global Telegram gateway."""
    global _gateway
    if _gateway is None:
        if command_handler is None:
            raise ValueError("command_handler is required to initialize TelegramGateway")
        _gateway = TelegramGateway(command_handler=command_handler)
    return _gateway

