from __future__ import annotations

import importlib.util
import json
import types
from pathlib import Path

import pytest

from chintu_backend.core.model_router import Intent, ModelRouter, RoutingDecision, TaskComplexity


class _LocalEchoLLM:
    is_available = True

    def __init__(self) -> None:
        self.model = "qwen3.5:4b"
        self.model_name = "qwen3.5:4b"
        self.num_gpu = 50
        self.keep_alive = None
        self.think = False

    def generate(self, prompt: str = "", system_prompt: str | None = None, **_kwargs) -> str:
        return f"local-model:{self.model}"

    def generate_stream(self, prompt: str = "", system_prompt: str | None = None, **_kwargs):
        yield f"local-model:{self.model}"


class _AirLLMEcho:
    is_available = True

    def __init__(self) -> None:
        self.model = "Qwen/Qwen3.5-27B"
        self.model_name = "Qwen/Qwen3.5-27B"

    def generate(self, prompt: str = "", system_prompt: str | None = None, **_kwargs) -> str:
        return f"airllm-model:{self.model}"

    def generate_stream(self, prompt: str = "", system_prompt: str | None = None, **_kwargs):
        yield f"airllm-model:{self.model}"


@pytest.mark.skipif(importlib.util.find_spec("airllm") is None, reason="airllm optional dependency is not installed")
def test_airllm_optional_dependency_smoke() -> None:
    from chintu_backend.brain.llm.airllm_client import AirLLMClient

    client = AirLLMClient(model_id="Qwen/Qwen2.5-32B-Instruct", max_tokens=64)
    assert client.is_available is True
    assert hasattr(client, "generate")
    assert hasattr(client, "generate_stream")


def test_airllm_client_missing_falls_back_to_local_ollama(monkeypatch) -> None:
    from chintu_backend.core import model_router as model_router_module

    cfg = model_router_module.get_config()
    monkeypatch.setattr(cfg, "airllm_enabled", True, raising=False)
    monkeypatch.setattr(cfg, "airllm_model_id", "Qwen/Qwen2.5-32B-Instruct", raising=False)
    monkeypatch.setattr(cfg, "ollama_model", "qwen3.5:4b", raising=False)
    monkeypatch.setattr(cfg, "ollama_model_strong", "qwen3.5:9b", raising=False)
    monkeypatch.setattr(cfg, "llm_local_strong_model_enabled", True, raising=False)
    monkeypatch.setattr(cfg, "llm_arbiter_enabled", False, raising=False)
    monkeypatch.setattr(model_router_module, "HAS_METRICS", False, raising=False)
    monkeypatch.setattr(model_router_module, "HAS_BUDGET", False, raising=False)

    router = ModelRouter(local_llm=_LocalEchoLLM(), prefer_local=True)
    router.ThinkingManagerClass = None
    router.airllm = None  # Simulates AirLLM import/init failure.
    router._ensure_local_model_available = lambda: True
    router._local_installed_models = {"qwen3.5:4b", "qwen3.5:9b"}

    decision = RoutingDecision(
        intent=Intent.REASONING,
        complexity=TaskComplexity.COMPLEX_REASONING,
        use_llm=True,
        prefer_cloud=True,
        extracted_params={},
    )
    router.intent_detector = types.SimpleNamespace(detect=lambda _text: decision)

    response, source = router.route_and_execute("Solve this step-by-step reasoning problem.")

    assert source == "local_llm"
    assert "qwen3.5:9b" in response


