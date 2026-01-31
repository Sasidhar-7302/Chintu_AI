"""LLM-assisted planner that converts requests into project specs."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from .models import ProjectStatus

logger = logging.getLogger(__name__)


class OrchestratorPlanner:
    """Build a validated orchestration spec from free-form requests."""

    def __init__(self, capability_registry=None):
        self._registry = capability_registry

    def plan(self, request: str, defaults: Dict[str, Any]) -> Dict[str, Any]:
        spec = self._plan_with_llm(request, defaults)
        if not spec:
            spec = self._heuristic_plan(request, defaults)
        return self._validate_spec(spec, request, defaults)

    # ------------------------------------------------------------------
    # LLM planning
    # ------------------------------------------------------------------
    def _plan_with_llm(self, request: str, defaults: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            from ..core.model_router import get_router
            from ..core.capabilities import get_registry

            registry = self._registry or get_registry()
            capabilities = registry.list_capabilities()
            cap_names = [c["name"] for c in capabilities][:80]

            router = get_router()
            prompt = self._build_prompt(request, defaults, cap_names)
            response, source = router.route_and_execute(prompt)
            if not response or source == "none":
                return None
            json_str = self._extract_json_object(response)
            if not json_str:
                return None
            return json.loads(json_str)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Orchestrator LLM planning failed: %s", exc)
            return None

    def _build_prompt(self, request: str, defaults: Dict[str, Any], cap_names: List[str]) -> str:
        run_start = int(defaults.get("run_start_hour", 9))
        run_end = int(defaults.get("run_end_hour", 21))
        budget = int(defaults.get("daily_budget_minutes", 120))
        caps = ", ".join(sorted(cap_names)) or "execute_workflow, web_search, read_file"
        return f"""
You are a project orchestrator. Break the request into safe, auditable steps.

Available capabilities (use these exact names when possible): {caps}

Return ONLY valid JSON with this shape:
{{
  "name": "short project name",
  "description": "one sentence",
  "run_window": {{"start_hour": {run_start}, "end_hour": {run_end}}},
  "daily_budget_minutes": {budget},
  "steps": [
    {{
      "title": "step title",
      "command": "what to do in natural language",
      "capability": "capability_name_or_null",
      "depends_on": [1],
      "risk_level": "low|medium|high",
      "required_inputs": ["api_key"],
      "estimated_minutes": 15
    }}
  ]
}}

Safety rules:
- Use risk_level=high for publishing, posting, spending money, or sending messages.
- Prefer low risk read-only steps early, and high-risk steps last.
- Keep steps atomic, practical, and under 12 steps.
- Use depends_on with step numbers (1-based).

