"""Local HF + LoRA adapter client for fine-tuned responses."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from chintu_backend.core.config import get_config

logger = logging.getLogger(__name__)


@dataclass
class AdapterInfo:
    base_model: str
    adapter_path: str


class AdapterLLMClient:
    """Local LLM client that uses a fine-tuned LoRA adapter."""

    def __init__(
        self,
        base_model: str,
        adapter_path: str,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ):
        self.base_model = base_model
        self.adapter_path = adapter_path
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._available = False

        try:
            import torch
            from transformers import AutoTokenizer, AutoModelForCausalLM
            from peft import PeftModel

            self._torch = torch
            self._tokenizer = AutoTokenizer.from_pretrained(base_model, use_fast=True)

            if torch.cuda.is_available():
                dtype = torch.float16
                device_map = "auto"
            else:
                dtype = torch.float32
                device_map = None

            self._model = AutoModelForCausalLM.from_pretrained(
                base_model,
                torch_dtype=dtype,
                device_map=device_map,
            )
            self._model = PeftModel.from_pretrained(self._model, adapter_path)
            self._model.eval()
            self._available = True
            logger.info("AdapterLLM loaded: %s + %s", base_model, adapter_path)
        except Exception as exc:
            logger.warning("AdapterLLM unavailable: %s", exc)
            self._available = False

    @property
    def is_available(self) -> bool:
        return self._available

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        if not self._available:
            return "[Fine-tuned model not available]"

        text = self._build_prompt(prompt, system_prompt)
        inputs = self._tokenizer(text, return_tensors="pt")
        if hasattr(self._torch, "cuda") and self._torch.cuda.is_available():
            inputs = {k: v.to(self._model.device) for k, v in inputs.items()}

        with self._torch.no_grad():
            output_ids = self._model.generate(
                **inputs,
                max_new_tokens=self.max_tokens,
                temperature=self.temperature,
                do_sample=self.temperature > 0.0,
            )

        decoded = self._tokenizer.decode(output_ids[0], skip_special_tokens=True)
        return self._strip_prompt(text, decoded)

    def generate_stream(self, prompt: str, system_prompt: Optional[str] = None):
        yield self.generate(prompt, system_prompt)

    def _build_prompt(self, prompt: str, system_prompt: Optional[str]) -> str:
        if hasattr(self._tokenizer, "apply_chat_template"):
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            return self._tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)

        if system_prompt:
            return f"System: {system_prompt}\nUser: {prompt}\nAssistant:"
        return f"User: {prompt}\nAssistant:"

    @staticmethod
    def _strip_prompt(prompt: str, decoded: str) -> str:
        if decoded.startswith(prompt):
            return decoded[len(prompt):].strip()
        return decoded.strip()


def _read_active_adapter(path: Path) -> Optional[AdapterInfo]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    base = data.get("base_model")
    adapter = data.get("adapter_path")
    if not base or not adapter:
        return None
    return AdapterInfo(base_model=base, adapter_path=adapter)


_adapter_client: Optional[AdapterLLMClient] = None


def get_adapter_client() -> Optional[AdapterLLMClient]:
    global _adapter_client
    if _adapter_client is not None:
        return _adapter_client

    config = get_config()
    if not getattr(config, "learning_use_finetuned_model", False):
        return None

    adapter_dir = getattr(config, "learning_adapter_dir", None)
    if not adapter_dir:
        return None

    info = _read_active_adapter(Path(adapter_dir) / "active_adapter.json")
    if not info:
        return None

    client = AdapterLLMClient(
        base_model=info.base_model,
        adapter_path=info.adapter_path,
        max_tokens=config.llm_max_tokens,
        temperature=config.llm_temperature,
    )
    if not client.is_available:
        return None
    _adapter_client = client
    return _adapter_client