def test_airllm_preferred_for_complex_reasoning(monkeypatch) -> None:
    from chintu_backend.core import model_router as model_router_module

    cfg = model_router_module.get_config()
    monkeypatch.setattr(cfg, "airllm_enabled", True, raising=False)
    monkeypatch.setattr(cfg, "airllm_model_id", "Qwen/Qwen3.5-27B", raising=False)
    monkeypatch.setattr(cfg, "ollama_model", "qwen3.5:4b", raising=False)
    monkeypatch.setattr(cfg, "ollama_model_strong", "qwen3.5:9b", raising=False)
    monkeypatch.setattr(cfg, "llm_local_strong_model_enabled", True, raising=False)
    monkeypatch.setattr(cfg, "llm_arbiter_enabled", False, raising=False)
    monkeypatch.setattr(model_router_module, "HAS_METRICS", False, raising=False)
    monkeypatch.setattr(model_router_module, "HAS_BUDGET", False, raising=False)

    router = ModelRouter(local_llm=_LocalEchoLLM(), prefer_local=True)
    router.ThinkingManagerClass = None
    router._ensure_local_model_available = lambda: True
    router._local_installed_models = {"qwen3.5:4b", "qwen3.5:9b"}
    router.airllm = _AirLLMEcho()

    decision = RoutingDecision(
        intent=Intent.REASONING,
        complexity=TaskComplexity.COMPLEX_REASONING,
        use_llm=True,
        prefer_cloud=False,
        extracted_params={},
    )
    router.intent_detector = types.SimpleNamespace(detect=lambda _text: decision)

    response, source = router.route_and_execute("Solve this hard reasoning problem.")

    assert source == "airllm"
    assert "airllm-model:Qwen/Qwen3.5-27B" in response


def test_airllm_resolve_model_source_fails_fast_on_incomplete_local_cache(monkeypatch, tmp_path: Path) -> None:
    from chintu_backend.brain.llm.airllm_client import AirLLMClient

    snapshot = tmp_path / "snapshot"
    snapshot.mkdir(parents=True, exist_ok=True)
    index_payload = {
        "weight_map": {
            "layer0": "model.safetensors-00001-of-00002.safetensors",
            "layer1": "model.safetensors-00002-of-00002.safetensors",
        }
    }
    (snapshot / "model.safetensors.index.json").write_text(json.dumps(index_payload), encoding="utf-8")
    (snapshot / "model.safetensors-00001-of-00002.safetensors").write_bytes(b"ok")

    import transformers

    class _Cfg:
        architectures = ["Qwen3ForCausalLM"]

    monkeypatch.setattr(transformers.AutoConfig, "from_pretrained", lambda *args, **kwargs: _Cfg())
    monkeypatch.setattr(
        AirLLMClient,
        "_latest_snapshot_dir",
        classmethod(lambda cls, _model_id: snapshot),
    )

    client = AirLLMClient(
        model_id="Qwen/Qwen3.5-27B",
        allow_download=False,
    )
    with pytest.raises(RuntimeError, match="incomplete"):
        client._resolve_model_source("")


def test_airllm_compression_mode_resolution() -> None:
    from chintu_backend.brain.llm.airllm_client import AirLLMClient
    import os

    client_auto = AirLLMClient(model_id="Qwen/Qwen3.5-27B", compression="auto")
    resolved_auto = client_auto._resolve_compression_mode()
    if os.name == "nt":
        assert resolved_auto is None
    else:
        assert resolved_auto == "4bit"

    client_none = AirLLMClient(model_id="Qwen/Qwen3.5-27B", compression="none")
    assert client_none._resolve_compression_mode() is None

    resolved_device = client_auto._resolve_device_mode()
    if os.name == "nt":
        assert resolved_device == "cpu"
    else:
        assert resolved_device == "cuda:0"

    client_cuda = AirLLMClient(model_id="Qwen/Qwen3.5-27B", device="cuda:0")
    assert client_cuda._resolve_device_mode() == "cuda:0"


def test_airllm_runtime_mode_auto_prefers_subprocess_on_windows(monkeypatch) -> None:
    from chintu_backend.brain.llm import airllm_client as airllm_client_module

    monkeypatch.setattr(airllm_client_module.os, "name", "nt", raising=False)
    client = airllm_client_module.AirLLMClient(
        model_id="Qwen/Qwen3.5-27B",
        runtime_mode="auto",
    )
    assert client._use_subprocess_mode() is True

    monkeypatch.setattr(airllm_client_module.os, "name", "posix", raising=False)
    client_posix = airllm_client_module.AirLLMClient(
        model_id="Qwen/Qwen3.5-27B",
        runtime_mode="auto",
    )
    assert client_posix._use_subprocess_mode() is False


