"""Unified policy resolver (tool profile + agent profile + runtime profile + context risk)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

from chintu_backend.policy.capability_contracts import CapabilityContract, RiskLevel
from chintu_backend.policy.action_risk import build_action_scope
from chintu_backend.policy.runtime_profiles import resolve_runtime_profile

logger = logging.getLogger(__name__)


class ResolverDecision(str, Enum):
    none = "none"
    allow = "allow"
    confirm = "confirm"
    deny = "deny"


@dataclass(frozen=True)
class ResolverOutcome:
    decision: ResolverDecision
    reason: str
    runtime_profile: str
    categories: list[str]
    scope_hash: str
    ledger_hit: bool = False
    risk_level: RiskLevel = RiskLevel.LOW

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision.value,
            "reason": self.reason,
            "runtime_profile": self.runtime_profile,
            "categories": list(self.categories),
            "scope_hash": self.scope_hash,
            "ledger_hit": bool(self.ledger_hit),
            "risk_level": self.risk_level.value,
        }


class UnifiedPolicyResolver:
    """Applies cross-cutting policy controls before default policy rules."""

    def __init__(self, config):
        self.config = config

    def resolve(
        self,
        *,
        capability_name: str,
        contract: CapabilityContract,
        context: Optional[Dict[str, Any]] = None,
    ) -> ResolverOutcome:
        cap = str(capability_name or "").strip()
        ctx = context if isinstance(context, dict) else {}
        request_text = str(ctx.get("_request_text") or ctx.get("request_text") or "").strip()
        safe_mode_channels = getattr(self.config, "workspace_untrusted_channels", [])
        profile = resolve_runtime_profile(
            ctx,
            default_profile=getattr(self.config, "security_runtime_profile", "balanced"),
            safe_mode_channels=safe_mode_channels,
        )

        scope = build_action_scope(cap, request_text, ctx)
        categories = list(scope.categories or [])

        # Agent-level deny still wins at this layer for consistency.
        agent_policy = ctx.get("_agent_policy")
        if agent_policy and hasattr(agent_policy, "allows"):
            try:
                if not bool(agent_policy.allows(cap)):
                    return ResolverOutcome(
                        decision=ResolverDecision.deny,
                        reason=f"Agent policy denied: {cap}",
                        runtime_profile=profile,
                        categories=categories,
                        scope_hash=scope.scope_hash,
                        risk_level=RiskLevel.HIGH,
                    )
            except Exception:
                pass

        # Optional approval cache reuse for risky non-payment actions.
        ledger_hit = False
        reuse_enabled = bool(getattr(self.config, "action_approval_reuse_enabled", True))
        if reuse_enabled and categories:
            try:
                from chintu_backend.policy.action_approvals import get_action_approval_ledger

                ledger = get_action_approval_ledger()
                if "payment" not in categories:
                    ledger_hit = bool(ledger.is_approved(scope.scope_hash))
            except Exception:
                ledger_hit = False

        if "payment" in categories:
            hard_block = bool(getattr(self.config, "security_payment_hard_block", False))
            if hard_block:
                return ResolverOutcome(
                    decision=ResolverDecision.deny,
                    reason="Payment/checkout action blocked by policy.",
                    runtime_profile=profile,
                    categories=categories,
                    scope_hash=scope.scope_hash,
                    ledger_hit=ledger_hit,
                    risk_level=RiskLevel.CRITICAL,
                )
            return ResolverOutcome(
                decision=ResolverDecision.confirm,
                reason="Payment/checkout action requires explicit confirmation.",
                runtime_profile=profile,
                categories=categories,
                scope_hash=scope.scope_hash,
                ledger_hit=ledger_hit,
                risk_level=RiskLevel.HIGH,
            )

        if "browser_submit" in categories and bool(getattr(self.config, "security_publish_confirmation_required", True)):
            if ledger_hit:
                return ResolverOutcome(
                    decision=ResolverDecision.allow,
                    reason="Reusing recent approval for sensitive browser submit action.",
                    runtime_profile=profile,
                    categories=categories,
                    scope_hash=scope.scope_hash,
                    ledger_hit=True,
                    risk_level=RiskLevel.MEDIUM,
                )
            return ResolverOutcome(
                decision=ResolverDecision.confirm,
                reason="Sensitive browser submit action requires explicit confirmation.",
                runtime_profile=profile,
                categories=categories,
                scope_hash=scope.scope_hash,
                ledger_hit=False,
                risk_level=RiskLevel.HIGH,
            )

        if "destructive" in categories and bool(getattr(self.config, "security_destructive_confirmation_required", True)):
            if ledger_hit and profile == "high_trust":
                return ResolverOutcome(
                    decision=ResolverDecision.allow,
                    reason="Reusing recent approval for destructive action (high-trust mode).",
                    runtime_profile=profile,
                    categories=categories,
                    scope_hash=scope.scope_hash,
                    ledger_hit=True,
                    risk_level=RiskLevel.HIGH,
                )
            return ResolverOutcome(
                decision=ResolverDecision.confirm,
                reason="Destructive action requires explicit confirmation.",
                runtime_profile=profile,
                categories=categories,
                scope_hash=scope.scope_hash,
                ledger_hit=ledger_hit,
                risk_level=RiskLevel.HIGH,
            )

        if profile == "safe_mode":
            if contract.risk_level in {RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL} and bool(contract.side_effects):
                return ResolverOutcome(
                    decision=ResolverDecision.confirm,
                    reason="Safe-mode requires confirmation for medium/high-risk side effects.",
                    runtime_profile=profile,
                    categories=categories,
                    scope_hash=scope.scope_hash,
                    ledger_hit=ledger_hit,
                    risk_level=contract.risk_level,
                )

        if profile == "high_trust" and contract.risk_level == RiskLevel.LOW and not contract.requires_confirmation:
            return ResolverOutcome(
                decision=ResolverDecision.allow,
                reason="High-trust mode auto-allows low-risk actions.",
                runtime_profile=profile,
                categories=categories,
                scope_hash=scope.scope_hash,
                ledger_hit=ledger_hit,
                risk_level=contract.risk_level,
            )

        return ResolverOutcome(
            decision=ResolverDecision.none,
            reason="No unified-policy override.",
            runtime_profile=profile,
            categories=categories,
            scope_hash=scope.scope_hash,
            ledger_hit=ledger_hit,
            risk_level=contract.risk_level,
        )
