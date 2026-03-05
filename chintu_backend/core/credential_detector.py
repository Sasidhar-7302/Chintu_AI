"""Credential and API token detector.

Detects when user provides API keys, tokens, or other credentials in conversation.
This enables automatic configuration of services like Telegram without manual setup.
"""

import re
import logging
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from enum import Enum

logger = logging.getLogger(__name__)


class CredentialType(Enum):
    """Types of credentials that can be detected."""
    TELEGRAM_BOT_TOKEN = "telegram_bot_token"
    GROQ_API_KEY = "groq_api_key"
    GEMINI_API_KEY = "gemini_api_key"
    NVIDIA_API_KEY = "nvidia_api_key"
    OPENAI_API_KEY = "openai_api_key"
    GITHUB_TOKEN = "github_token"
    NOTION_TOKEN = "notion_token"
    HASS_URL = "hass_url"
    HASS_TOKEN = "hass_token"
    GOOGLE_CLIENT_ID = "google_client_id"
    GOOGLE_CLIENT_SECRET = "google_client_secret"
    GENERIC_API_KEY = "generic_api_key"


@dataclass
class DetectedCredential:
    """A detected credential from user input."""
    credential_type: CredentialType
    value: str
    service_name: str
    config_key: str  # The key name in config.yaml
    description: str


class CredentialDetector:
    """Detect credentials and API tokens in user messages."""
    
    # Patterns for different credential types
    PATTERNS = {
        # Telegram bot tokens: <bot_id>:<secret> (e.g., 1234567890:ABCdefGHIjklMNOpqrsTUVwxyz)
        CredentialType.TELEGRAM_BOT_TOKEN: {
            "pattern": r'\b(\d{8,12}:[A-Za-z0-9_-]{35,})\b',
            "service": "Telegram",
            "config_key": "telegram_bot_token",
            "description": "Telegram Bot API token",
        },
        # Groq API keys: gsk_xxxxxx
        CredentialType.GROQ_API_KEY: {
            "pattern": r'\b(gsk_[A-Za-z0-9]{40,})\b',
            "service": "Groq",
            "config_key": "groq_api_key",
            "description": "Groq API key",
        },
        # Gemini/Google API keys: AIzaSy... (39 chars)
        CredentialType.GEMINI_API_KEY: {
            "pattern": r'\b(AIzaSy[A-Za-z0-9_-]{33})\b',
            "service": "Gemini",
            "config_key": "gemini_api_key",
            "description": "Google/Gemini API key",
        },
        # NVIDIA API keys: nvapi-xxxx
        CredentialType.NVIDIA_API_KEY: {
            "pattern": r'\b(nvapi-[A-Za-z0-9_-]{20,})\b',
            "service": "NVIDIA",
            "config_key": "nvidia_api_key",
            "description": "NVIDIA API key (NIM)",
        },
        # OpenAI API keys: sk-xxxxxx
        CredentialType.OPENAI_API_KEY: {
            "pattern": r'\b(sk-[A-Za-z0-9]{48,})\b',
            "service": "OpenAI",
            "config_key": "openai_api_key",
            "description": "OpenAI API key",
        },
        # GitHub tokens (classic or fine-grained)
        CredentialType.GITHUB_TOKEN: {
            "pattern": r'\b(ghp_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{20,})\b',
            "service": "GitHub",
            "config_key": "github_token",
            "description": "GitHub token",
        },
    }
    
    # Context keywords that suggest the user is providing a credential
    CONTEXT_KEYWORDS = {
        CredentialType.TELEGRAM_BOT_TOKEN: [
            "telegram", "bot", "token", "api", "http api", "botfather",
            "t.me", "connect telegram", "setup telegram"
        ],
        CredentialType.GROQ_API_KEY: ["groq", "llm", "api key"],
        CredentialType.GEMINI_API_KEY: ["gemini", "google", "bard", "api key"],
        CredentialType.NVIDIA_API_KEY: ["nvidia", "nim", "api key", "nvapi"],
        CredentialType.OPENAI_API_KEY: ["openai", "chatgpt", "gpt", "api key"],
        CredentialType.GITHUB_TOKEN: ["github", "gh", "token", "api key"],
    }

    # Explicit env-key assignments we can safely capture from user text
    ENV_KEY_MAP = {
        "GITHUB_TOKEN": (CredentialType.GITHUB_TOKEN, "GitHub", "github_token", "GitHub token"),
        "NOTION_TOKEN": (CredentialType.NOTION_TOKEN, "Notion", "notion_token", "Notion token"),
        "HASS_URL": (CredentialType.HASS_URL, "Home Assistant", "hass_url", "Home Assistant URL"),
        "HASS_TOKEN": (CredentialType.HASS_TOKEN, "Home Assistant", "hass_token", "Home Assistant token"),
        "GOOGLE_CLIENT_ID": (CredentialType.GOOGLE_CLIENT_ID, "Google", "google_client_id", "Google client ID"),
        "GOOGLE_CLIENT_SECRET": (CredentialType.GOOGLE_CLIENT_SECRET, "Google", "google_client_secret", "Google client secret"),
        "NVIDIA_API_KEY": (CredentialType.NVIDIA_API_KEY, "NVIDIA", "nvidia_api_key", "NVIDIA API key"),
    }
    
    def detect(self, text: str) -> Optional[DetectedCredential]:
        """
        Detect credentials in user text.
        
        Returns the first detected credential, or None if no credentials found.
        Priority: specific patterns over generic detection.
        """
        text_lower = text.lower()
        
        # Check each credential type
        for cred_type, config in self.PATTERNS.items():
            pattern = config["pattern"]
            matches = re.findall(pattern, text)
            
            if matches:
                # Found a match! Check for context keywords to boost confidence
                keywords = self.CONTEXT_KEYWORDS.get(cred_type, [])
                has_context = any(kw in text_lower for kw in keywords)
                
                # For Telegram tokens, always accept (pattern is specific enough)
                # For others, prefer context keywords
                if cred_type == CredentialType.TELEGRAM_BOT_TOKEN or has_context:
                    logger.info(f"Detected {cred_type.value}: {matches[0][:10]}...")
                    return DetectedCredential(
                        credential_type=cred_type,
                        value=matches[0],
                        service_name=config["service"],
                        config_key=config["config_key"],
                        description=config["description"],
                    )

        # Detect explicit env assignments (KEY=VALUE)
        env_match = re.findall(r"\b([A-Z0-9_]{4,})\s*=\s*([^\s]+)", text)
        for key, value in env_match:
            if key in self.ENV_KEY_MAP:
                cred_type, service, config_key, description = self.ENV_KEY_MAP[key]
                return DetectedCredential(
                    credential_type=cred_type,
                    value=value,
                    service_name=service,
                    config_key=config_key,
                    description=description,
                )
        
        return None
    
    def detect_all(self, text: str) -> List[DetectedCredential]:
        """Detect all credentials in user text (may return multiple)."""
        results = []
        
        for cred_type, config in self.PATTERNS.items():
            pattern = config["pattern"]
            matches = re.findall(pattern, text)
            
            for match in matches:
                results.append(DetectedCredential(
                    credential_type=cred_type,
                    value=match,
                    service_name=config["service"],
                    config_key=config["config_key"],
                    description=config["description"],
                ))
        
        return results


