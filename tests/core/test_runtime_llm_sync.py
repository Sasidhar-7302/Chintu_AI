from __future__ import annotations

from types import SimpleNamespace

from chintu_backend.core.runtime_llm_sync import sync_runtime_llm_clients


class OllamaStub:
    def __init__(self) -> None:
        self.model = "old-model"
        self.model_name = "old-model"
        self.num_gpu = 55
        self.num_threads = 8
        self.num_ctx = 8192
        self.max_tokens = 4096
        self.temperature = 0.9


class AdapterStub:
    def __init__(self) -> None:
        self.base_model = "adapter-base"
        self.max_tokens = 4096
        self.temperature = 0.8


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        ollama_model="qwen2.5-coder:7b",
        llm_num_gpu=0,
        llm_num_threads=4,
        llm_num_ctx=4096,
        llm_max_tokens=1024,
        llm_temperature=0.2,
    )


def test_sync_runtime_llm_clients_updates_ollama_targets():
    config = _config()
    client = OllamaStub()

    receipt = sync_runtime_llm_clients(config, [client])

    assert receipt["changed_targets"] == 1
    assert client.model == "qwen2.5-coder:7b"
    assert client.model_name == "qwen2.5-coder:7b"
    assert client.num_gpu == 0
    assert client.num_threads == 4
    assert client.num_ctx == 4096
    assert client.max_tokens == 1024
    assert abs(client.temperature - 0.2) < 1e-6


def test_sync_runtime_llm_clients_keeps_non_ollama_model_identity():
    config = _config()
    adapter = AdapterStub()

    receipt = sync_runtime_llm_clients(config, [adapter])

    assert receipt["changed_targets"] == 1
    assert adapter.base_model == "adapter-base"
    assert adapter.max_tokens == 1024
    assert abs(adapter.temperature - 0.2) < 1e-6


def test_sync_runtime_llm_clients_deduplicates_targets():
    config = _config()
    client = OllamaStub()

    receipt = sync_runtime_llm_clients(config, [client, client, None])

    assert receipt["scanned_targets"] == 1
    assert receipt["changed_targets"] == 1

