"""Unit tests for the Phase 28 Telegram control-plane gate script."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parents[2]
    target = root / "scripts" / "phase28_telegram_control_plane_gate.py"
    spec = importlib.util.spec_from_file_location("phase28_control_plane_gate_module", target)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


def test_phase28_gate_passes():
    module = _load_module()
    report = module.run_phase28_gate()  # type: ignore[attr-defined]
    checks = report.get("checks") or {}
    assert bool(report.get("overall_ok")) is True
    assert bool(checks.get("control_plane_sections")) is True
    assert bool(checks.get("signed_approval_payloads")) is True
    assert bool(checks.get("remote_approval_resolution")) is True
    assert bool(checks.get("run_receipt_access")) is True
    assert bool(checks.get("run_cancel_action")) is True

