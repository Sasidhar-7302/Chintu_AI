"""Pipeline templates for business/product orchestration."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def match_template(request: str) -> Optional[str]:
    text = (request or "").lower()
    business_keywords = {"business", "startup", "company", "venture", "cofounder", "co-founder"}
    product_keywords = {"product", "mvp", "launch", "go-to-market", "gtm", "roadmap"}

    if any(word in text for word in business_keywords):
        return "business_pipeline"
    if any(word in text for word in product_keywords):
        return "product_pipeline"
    return None


def build_pipeline_spec(template_key: str, request: str, defaults: Dict[str, Any]) -> Dict[str, Any]:
    template_key = (template_key or "").strip().lower()
    builder = _TEMPLATE_BUILDERS.get(template_key)
    if not builder:
        raise ValueError(f"Unknown pipeline template: {template_key}")
    return builder(request, defaults)


def _business_pipeline_spec(request: str, defaults: Dict[str, Any]) -> Dict[str, Any]:
    goal = request.strip() or "Business pipeline"
    required_inputs = [
        "business_goal",
        "target_customer",
        "budget_range",
        "timeline",
        "product_or_service",
        "success_metric",
    ]
    steps = [
        {
            "title": "Confirm the business brief",
            "command": "Review the collected inputs and confirm the business brief.",
            "capability": "orchestrator_review_inputs",
            "required_inputs": required_inputs,
            "risk_level": "low",
            "estimated_minutes": 10,
            "approval_required": True,
            "assigned_agent": "founder",
        },
        {
            "title": "Market + competitor research",
            "command": f"Research the market, competitors, and trends for: {goal}.",
            "capability": "web_research",
            "risk_level": "low",
            "estimated_minutes": 25,
            "approval_required": False,
            "assigned_agent": "research",
            "depends_on": [1],
        },
        {
            "title": "Problem/solution hypothesis + positioning",
            "command": "Draft the problem statement, solution hypothesis, and positioning.",
            "capability": "execute_workflow",
            "risk_level": "medium",
            "estimated_minutes": 20,
            "approval_required": False,
            "assigned_agent": "product",
            "depends_on": [2],
        },
        {
            "title": "MVP scope + roadmap",
            "command": "Define MVP scope, milestones, and a 90-day roadmap.",
            "capability": "execute_workflow",
            "risk_level": "medium",
            "estimated_minutes": 30,
            "approval_required": False,
            "assigned_agent": "product",
            "depends_on": [3],
        },
        {
            "title": "Business model + pricing strategy",
            "command": "Outline revenue model, pricing strategy, and cost structure.",
            "capability": "execute_workflow",
            "risk_level": "medium",
            "estimated_minutes": 20,
            "approval_required": False,
            "assigned_agent": "finance",
            "depends_on": [3],
        },
        {
            "title": "Go-to-market plan",
            "command": "Create a go-to-market plan, channel strategy, and launch checklist.",
            "capability": "execute_workflow",
            "risk_level": "high",
            "estimated_minutes": 30,
            "approval_required": True,
            "assigned_agent": "marketing",
            "depends_on": [4, 5],
        },
        {
            "title": "Operational setup + launch readiness",
            "command": "Define operational needs, tooling, and a launch readiness checklist.",
            "capability": "execute_workflow",
            "risk_level": "medium",
            "estimated_minutes": 20,
            "approval_required": False,
            "assigned_agent": "operations",
            "depends_on": [6],
        },
        {
            "title": "Metrics + feedback loop",
            "command": "Define north-star metrics and feedback loops to iterate post-launch.",
            "capability": "execute_workflow",
            "risk_level": "low",
            "estimated_minutes": 15,
            "approval_required": False,
            "assigned_agent": "analytics",
            "depends_on": [6],
        },
        {
            "title": "Execution plan + task ownership",
            "command": "Create the execution plan with owners, timelines, and checkpoints.",
            "capability": "execute_workflow",
            "risk_level": "medium",
            "estimated_minutes": 20,
            "approval_required": False,
            "assigned_agent": "founder",
            "depends_on": [7, 8],
        },
    ]

    return _build_spec(
        name="Business Pipeline",
        description=goal,
        steps=steps,
        defaults=defaults,
        template="business_pipeline",
        team=[
            "founder",
            "research",
            "product",
            "finance",
            "marketing",
            "operations",
            "analytics",
        ],
    )


def _product_pipeline_spec(request: str, defaults: Dict[str, Any]) -> Dict[str, Any]:
    goal = request.strip() or "Product pipeline"
    required_inputs = [
        "product_goal",
        "target_user",
        "problem_to_solve",
        "budget_range",
        "timeline",
        "success_metric",
    ]
    steps = [
        {
            "title": "Confirm the product brief",
            "command": "Review the collected inputs and confirm the product brief.",
            "capability": "orchestrator_review_inputs",
            "required_inputs": required_inputs,
            "risk_level": "low",
            "estimated_minutes": 10,
            "approval_required": True,
            "assigned_agent": "product",
        },
        {
            "title": "User + market research",
            "command": f"Research users, pain points, and alternatives for: {goal}.",
            "capability": "web_research",
            "risk_level": "low",
            "estimated_minutes": 20,
            "approval_required": False,
            "assigned_agent": "research",
            "depends_on": [1],
        },
        {
            "title": "Product requirements (PRD)",
            "command": "Draft a PRD with goals, scope, and success metrics.",
            "capability": "execute_workflow",
            "risk_level": "medium",
            "estimated_minutes": 25,
            "approval_required": False,
            "assigned_agent": "product",
            "depends_on": [2],
        },
        {
            "title": "UX + design direction",
            "command": "Propose UX flow, key screens, and design direction.",
            "capability": "execute_workflow",
            "risk_level": "medium",
            "estimated_minutes": 20,
            "approval_required": False,
            "assigned_agent": "design",
            "depends_on": [3],
        },
        {
            "title": "Technical architecture",
            "command": "Outline the technical architecture, stack, and integration plan.",
            "capability": "execute_workflow",
            "risk_level": "medium",
            "estimated_minutes": 20,
            "approval_required": False,
            "assigned_agent": "engineering",
            "depends_on": [3],
        },
        {
            "title": "Build + QA plan",
            "command": "Create the build plan, QA approach, and release checklist.",
            "capability": "execute_workflow",
            "risk_level": "high",
            "estimated_minutes": 30,
            "approval_required": True,
            "assigned_agent": "engineering",
            "depends_on": [4, 5],
        },
        {
            "title": "Go-to-market prep",
            "command": "Prepare launch messaging, marketing assets, and rollout plan.",
            "capability": "execute_workflow",
            "risk_level": "high",
            "estimated_minutes": 25,
            "approval_required": True,
            "assigned_agent": "marketing",
            "depends_on": [6],
        },
        {
            "title": "Post-launch metrics + iteration",
            "command": "Define tracking, analytics, and iteration cadence post-launch.",
            "capability": "execute_workflow",
            "risk_level": "low",
            "estimated_minutes": 15,
            "approval_required": False,
            "assigned_agent": "analytics",
            "depends_on": [7],
        },
    ]

    return _build_spec(
        name="Product Pipeline",
        description=goal,
        steps=steps,
        defaults=defaults,
        template="product_pipeline",
        team=[
            "product",
            "research",
            "design",
            "engineering",
            "marketing",
            "analytics",
        ],
    )


def _build_spec(
    *,
    name: str,
    description: str,
    steps: List[Dict[str, Any]],
    defaults: Dict[str, Any],
    template: str,
    team: List[str],
) -> Dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "run_start_hour": int(defaults.get("run_start_hour", 9)),
        "run_end_hour": int(defaults.get("run_end_hour", 21)),
        "daily_budget_minutes": int(defaults.get("daily_budget_minutes", 120)),
        "steps": steps,
        "metadata": {
            "template": template,
            "approval_mode": "all_steps",
            "team": team,
        },
    }


_TEMPLATE_BUILDERS = {
    "business_pipeline": _business_pipeline_spec,
    "product_pipeline": _product_pipeline_spec,
}
