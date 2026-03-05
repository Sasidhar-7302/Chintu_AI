"""Dashboard Studio capabilities (Phase 13)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from chintu_backend.core.capabilities import ActionResult, Capability, CapabilityType
from .dashboard_studio import get_dashboard_studio


class DashboardBuildSchema(BaseModel):
    kind: Optional[str] = Field(None, description="Dashboard kind: reliability, content, finance")
    name: Optional[str] = Field(None, description="Optional dashboard title")
    finance_csv_path: Optional[str] = Field(None, description="CSV path for finance dashboard")


class DashboardSourcesSchema(BaseModel):
    pass


def _infer_kind(text: str, explicit: Optional[str]) -> str:
    if explicit:
        candidate = str(explicit).strip().lower()
        if candidate in {"reliability", "content", "finance"}:
            return candidate
    low = str(text or "").lower()
    if "finance" in low or "portfolio" in low:
        return "finance"
    if "content" in low or "youtube" in low or "instagram" in low:
        return "content"
    return "reliability"


def _extract_csv_path(text: str) -> Optional[str]:
    match = re.search(r"([A-Za-z]:\\[^\n\r]+?\.csv|\.{0,2}[\\/][^\n\r]+?\.csv)", str(text or ""), re.IGNORECASE)
    if match:
        return str(match.group(1)).strip()
    return None


def handle_dashboard_sources(_text: str, _context: Dict[str, Any]) -> ActionResult:
    studio = get_dashboard_studio()
    sources = studio.discover_sources()
    lines = ["Dashboard data sources:"]
    for key, value in sources.items():
        lines.append(f"- {key}: {value}")
    return ActionResult.ok("\n".join(lines), {"sources": sources}, "dashboard_studio_sources")


def handle_dashboard_build(text: str, context: Dict[str, Any]) -> ActionResult:
    validated = context.get("_validated_params")
    explicit_kind = None
    explicit_name = None
    explicit_csv = None
    if isinstance(validated, DashboardBuildSchema):
        explicit_kind = validated.kind
        explicit_name = validated.name
        explicit_csv = validated.finance_csv_path

    kind = _infer_kind(text, explicit_kind)
    csv_hint = explicit_csv or _extract_csv_path(text)
    finance_csv_path = Path(csv_hint).expanduser() if (kind == "finance" and csv_hint) else None

    studio = get_dashboard_studio()
    try:
        result = studio.build_dashboard(
            kind=kind,
            name=explicit_name,
            finance_csv_path=finance_csv_path,
        )
    except Exception as exc:
        if kind == "finance" and not csv_hint:
            return ActionResult.fail(
                "For finance dashboard, provide a CSV path. Example: build finance dashboard using C:\\data\\portfolio.csv",
                "dashboard_studio_build",
            )
        return ActionResult.fail(f"Dashboard build failed: {exc}", "dashboard_studio_build")

    payload = result.to_dict()
    msg = (
        f"{kind.title()} dashboard project created.\n"
        f"- Project: {payload['project_dir']}\n"
        f"- App: {payload['app_path']}\n"
        f"- Spec: {payload['spec_path']}\n"
        f"- Data: {payload['data_path']}\n"
        f"- Tests: {payload['test_path']}\n"
        "- Run: streamlit run app.py"
    )
    return ActionResult.ok(msg, payload, "dashboard_studio_build")


def register_dashboard_capabilities(registry=None) -> None:
    from chintu_backend.core.capabilities import get_registry

    reg = registry or get_registry()
    reg.register(
        Capability(
            name="dashboard_studio_sources",
            triggers=[
                "dashboard data sources",
                "what data do we have for dashboard",
                "dashboard sources",
            ],
            handler=handle_dashboard_sources,
            requires_confirmation=False,
            description="show available dashboard data sources",
            capability_type=CapabilityType.PRODUCTIVITY,
            schema=DashboardSourcesSchema,
            examples=["Dashboard data sources"],
        )
    )
    reg.register(
        Capability(
            name="dashboard_studio_build",
            triggers=[
                "build dashboard",
                "create dashboard",
                "dashboard studio",
                "reliability dashboard",
                "content dashboard",
                "finance dashboard",
            ],
            handler=handle_dashboard_build,
            requires_confirmation=False,
            description="build exportable dashboard projects",
            capability_type=CapabilityType.PRODUCTIVITY,
            schema=DashboardBuildSchema,
            examples=[
                "Build reliability dashboard",
                "Create content dashboard",
                "Build finance dashboard using C:\\data\\portfolio.csv",
            ],
        )
    )

