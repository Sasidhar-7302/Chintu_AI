"""Memory lifecycle management: dedupe, summarize, decay, soul updates."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from chintu_backend.core.config import get_config
from chintu_backend.brain.memory.hybrid_memory import HybridMemoryManager

logger = logging.getLogger(__name__)


class MemoryLifecycleManager:
    def __init__(self, memory: HybridMemoryManager):
        self.config = get_config()
        self.memory = memory
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="MemoryLifecycle")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _loop(self) -> None:
        interval_hours = float(getattr(self.config, "memory_lifecycle_interval_hours", 6.0))
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception as exc:
                logger.warning("Memory lifecycle error: %s", exc)
            self._stop.wait(interval_hours * 3600)

    def run_once(self) -> None:
        self._decay_old()
        self._dedupe_recent()
        self._summarize_recent()
        self._update_soul()

    def _decay_old(self) -> None:
        days = int(getattr(self.config, "memory_decay_days", 90))
        cutoff = datetime.now() - timedelta(days=days)
        with self.memory._lock:
            cur = self.memory._conn.execute(
                "UPDATE interactions SET archived = 1 WHERE archived = 0 AND created_at < ?",
                (cutoff.isoformat(),),
            )
            self.memory._conn.commit()
        if cur.rowcount:
            logger.info("Archived %d old memories", cur.rowcount)

    def _dedupe_recent(self) -> None:
        # Lightweight dedupe: collapse exact duplicates from last 1000 rows
        with self.memory._lock:
            cur = self.memory._conn.execute(
                "SELECT id, content FROM interactions WHERE archived = 0 ORDER BY id DESC LIMIT 1000"
            )
            rows = cur.fetchall()
            seen = {}
            dup_ids = []
            for row_id, content in rows:
                key = content.strip().lower()
                if key in seen:
                    dup_ids.append(row_id)
                else:
                    seen[key] = row_id
            if dup_ids:
                placeholders = ",".join("?" for _ in dup_ids)
                self.memory._conn.execute(
                    f"UPDATE interactions SET archived = 1 WHERE id IN ({placeholders})",
                    dup_ids,
                )
                self.memory._conn.commit()
                logger.info("Deduped %d duplicate memories", len(dup_ids))

    def _summarize_recent(self) -> None:
        # Simple summary of last 50 interactions
        with self.memory._lock:
            cur = self.memory._conn.execute(
                "SELECT content FROM interactions WHERE archived = 0 ORDER BY id DESC LIMIT 50"
            )
            rows = [r[0] for r in cur.fetchall()]
            if len(rows) < 10:
                return
        summary = "Recent topics: " + ", ".join(_extract_keywords(rows, max_terms=8))
        now = datetime.now().isoformat()
        with self.memory._lock:
            self.memory._conn.execute(
                "INSERT INTO summaries(period_start, period_end, summary, created_at) VALUES (?, ?, ?, ?)",
                (now, now, summary, now),
            )
            self.memory._conn.commit()
        logger.info("Summary updated")

    def _update_soul(self) -> None:
        soul_path = Path(self.config.memory_markdown_dir or (self.config.data_dir / "brain_md")) / "SOUL.md"
        soul_path.parent.mkdir(parents=True, exist_ok=True)
        profile = self.memory.get_profile_context()
        summary = self._latest_summary()
        content = "# SOUL\n\n## User Profile\n"
        content += profile or "No user profile yet.\n"
        content += "\n## Recent Summary\n"
        content += summary or "No summary yet.\n"
        soul_path.write_text(content, encoding="utf-8")

    def _latest_summary(self) -> str:
        with self.memory._lock:
            cur = self.memory._conn.execute(
                "SELECT summary FROM summaries ORDER BY id DESC LIMIT 1"
            )
            row = cur.fetchone()
        return row[0] if row else ""


def _extract_keywords(texts, max_terms: int = 8):
    counts = {}
    for text in texts:
        for token in text.lower().split():
            token = token.strip(".,!?;:\"'()[]{}")
            if len(token) < 4:
                continue
            counts[token] = counts.get(token, 0) + 1
    ranked = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    return [w for w, _ in ranked[:max_terms]]
