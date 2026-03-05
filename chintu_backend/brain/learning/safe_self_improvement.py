"""Phase 15 safe self-improvement manager."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from chintu_backend.core.arbiter_telemetry import get_arbiter_telemetry
from chintu_backend.core.config import get_config
from chintu_backend.core.execution_contracts import FailureTaxonomy, classify_failure_type

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _slug(text: str, *, max_len: int = 60) -> str:
    clean = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return (clean or "task")[:max_len].strip("-") or "task"


def _extract_dependency_name(message: str) -> str:
    low = str(message or "")
    m = re.search(r"No module named ['\"]?([A-Za-z0-9_.-]+)['\"]?", low, flags=re.IGNORECASE)
    if m:
        return str(m.group(1) or "").strip()
    m = re.search(r"missing (?:library|dependency)\s*[:=]\s*([A-Za-z0-9_.-]+)", low, flags=re.IGNORECASE)
    if m:
        return str(m.group(1) or "").strip()
    return ""


class SafeSelfImprovementManager:
    """Generates unblock plans, gated skill upgrades, and routing tuning reports."""

    def __init__(self, config: Optional[Any] = None) -> None:
        self.config = config or get_config()
        self.enabled = bool(getattr(self.config, "phase15_enabled", True))
        self.base_dir = Path(getattr(self.config, "phase15_dir", self.config.data_dir / "self_improvement"))
        self.gap_dir = Path(getattr(self.config, "phase15_gap_plans_dir", self.base_dir / "gap_plans"))
        self.change_dir = Path(getattr(self.config, "phase15_change_reports_dir", self.base_dir / "change_reports"))
        self.routing_dir = Path(getattr(self.config, "phase15_routing_reports_dir", self.base_dir / "routing_reports"))
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.gap_dir.mkdir(parents=True, exist_ok=True)
        self.change_dir.mkdir(parents=True, exist_ok=True)
        self.routing_dir.mkdir(parents=True, exist_ok=True)

    def create_unblock_plan(
        self,
        *,
        task_text: str,
        failure_message: str,
        capability_name: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a structured unblock plan and optional gated skill-upgrade report."""
        if not self.enabled:
            return {}

        task = str(task_text or "").strip()
        message = str(failure_message or "").strip()
        cap_name = str(capability_name or "").strip()
        failure_type = classify_failure_type(message)
        missing_capability = self._looks_like_missing_capability(message=message, capability_name=cap_name)
        if missing_capability:
            failure_type = "missing_capability"

        dependency_name = _extract_dependency_name(message)
        proposal_info: Dict[str, Any] = {}
        change_report_info: Dict[str, Any] = {}

        skill_family = self._derive_skill_family(task)
        risks = self._build_risks(failure_type)
        tests = self._build_tests(task, failure_type)
        dependencies: List[str] = []
        if dependency_name:
            dependencies.append(dependency_name)
        if failure_type == FailureTaxonomy.missing_dependency.value and not dependencies:
            dependencies.append("missing_dependency_from_error")

        unblock_steps = self._build_unblock_steps(
            failure_type=failure_type,
            task_text=task,
            dependency_name=dependency_name,
            skill_family=skill_family,
        )
        tools = self._suggest_tools(task, failure_type)

        if missing_capability and bool(getattr(self.config, "phase15_auto_propose_skill_on_missing_capability", True)):
            proposal_info = self._draft_skill_upgrade(task, context=context or {})
            proposal_id = str(proposal_info.get("proposal_id") or "")
            if proposal_id:
                change_report_info = self._precheck_proposal(proposal_id)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        plan_id = f"gap_{stamp}_{_slug(task, max_len=42)}"
        plan_path = self.gap_dir / f"{plan_id}.json"

        plan: Dict[str, Any] = {
            "id": plan_id,
            "created_at": _utc_now(),
            "task_text": task,
            "capability_name": cap_name,
            "failure_message": message[:2000],
            "failure_type": failure_type,
            "skill_family": skill_family,
            "suggested_tools": tools,
            "dependencies": dependencies,
            "risks": risks,
            "targeted_tests": tests,
            "unblock_steps": unblock_steps,
            "requires_explicit_approval": True,
            "proposal": proposal_info,
            "change_report": change_report_info,
            "status": "blocked_with_unblock_plan",
        }
        plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=True), encoding="utf-8")
        plan["plan_path"] = str(plan_path)
        plan["message"] = self._build_user_message(plan)

        try:
            from chintu_backend.brain.learning.learning_engine import get_learning_engine

            get_learning_engine().record_gap(
                gap=f"Blocked with unblock plan for task: {task[:180]}",
                context={
                    "phase": "phase15",
                    "failure_type": failure_type,
                    "capability": cap_name,
                    "plan_path": str(plan_path),
                },
            )
        except Exception:
            pass

        return plan

    def tune_routing_from_telemetry(self, *, hours: int = 72, apply: bool = False) -> Dict[str, Any]:
        """Generate an A/B-gated routing-priority proposal from telemetry."""
        telemetry = get_arbiter_telemetry().summarize(hours=max(1, int(hours)), limit=2000)
        providers = telemetry.get("providers") if isinstance(telemetry, dict) else {}
        providers = providers if isinstance(providers, dict) else {}

        min_events = int(getattr(self.config, "phase15_routing_min_events", 40))
        min_attempts = int(getattr(self.config, "phase15_routing_min_provider_attempts", 4))
        baseline = list(getattr(self.config, "routing_cloud_priority", []) or [])

        scored: List[Dict[str, Any]] = []
        for provider, stats in providers.items():
            if not isinstance(stats, dict):
                continue
            attempts = int(stats.get("attempts", 0) or 0)
            if attempts < min_attempts:
                continue
            success = int(stats.get("success", 0) or 0)
            latency = float(stats.get("avg_latency_ms", 0.0) or 0.0)
            success_rate = (success / attempts) if attempts > 0 else 0.0
            # Higher success is more important; latency still influences ordering.
            score = (success_rate * 100.0) - min(40.0, latency / 250.0)
            scored.append(
                {
                    "provider": str(provider),
                    "attempts": attempts,
                    "success_rate": round(success_rate, 4),
                    "avg_latency_ms": round(latency, 2),
                    "score": round(score, 4),
                }
            )

        scored.sort(key=lambda row: float(row.get("score") or 0.0), reverse=True)
        recommended = [str(row["provider"]) for row in scored]

        gate_pass = (
            int(telemetry.get("events_scanned", 0) or 0) >= min_events
            and len(scored) >= 2
            and bool(recommended)
        )
        has_change = bool(recommended and recommended != baseline)

        applied = False
        apply_allowed = bool(getattr(self.config, "phase15_apply_routing_changes_automatically", False))
        should_apply = bool(apply and gate_pass and has_change and (apply_allowed or apply))
        if should_apply:
            self.config.routing_cloud_priority = recommended
            applied = True

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        report_path = self.routing_dir / f"routing_tuning_{stamp}.json"
        report = {
            "generated_at": _utc_now(),
            "hours": int(hours),
            "telemetry_events": int(telemetry.get("events_scanned", 0) or 0),
            "gate": {
                "passed": gate_pass,
                "min_events": min_events,
                "min_provider_attempts": min_attempts,
            },
            "baseline_priority": baseline,
            "recommended_priority": recommended,
            "provider_scores": scored,
            "changed": has_change,
            "applied": applied,
        }
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
        report["report_path"] = str(report_path)
        return report

    def _draft_skill_upgrade(self, task_text: str, *, context: Dict[str, Any]) -> Dict[str, Any]:
        info: Dict[str, Any] = {}
        try:
            from chintu_backend.capabilities.active_learning import get_active_learner

            msg = str(get_active_learner().learn_skill(task_text[:120]))
            info["message"] = msg
            match = re.search(r"(proposal_[a-z0-9_-]+)", msg.lower())
            if match:
                info["proposal_id"] = match.group(1)
        except Exception as exc:
            info["error"] = str(exc)
        return info

    def _precheck_proposal(self, proposal_id: str) -> Dict[str, Any]:
        report: Dict[str, Any] = {"proposal_id": proposal_id}
        try:
            from chintu_backend.automation.skills.skill_proposals import list_proposals
            from chintu_backend.automation.skills.skill_registry import parse_skills_from_markdown
            from chintu_backend.automation.skills.skill_tester import run_skill_tests

            proposal = next((p for p in list_proposals() if str(p.id) == proposal_id), None)
            if proposal is None:
                report["error"] = "proposal_not_found"
                return report

            md_path = Path(str(proposal.md_path or ""))
            if not md_path.exists():
                report["error"] = "proposal_markdown_missing"
                return report
            specs = parse_skills_from_markdown(md_path.read_text(encoding="utf-8"))
            tests = run_skill_tests(specs, self.config)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            path = self.change_dir / f"skill_upgrade_{proposal_id}_{stamp}.json"
            payload = {
                "generated_at": _utc_now(),
                "proposal_id": proposal_id,
                "names": list(proposal.names or []),
                "status": str(proposal.status or ""),
                "tests": tests,
                "approval_required_to_enable": True,
                "next_step": f"approve skill {proposal_id}",
            }
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
            report.update(
                {
                    "status": "ready_for_approval" if bool(tests.get("passed", False)) else "tests_failed",
                    "tests": tests,
                    "report_path": str(path),
                }
            )
            return report
        except Exception as exc:
            report["error"] = str(exc)
            return report

    def _looks_like_missing_capability(self, *, message: str, capability_name: str) -> bool:
        low = str(message or "").lower()
        patterns = (
            "can't do that yet",
            "cannot do that yet",
            "not supported yet",
            "missing capability",
            "no capability",
            "no tool found",
            "not available yet",
            "couldn't complete that automatically",
        )
        if any(p in low for p in patterns):
            return True
        cap_name = str(capability_name or "").strip().lower()
        return cap_name in {"", "conversation", "compound_command", "unknown"} and "not available" in low

    def _derive_skill_family(self, task_text: str) -> str:
        low = str(task_text or "").lower()
        if any(k in low for k in ("compare", "best price", "buy", "shopping", "deal")):
            return "product_research_compare"
        if any(k in low for k in ("dashboard", "metrics", "report")):
            return "dashboard_builder"
        if any(k in low for k in ("calendar", "meeting", "schedule", "remind")):
            return "calendar_productivity"
        if any(k in low for k in ("browser", "website", "research", "search")):
            return "browser_research"
        if any(k in low for k in ("code", "project", "app", "build")):
            return "project_builder"
        return f"general_{_slug(task_text, max_len=36)}"

    def _build_risks(self, failure_type: str) -> List[str]:
        risks = [
            "Policy bypass attempts must remain blocked.",
            "Any new capability must stay inside approved workspace boundaries.",
        ]
        if failure_type == FailureTaxonomy.missing_dependency.value:
            risks.append("Dependency installs can break environments if not isolated.")
        if failure_type == "missing_capability":
            risks.append("New skill should be generalized to avoid duplicate narrow skills.")
        return risks[:4]

    def _build_tests(self, task_text: str, failure_type: str) -> List[str]:
        checks = [
            "Replay the original failing prompt and verify completion evidence.",
            "Run regression tests for policy gates and confirmation behavior.",
            "Verify artifact/provenance logging in run dossier.",
        ]
        if failure_type == FailureTaxonomy.missing_dependency.value:
            checks.append("Verify dependency recovery uses isolated env (uv/venv/container).")
        if "browser" in str(task_text or "").lower():
            checks.append("Verify relevance gating prevents unrelated site opens.")
        return checks[:5]

    def _suggest_tools(self, task_text: str, failure_type: str) -> List[str]:
        low = str(task_text or "").lower()
        tools = ["planner", "verifier", "task_history"]
        if any(k in low for k in ("browser", "web", "search", "research")):
            tools.extend(["browser_pilot", "web_search", "page_content"])
        if any(k in low for k in ("code", "project", "build")):
            tools.extend(["terminal_exec", "code_interpreter"])
        if failure_type == FailureTaxonomy.missing_dependency.value:
            tools.append("dependency_bootstrap")
        return list(dict.fromkeys(tools))

    def _build_unblock_steps(
        self,
        *,
        failure_type: str,
        task_text: str,
        dependency_name: str,
        skill_family: str,
    ) -> List[str]:
        if failure_type == FailureTaxonomy.blocked_by_policy.value:
            return [
                "Confirm the sensitive action explicitly if you want to proceed.",
                "Keep payment/destructive operations blocked by default.",
                "Resume task after approval with evidence capture enabled.",
            ]
        if failure_type == FailureTaxonomy.missing_dependency.value:
            dep = dependency_name or "required_dependency"
            return [
                f"Install '{dep}' using isolated dependency bootstrap (uv/venv/container).",
                "Re-run the failed step automatically and collect verification evidence.",
                "Store dependency receipt (installed, scope, rollback hint).",
            ]
        if failure_type == "missing_capability":
            return [
                f"Draft generalized skill family '{skill_family}' for this task pattern.",
                "Run targeted skill tests and replay the failing scenario in sandbox.",
                "Generate change report and require explicit approval before enabling.",
            ]
        return [
            "Classify failure and retry with the safest local fallback.",
            "If retry fails, propose a generalized skill upgrade plan.",
            "Return blocked-with-unblock-plan instead of giving up silently.",
        ]

    def _build_user_message(self, plan: Dict[str, Any]) -> str:
        failure_type = str(plan.get("failure_type") or "unknown")
        steps = plan.get("unblock_steps") if isinstance(plan.get("unblock_steps"), list) else []
        proposal = plan.get("proposal") if isinstance(plan.get("proposal"), dict) else {}
        proposal_id = str(proposal.get("proposal_id") or "")
        lines = [f"Blocked with unblock plan ({failure_type})."]
        for idx, step in enumerate(steps[:3], start=1):
            lines.append(f"{idx}. {step}")
        if proposal_id:
            lines.append(f"Drafted skill proposal: {proposal_id} (approval required).")
        lines.append("I did not execute any unsafe self-modification.")
        return "\n".join(lines)


_manager: Optional[SafeSelfImprovementManager] = None


def get_safe_self_improvement_manager(config: Optional[Any] = None) -> SafeSelfImprovementManager:
    global _manager
    if _manager is None or config is not None:
        _manager = SafeSelfImprovementManager(config=config)
    return _manager


def reset_safe_self_improvement_manager() -> None:
    global _manager
    _manager = None
