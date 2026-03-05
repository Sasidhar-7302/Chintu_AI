"""Provider-level circuit breaker for cloud model routing.

This module keeps provider failure storms from repeatedly hammering unhealthy
APIs. It is intentionally lightweight and in-process for local-first runtime.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, Optional


class CircuitState(str, Enum):
    """Circuit breaker state per provider."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class ProviderCircuit:
    """Mutable state for one provider circuit."""

    state: CircuitState = CircuitState.CLOSED
    failures: int = 0
    successes: int = 0
    opened_at: float = 0.0


class ProviderCircuitBreakerManager:
    """Tracks and updates provider circuit state."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        failure_threshold: int = 3,
        recovery_seconds: float = 45.0,
        half_open_successes: int = 1,
        now_fn: Optional[Callable[[], float]] = None,
    ) -> None:
        self.enabled = bool(enabled)
        self.failure_threshold = max(1, int(failure_threshold))
        self.recovery_seconds = max(1.0, float(recovery_seconds))
        self.half_open_successes = max(1, int(half_open_successes))
        self._now = now_fn or time.time
        self._circuits: Dict[str, ProviderCircuit] = {}

    @classmethod
    def from_config(cls, config) -> "ProviderCircuitBreakerManager":
        return cls(
            enabled=bool(getattr(config, "provider_circuit_breaker_enabled", True)),
            failure_threshold=int(getattr(config, "provider_circuit_failure_threshold", 3) or 3),
            recovery_seconds=float(getattr(config, "provider_circuit_recovery_seconds", 45.0) or 45.0),
            half_open_successes=int(getattr(config, "provider_circuit_half_open_successes", 1) or 1),
        )

    def allow_call(self, provider: str) -> bool:
        if not self.enabled:
            return True
        circuit = self._ensure(provider)
        if circuit.state != CircuitState.OPEN:
            return True
        if (self._now() - circuit.opened_at) >= self.recovery_seconds:
            circuit.state = CircuitState.HALF_OPEN
            circuit.successes = 0
            return True
        return False

    def record_success(self, provider: str) -> None:
        if not self.enabled:
            return
        circuit = self._ensure(provider)
        if circuit.state == CircuitState.HALF_OPEN:
            circuit.successes += 1
            if circuit.successes >= self.half_open_successes:
                self._close(circuit)
            return
        self._close(circuit)

    def record_failure(self, provider: str) -> None:
        if not self.enabled:
            return
        circuit = self._ensure(provider)
        if circuit.state == CircuitState.HALF_OPEN:
            self._open(circuit)
            return
        circuit.failures += 1
        if circuit.failures >= self.failure_threshold:
            self._open(circuit)

    def get_state(self, provider: str) -> Dict[str, object]:
        circuit = self._ensure(provider)
        return {
            "provider": provider,
            "state": circuit.state.value,
            "failures": int(circuit.failures),
            "successes": int(circuit.successes),
            "opened_at": float(circuit.opened_at),
            "enabled": bool(self.enabled),
        }

    def _ensure(self, provider: str) -> ProviderCircuit:
        key = str(provider or "").strip().lower()
        if key not in self._circuits:
            self._circuits[key] = ProviderCircuit()
        return self._circuits[key]

    def _open(self, circuit: ProviderCircuit) -> None:
        circuit.state = CircuitState.OPEN
        circuit.opened_at = self._now()
        circuit.successes = 0
        if circuit.failures < self.failure_threshold:
            circuit.failures = self.failure_threshold

    def _close(self, circuit: ProviderCircuit) -> None:
        circuit.state = CircuitState.CLOSED
        circuit.failures = 0
        circuit.successes = 0
        circuit.opened_at = 0.0

