"""Execution contracts for deterministic completion checks (Phase 2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Tuple


class FailureTaxonomy(str, Enum):
    missing_dependency = "missing_dependency"
    blocked_by_policy = "blocked_by_policy"
    verification_failed = "verification_failed"
    timeout = "timeout"
    cancelled = "cancelled"
    execution_failed = "execution_failed"
    unknown = "unknown"


@dataclass(frozen=True)
class RetryPolicy:
    max_verification_attempts: int = 1
    retry_on_verification_failure: bool = False


@dataclass(frozen=True)
class ExecutionContract:
    capability: str
    expected_artifacts: Tuple[str, ...] = field(default_factory=tuple)
    verification_hooks: Tuple[str, ...] = field(default_factory=tuple)
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    enforce: bool = False

    def required_checks(self) -> Tuple[str, ...]:
        ordered: List[str] = []
        for item in list(self.expected_artifacts) + list(self.verification_hooks):
            if item and item not in ordered:
                ordered.append(item)
        return tuple(ordered)


@dataclass(frozen=True)
class ContractEvaluation:
    ok: bool
    failure_type: str = ""
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": bool(self.ok),
            "failure_type": str(self.failure_type or ""),
            "detail": str(self.detail or ""),
        }


_DEFAULT_CONTRACTS: Dict[str, ExecutionContract] = {
    "read_file": ExecutionContract(
        capability="read_file",
        expected_artifacts=("path_exists",),
        verification_hooks=("path_exists",),
        retry_policy=RetryPolicy(max_verification_attempts=1, retry_on_verification_failure=False),
        enforce=True,
    ),
    "list_files": ExecutionContract(
        capability="list_files",
        expected_artifacts=("path_exists",),
        verification_hooks=("path_exists",),
        retry_policy=RetryPolicy(max_verification_attempts=1, retry_on_verification_failure=False),
        enforce=True,
    ),
    "write_file": ExecutionContract(
        capability="write_file",
        expected_artifacts=("path_exists",),
        verification_hooks=("path_exists",),
        retry_policy=RetryPolicy(max_verification_attempts=2, retry_on_verification_failure=True),
        enforce=True,
    ),
    "move_file": ExecutionContract(
        capability="move_file",
        expected_artifacts=("path_exists",),
        verification_hooks=("path_exists",),
        retry_policy=RetryPolicy(max_verification_attempts=2, retry_on_verification_failure=True),
        enforce=True,
    ),
    "screenshot": ExecutionContract(
        capability="screenshot",
        expected_artifacts=("path_exists",),
        verification_hooks=("path_exists",),
        retry_policy=RetryPolicy(max_verification_attempts=2, retry_on_verification_failure=True),
        enforce=True,
    ),
    "open_app": ExecutionContract(
        capability="open_app",
        retry_policy=RetryPolicy(max_verification_attempts=2, retry_on_verification_failure=True),
        enforce=True,
    ),
    "open_url": ExecutionContract(
        capability="open_url",
        verification_hooks=("url_valid",),
        retry_policy=RetryPolicy(max_verification_attempts=1, retry_on_verification_failure=False),
        enforce=True,
    ),
    "web_search": ExecutionContract(
        capability="web_search",
        verification_hooks=("url_valid",),
        retry_policy=RetryPolicy(max_verification_attempts=1, retry_on_verification_failure=False),
        enforce=True,
    ),
    "live_search": ExecutionContract(
        capability="live_search",
        verification_hooks=("url_valid",),
        retry_policy=RetryPolicy(max_verification_attempts=1, retry_on_verification_failure=False),
        enforce=True,
    ),
    "browse_url": ExecutionContract(
        capability="browse_url",
        verification_hooks=("url_valid", "content_nonempty"),
        retry_policy=RetryPolicy(max_verification_attempts=1, retry_on_verification_failure=False),
        enforce=True,
    ),
    "open_browser": ExecutionContract(
        capability="open_browser",
        verification_hooks=("url_valid",),
        retry_policy=RetryPolicy(max_verification_attempts=1, retry_on_verification_failure=False),
        enforce=True,
    ),
    "browser_search": ExecutionContract(
        capability="browser_search",
        verification_hooks=("url_valid",),
        retry_policy=RetryPolicy(max_verification_attempts=1, retry_on_verification_failure=False),
        enforce=True,
    ),
    "page_content": ExecutionContract(
        capability="page_content",
        verification_hooks=("url_valid",),
        retry_policy=RetryPolicy(max_verification_attempts=1, retry_on_verification_failure=False),
        enforce=True,
    ),
    "click_link": ExecutionContract(
        capability="click_link",
        verification_hooks=("url_valid",),
        retry_policy=RetryPolicy(max_verification_attempts=1, retry_on_verification_failure=False),
        enforce=True,
    ),
    "browser_snapshot_refs": ExecutionContract(
        capability="browser_snapshot_refs",
        verification_hooks=("url_valid",),
        retry_policy=RetryPolicy(max_verification_attempts=1, retry_on_verification_failure=False),
        enforce=True,
    ),
    "browser_act_ref": ExecutionContract(
        capability="browser_act_ref",
        verification_hooks=("url_valid",),
        retry_policy=RetryPolicy(max_verification_attempts=1, retry_on_verification_failure=False),
        enforce=True,
    ),
    "organize_downloads": ExecutionContract(
        capability="organize_downloads",
        verification_hooks=("path_exists",),
        retry_policy=RetryPolicy(max_verification_attempts=1, retry_on_verification_failure=False),
        enforce=True,
    ),
    "terminal_exec": ExecutionContract(
        capability="terminal_exec",
        verification_hooks=("exit_code_zero",),
        retry_policy=RetryPolicy(max_verification_attempts=1, retry_on_verification_failure=False),
        enforce=True,
    ),
}


def get_execution_contract(capability_name: str) -> ExecutionContract:
    cap = str(capability_name or "").strip()
    if not cap:
        return ExecutionContract(capability="")
    if cap in _DEFAULT_CONTRACTS:
        return _DEFAULT_CONTRACTS[cap]
    if cap.startswith("skill::"):
        return ExecutionContract(capability=cap, enforce=False)
    return ExecutionContract(capability=cap, enforce=False)


def _checks_by_kind(verification: Dict[str, Any]) -> Dict[str, List[bool]]:
    grouped: Dict[str, List[bool]] = {}
    checks = verification.get("checks") if isinstance(verification, dict) else None
    if not isinstance(checks, list):
        return grouped
    for row in checks:
        if not isinstance(row, dict):
            continue
        kind = str(row.get("kind") or "").strip()
        if not kind:
            continue
        grouped.setdefault(kind, []).append(bool(row.get("ok")))
    return grouped


def evaluate_execution_contract(contract: ExecutionContract, verification: Dict[str, Any]) -> ContractEvaluation:
    if not contract.enforce:
        return ContractEvaluation(ok=True, detail="contract not enforced")

    required = contract.required_checks()
    if not required:
        checks = (verification or {}).get("checks") if isinstance(verification, dict) else None
        # Some capabilities are observable but have no deterministic verifier yet.
        # Do not hard-fail these when no checks are emitted.
        if not checks:
            return ContractEvaluation(ok=True, detail="no deterministic checks available")
        ok = bool((verification or {}).get("ok"))
        if ok:
            return ContractEvaluation(ok=True, detail="verification ok")
        return ContractEvaluation(
            ok=False,
            failure_type=FailureTaxonomy.verification_failed.value,
            detail="verification reported failure",
        )

    grouped = _checks_by_kind(verification or {})
    for req in required:
        hits = grouped.get(req) or []
        if not hits or not any(hits):
            return ContractEvaluation(
                ok=False,
                failure_type=FailureTaxonomy.verification_failed.value,
                detail=f"missing required verification check: {req}",
            )
    return ContractEvaluation(ok=True, detail="all required checks passed")


def classify_failure_type(
    message: str,
    contract_eval: ContractEvaluation | None = None,
) -> str:
    if contract_eval and not contract_eval.ok and contract_eval.failure_type:
        return str(contract_eval.failure_type)

    low = str(message or "").lower()
    if not low:
        return FailureTaxonomy.unknown.value
    if (
        "no module named" in low
        or "missing library" in low
        or "not installed" in low
        or "no such file or directory" in low
        or "command not found" in low
        or "is not recognized as an internal or external command" in low
    ):
        return FailureTaxonomy.missing_dependency.value
    if "need your confirmation" in low or "blocked" in low or "not allowed" in low:
        return FailureTaxonomy.blocked_by_policy.value
    if "timed out" in low or "timeout" in low:
        return FailureTaxonomy.timeout.value
    if "cancelled" in low or "canceled" in low:
        return FailureTaxonomy.cancelled.value
    if "verify" in low or "verification" in low:
        return FailureTaxonomy.verification_failed.value
    return FailureTaxonomy.execution_failed.value


def contract_to_dict(contract: ExecutionContract) -> Dict[str, Any]:
    return {
        "capability": contract.capability,
        "expected_artifacts": list(contract.expected_artifacts),
        "verification_hooks": list(contract.verification_hooks),
        "retry_policy": {
            "max_verification_attempts": int(contract.retry_policy.max_verification_attempts),
            "retry_on_verification_failure": bool(contract.retry_policy.retry_on_verification_failure),
        },
        "enforce": bool(contract.enforce),
    }
