"""Unit tests for Phase 18 UI vNext gate script."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parents[2]
    target = root / "scripts" / "phase18_ui_vnext_gate.py"
    spec = importlib.util.spec_from_file_location("phase18_ui_gate_module", target)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


def test_phase18_gate_static_checks_pass_without_flutter():
    module = _load_module()
    report = module.run_phase18_gate(run_flutter_tests=False)  # type: ignore[attr-defined]
    gates = report.get("gates") or {}
    assert bool(report.get("overall_ok")) is True
    assert bool(gates.get("dashboard_models_identity_tabs")) is True
    assert bool(gates.get("websocket_test_mode")) is True
    assert bool(gates.get("flutter_widget_tests")) is True

