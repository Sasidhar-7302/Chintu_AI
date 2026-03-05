"""Live canvas manager for Chintu."""

from __future__ import annotations

import logging
import threading
import time
from typing import Dict, Any, List, Optional
from pathlib import Path

from chintu_backend.core.config import get_config
from chintu_backend.core.events import Event, EventType, get_event_bus
from chintu_backend.core.state import get_state_manager
from .models import CanvasState, CanvasBoard, CanvasColumn, CanvasCard
from .store import CanvasStore

logger = logging.getLogger(__name__)


class CanvasManager:
    def __init__(self, store_path: Optional[Path] = None):
        self.config = get_config()
        self.state_manager = get_state_manager()
        self.event_bus = get_event_bus()
        self._lock = threading.Lock()
        self._last_system_refresh = 0.0

        path = store_path or (self.config.data_dir / "canvas" / "state.json")
        self.store = CanvasStore(path)
        self._ensure_defaults()

        # Subscribe to UI connects for initial push
        try:
            self.event_bus.subscribe(EventType.UI_CONNECTED, self._on_ui_connected)
        except Exception:
            pass

        # Optional: throttle system refresh on state updates
        self.state_manager.add_listener(self._on_state_change)

    def _ensure_defaults(self) -> None:
        if not self.store.get_board("plan"):
            self.store.upsert_board(
                CanvasBoard(
                    id="plan",
                    title="Execution Plans",
                    kind="plan",
                    columns=[
                        CanvasColumn(id="pending", title="Pending", order=1),
                        CanvasColumn(id="running", title="Running", order=2),
                        CanvasColumn(id="done", title="Done", order=3),
                        CanvasColumn(id="failed", title="Failed", order=4),
                    ],
                    cards=[],
                    meta={"locked": False},
                )
            )
        if not self.store.get_board("system"):
            self.store.upsert_board(
                CanvasBoard(
                    id="system",
                    title="System Status",
                    kind="system",
                    columns=[
                        CanvasColumn(id="active", title="Active", order=1),
                        CanvasColumn(id="inactive", title="Inactive", order=2),
                        CanvasColumn(id="error", title="Issues", order=3),
                    ],
                    cards=[],
                    meta={"locked": True},
                )
            )
        if not self.store.get_board("knowledge"):
            self.store.upsert_board(
                CanvasBoard(
                    id="knowledge",
                    title="Knowledge Feed",
                    kind="knowledge",
                    columns=[CanvasColumn(id="notes", title="Latest", order=1)],
                    cards=[],
                    meta={"locked": False},
                )
            )
        self._persist_and_publish()

    def _on_ui_connected(self, _event: Event) -> None:
        self.publish()

    def _on_state_change(self, _state) -> None:
        now = time.monotonic()
        if now - self._last_system_refresh < 5.0:
            return
        self._last_system_refresh = now
        try:
            self.update_system_from_state()
        except Exception:
            pass

    def publish(self) -> None:
        payload = {"canvas": self.store.to_dict()}
        try:
            self.event_bus.publish_sync(Event(EventType.CANVAS_UPDATE, payload, source="canvas"))
        except Exception:
            pass
        try:
            self.state_manager.set_canvas_state(self.store.to_dict())
        except Exception:
            pass

    def _persist_and_publish(self) -> None:
        self.store.save()
        self.publish()

    # ------------------------------------------------------------------
    # Board Updates
    # ------------------------------------------------------------------
    def update_plan(self, plan) -> None:
        board = self.store.get_board("plan")
        if not board:
            return

        cards: List[CanvasCard] = []
        for step in plan.steps:
            status = "pending"
            if step.completed:
                status = "done" if not step.error else "failed"
            elif step.result:
                status = "running"
            card = CanvasCard(
                id=f"step:{step.order}",
                title=step.description,
                body=step.result or "",
                status=status,
                tags=["risky"] if step.is_risky else [],
                priority=step.order,
                meta={"capability": step.capability, "estimated_seconds": step.estimated_seconds},
            )
            cards.append(card)

        board.cards = cards
        board.meta.update({
            "goal": plan.goal,
            "risk": plan.estimated_risk,
            "eta_seconds": plan.estimated_duration_seconds,
        })
        self._persist_and_publish()

    def update_system_from_state(self) -> None:
        board = self.store.get_board("system")
        if not board:
            return
        features = self.state_manager.state.features
        cards: List[CanvasCard] = []
        for key, feature in features.items():
            status = feature.status or "inactive"
            column = "active" if status == "active" else ("error" if status == "error" else "inactive")
            cards.append(
                CanvasCard(
                    id=f"feature:{key}",
                    title=feature.name,
                    body=feature.error_message or "",
                    status=column,
                    tags=[status],
                    meta={"enabled": feature.enabled},
                )
            )
        board.cards = cards
        self._persist_and_publish()

    def add_knowledge_item(self, title: str, summary: str, sources: Optional[List[str]] = None, tag: str = "") -> None:
        board = self.store.get_board("knowledge")
        if not board:
            return
        sources = sources or []
        card = CanvasCard(
            id=f"note:{int(time.time())}",
            title=title,
            body=summary,
            status="notes",
            tags=[t for t in [tag] if t] + ["knowledge"],
            meta={"sources": sources[:6]},
        )
        board.cards.insert(0, card)
        board.cards = board.cards[:30]
        self._persist_and_publish()

    # ------------------------------------------------------------------
    # Actions from UI
    # ------------------------------------------------------------------
    def apply_action(self, action: Dict[str, Any]) -> bool:
        board_id = str(action.get("board_id") or "")
        if not board_id:
            return False
        board = self.store.get_board(board_id)
        if not board:
            return False
        if board.meta.get("locked"):
            return False

        action_type = str(action.get("action") or "")
        card_id = str(action.get("card_id") or "")

        if action_type == "move_card":
            target = str(action.get("target_column") or "")
            if not target:
                return False
            for card in board.cards:
                if card.id == card_id:
                    card.status = target
                    card.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    self._persist_and_publish()
                    return True

        if action_type == "edit_card":
            for card in board.cards:
                if card.id == card_id:
                    title = action.get("title")
                    body = action.get("body")
                    if title is not None:
                        card.title = str(title)
                    if body is not None:
                        card.body = str(body)
                    card.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    self._persist_and_publish()
                    return True

        if action_type == "add_card":
            title = str(action.get("title") or "New Card")
            body = str(action.get("body") or "")
            status = str(action.get("status") or (board.columns[0].id if board.columns else ""))
            card = CanvasCard(id=f"card:{int(time.time() * 1000)}", title=title, body=body, status=status)
            board.cards.insert(0, card)
            self._persist_and_publish()
            return True

        if action_type == "remove_card":
            before = len(board.cards)
            board.cards = [c for c in board.cards if c.id != card_id]
            if len(board.cards) != before:
                self._persist_and_publish()
                return True

        return False


_canvas_manager: Optional[CanvasManager] = None


def get_canvas_manager() -> CanvasManager:
    global _canvas_manager
    if _canvas_manager is None:
        _canvas_manager = CanvasManager()
    return _canvas_manager
