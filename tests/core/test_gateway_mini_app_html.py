from __future__ import annotations

from chintu_backend.interfaces.gateway.mini_app_html import (
    render_control_plane_mini_app_html,
)


def test_mini_app_html_contains_core_sections():
    html = render_control_plane_mini_app_html()
    assert "Chintu Operator Console" in html
    assert 'id="approvals-grid"' in html
    assert 'id="runs-grid"' in html
    assert 'id="telemetry-list"' in html
    assert 'id="provider-trends"' in html
    assert 'id="artifact-list"' in html
    assert 'id="run-status-filter"' in html
    assert 'id="run-page-size"' in html
    assert 'id="artifact-kind-filter"' in html
    assert 'id="artifact-page-size"' in html


def test_mini_app_html_wires_control_plane_endpoints():
    html = render_control_plane_mini_app_html()
    assert "/ops/control-plane?" in html
    assert "/ops/resolve-approval?" in html
    assert 'requestQs.set("limit_runs"' in html
    assert 'requestQs.set("limit_approvals"' in html
    assert 'id="auto-refresh"' in html
    assert "Auto-refresh 10s" in html
