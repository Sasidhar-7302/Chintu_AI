"""Mental model store for long-term user preferences and style."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

from .behavior_utils import safe_load_json, safe_save_json


@dataclass
class MentalModel:
    role: str = "cofounder"
    values: List[str] = field(default_factory=lambda: ["clarity", "speed", "quality"])
    product_focus: List[str] = field(default_factory=list)
    communication: Dict[str, Any] = field(default_factory=lambda: {
        "tone": "warm",
        "brevity": "balanced",
        "empathy": "medium",
        "directness": "high",
    })
    risk_posture: str = "balanced"
    persistence: str = "high"
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def update(self, **kwargs) -> None:
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self.updated_at = datetime.now().isoformat()

    def to_context(self) -> str:
        values = ", ".join(self.values) if self.values else "none"
        focus = ", ".join(self.product_focus) if self.product_focus else "none"
        comm = self.communication or {}
        return (
            f"role={self.role}; values={values}; product_focus={focus}; "
            f"tone={comm.get('tone','warm')}; brevity={comm.get('brevity','balanced')}; "
            f"empathy={comm.get('empathy','medium')}; directness={comm.get('directness','high')}; "
            f"risk={self.risk_posture}; persistence={self.persistence}"
        )


class MentalModelManager:
    """Persisted user mental model for behavior guidance."""

    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_path = storage_path or (Path.home() / ".chintu" / "mental_model.json")
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._model = self._load()

    def _load(self) -> MentalModel:
        data = safe_load_json(self.storage_path)
        if not data:
            return MentalModel()
        try:
            return MentalModel(**data)
        except Exception:
            return MentalModel()

    def save(self) -> None:
        safe_save_json(self.storage_path, asdict(self._model))

    @property
    def model(self) -> MentalModel:
        return self._model

    def update(self, **kwargs) -> None:
        self._model.update(**kwargs)
        self.save()
