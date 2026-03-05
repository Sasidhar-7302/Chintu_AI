"""Phase 8 security/control replay gate."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from chintu_backend.core.capabilities import ActionResult, Capability, CapabilityRegistry, CapabilityType
from chintu_backend.policy.capability_contracts import CapabilityContract, RiskLevel
from chintu_backend.policy.unified_resolver import ResolverDecision, UnifiedPolicyResolver
from chintu_backend.policy import action_approvals as approvals


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def run_replay(out_dir: Path) -> dict:
    workspace = out_dir / "phase8_security_tmp"
    workspace.mkdir(parents=True, exist_ok=True)
    cfg = SimpleNamespace(
        data_dir=workspace,
        security_unified_policy_enabled=True,
        security_runtime_profile="balanced",
        security_payment_hard_block=True,
        security_publish_confirmation_required=True,
        security_destructive_confirmation_required=True,
        action_approval_enabled=True,
        action_approval_reuse_enabled=True,
        action_approval_ttl_minutes=30,
        action_approval_path=workspace / "action_approvals.json",
        exec_approval_enabled=False,
        exec_approval_ttl_minutes=10,
        exec_approval_path=workspace / "exec_approvals.json",
    )

    # Patch config lookups used by approval ledgers in this replay.
    import chintu_backend.core.config as cfg_module

    old_cfg_fn = cfg_module.get_config
    old_approval_cfg_fn = approvals.get_config
    cfg_module.get_config = lambda: cfg
    approvals.get_config = lambda: cfg
    approvals.reset_action_approval_ledger()

    try:
        resolver = UnifiedPolicyResolver(cfg)
        medium_browser = CapabilityContract(
            risk_level=RiskLevel.MEDIUM,
            requires_internet=True,
            requires_confirmation=False,
            side_effects=["browser_action"],
        )

        safe_mode = resolver.resolve(
            capability_name="browser_act_ref",
            contract=medium_browser,
            context={"_request_text": "click publish", "_runtime_profile": "safe_mode"},
        )
        high_trust = resolver.resolve(
            capability_name="list_files",
            contract=CapabilityContract(risk_level=RiskLevel.LOW),
            context={"_request_text": "list files", "_runtime_profile": "high_trust"},
        )
        payment = resolver.resolve(
            capability_name="click_link",
            contract=medium_browser,
            context={"_request_text": "click checkout"},
        )

        # Verify approval ledger write path by confirming a sensitive action in CapabilityRegistry.
        registry = CapabilityRegistry()
        registry.register(
            Capability(
                name="click_link",
                triggers=["publish"],
                handler=lambda _text, _ctx: ActionResult.ok("done", capability="click_link"),
                requires_confirmation=True,
                capability_type=CapabilityType.AUTOMATION,
                description="phase8 replay submit",
            )
        )
        pending = registry.execute(
            registry.get("click_link"),
            "publish this post",
            context={},
        )
        confirmed = registry.confirm_pending() if pending and pending.requires_confirmation else None
        ledger_rows = approvals.get_action_approval_ledger().recent(limit=10)

        checks = {
            "safe_mode_submit_confirmation": safe_mode.decision == ResolverDecision.confirm,
            "high_trust_low_risk_allow": high_trust.decision == ResolverDecision.allow,
            "payment_blocked": payment.decision == ResolverDecision.deny,
            "approval_confirmation_executed": bool(confirmed and confirmed.success),
            "approval_ledger_written": bool(ledger_rows),
        }
        success = all(checks.values())
        return {
            "phase": "phase8",
            "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "success": success,
            "checks": checks,
            "resolver": {
                "safe_mode": safe_mode.to_dict(),
                "high_trust": high_trust.to_dict(),
                "payment": payment.to_dict(),
            },
            "approval_ledger_entries": ledger_rows,
        }
    finally:
        cfg_module.get_config = old_cfg_fn
        approvals.get_config = old_approval_cfg_fn
        approvals.reset_action_approval_ledger()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Phase 8 security/control replay checks.")
    parser.add_argument("--out-dir", default="generated_reports")
    args = parser.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    report = run_replay(out_dir)
    report_path = out_dir / f"phase8_security_doctor_{_now()}.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    print(f"Wrote: {report_path}")
    print(json.dumps({"success": report["success"], "checks": report["checks"]}, indent=2))
    return 0 if bool(report.get("success")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
