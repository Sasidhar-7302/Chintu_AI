"""Model/tool catalog updater for Phase 2.5 orchestration."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib import error as urlerror
from urllib import request as urlrequest
from xml.etree import ElementTree

from .config import get_config

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_text(value: Any, max_chars: int = 300) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _strip_namespace(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _first_child_text(node: ElementTree.Element, names: List[str]) -> str:
    wanted = set(names)
    for child in list(node):
        if _strip_namespace(child.tag) in wanted:
            text = _safe_text(child.text or "", max_chars=500)
            if text:
                return text
    return ""


def _parse_feed_payload(raw_xml: str, source_url: str, max_items: int = 20) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    if not raw_xml:
        return out
    try:
        root = ElementTree.fromstring(raw_xml)
    except Exception:
        return out

    # RSS 2.0
    if _strip_namespace(root.tag).lower() == "rss":
        channel = None
        for child in list(root):
            if _strip_namespace(child.tag).lower() == "channel":
                channel = child
                break
        if channel is not None:
            for item in list(channel):
                if _strip_namespace(item.tag).lower() != "item":
                    continue
                title = _first_child_text(item, ["title"])
                link = _first_child_text(item, ["link"])
                published = _first_child_text(item, ["pubDate", "published", "updated"])
                if title:
                    out.append(
                        {
                            "title": title,
                            "url": link,
                            "published": published,
                            "source": source_url,
                        }
                    )
                if len(out) >= max_items:
                    break
        return out

    # Atom
    if _strip_namespace(root.tag).lower() == "feed":
        for entry in list(root):
            if _strip_namespace(entry.tag).lower() != "entry":
                continue
            title = _first_child_text(entry, ["title"])
            published = _first_child_text(entry, ["published", "updated"])
            link = ""
            for child in list(entry):
                if _strip_namespace(child.tag).lower() != "link":
                    continue
                href = child.attrib.get("href", "")
                rel = child.attrib.get("rel", "")
                if href and (not link or rel in ("alternate", "")):
                    link = href
            if title:
                out.append(
                    {
                        "title": title,
                        "url": _safe_text(link, max_chars=500),
                        "published": published,
                        "source": source_url,
                    }
                )
            if len(out) >= max_items:
                break
    return out


class ModelCatalogUpdater:
    """Refresh local model/tool catalog with optional release feed aggregation."""

    def __init__(
        self,
        *,
        fetch_fn: Optional[Callable[[str], str]] = None,
    ) -> None:
        self.config = get_config()
        self.fetch_fn = fetch_fn or self._fetch_url

    def _fetch_url(self, url: str, timeout_seconds: float = 5.0) -> str:
        try:
            with urlrequest.urlopen(url, timeout=timeout_seconds) as response:
                return response.read().decode("utf-8", errors="ignore")
        except (urlerror.URLError, OSError, ValueError, TimeoutError):
            return ""

    def _collect_local_models(self) -> List[Dict[str, Any]]:
        try:
            from chintu_backend.brain.llm.model_selector import list_local_ollama_models
        except Exception:
            return []
        host = str(getattr(self.config, "ollama_host", "http://localhost:11434") or "http://localhost:11434")
        rows: List[Dict[str, Any]] = []
        for item in list_local_ollama_models(host):
            rows.append(
                {
                    "name": str(item.name),
                    "size_bytes": int(item.size_bytes) if item.size_bytes is not None else None,
                }
            )
        return rows

    def _collect_provider_models(self) -> Dict[str, Dict[str, Any]]:
        cfg = self.config
        key_map = {
            "nvidia": bool(getattr(cfg, "nvidia_api_key", None) or os.environ.get("NVIDIA_API_KEY")),
            "groq": bool(getattr(cfg, "groq_api_key", None) or os.environ.get("GROQ_API_KEY")),
            "gemini": bool(getattr(cfg, "google_ai_key", None) or os.environ.get("GOOGLE_AI_KEY")),
            "deepseek": bool(getattr(cfg, "deepseek_api_key", None) or os.environ.get("DEEPSEEK_API_KEY")),
        }
        return {
            "local": {
                "configured": True,
                "model": str(getattr(cfg, "ollama_model", "") or ""),
            },
            "nvidia": {
                "configured": key_map["nvidia"],
                "model": str(getattr(cfg, "nvidia_model", "") or ""),
            },
            "groq": {
                "configured": key_map["groq"],
                "model": str(getattr(cfg, "groq_model", "") or ""),
            },
            "gemini": {
                "configured": key_map["gemini"],
                "model": str(getattr(cfg, "gemini_model", "") or ""),
            },
            "deepseek": {
                "configured": key_map["deepseek"],
                "model": str(getattr(cfg, "deepseek_model", "") or ""),
            },
        }

    def _collect_release_entries(self, max_items: int) -> List[Dict[str, str]]:
        feed_urls = list(getattr(self.config, "catalog_model_feed_urls", []) or [])
        if not feed_urls:
            return []
        rows: List[Dict[str, str]] = []
        for feed_url in feed_urls:
            url = str(feed_url or "").strip()
            if not url:
                continue
            try:
                raw = self.fetch_fn(url)
            except Exception as exc:
                logger.debug("Feed fetch failed for %s: %s", url, exc)
                raw = ""
            if not raw:
                continue
            parsed = _parse_feed_payload(raw, source_url=url, max_items=max_items)
            rows.extend(parsed)
        # De-dup by title + URL while preserving order.
        seen: set[str] = set()
        deduped: List[Dict[str, str]] = []
        for row in rows:
            key = f"{row.get('title','')}::{row.get('url','')}"
            if key in seen:
                continue
            seen.add(key)
            deduped.append(row)
            if len(deduped) >= max_items:
                break
        return deduped

    def build_snapshot(self, *, fetch_releases: bool = False) -> Dict[str, Any]:
        max_releases = int(getattr(self.config, "catalog_model_max_releases", 20) or 20)
        local_models = self._collect_local_models()
        provider_models = self._collect_provider_models()
        releases: List[Dict[str, str]] = []
        if fetch_releases:
            releases = self._collect_release_entries(max_items=max_releases)
        return {
            "generated_at_utc": _utc_now_iso(),
            "local_models": local_models,
            "providers": provider_models,
            "release_updates": releases,
        }

    def save_snapshot(self, snapshot: Dict[str, Any]) -> Path:
        out_path_cfg = getattr(self.config, "catalog_model_path", None)
        out_path = Path(out_path_cfg or (Path.cwd() / "generated_reports" / "model_catalog.json"))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=True), encoding="utf-8")
        return out_path

    def _save_summary_to_memory(self, snapshot: Dict[str, Any]) -> None:
        if not bool(getattr(self.config, "catalog_model_save_memory", True)):
            return
        try:
            from chintu_backend.brain.memory.facade import get_memory_facade
        except Exception:
            return

        local_count = len(snapshot.get("local_models", []) or [])
        release_updates = snapshot.get("release_updates", []) or []
        top_titles = [str(item.get("title") or "") for item in release_updates[:3] if isinstance(item, dict)]
        lines = [
            "Model catalog refresh",
            f"- local_models: {local_count}",
            f"- release_updates: {len(release_updates)}",
        ]
        for title in top_titles:
            if title:
                lines.append(f"- {title}")
        try:
            get_memory_facade().save_note(
                "\n".join(lines),
                category="model_catalog",
                generated_at=snapshot.get("generated_at_utc", ""),
            )
        except Exception:
            return

    def refresh(self, *, fetch_releases: bool = False, write_memory: bool = True) -> Dict[str, Any]:
        snapshot = self.build_snapshot(fetch_releases=fetch_releases)
        out_path = self.save_snapshot(snapshot)
        snapshot["catalog_path"] = str(out_path)
        if write_memory:
            self._save_summary_to_memory(snapshot)
        return snapshot


def load_model_catalog(path: Optional[Path] = None) -> Dict[str, Any]:
    config = get_config()
    catalog_cfg = getattr(config, "catalog_model_path", None)
    catalog_path = Path(path or catalog_cfg or (Path.cwd() / "generated_reports" / "model_catalog.json"))
    if not catalog_path.exists():
        return {}
    try:
        return json.loads(catalog_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


_updater: Optional[ModelCatalogUpdater] = None


def get_model_catalog_updater() -> ModelCatalogUpdater:
    global _updater
    if _updater is None:
        _updater = ModelCatalogUpdater()
    return _updater
