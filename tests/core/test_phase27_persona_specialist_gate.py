"""Unit tests for Phase 27 persona specialist gate."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parents[2]
    target = root / "scripts" / "phase27_persona_specialist_gate.py"
    spec = importlib.util.spec_from_file_location("phase27_persona_gate_module", target)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


def test_phase27_gate_passes_default_cases():
    module = _load_module()
    report = module.run_phase27_gate()  # type: ignore[attr-defined]
    summary = report.get("summary") or {}
    assert bool(report.get("overall_ok")) is True
    assert int(summary.get("total", 0)) >= 4
    assert int(summary.get("passed", 0)) == int(summary.get("total", 0))
    assert bool(summary.get("fallback_contract_ok")) is True

