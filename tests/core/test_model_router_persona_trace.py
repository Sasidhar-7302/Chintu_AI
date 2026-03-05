from __future__ import annotations

import threading
from types import SimpleNamespace

from chintu_backend.core.model_router import ModelRouter
from chintu_backend.core.persona_registry import PersonaRegistry


def test_model_router_records_persona_in_execution_trace():
    router = ModelRouter.__new__(ModelRouter)
    router.persona_registry = PersonaRegistry(enabled=True, specs=None)
    router._execution_trace_local = threading.local()
    router.arbiter_telemetry = None

    router._reset_execution_trace("debug my python app")
    decision = SimpleNamespace(intent=SimpleNamespace(value="coding"))
    persona = router._select_persona_overlay("debug my python app", decision)
    trace = router.consume_execution_trace()

    assert persona.get("name") == "coding"
    assert isinstance(trace.get("persona"), dict)
    assert trace["persona"].get("name") == "coding"
