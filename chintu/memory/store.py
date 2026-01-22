"""Persistent memory store using JSONL on disk."""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .embedding import BaseEmbedder, HashingEmbedder


@dataclass
class MemoryRecord:
    """A single memory entry."""

    id: str
    text: str
    embedding: List[float]
    metadata: Dict[str, Any]
    created_at: str


class MemoryStore:
    """Stores memory entries and supports similarity search."""

    def __init__(self, path: Path, embedder: BaseEmbedder, max_items: int = 2000):
        self.path = path
        self.embedder = embedder
        self.max_items = max_items
        self._records: List[MemoryRecord] = []
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            return
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                embedding = data.get("embedding")
                if not isinstance(embedding, list):
                    embedding = self.embedder.embed(data.get("text", ""))
                record = MemoryRecord(
                    id=data.get("id", str(uuid.uuid4())),
                    text=data.get("text", ""),
                    embedding=[float(v) for v in embedding] if embedding else [],
                    metadata=data.get("metadata", {}) or {},
                    created_at=data.get("created_at", datetime.utcnow().isoformat()),
                )
                self._records.append(record)

        if len(self._records) > self.max_items:
            self._records = self._records[-self.max_items:]
            self._rewrite()

    def _append(self, record: MemoryRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(record), ensure_ascii=True) + "\n")

    def _rewrite(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            for record in self._records:
                handle.write(json.dumps(asdict(record), ensure_ascii=True) + "\n")

    def add(self, text: str, metadata: Dict[str, Any]) -> MemoryRecord:
        record = MemoryRecord(
            id=str(uuid.uuid4()),
            text=text.strip(),
            embedding=self.embedder.embed(text),
            metadata=metadata,
            created_at=datetime.utcnow().isoformat(),
        )
        with self._lock:
            self._records.append(record)
            if len(self._records) > self.max_items:
                self._records = self._records[-self.max_items:]
                self._rewrite()
            else:
                self._append(record)
        return record

    def search(
        self,
        query: str,
        top_k: int = 4,
        min_score: float = 0.25,
    ) -> List[Tuple[MemoryRecord, float]]:
        if not query.strip():
            return []
        if not self._records:
            return []
        if top_k <= 0:
            return []
        query_vec = self.embedder.embed(query)
        if not query_vec:
            return []

        scored: List[Tuple[MemoryRecord, float]] = []
        for record in self._records:
            if not record.embedding:
                continue
            score = _dot(query_vec, record.embedding)
            if score >= min_score:
                scored.append((record, score))

        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:top_k]


def _dot(a: List[float], b: List[float]) -> float:
    return sum(x * y for x, y in zip(a, b))