class ServiceIntent(Enum):
    """Detected service setup intents (when user wants to connect but hasn't provided credentials)."""
    TELEGRAM_SETUP = "telegram_setup"
    GROQ_SETUP = "groq_setup"
    GEMINI_SETUP = "gemini_setup"
    NVIDIA_SETUP = "nvidia_setup"
    OPENAI_SETUP = "openai_setup"
    GITHUB_SETUP = "github_setup"
    NOTION_SETUP = "notion_setup"
    HASS_SETUP = "hass_setup"
    GOOGLE_CALENDAR_SETUP = "google_calendar_setup"
    NONE = "none"


@dataclass
class DetectedServiceIntent:
    """A detected intent to set up a service."""
    intent: ServiceIntent
    service_name: str
    required_credential: str  # Human-readable name of what's needed
    help_text: str  # How to get the credential


class ServiceIntentDetector:
    """Detect when user wants to set up a service but hasn't provided credentials."""
    
    INTENT_PATTERNS = {
        ServiceIntent.TELEGRAM_SETUP: {
            "patterns": [
                # Only trigger for explicit setup requests, NOT status questions
                r"^(?!.*(is|are|working|status|check|test)).*\b(connect|setup|configure|enable|start|link)\b.*\btelegram\b",
                r"^(?!.*(is|are|working|status|check|test)).*\btelegram\b.*\b(connect|setup|configure|enable)\b",
                r"\bset\s*up\s+telegram\b",
                r"\badd\s+.*telegram\s+(token|api)\b",
            ],
            "service_name": "Telegram",
            "required_credential": "bot token from @BotFather",
            "help_text": (
                "To connect Telegram, you need a bot token from @BotFather on Telegram. "
                "Just message /newbot to @BotFather and it'll give you a token. "
                "Then paste it here!"
            ),
        },
        ServiceIntent.GROQ_SETUP: {
            "patterns": [
                r"\b(connect|setup|configure|enable|use)\b.*\bgroq\b",
                r"\bgroq\b.*\b(key|api|setup)\b",
            ],
            "service_name": "Groq",
            "required_credential": "API key from console.groq.com",
            "help_text": "Get your Groq API key from console.groq.com and paste it here.",
        },
        ServiceIntent.GEMINI_SETUP: {
            "patterns": [
                r"\b(connect|setup|configure|enable|use)\b.*\b(gemini|google\s*ai)\b",
                r"\b(gemini|google\s*ai)\b.*\b(key|api|setup)\b",
            ],
            "service_name": "Gemini",
            "required_credential": "API key from aistudio.google.com",
            "help_text": "Get your Gemini API key from aistudio.google.com and paste it here.",
        },
        ServiceIntent.NVIDIA_SETUP: {
            "patterns": [
                r"\b(connect|setup|configure|enable|use)\b.*\b(nvidia|nim)\b",
                r"\b(nvidia|nim)\b.*\b(key|api|setup)\b",
            ],
            "service_name": "NVIDIA",
            "required_credential": "API key from build.nvidia.com",
            "help_text": "Get your NVIDIA API key from build.nvidia.com and paste it here.",
        },
        ServiceIntent.OPENAI_SETUP: {
            "patterns": [
                r"\b(connect|setup|configure|enable|use)\b.*\b(openai|gpt|chatgpt)\b",
                r"\b(openai|chatgpt)\b.*\b(key|api|setup)\b",
            ],
            "service_name": "OpenAI",
            "required_credential": "API key from platform.openai.com",
            "help_text": "Get your OpenAI API key from platform.openai.com and paste it here.",
        },
        ServiceIntent.GITHUB_SETUP: {
            "patterns": [
                r"\b(connect|setup|configure|enable|use)\b.*\bgithub\b",
                r"\bgithub\b.*\b(token|api|setup)\b",
            ],
            "service_name": "GitHub",
            "required_credential": "GitHub token (PAT)",
            "help_text": "Create a GitHub token (PAT) and paste it here. You can also send `GITHUB_TOKEN=...`.",
        },
        ServiceIntent.NOTION_SETUP: {
            "patterns": [
                r"\b(connect|setup|configure|enable|use)\b.*\bnotion\b",
                r"\bnotion\b.*\b(token|api|setup)\b",
            ],
            "service_name": "Notion",
            "required_credential": "Notion integration token",
            "help_text": "Create a Notion integration token and paste it here. You can also send `NOTION_TOKEN=...`.",
        },
        ServiceIntent.HASS_SETUP: {
            "patterns": [
                r"\b(connect|setup|configure|enable|use)\b.*\b(home assistant|hass)\b",
                r"\b(home assistant|hass)\b.*\b(token|api|setup)\b",
            ],
            "service_name": "Home Assistant",
            "required_credential": "HASS_URL and HASS_TOKEN",
            "help_text": "Provide `HASS_URL=...` and `HASS_TOKEN=...` to connect Home Assistant.",
        },
        ServiceIntent.GOOGLE_CALENDAR_SETUP: {
            "patterns": [
                r"\b(connect|setup|configure|enable|use)\b.*\b(google calendar|gcal)\b",
                r"\b(google calendar|gcal)\b.*\b(client id|secret|setup|oauth)\b",
            ],
            "service_name": "Google Calendar",
            "required_credential": "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET",
            "help_text": "Provide `GOOGLE_CLIENT_ID=...` and `GOOGLE_CLIENT_SECRET=...` to use gcalcli.",
        },
    }
    
    def detect(self, text: str) -> Optional[DetectedServiceIntent]:
        """Detect service setup intent in user text."""
        text_lower = text.lower()
        
        for intent, config in self.INTENT_PATTERNS.items():
            for pattern in config["patterns"]:
                if re.search(pattern, text_lower, re.IGNORECASE):
                    logger.info(f"Detected service intent: {intent.value}")
                    return DetectedServiceIntent(
                        intent=intent,
                        service_name=config["service_name"],
                        required_credential=config["required_credential"],
                        help_text=config["help_text"],
                    )
        
        return None


# Singleton instances
_detector: Optional[CredentialDetector] = None
_intent_detector: Optional[ServiceIntentDetector] = None


def get_credential_detector() -> CredentialDetector:
    """Get the singleton credential detector instance."""
    global _detector
    if _detector is None:
        _detector = CredentialDetector()
    return _detector


def get_service_intent_detector() -> ServiceIntentDetector:
    """Get the singleton service intent detector instance."""
    global _intent_detector
    if _intent_detector is None:
        _intent_detector = ServiceIntentDetector()
    return _intent_detector
