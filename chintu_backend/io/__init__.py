"""External IO gateways (Telegram, etc.)."""

"""Backward-compatible re-exports for channel gateways."""

from ..channels.telegram import TelegramGateway, get_telegram_gateway
try:
    from ..channels.whatsapp import WhatsAppGateway
except Exception:  # Optional dependency (fastapi) may be missing
    WhatsAppGateway = None  # type: ignore[assignment]

__all__ = ["TelegramGateway", "get_telegram_gateway", "WhatsAppGateway"]
