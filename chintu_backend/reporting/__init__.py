"""Reporting and dashboard capabilities."""

from .dashboard_studio import DashboardStudio, get_dashboard_studio
from .dashboard_capabilities import register_dashboard_capabilities

__all__ = [
    "DashboardStudio",
    "get_dashboard_studio",
    "register_dashboard_capabilities",
]

