"""Telegram gateway for headless control and push notifications."""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from chintu_backend.core.config import get_config
from chintu_backend.core.events import Event, EventType, get_event_bus
from chintu_backend.core.state import get_state_manager

logger = logging.getLogger(__name__)


def _import_telegram():
    """Import telegram dependencies lazily to avoid hard failures."""
    try:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
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
        self._app.add_handler(CallbackQueryHandler(self._on_callback))
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_text))

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
        try:
            user_id = int(getattr(update.effective_user, "id", 0) or 0)
            response = self.command_handler.handle(
                text,
                source="telegram",
                context={"channel": "telegram", "user_id": user_id},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Telegram command failed: %s", exc)
            response = f"Command failed: {exc}"
        await self._safe_reply(update, response)
        
        # Send voice note if enabled and response is not too long
        if self._should_send_voice(response):
            await self._send_voice_note(update.effective_chat.id, response)

    async def _on_callback(self, update, _context) -> None:
        if not self._is_allowed(update):
            return
        query = update.callback_query
        if not query:
            return
        data = query.data or ""
        await query.answer()
        if data.startswith("orch:approve:"):
            step_id = data.split(":", 2)[-1]
            await self._handle_orchestrator_approval(step_id, approve=True, update=update)
            return
        if data.startswith("orch:reject:"):
            step_id = data.split(":", 2)[-1]
            await self._handle_orchestrator_approval(step_id, approve=False, update=update)
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
            "critical": "🛑",
            "high": "⚠️",
            "medium": "ℹ️",
            "low": "✅",
            "info": "ℹ️",
        }.get(severity, "ℹ️")

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
                            InlineKeyboardButton("✅ Approve", callback_data=f"orch:approve:{step_id}"),
                            InlineKeyboardButton("❌ Reject", callback_data=f"orch:reject:{step_id}"),
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

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
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
                f"☀️ Good morning! It's {day_name}, {date_str}.",
                f"Current time: {time_str}",
            ]
            
            # Add tasks due today
            try:
                from chintu_backend.tasks.task_manager import get_task_manager
                tm = get_task_manager()
                due_today = tm.get_tasks_due_today() if tm else []
                if due_today:
                    briefing_parts.append(f"\n📋 Tasks due today: {len(due_today)}")
                    for task in due_today[:3]:
                        briefing_parts.append(f"  • {task.title}")
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
        
        text = f"🔐 Chintu needs credentials for:\n**{service}** / {username}\n\nReply with 'approve' to use stored password, or send the new password."
        
        reply_markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Use Stored", callback_data=f"cred:approve:{service}:{username}"),
                InlineKeyboardButton("❌ Cancel", callback_data="cred:cancel"),
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
