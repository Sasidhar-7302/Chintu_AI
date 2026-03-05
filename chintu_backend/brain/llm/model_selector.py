"""Local model selection helpers for Ollama.

This module keeps startup resilient when the configured model is not
available and picks a sensible fallback for the current hardware.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional
from urllib import error as urlerror
from urllib import request as urlrequest

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelInfo:
    name: str
    size_bytes: Optional[int] = None


# Ordered by quality/performance for local assistant "brain" usage.
PREFERRED_BRAIN_MODELS: List[str] = [
    "qwen3.5:4b",
    "qwen3.5:9b",
    "qwen2.5-coder:14b",
    "qwen2.5-coder:7b",
    "llama3.1:8b",
    "llama3:latest",
    "phi3.5:latest",
    "qwen2.5:3b",
    "qwen2.5:1.5b",
]


def list_local_ollama_models(host: str, timeout_seconds: float = 2.5) -> List[ModelInfo]:
    """List installed Ollama models using /api/tags."""
    url = f"{host.rstrip('/')}/api/tags"
    try:
        with urlrequest.urlopen(url, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except (urlerror.URLError, TimeoutError, OSError, ValueError):
        return []

    try:
        payload = json.loads(raw)
    except Exception:
        return []

    models: List[ModelInfo] = []
    for item in payload.get("models", []) or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        size = item.get("size")
        size_bytes: Optional[int] = None
        try:
            if size is not None:
                size_bytes = int(size)
        except Exception:
            size_bytes = None
        models.append(ModelInfo(name=name, size_bytes=size_bytes))
    return models


def detect_gpu_vram_mb() -> Optional[int]:
    """Detect total VRAM (MiB) using nvidia-smi when available."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
    except Exception:
        return None

    if result.returncode != 0:
        return None

    lines = [ln.strip() for ln in (result.stdout or "").splitlines() if ln.strip()]
    if not lines:
        return None

    try:
        values = [int(ln) for ln in lines]
    except Exception:
        return None
    return max(values) if values else None


def choose_local_brain_model(
    preferred_model: str,
    host: str,
    auto_select: bool = True,
) -> str:
    """Choose the best local model available for this machine.

    Rules:
    - If auto-select is disabled, keep the configured model.
    - If configured model exists locally, keep it.
    - Otherwise, select best-ranked installed model that should fit VRAM.
    - Fallback to smallest installed model if needed.
    """
    if not auto_select:
        return preferred_model

    installed = list_local_ollama_models(host)
    if not installed:
        return preferred_model

    by_name: Dict[str, ModelInfo] = {m.name: m for m in installed}
    if preferred_model in by_name:
        return preferred_model

    vram_mb = detect_gpu_vram_mb()

    def _likely_fits(model_name: str) -> bool:
        if vram_mb is None:
            return True
        info = by_name.get(model_name)
        if not info or info.size_bytes is None:
            return True
        # Keep headroom for KV cache and runtime overhead.
        model_mb = info.size_bytes / (1024 * 1024)
        # RTX 3060 12GB class cards can usually tolerate a bit less headroom.
        headroom = 0.75 if vram_mb >= 11000 else 0.65
        return model_mb <= (vram_mb * headroom)

    for candidate in PREFERRED_BRAIN_MODELS:
        if candidate in by_name and _likely_fits(candidate):
            return candidate

    # Fallback: smallest model available.
    smallest = sorted(
        installed,
        key=lambda m: (m.size_bytes if m.size_bytes is not None else (1 << 62), m.name),
    )
    if smallest:
        chosen = smallest[0].name
        logger.warning(
            "Configured model '%s' unavailable; selected smallest local model '%s'.",
            preferred_model,
            chosen,
        )
        return chosen

    return preferred_model
