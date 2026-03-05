"""Persistent finance watchlist storage and brief logging."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional

from chintu_backend.core.config import get_config

logger = logging.getLogger(__name__)


DEFAULT_PROFILE = {
    "risk_profile": "moderate",
    "time_horizon": "6-12 months",
    "strategy_style": "long-term",
    "notes": "",
}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _normalize_symbol(value: str) -> str:
    text = (value or "").strip()
    if text.startswith("$"):
        text = text[1:]
    return text.upper()


NAME_MAP = {
    "bitcoin": "BTC",
    "ethereum": "ETH",
    "solana": "SOL",
    "dogecoin": "DOGE",
    "ripple": "XRP",
    "cardano": "ADA",
    "polkadot": "DOT",
    "chainlink": "LINK",
    "litecoin": "LTC",
    "avalanche": "AVAX",
}


@dataclass
class WatchItem:
    symbol: str
    label: str
    asset_type: str = "crypto"

    def to_dict(self) -> Dict[str, str]:
        return {"symbol": self.symbol, "label": self.label, "asset_type": self.asset_type}


class WatchlistStore:
    """Persist a personal watchlist and analysis briefs."""

    def __init__(self, path: Optional[Path] = None, brief_dir: Optional[Path] = None) -> None:
        config = get_config()
        self.path = Path(path or config.finance_watchlist_path)
        self.brief_dir = Path(brief_dir or config.finance_brief_dir)
        self._lock = Lock()
        self._data: Dict[str, object] = {}
        self._load()

    def _load(self) -> None:
        with self._lock:
            if self.path.exists():
                try:
                    raw = json.loads(self.path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        self._data = raw
                except Exception as exc:
                    logger.warning("Failed to load finance watchlist: %s", exc)
            if not self._data:
                self._data = {
                    "items": [],
                    "profile": dict(DEFAULT_PROFILE),
                    "last_brief_at": None,
                    "candidates": [],
                    "candidate_log": [],
                }
            profile = self._data.get("profile")
            if not isinstance(profile, dict):
                self._data["profile"] = dict(DEFAULT_PROFILE)
            else:
                merged = dict(DEFAULT_PROFILE)
                merged.update(profile)
                self._data["profile"] = merged
            if "candidates" not in self._data:
                self._data["candidates"] = []
            if "candidate_log" not in self._data:
                self._data["candidate_log"] = []

    def _save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    def list_items(self) -> List[WatchItem]:
        items = []
        for raw in (self._data.get("items") or []):
            if not isinstance(raw, dict):
                continue
            symbol = _normalize_symbol(str(raw.get("symbol") or ""))
            if not symbol:
                continue
            items.append(
                WatchItem(
                    symbol=symbol,
                    label=str(raw.get("label") or symbol),
                    asset_type=str(raw.get("asset_type") or "crypto"),
                )
            )
        return items

    def list_candidates(self) -> List[Dict[str, str]]:
        candidates = []
        for raw in (self._data.get("candidates") or []):
            if not isinstance(raw, dict):
                continue
            symbol = _normalize_symbol(str(raw.get("symbol") or ""))
            if not symbol:
                continue
            item = dict(raw)
            item["symbol"] = symbol
            candidates.append(item)
        return candidates

    def add_items(self, values: List[str], asset_type: str = "crypto") -> List[WatchItem]:
        added: List[WatchItem] = []
        existing = {item.symbol: item for item in self.list_items()}
        for raw in values:
            normalized = _normalize_symbol(raw)
            if not normalized:
                continue
            label = NAME_MAP.get(raw.lower(), normalized)
            symbol = _normalize_symbol(label)
            if symbol in existing:
                continue
            item = WatchItem(symbol=symbol, label=label, asset_type=asset_type)
            existing[symbol] = item
            added.append(item)
        if added:
            self._data["items"] = [item.to_dict() for item in existing.values()]
            self._save()
        return added

    def add_candidates(
        self,
        candidates: List[Dict[str, str]] | List[str],
        *,
        source: str,
        max_per_day: int,
    ) -> List[Dict[str, str]]:
        added: List[Dict[str, str]] = []
        today = datetime.now().strftime("%Y-%m-%d")
        current_count = 0
        for entry in self._data.get("candidate_log") or []:
            if isinstance(entry, dict) and entry.get("date") == today:
                current_count += 1
        remaining = max(0, int(max_per_day) - current_count)
        if remaining <= 0:
            return []

        existing = {c.get("symbol") for c in self.list_candidates()}
        for raw in candidates:
            if remaining <= 0:
                break
            if isinstance(raw, str):
                symbol = _normalize_symbol(raw)
                label = NAME_MAP.get(raw.lower(), symbol)
                region = ""
                rationale = ""
            elif isinstance(raw, dict):
                symbol = _normalize_symbol(str(raw.get("symbol") or raw.get("ticker") or ""))
                label = str(raw.get("label") or raw.get("name") or symbol)
                region = str(raw.get("region") or "")
                rationale = str(raw.get("rationale") or raw.get("reason") or "")
            else:
                continue
            if not symbol or symbol in existing:
                continue
            entry = {
                "symbol": symbol,
                "label": label or symbol,
                "region": region,
                "rationale": rationale,
                "source": source,
                "added_at": _now_iso(),
            }
            added.append(entry)
            existing.add(symbol)
            remaining -= 1
            self._data.setdefault("candidate_log", []).append(
                {"symbol": symbol, "date": today, "source": source}
            )

        if added:
            candidates_list = self._data.get("candidates") or []
            candidates_list.extend(added)
            self._data["candidates"] = candidates_list
            self._save()
        return added

    def promote_candidate(self, symbol: str) -> Optional[WatchItem]:
        symbol = _normalize_symbol(symbol)
        if not symbol:
            return None
        candidates = self.list_candidates()
        candidate = next((c for c in candidates if c.get("symbol") == symbol), None)
        if not candidate:
            return None
        self._data["candidates"] = [c for c in candidates if c.get("symbol") != symbol]
        self._save()
        added = self.add_items([symbol], asset_type="crypto")
        return added[0] if added else None

    def remove_items(self, values: List[str]) -> List[str]:
        remove_symbols = {_normalize_symbol(v) for v in values if _normalize_symbol(v)}
        if not remove_symbols:
            return []
        kept = []
        removed = []
        for item in self.list_items():
            if item.symbol in remove_symbols:
                removed.append(item.symbol)
            else:
                kept.append(item)
        if removed:
            self._data["items"] = [item.to_dict() for item in kept]
            self._save()
        return removed

    def get_profile(self) -> Dict[str, str]:
        profile = self._data.get("profile")
        if not isinstance(profile, dict):
            profile = dict(DEFAULT_PROFILE)
            self._data["profile"] = profile
        return {k: str(v) for k, v in profile.items()}

    def update_profile(
        self,
        *,
        risk_profile: Optional[str] = None,
        time_horizon: Optional[str] = None,
        strategy_style: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, str]:
        profile = self.get_profile()
        if risk_profile:
            profile["risk_profile"] = risk_profile
        if time_horizon:
            profile["time_horizon"] = time_horizon
        if strategy_style:
            profile["strategy_style"] = strategy_style
        if notes is not None:
            profile["notes"] = notes
        self._data["profile"] = profile
        self._save()
        return profile

    def record_brief(self, title: str, content: str, sources: List[Dict[str, str]]) -> Path:
        self.brief_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        path = self.brief_dir / f"{stamp}_finance_brief.md"
        lines = [
            f"# {title}",
            f"- Generated: {_now_iso()}",
            "",
            content.strip(),
            "",
            "## Sources",
        ]
        if sources:
            for idx, src in enumerate(sources, start=1):
                name = src.get("title") or f"Source {idx}"
                url = src.get("url") or ""
                lines.append(f"{idx}. {name} - {url}")
        else:
            lines.append("No external sources captured.")
        path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
        self._data["last_brief_at"] = _now_iso()
        self._save()
        return path


_store: Optional[WatchlistStore] = None


def get_watchlist_store() -> WatchlistStore:
    global _store
    if _store is None:
        _store = WatchlistStore()
    return _store
