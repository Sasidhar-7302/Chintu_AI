"""Model swapping and chat helper for the v5.1 swarm."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)


class ModelManager:
    """Manage Ollama model swaps using keep_alive for tight VRAM budgets."""

    def __init__(self, base_url: str = "http://localhost:11434", timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.active_model: Optional[str] = None
        self._session = requests.Session()

    def switch_model(self, target_model: str, warm_prompt: str = "warmup") -> None:
        """Unload the current model and warm-load the target model."""
        if not target_model:
            raise ValueError("target_model is required")

        if self.active_model == target_model:
            return

        if self.active_model:
            self._unload_model(self.active_model)

        self._warm_load(target_model, warm_prompt)
        self.active_model = target_model

    def chat(
        self,
        model: str,
        messages: List[Dict[str, str]],
        keep_alive: int = -1,
    ) -> Tuple[str, Dict[str, Any]]:
        """Send a chat request and return (content, raw_response)."""
        if not model:
            raise ValueError("model is required")
        if not messages:
            raise ValueError("messages must not be empty")

        if self.active_model != model:
            self.switch_model(model)

        payload = {
            "model": model,
            "messages": messages,
            "keep_alive": keep_alive,
        }
        data = self._post_json("/api/chat", payload)
        content = data.get("message", {}).get("content", "")
        return content, data

    def _unload_model(self, model: str) -> None:
        payload = {"model": model, "messages": [{"role": "user", "content": "unload"}], "keep_alive": 0}
        try:
            self._post_json("/api/chat", payload)
            logger.info("Unloaded model: %s", model)
        except Exception as exc:
            logger.warning("Failed to unload model %s: %s", model, exc)

    def _warm_load(self, model: str, warm_prompt: str) -> None:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": warm_prompt}],
            "keep_alive": -1,
        }
        self._post_json("/api/chat", payload)
        logger.info("Loaded model: %s", model)

    def _post_json(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        response = self._session.post(url, json=payload, timeout=self.timeout)
        response.raise_for_status()
        if not response.content:
            return {}
        return response.json()
