"""Persistent canvas store for Chintu."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, List, Optional

from .models import CanvasState, CanvasBoard, CanvasColumn, CanvasCard


def _safe_load(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_write(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


class CanvasStore:
    def __init__(self, path: Path):
        self.path = path
        self.state = self._load()

    def _load(self) -> CanvasState:
        raw = _safe_load(self.path)
        if not raw:
            return CanvasState()
        try:
            boards = []
            for board in raw.get("boards", []):
                columns = [
                    CanvasColumn(
                        id=str(c.get("id", "")),
                        title=str(c.get("title", "")),
                        order=int(c.get("order", 0)),
                    )
                    for c in board.get("columns", [])
                ]
                cards = [
                    CanvasCard(
                        id=str(card.get("id", "")),
                        title=str(card.get("title", "")),
                        body=str(card.get("body", "")),
                        status=str(card.get("status", "")),
                        tags=list(card.get("tags", [])),
                        priority=int(card.get("priority", 0)),
                        meta=dict(card.get("meta", {})),
                        updated_at=str(card.get("updated_at", "")),
                    )
                    for card in board.get("cards", [])
                ]
                boards.append(
                    CanvasBoard(
                        id=str(board.get("id", "")),
                        title=str(board.get("title", "")),
                        kind=str(board.get("kind", "")),
                        columns=columns,
                        cards=cards,
                        meta=dict(board.get("meta", {})),
                    )
                )
            return CanvasState(
                version=int(raw.get("version", 1)),
                updated_at=str(raw.get("updated_at", "")),
                boards=boards,
            )
        except Exception:
            return CanvasState()

    def save(self) -> None:
        self.state.updated_at = self.state.updated_at or ""
        _safe_write(self.path, self.state.to_dict())

    def get_board(self, board_id: str) -> Optional[CanvasBoard]:
        for board in self.state.boards:
            if board.id == board_id:
                return board
        return None

    def upsert_board(self, board: CanvasBoard) -> None:
        existing = self.get_board(board.id)
        if existing:
            existing.title = board.title
            existing.kind = board.kind
            existing.columns = board.columns
            existing.cards = board.cards
            existing.meta = board.meta
        else:
            self.state.boards.append(board)

    def remove_board(self, board_id: str) -> None:
        self.state.boards = [b for b in self.state.boards if b.id != board_id]

    def to_dict(self) -> Dict[str, Any]:
        return self.state.to_dict()
