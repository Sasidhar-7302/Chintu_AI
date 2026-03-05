"""Live canvas models for Chintu."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


@dataclass
class CanvasCard:
    id: str
    title: str
    body: str = ""
    status: str = ""
    tags: List[str] = field(default_factory=list)
    priority: int = 0
    meta: Dict[str, Any] = field(default_factory=dict)
    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "body": self.body,
            "status": self.status,
            "tags": list(self.tags),
            "priority": int(self.priority),
            "meta": dict(self.meta),
            "updated_at": self.updated_at,
        }


@dataclass
class CanvasColumn:
    id: str
    title: str
    order: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "title": self.title, "order": int(self.order)}


@dataclass
class CanvasBoard:
    id: str
    title: str
    kind: str
    columns: List[CanvasColumn] = field(default_factory=list)
    cards: List[CanvasCard] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "kind": self.kind,
            "columns": [c.to_dict() for c in self.columns],
            "cards": [c.to_dict() for c in self.cards],
            "meta": dict(self.meta),
        }


@dataclass
class CanvasState:
    version: int = 1
    updated_at: str = field(default_factory=_now_iso)
    boards: List[CanvasBoard] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": int(self.version),
            "updated_at": self.updated_at,
            "boards": [b.to_dict() for b in self.boards],
        }
