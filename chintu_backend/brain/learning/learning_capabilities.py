"""Capabilities for inspecting Chintu's learning system."""

from __future__ import annotations

from typing import Dict, Any

from chintu_backend.core.capabilities import Capability, CapabilityType, ActionResult
from chintu_backend.brain.learning.learning_engine import get_learning_engine


def handle_learning_status(text: str, context: Dict[str, Any]) -> ActionResult:
    engine = get_learning_engine()
    stats = engine.store.get_stats()
    state = engine.store.load_state()
    config = engine.config
    total = stats.get("total", 0)
    by_category = stats.get("by_category", {})

    if total == 0:
        return ActionResult.ok(
            "I haven't stored any learning events yet.",
            {"stats": stats},
            "learning_status",
        )

    lines = [f"Learning events: {total}"]
    base_model = getattr(config, "learning_base_model_id", "")
    if base_model:
        lines.append(f"Training base model: {base_model}")
    if state.get("last_training_message"):
        lines.append(f"Last training: {state.get('last_training_message')}")
    for category, count in sorted(by_category.items()):
        lines.append(f"- {category}: {count}")
    return ActionResult.ok("\n".join(lines), {"stats": stats}, "learning_status")


def register_learning_capabilities(registry) -> None:
    registry.register(
        Capability(
            name="learning_status",
            triggers=[
                "learning status",
                "what did you learn",
                "learning stats",
                "show learning",
            ],
            handler=handle_learning_status,
            requires_confirmation=False,
            description="show learning event statistics",
            capability_type=CapabilityType.SYSTEM,
            examples=["Learning status", "What did you learn?"],
        )
    )
