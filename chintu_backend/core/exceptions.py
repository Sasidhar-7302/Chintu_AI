"""Shared exception taxonomy for Chintu core services."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ChintuError(Exception):
    """Base typed exception for recoverable Chintu service errors."""

    message: str
    code: str = "chintu_error"
    component: str = "core"
    details: Dict[str, Any] = field(default_factory=dict)
    cause: Optional[Exception] = None

    def __str__(self) -> str:
        base = f"[{self.component}:{self.code}] {self.message}"
        if self.details:
            return f"{base} | details={self.details}"
        return base


class ValidationFailure(ChintuError):
    def __init__(self, message: str, *, component: str = "validation", details: Optional[Dict[str, Any]] = None):
        super().__init__(message=message, code="validation_failure", component=component, details=details or {})


class PolicyViolation(ChintuError):
    def __init__(self, message: str, *, component: str = "policy", details: Optional[Dict[str, Any]] = None):
        super().__init__(message=message, code="policy_violation", component=component, details=details or {})


class ExternalServiceFailure(ChintuError):
    def __init__(self, message: str, *, component: str = "external_service", details: Optional[Dict[str, Any]] = None):
        super().__init__(message=message, code="external_service_failure", component=component, details=details or {})


class ProviderUnavailable(ExternalServiceFailure):
    def __init__(self, provider: str, reason: str = ""):
        super().__init__(
            message=f"Provider '{provider}' unavailable",
            component="provider",
            details={"provider": provider, "reason": reason},
        )


class QualityGateFailure(ChintuError):
    def __init__(self, message: str, *, details: Optional[Dict[str, Any]] = None):
        super().__init__(message=message, code="quality_gate_failed", component="quality_gate", details=details or {})

