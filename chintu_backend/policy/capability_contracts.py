"""Capability contracts for policy evaluation."""

from enum import Enum
from dataclasses import dataclass, field
from typing import List


class RiskLevel(Enum):
    """Risk levels for capability actions."""

    NONE = "none"           # Time queries, help, status - zero risk
    LOW = "low"             # Read operations, simple queries
    MEDIUM = "medium"       # Browser clicks, data transfers, external calls
    HIGH = "high"           # Destructive memory ops, file modifications
    CRITICAL = "critical"   # System commands, credential access


@dataclass
class CapabilityContract:
    """
    Contract declaring capability metadata for policy evaluation.

    Each capability should declare a contract so the policy engine can make
    consistent decisions about confirmation, internet requirements, and risk.
    """

    risk_level: RiskLevel = RiskLevel.LOW
    requires_internet: bool = False
    requires_confirmation: bool = False
    can_run_background: bool = True
    can_run_low_battery: bool = True
    side_effects: List[str] = field(default_factory=list)
    inputs: List[str] = field(default_factory=list)
    outputs: List[str] = field(default_factory=list)
    description: str = ""
