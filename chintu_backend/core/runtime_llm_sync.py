"""Helpers to apply runtime config changes to active LLM clients.

Used after hardware adaptation retunes config so long-lived client instances
pick up new model/runtime options without requiring a restart.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List

logger = logging.getLogger(__name__)


def _is_ollama_like(client: Any) -> bool:
    name = str(getattr(getattr(client, "__class__", None), "__name__", "") or "").lower()
    module = str(getattr(getattr(client, "__class__", None), "__module__", "") or "").lower()
    return "ollama" in name or "ollama" in module


def _iter_unique_targets(targets: Iterable[Any]) -> Iterable[Any]:
    seen_ids = set()
    for target in targets:
        if target is None:
            continue
        ident = id(target)
        if ident in seen_ids:
            continue
        seen_ids.add(ident)
        yield target


def _set_attr_if_supported(target: Any, attr: str, value: Any) -> bool:
    if not hasattr(target, attr):
        return False
    try:
        current = getattr(target, attr)
    except Exception:
        return False
    if current == value:
        return False
    try:
        setattr(target, attr, value)
        return True
    except Exception:
        return False


def sync_runtime_llm_clients(config: Any, targets: Iterable[Any]) -> Dict[str, Any]:
    """Apply current config values to all supported LLM client targets.

    Returns a small receipt suitable for logging/audit.
    """

    changed: List[Dict[str, Any]] = []
    scanned = 0
    for target in _iter_unique_targets(targets):
        scanned += 1
        updates: Dict[str, Any] = {}

        # General knobs many clients support.
        for attr, cfg_key in (
            ("max_tokens", "llm_max_tokens"),
            ("temperature", "llm_temperature"),
        ):
            value = getattr(config, cfg_key, None)
            if value is None:
                continue
            if _set_attr_if_supported(target, attr, value):
                updates[attr] = value

        # Ollama-specific runtime controls.
        if _is_ollama_like(target):
            for attr, cfg_key in (
                ("model", "ollama_model"),
                ("model_name", "ollama_model"),
                ("num_gpu", "llm_num_gpu"),
                ("num_threads", "llm_num_threads"),
                ("num_ctx", "llm_num_ctx"),
            ):
                value = getattr(config, cfg_key, None)
                if value is None:
                    continue
                if _set_attr_if_supported(target, attr, value):
                    updates[attr] = value

        if updates:
            changed.append(
                {
                    "target_type": str(getattr(target.__class__, "__name__", "unknown")),
                    "updates": updates,
                }
            )

    receipt = {
        "scanned_targets": int(scanned),
        "changed_targets": len(changed),
        "changes": changed,
    }
    if changed:
        logger.info("Runtime LLM sync applied: %s", receipt)
    return receipt