Request: {request!r}
""".strip()

    def _extract_json_object(self, text: str) -> Optional[str]:
        start = text.find("{")
        if start < 0:
            return None
        depth = 0
        for i in range(start, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        return None

    # ------------------------------------------------------------------
    # Heuristic fallback
    # ------------------------------------------------------------------
    def _heuristic_plan(self, request: str, defaults: Dict[str, Any]) -> Dict[str, Any]:
        from ..agents.task_planner import get_task_planner, StepType

        planner = get_task_planner()
        plan = planner.plan(request)
        steps: List[Dict[str, Any]] = []
        action_to_cap = {
            StepType.SEARCH: "web_search",
            StepType.BROWSE: "open_browser",
            StepType.CLICK: "browser_click",
            StepType.FILL: "browser_type",
            StepType.READ: "browser_extract",
            StepType.EXTRACT: "browser_extract",
            StepType.SCREENSHOT: "browser_screenshot",
            StepType.REMEMBER: "remember",
            StepType.NOTIFY: "conversation",
            StepType.WAIT: "conversation",
            StepType.CUSTOM: "execute_workflow",
        }

        for step in plan.steps[:10]:
            cap = action_to_cap.get(step.action, "execute_workflow")
            risk = "medium" if step.action in {StepType.BROWSE, StepType.FILL, StepType.CLICK} else "low"
            steps.append(
                {
                    "title": step.description,
                    "command": step.description,
                    "capability": cap,
                    "depends_on": step.depends_on,
                    "risk_level": risk,
                    "required_inputs": [],
                    "estimated_minutes": 10,
                }
            )

        short_name = " ".join(request.strip().split()[:6]) or "New Project"
        return {
            "name": short_name,
            "description": request.strip(),
            "run_window": {
                "start_hour": int(defaults.get("run_start_hour", 9)),
                "end_hour": int(defaults.get("run_end_hour", 21)),
            },
            "daily_budget_minutes": int(defaults.get("daily_budget_minutes", 120)),
            "steps": steps,
            "status": ProjectStatus.ACTIVE.value,
        }

    # ------------------------------------------------------------------
    # Validation and normalization
    # ------------------------------------------------------------------
    def _validate_spec(self, spec: Dict[str, Any], request: str, defaults: Dict[str, Any]) -> Dict[str, Any]:
        from ..core.capabilities import get_registry

        registry = self._registry or get_registry()
        known_caps = {c["name"] for c in registry.list_capabilities()}

        run_window = spec.get("run_window") or {}
        start_hour = int(run_window.get("start_hour", defaults.get("run_start_hour", 9)))
        end_hour = int(run_window.get("end_hour", defaults.get("run_end_hour", 21)))
        start_hour = max(0, min(23, start_hour))
        end_hour = max(start_hour + 1, min(24, end_hour))

        budget = int(spec.get("daily_budget_minutes", defaults.get("daily_budget_minutes", 120)))
        budget = max(15, min(24 * 60, budget))

        steps_in = spec.get("steps") or []
        steps: List[Dict[str, Any]] = []
        allowed_risks = {"none", "low", "medium", "high", "critical"}
        approval_keywords = {"publish", "post", "send", "buy", "purchase", "pay", "delete", "remove"}

        for i, raw in enumerate(steps_in[:12], start=1):
            title = str(raw.get("title") or f"Step {i}").strip()[:200]
            command = str(raw.get("command") or title).strip()
            if not command:
                continue
            cap = raw.get("capability")
            cap_name = str(cap).strip() if cap else None
            if cap_name and cap_name not in known_caps:
                cap_name = None

            depends_on = raw.get("depends_on") or []
            depends_nums = [int(x) for x in depends_on if str(x).isdigit()]
            depends_nums = [n for n in depends_nums if 1 <= n < i]

            req_inputs = [str(x).strip().lower() for x in (raw.get("required_inputs") or []) if str(x).strip()]
            risk = str(raw.get("risk_level") or "low").strip().lower()
            if risk not in allowed_risks:
                risk = "low"

            # Escalate risk if command implies external side effects.
            command_words = {w.strip(".,!?").lower() for w in command.split()}
            if command_words & approval_keywords and risk in {"none", "low"}:
                risk = "high"

            approval_required = risk in {"high", "critical"}
            est_minutes = int(raw.get("estimated_minutes") or 10)
            est_minutes = max(1, min(8 * 60, est_minutes))

            steps.append(
                {
                    "title": title,
                    "command": command,
                    "capability": cap_name,
                    "depends_on_numbers": depends_nums,
                    "risk_level": risk,
                    "required_inputs": req_inputs,
                    "estimated_minutes": est_minutes,
                    "approval_required": approval_required,
                }
            )

        if not steps:
            steps = [
                {
                    "title": "Analyze request",
                    "command": f"Analyze and break down: {request}",
                    "capability": "execute_workflow" if "execute_workflow" in known_caps else None,
                    "depends_on_numbers": [],
                    "risk_level": "low",
                    "required_inputs": [],
                    "estimated_minutes": 15,
                    "approval_required": False,
                }
            ]

        name = str(spec.get("name") or " ".join(request.split()[:6]) or "New Project").strip()[:200]
        description = str(spec.get("description") or request).strip()

        return {
            "name": name,
            "description": description,
            "status": str(spec.get("status") or ProjectStatus.ACTIVE.value),
            "run_start_hour": start_hour,
            "run_end_hour": end_hour,
            "daily_budget_minutes": budget,
            "steps": steps,
        }