def test_airllm_generate_routes_to_worker_when_subprocess_mode(monkeypatch) -> None:
    from chintu_backend.brain.llm.airllm_client import AirLLMClient

    client = AirLLMClient(
        model_id="Qwen/Qwen3.5-27B",
        runtime_mode="subprocess",
    )

    called = {"worker": False}

    def _fake_worker(prompt: str, system_prompt: str | None) -> str:
        called["worker"] = True
        return f"worker:{prompt}:{system_prompt or ''}"

    monkeypatch.setattr(client, "_generate_via_worker", _fake_worker)
    result = client.generate("hello", "system")

    assert called["worker"] is True
    assert "worker:hello:system" in result


def test_airllm_dtype_resolution_cpu_prefers_float32() -> None:
    from chintu_backend.brain.llm.airllm_client import AirLLMClient
    import torch

    client = AirLLMClient(model_id="Qwen/Qwen3.5-27B")
    assert client._resolve_dtype(resolved_device="cpu") == torch.float32
    assert client._resolve_dtype(resolved_device="cuda:0") == torch.float16


def test_airllm_prepare_layer_shards_quarantines_incomplete(tmp_path: Path) -> None:
    from chintu_backend.brain.llm.airllm_client import AirLLMClient

    client = AirLLMClient(
        model_id="Qwen/Qwen3.5-27B",
        cache_dir=tmp_path,
        runtime_mode="inprocess",
    )

    shards_dir = tmp_path / "layer_shards" / client._safe_model_key(client.model)
    shards_dir.mkdir(parents=True, exist_ok=True)
    (shards_dir / "partial.bin").write_bytes(b"broken")

    prepared = client._prepare_layer_shards_dir()
    assert prepared == shards_dir
    assert shards_dir.exists()
    assert not (shards_dir / "partial.bin").exists()

    quarantine_root = tmp_path / "verify_layer_shards"
    moved = list(quarantine_root.glob("*.partial_*"))
    assert moved


def test_airllm_clean_memory_patch_sets_guard(monkeypatch) -> None:
    from chintu_backend.brain.llm import airllm_client as airllm_client_module

    class _FakeUtils:
        _chintu_clean_memory_patch = False

        @staticmethod
        def clean_memory():
            return None

    original_import_module = airllm_client_module.importlib.import_module

    def _fake_import_module(name: str):
        if name == "airllm.utils":
            return _FakeUtils
        return original_import_module(name)

    monkeypatch.setattr(airllm_client_module.importlib, "import_module", _fake_import_module)
    monkeypatch.setattr(airllm_client_module.os, "name", "nt", raising=False)

    airllm_client_module.AirLLMClient._patch_airllm_clean_memory()

    assert getattr(_FakeUtils, "_chintu_clean_memory_patch", False) is True


def test_airllm_qwen3_layer_name_detection(tmp_path: Path) -> None:
    from chintu_backend.brain.llm.airllm_client import AirLLMClient

    index_payload = {
        "weight_map": {
            "model.language_model.layers.0.self_attn.q_proj.weight": "model.safetensors-00001-of-00011.safetensors",
            "model.language_model.layers.1.self_attn.q_proj.weight": "model.safetensors-00001-of-00011.safetensors",
            "model.language_model.norm.weight": "model.safetensors-00011-of-00011.safetensors",
            "lm_head.weight": "model.safetensors-00011-of-00011.safetensors",
        }
    }
    (tmp_path / "model.safetensors.index.json").write_text(json.dumps(index_payload), encoding="utf-8")
    pairs = AirLLMClient._qwen3_layer_pairs_from_snapshot(tmp_path)
    targets = [target for _, target in pairs]
    assert targets[:3] == [
        "model.language_model.embed_tokens.",
        "model.language_model.layers.0.",
        "model.language_model.layers.1.",
    ]
    assert targets[-2:] == ["model.language_model.norm.", "lm_head."]
