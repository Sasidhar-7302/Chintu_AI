"""Bi-weekly export pipeline for approved training data."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from chintu_backend.brain.learning.dataset_generator import generate_dataset_v2
from chintu_backend.core.config import get_config
from chintu_backend.training.gold_data import get_gold_data_manager


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass
class ExportResult:
    style_path: Path
    facts_path: Path
    style_count: int
    facts_count: int
    memory_path: Optional[Path] = None
    memory_count: int = 0
    style_gold_count: int = 0
    from_timestamp: Optional[str] = None
    latest_approved_timestamp: Optional[str] = None
    generated_at: str = ""
    manifest_path: Optional[Path] = None


def export_biweekly_datasets(
    since_timestamp: Optional[str] = None,
    include_memory: bool = True,
    memory_limit: int = 1000,
) -> ExportResult:
    config = get_config()
    export_dir = Path(config.training_exports_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    stamp = _utc_now().strftime("%Y%m%d_%H%M%S")
    generated_at = _utc_iso(_utc_now())

    style_path = export_dir / f"style_{stamp}.jsonl"
    facts_path = export_dir / f"facts_{stamp}.jsonl"
    memory_path = export_dir / f"memory_{stamp}.jsonl"
    manifest_path = export_dir / f"manifest_{stamp}.json"

    style_tags = [t.lower() for t in (getattr(config, "training_style_tags", []) or [])]
    fact_tags = [t.lower() for t in (getattr(config, "training_fact_tags", []) or [])]

    gold = get_gold_data_manager()
    approved = gold.get_approved(limit=10000)
    filtered, latest_approved_ts = _filter_by_since(approved, since_timestamp)

    style_rows, fact_rows = _split_by_tags(filtered, style_tags, fact_tags)
    style_gold_count = len(style_rows)

    memory_rows: List[dict] = []
    if include_memory:
        try:
            generate_dataset_v2(str(memory_path), limit=int(memory_limit))
            memory_rows = _read_jsonl(memory_path)
        except Exception:
            memory_rows = []

    style_rows.extend(memory_rows)
    style_rows = _dedupe_rows(style_rows)
    fact_rows = _dedupe_rows(fact_rows)

    _write_jsonl(style_path, style_rows)
    _write_jsonl(facts_path, fact_rows)
    if include_memory and not memory_path.exists():
        _write_jsonl(memory_path, [])

    manifest = {
        "generated_at": generated_at,
        "from_timestamp": since_timestamp,
        "latest_approved_timestamp": latest_approved_ts,
        "style_path": str(style_path),
        "facts_path": str(facts_path),
        "memory_path": str(memory_path) if include_memory else "",
        "counts": {
            "style": len(style_rows),
            "facts": len(fact_rows),
            "memory": len(memory_rows),
            "style_gold": style_gold_count,
            "approved_filtered": len(filtered),
        },
        "tags": {
            "style": style_tags,
            "facts": fact_tags,
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    _copy_latest(style_path, export_dir / "latest_style.jsonl")
    _copy_latest(facts_path, export_dir / "latest_facts.jsonl")
    if include_memory:
        _copy_latest(memory_path, export_dir / "latest_memory.jsonl")
    _copy_latest(manifest_path, export_dir / "latest_manifest.json")

    return ExportResult(
        style_path=style_path,
        facts_path=facts_path,
        style_count=len(style_rows),
        facts_count=len(fact_rows),
        memory_path=memory_path if include_memory else None,
        memory_count=len(memory_rows),
        style_gold_count=style_gold_count,
        from_timestamp=since_timestamp,
        latest_approved_timestamp=latest_approved_ts,
        generated_at=generated_at,
        manifest_path=manifest_path,
    )


def _filter_by_since(items: Iterable[object], since_timestamp: Optional[str]) -> Tuple[List[object], Optional[str]]:
    since_dt = _parse_ts(since_timestamp)
    filtered: List[object] = []
    latest_dt: Optional[datetime] = None
    for item in items:
        item_ts = _extract_item_timestamp(item)
        if since_dt and item_ts and item_ts <= since_dt:
            continue
        filtered.append(item)
        if item_ts and (latest_dt is None or item_ts > latest_dt):
            latest_dt = item_ts
    return filtered, _utc_iso(latest_dt) if latest_dt else None


def _extract_item_timestamp(item: object) -> Optional[datetime]:
    approval_ts = getattr(item, "approval_timestamp", None)
    if approval_ts:
        parsed = _parse_ts(str(approval_ts))
        if parsed:
            return parsed
    raw_ts = getattr(item, "timestamp", None)
    if raw_ts:
        return _parse_ts(str(raw_ts))
    return None


def _split_by_tags(approved: Iterable[object], style_tags: List[str], fact_tags: List[str]) -> Tuple[List[dict], List[dict]]:
    style_rows: List[dict] = []
    fact_rows: List[dict] = []
    for item in approved:
        tags = [str(t).lower() for t in (getattr(item, "tags", []) or [])]
        row = item.to_chat_format()
        is_fact = any(t in tags for t in fact_tags)
        is_style = any(t in tags for t in style_tags)
        if is_fact and not is_style:
            fact_rows.append(row)
        else:
            # Default untagged data to style so approved interactions are not dropped.
            style_rows.append(row)
    return style_rows, fact_rows


def _dedupe_rows(rows: List[dict]) -> List[dict]:
    unique: List[dict] = []
    seen = set()
    for row in rows:
        key = _row_key(row)
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def _row_key(row: dict) -> str:
    messages = row.get("messages")
    if isinstance(messages, list):
        user_text = ""
        assistant_text = ""
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role", "")).strip().lower()
            content = str(msg.get("content", "")).strip()
            if role == "user" and not user_text:
                user_text = content
            elif role == "assistant" and not assistant_text:
                assistant_text = content
        if user_text or assistant_text:
            return f"{user_text}\n{assistant_text}"
    return json.dumps(row, sort_keys=True, ensure_ascii=True)


def _read_jsonl(path: Path) -> List[dict]:
    if not path.exists():
        return []
    rows: List[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                rows.append(data)
    return rows


def _write_jsonl(path: Path, rows: List[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def _copy_latest(source: Path, target: Path) -> None:
    if not source.exists():
        target.write_text("", encoding="utf-8")
        return
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
