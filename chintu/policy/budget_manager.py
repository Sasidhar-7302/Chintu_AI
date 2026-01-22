"""
Rate limit budget manager for Chintu AI Assistant.

Tracks API usage across providers and enforces free-tier limits.
"""

import time
import threading
import hashlib
import logging
from dataclasses import dataclass
from typing import Dict, Optional, Tuple
from collections import deque
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class ProviderLimits:
    """Rate limits for an API provider."""

    requests_per_minute: int
    requests_per_day: int
    tokens_per_minute: int = 0      # 0 means unlimited/not tracked
    tokens_per_day: int = 0         # 0 means unlimited/not tracked
    cooldown_minutes: int = 1       # Cooldown after hitting limit


@dataclass
class UsageRecord:
    """A single usage record."""

    timestamp: float
    tokens: int = 0
    success: bool = True


@dataclass
class CachedResponse:
    """A cached API response."""

    response: str
    timestamp: float
    ttl_seconds: int
    hit_count: int = 0


class RateLimitBudgetManager:
    """
    Manages API budgets and auto-switches to cheaper/local options.

    Free tier limits are conservative to avoid hitting actual limits:
    - Groq: ~30 req/min, ~1000 req/day on free tier
    - Gemini: ~15 req/min, ~1500 req/day on free tier
    - Local: Unlimited but slow
    """

    DEFAULT_LIMITS: Dict[str, ProviderLimits] = {
        "groq": ProviderLimits(
            requests_per_minute=25,
            requests_per_day=800,
            tokens_per_minute=5000,
            tokens_per_day=80000,
        ),
        "gemini": ProviderLimits(
            requests_per_minute=12,
            requests_per_day=1200,
            tokens_per_minute=0,
            tokens_per_day=0,
        ),
        "local": ProviderLimits(
            requests_per_minute=999,
            requests_per_day=99999,
            tokens_per_minute=0,
            tokens_per_day=0,
        ),
    }

    CACHEABLE_PATTERNS = [
        "what can you do",
        "help",
        "status",
        "your capabilities",
        "how do i use",
    ]

    def __init__(self, limits: Optional[Dict[str, ProviderLimits]] = None):
        self._limits = limits or self.DEFAULT_LIMITS.copy()
        self._usage: Dict[str, deque] = {
            provider: deque(maxlen=10000)
            for provider in self._limits
        }
        self._daily_counts: Dict[str, int] = {provider: 0 for provider in self._limits}
        self._daily_success: Dict[str, int] = {provider: 0 for provider in self._limits}
        self._daily_reset_time: float = self._next_midnight()
        self._cache: Dict[str, CachedResponse] = {}
        self._lock = threading.Lock()
        self._cooldowns: Dict[str, float] = {}

        logger.info("RateLimitBudgetManager initialized with providers: %s", list(self._limits.keys()))

    def _next_midnight(self) -> float:
        now = datetime.now()
        tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        return tomorrow.timestamp()

    def _check_daily_reset(self):
        now = time.time()
        if now >= self._daily_reset_time:
            with self._lock:
                for provider in self._daily_counts:
                    self._daily_counts[provider] = 0
                    self._daily_success[provider] = 0
                self._daily_reset_time = self._next_midnight()
                logger.info("Daily rate limits reset")

    def _get_minute_usage(self, provider: str) -> Tuple[int, int]:
        now = time.time()
        minute_ago = now - 60

        requests = 0
        tokens = 0

        with self._lock:
            for record in self._usage.get(provider, []):
                if record.timestamp >= minute_ago:
                    requests += 1
                    tokens += record.tokens

        return requests, tokens

    def can_use(self, provider: str) -> bool:
        if provider not in self._limits:
            logger.warning("Unknown provider: %s", provider)
            return False

        if provider in self._cooldowns:
            if time.time() < self._cooldowns[provider]:
                return False
            del self._cooldowns[provider]

        self._check_daily_reset()
        limits = self._limits[provider]

        minute_requests, minute_tokens = self._get_minute_usage(provider)
        if minute_requests >= limits.requests_per_minute:
            logger.debug("%s: minute request limit reached (%s/%s)", provider, minute_requests, limits.requests_per_minute)
            return False

        if limits.tokens_per_minute > 0 and minute_tokens >= limits.tokens_per_minute:
            logger.debug("%s: minute token limit reached (%s/%s)", provider, minute_tokens, limits.tokens_per_minute)
            return False

        with self._lock:
            daily_requests = self._daily_counts.get(provider, 0)

        if daily_requests >= limits.requests_per_day:
            logger.debug("%s: daily limit reached (%s/%s)", provider, daily_requests, limits.requests_per_day)
            return False

        return True

    def record_usage(self, provider: str, tokens: int = 0, success: bool = True):
        if provider not in self._limits:
            return

        record = UsageRecord(
            timestamp=time.time(),
            tokens=tokens,
            success=success,
        )

        with self._lock:
            self._usage[provider].append(record)
            self._daily_counts[provider] = self._daily_counts.get(provider, 0) + 1
            if success:
                self._daily_success[provider] = self._daily_success.get(provider, 0) + 1

        logger.debug("Recorded %s usage: %s tokens, success=%s", provider, tokens, success)

    def set_cooldown(self, provider: str, minutes: Optional[int] = None):
        if provider not in self._limits:
            return

        duration = minutes or self._limits[provider].cooldown_minutes
        self._cooldowns[provider] = time.time() + (duration * 60)
        logger.warning("Set %s minute cooldown for %s", duration, provider)

    def get_best_provider(self, prefer_cloud: bool = True, require_fast: bool = False) -> str:
        if prefer_cloud:
            priority = ["groq", "gemini", "local"]
        else:
            priority = ["local", "groq", "gemini"]

        for provider in priority:
            if require_fast and provider == "local":
                continue
            if self.can_use(provider):
                return provider

        if self.can_use("local"):
            return "local"

        logger.warning("All providers at capacity, defaulting to groq")
        return "groq"

    def get_usage_remaining(self, provider: str) -> Dict:
        if provider not in self._limits:
            return {}

        self._check_daily_reset()
        limits = self._limits[provider]
        minute_requests, minute_tokens = self._get_minute_usage(provider)

        with self._lock:
            daily_requests = self._daily_counts.get(provider, 0)

        return {
            "minute_requests_remaining": max(0, limits.requests_per_minute - minute_requests),
            "minute_tokens_remaining": max(0, limits.tokens_per_minute - minute_tokens) if limits.tokens_per_minute > 0 else "unlimited",
            "daily_requests_remaining": max(0, limits.requests_per_day - daily_requests),
            "daily_tokens_remaining": max(0, limits.tokens_per_day - self._get_daily_tokens(provider)) if limits.tokens_per_day > 0 else "unlimited",
        }

    def _get_daily_tokens(self, provider: str) -> int:
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        tokens = 0
        with self._lock:
            for record in self._usage.get(provider, []):
                if record.timestamp >= today_start:
                    tokens += record.tokens
        return tokens

    def _cache_key(self, query: str) -> str:
        normalized = query.lower().strip()
        return hashlib.md5(normalized.encode()).hexdigest()[:16]

    def is_cacheable(self, query: str) -> bool:
        query_lower = query.lower()
        return any(pattern in query_lower for pattern in self.CACHEABLE_PATTERNS)

    def get_cached(self, query: str) -> Optional[str]:
        key = self._cache_key(query)
        with self._lock:
            cached = self._cache.get(key)
            if not cached:
                return None

            now = time.time()
            if now - cached.timestamp > cached.ttl_seconds:
                del self._cache[key]
                return None

            cached.hit_count += 1
            logger.debug("Cache hit for query (hits: %s)", cached.hit_count)
            return cached.response

    def cache_response(self, query: str, response: str, ttl_seconds: int = 3600):
        key = self._cache_key(query)
        with self._lock:
            self._cache[key] = CachedResponse(
                response=response,
                timestamp=time.time(),
                ttl_seconds=ttl_seconds,
            )
        logger.debug("Cached response for query (TTL: %ss)", ttl_seconds)

    def clear_cache(self):
        with self._lock:
            self._cache.clear()
        logger.info("Response cache cleared")

    def get_cache_stats(self) -> Dict:
        with self._lock:
            total_entries = len(self._cache)
            total_hits = sum(c.hit_count for c in self._cache.values())

        return {
            "entries": total_entries,
            "total_hits": total_hits,
        }

    def get_usage_stats(self) -> Dict:
        self._check_daily_reset()

        stats = {
            "providers": {},
            "cache": self.get_cache_stats(),
            "daily_reset_in_seconds": max(0, int(self._daily_reset_time - time.time())),
        }

        for provider in self._limits:
            minute_requests, minute_tokens = self._get_minute_usage(provider)
            limits = self._limits[provider]

            with self._lock:
                daily = self._daily_counts.get(provider, 0)
                success = self._daily_success.get(provider, 0)

            stats["providers"][provider] = {
                "available": self.can_use(provider),
                "minute_usage": f"{minute_requests}/{limits.requests_per_minute}",
                "daily_usage": f"{daily}/{limits.requests_per_day}",
                "daily_success": success,
                "in_cooldown": provider in self._cooldowns,
            }

        return stats


_budget_manager: Optional[RateLimitBudgetManager] = None


def get_budget_manager() -> RateLimitBudgetManager:
    """Get or create the global budget manager instance."""
    global _budget_manager
    if _budget_manager is None:
        _budget_manager = RateLimitBudgetManager()
    return _budget_manager


def reset_budget_manager():
    """Reset the global budget manager (for testing)."""
    global _budget_manager
    _budget_manager = None
