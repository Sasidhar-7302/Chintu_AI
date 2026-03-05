from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from chintu_backend.core import model_fit


@dataclass
class _StubConfig:
    ollama_model: str = "qwen3.5:4b"
    ollama_model_strong: str = "qwen3.5:9b"
    vision_ollama_model: str = "qwen2.5-vl:7b"
    llm_num_gpu: int = 40
    llm_local_fallback_models: List[str] = field(
        default_factory=lambda: ["qwen3.5:4b", "qwen3.5:9b", "llama3.1:8b"]
    )


def test_recommend_model_settings_alignment(monkeypatch) -> None:
    monkeypatch.setattr(model_fit, "get_config", lambda: _StubConfig())
    snapshot = {
        "system": {"gpus": [{"memory_total_mb": 12288}]},
        "ollama": {"installed_names": ["qwen3.5:4b", "qwen3.5:9b", "qwen2.5-vl:7b"]},
    }
    fit = model_fit.recommend_model_settings(snapshot)
    assert fit["recommended"]["ollama_model"] == "qwen3.5:4b"
    assert fit["recommended"]["ollama_model_strong"] == "qwen3.5:9b"
    assert fit["recommended"]["vision_ollama_model"] == "qwen2.5-vl:7b"
    assert fit["recommended"]["llm_num_gpu"] == 40
    assert fit["mismatches"] == []


def test_recommend_model_settings_detects_mismatch(monkeypatch) -> None:
    cfg = _StubConfig(
        ollama_model="missing:1b",
        ollama_model_strong="missing:9b",
        vision_ollama_model="missing-vl:7b",
        llm_num_gpu=0,
    )
    monkeypatch.setattr(model_fit, "get_config", lambda: cfg)
    snapshot = {
        "system": {"gpus": [{"memory_total_mb": 24576}]},
        "ollama": {"installed_names": ["qwen3.5:4b", "qwen3.5:9b", "llava:7b"]},
    }
    fit = model_fit.recommend_model_settings(snapshot)
    assert fit["recommended"]["ollama_model"] in {"qwen3.5:4b", "qwen3.5:9b"}
    assert fit["recommended"]["llm_num_gpu"] == 60
    assert len(fit["mismatches"]) >= 3
