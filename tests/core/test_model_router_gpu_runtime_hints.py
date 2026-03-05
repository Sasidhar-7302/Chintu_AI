from __future__ import annotations

from dataclasses import dataclass

from chintu_backend.core.config import get_config
from chintu_backend.core.model_router import Intent, ModelRouter, RoutingDecision, TaskComplexity


@dataclass
class _Selection:
    role: str
    gpu_id: int | None
    reason: str = "test"
    allow_cpu_fallback: bool = True

    def to_dict(self):
        return {
            "role": self.role,
            "gpu_id": self.gpu_id,
            "reason": self.reason,
            "allow_cpu_fallback": self.allow_cpu_fallback,
        }


class _GPUManager:
    def __init__(self, gpu_id: int | None):
        self.gpu_id = gpu_id
        self.calls = []

    def choose_for_role(self, *, role: str, max_vram_mb: int, allow_cpu_fallback: bool):
        self.calls.append((role, max_vram_mb, allow_cpu_fallback))
        return _Selection(role=role, gpu_id=self.gpu_id, allow_cpu_fallback=allow_cpu_fallback)


class _LocalLLM:
    def __init__(self):
        self.num_gpu = int(getattr(get_config(), "llm_num_gpu", 50) or 50)

    def generate_stream(self, _text: str, _system_prompt: str | None = None):
        yield f"num_gpu={self.num_gpu}"


def _router_with(gpu_id: int | None) -> ModelRouter:
    router = ModelRouter.__new__(ModelRouter)
    router.local_llm = _LocalLLM()
    router.gpu_resource_manager = _GPUManager(gpu_id=gpu_id)
    return router


def _decision(intent: Intent, complexity: TaskComplexity) -> RoutingDecision:
    return RoutingDecision(
        intent=intent,
        complexity=complexity,
        use_llm=True,
        prefer_cloud=False,
        extracted_params={},
    )


def test_local_runtime_hint_uses_role_based_layers_when_gpu_available():
    cfg = get_config()
    router = _router_with(gpu_id=1)
    decision = _decision(Intent.SIMPLE_CHAT, TaskComplexity.SIMPLE)

    overrides, hint = router._local_runtime_hint(decision)

    assert hint["role"] == "background"
    assert hint["selection"]["gpu_id"] == 1
    assert overrides["num_gpu"] == int(getattr(cfg, "gpu_local_background_num_gpu", 20))


def test_local_runtime_hint_forces_cpu_when_budget_insufficient():
    router = _router_with(gpu_id=None)
    decision = _decision(Intent.REASONING, TaskComplexity.COMPLEX_REASONING)

    overrides, hint = router._local_runtime_hint(decision)

    assert hint["role"] == "brain"
    assert hint["selection"]["gpu_id"] is None
    assert overrides["num_gpu"] == 0


def test_run_local_with_runtime_hint_restores_original_num_gpu():
    router = _router_with(gpu_id=None)
    decision = _decision(Intent.RESEARCH, TaskComplexity.MEDIUM)
    original = router.local_llm.num_gpu
    constraints = {}

    observed, hint = router._run_local_with_runtime_hint(
        decision,
        lambda: router.local_llm.num_gpu,
        routing_constraints=constraints,
    )

    assert observed == 0
    assert router.local_llm.num_gpu == original
    assert constraints["local_gpu_hint"]["selection"]["gpu_id"] is None
    assert hint["num_gpu_override"] == 0


def test_stream_with_runtime_hint_applies_and_restores_num_gpu():
    cfg = get_config()
    router = _router_with(gpu_id=0)
    decision = _decision(Intent.CODING, TaskComplexity.COMPLEX)
    original = router.local_llm.num_gpu
    constraints = {}

    chunks = list(
        router._iter_local_stream_with_runtime_hint(
            decision,
            "hello",
            None,
            routing_constraints=constraints,
        )
    )

    expected = int(getattr(cfg, "gpu_local_brain_num_gpu", -1) or -1)
    if expected < 0:
        expected = int(getattr(cfg, "llm_num_gpu", 50) or 50)
    assert chunks == [f"num_gpu={expected}"]
    assert router.local_llm.num_gpu == original
    assert constraints["local_gpu_hint"]["role"] == "brain"

