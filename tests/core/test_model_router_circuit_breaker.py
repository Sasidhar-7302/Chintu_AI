from __future__ import annotations

import types
from types import SimpleNamespace

from chintu_backend.core.model_router import Intent, ModelRouter, RoutingDecision, TaskComplexity
from chintu_backend.core.provider_circuit_breaker import ProviderCircuitBreakerManager


class _FailingClient:
    def __init__(self) -> None:
        self.is_available = True
        self.calls = 0

    def chat(self, _prompt: str, _system_prompt: str | None = None) -> str:
        self.calls += 1
        raise RuntimeError("provider unavailable")


def _decision() -> RoutingDecision:
    return RoutingDecision(
        intent=Intent.REASONING,
        complexity=TaskComplexity.COMPLEX,
        use_llm=True,
        prefer_cloud=True,
        extracted_params={},
    )


def test_try_cloud_provider_honors_open_circuit(monkeypatch):
    from chintu_backend.core import model_router as model_router_module

    monkeypatch.setattr(model_router_module, "HAS_METRICS", False)

    router = ModelRouter.__new__(ModelRouter)
    router.provider_circuit_breaker = ProviderCircuitBreakerManager(
        enabled=True,
        failure_threshold=1,
        recovery_seconds=60.0,
        half_open_successes=1,
    )

    attempts: list[dict] = []
    client = _FailingClient()

    def _provider_client(self, provider: str):
        assert provider == "groq"
        return client

    def _record_provider_attempt(self, provider: str, **kwargs):
        payload = {"provider": provider}
        payload.update(kwargs)
        attempts.append(payload)

    router._provider_client = types.MethodType(_provider_client, router)
    router._record_provider_attempt = types.MethodType(_record_provider_attempt, router)

    first = router._try_cloud_provider(
        "groq",
        "hello",
        "system",
        _decision(),
        cloud_allowed=True,
        budget=None,
        cacheable=False,
        use_budget=True,
    )
    second = router._try_cloud_provider(
        "groq",
        "hello",
        "system",
        _decision(),
        cloud_allowed=True,
        budget=None,
        cacheable=False,
        use_budget=True,
    )

    assert first is None
    assert second is None
    assert client.calls == 1
    assert attempts[-1].get("reason") == "circuit_open"


def test_get_provider_health_marks_open_circuit_unavailable(monkeypatch):
    from chintu_backend.core import model_router as model_router_module

    cfg = SimpleNamespace(
        ollama_model="qwen2.5-coder:7b",
        nvidia_api_key="",
        groq_api_key="test-key",
        google_ai_key="",
        deepseek_api_key="",
        nvidia_model="",
        groq_model="llama-3.1-8b-instant",
        gemini_model="",
        deepseek_model="",
    )
    monkeypatch.setattr(model_router_module, "get_config", lambda: cfg)

    router = ModelRouter.__new__(ModelRouter)
    router.local_llm = None
    router.nvidia = None
    router.gemini = None
    router.deepseek = None

    class _Client:
        is_available = True
        model = "llama-3.1-8b-instant"

    router.groq = _Client()
    now = [0.0]
    breaker = ProviderCircuitBreakerManager(
        enabled=True,
        failure_threshold=1,
        recovery_seconds=60.0,
        half_open_successes=1,
        now_fn=lambda: now[0],
    )
    breaker.record_failure("groq")
    router.provider_circuit_breaker = breaker

    health = router.get_provider_health()

    assert health["groq"]["available"] is False
    assert health["groq"]["reason"] == "circuit_open"
    assert health["groq"]["circuit"]["state"] == "open"
