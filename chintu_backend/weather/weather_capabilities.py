"""Weather capabilities for Chintu AI Assistant (Open-Meteo)."""

from __future__ import annotations

import logging
from typing import Dict, Any, Optional

import requests

from chintu_backend.core.capabilities import ActionResult, Capability, CapabilityType, get_registry
from chintu_backend.brain.memory.preferences import get_preference_manager

logger = logging.getLogger(__name__)


def _resolve_location(text: str) -> Optional[str]:
    """Extract a location from the text or fallback to preferences."""
    text_lower = (text or "").lower()
    for prefix in ["weather in ", "temperature in ", "forecast for ", "forecast in "]:
        if prefix in text_lower:
            idx = text_lower.find(prefix) + len(prefix)
            loc = text[idx:].strip().strip(".?!")
            if loc:
                return loc
    # Fallback: use saved preference
    prefs = get_preference_manager().preferences
    if prefs.location:
        return prefs.location
    return None


def _geocode(location: str) -> Optional[Dict[str, Any]]:
    url = "https://geocoding-api.open-meteo.com/v1/search"
    resp = requests.get(url, params={"name": location, "count": 1, "language": "en", "format": "json"}, timeout=10)
    if resp.status_code != 200:
        return None
    data = resp.json()
    results = data.get("results") or []
    if not results:
        return None
    return results[0]


def _fetch_weather(lat: float, lon: float) -> Optional[Dict[str, Any]]:
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": "auto",
    }
    resp = requests.get(url, params=params, timeout=10)
    if resp.status_code != 200:
        return None
    return resp.json()


def handle_weather(text: str, _context: Dict[str, Any]) -> ActionResult:
    location = _resolve_location(text)
    if not location:
        return ActionResult.fail("Which location should I check the weather for?", "weather")

    geo = _geocode(location)
    if not geo:
        return ActionResult.fail(f"I couldn't find weather data for '{location}'.", "weather")

    data = _fetch_weather(float(geo["latitude"]), float(geo["longitude"]))
    if not data:
        return ActionResult.fail("Weather service is unavailable right now.", "weather")

    current = data.get("current", {}) or {}
    daily = data.get("daily", {}) or {}
    temp = current.get("temperature_2m")
    wind = current.get("wind_speed_10m")
    tmax = (daily.get("temperature_2m_max") or [None])[0]
    tmin = (daily.get("temperature_2m_min") or [None])[0]
    rain = (daily.get("precipitation_probability_max") or [None])[0]

    parts = [f"Weather for {geo.get('name')}, {geo.get('country_code', '')}:"]
    if temp is not None:
        parts.append(f"- Current: {temp} C")
    if tmin is not None and tmax is not None:
        parts.append(f"- Today: {tmin} C to {tmax} C")
    if wind is not None:
        parts.append(f"- Wind: {wind} km/h")
    if rain is not None:
        parts.append(f"- Precipitation chance: {rain}%")

    return ActionResult.ok("\n".join(parts), {"location": geo.get("name")}, "weather")


def register_weather_capabilities() -> None:
    registry = get_registry()
    registry.register(Capability(
        name="weather",
        triggers=["weather", "temperature", "forecast"],
        handler=handle_weather,
        requires_confirmation=False,
        description="get the weather for a location",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=["Weather in New York", "Temperature in Hyderabad"],
    ))

    logger.info("Registered weather capabilities")
