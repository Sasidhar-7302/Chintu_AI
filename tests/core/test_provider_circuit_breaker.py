from __future__ import annotations

from chintu_backend.core.provider_circuit_breaker import (
    CircuitState,
    ProviderCircuitBreakerManager,
)


def test_circuit_opens_after_threshold_and_blocks_until_recovery_window():
    now = [100.0]
    breaker = ProviderCircuitBreakerManager(
        enabled=True,
        failure_threshold=2,
        recovery_seconds=30.0,
        half_open_successes=1,
        now_fn=lambda: now[0],
    )

    assert breaker.allow_call("groq") is True
    breaker.record_failure("groq")
    assert breaker.get_state("groq")["state"] == CircuitState.CLOSED.value

    breaker.record_failure("groq")
    assert breaker.get_state("groq")["state"] == CircuitState.OPEN.value
    assert breaker.allow_call("groq") is False

    now[0] = 131.0
    assert breaker.allow_call("groq") is True
    assert breaker.get_state("groq")["state"] == CircuitState.HALF_OPEN.value

    breaker.record_success("groq")
    assert breaker.get_state("groq")["state"] == CircuitState.CLOSED.value


def test_half_open_failure_reopens_circuit():
    now = [10.0]
    breaker = ProviderCircuitBreakerManager(
        enabled=True,
        failure_threshold=1,
        recovery_seconds=5.0,
        half_open_successes=2,
        now_fn=lambda: now[0],
    )

    breaker.record_failure("nvidia")
    assert breaker.get_state("nvidia")["state"] == CircuitState.OPEN.value

    now[0] = 16.0
    assert breaker.allow_call("nvidia") is True
    assert breaker.get_state("nvidia")["state"] == CircuitState.HALF_OPEN.value

    breaker.record_failure("nvidia")
    assert breaker.get_state("nvidia")["state"] == CircuitState.OPEN.value

