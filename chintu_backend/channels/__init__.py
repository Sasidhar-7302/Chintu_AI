"""Channel policy, gateways, and routing helpers."""

from .policy import ChannelPolicyManager
from .telegram import TelegramGateway, get_telegram_gateway
from .slack import SlackGateway
from .discord import DiscordGateway
from .relay import RelayGateway

try:
    from .whatsapp import WhatsAppGateway
except Exception:  # Optional dependency (fastapi) may be missing
    WhatsAppGateway = None  # type: ignore[assignment]

__all__ = [
    "ChannelPolicyManager",
    "TelegramGateway",
    "get_telegram_gateway",
    "WhatsAppGateway",
    "SlackGateway",
    "DiscordGateway",
    "RelayGateway",
]
