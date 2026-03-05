"""Unit tests for release-readiness gate."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parents[2]
    target = root / "scripts" / "release_readiness_gate.py"
    spec = importlib.util.spec_from_file_location("release_readiness_gate_module", target)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


def test_release_readiness_static_gate_passes():
    module = _load_module()
    report = module.run_release_readiness_gate(run_package_smoke=False)  # type: ignore[attr-defined]
    gates = report.get("gates") or {}
    assert bool(report.get("overall_ok")) is True
    assert bool(gates.get("required_paths")) is True
    assert bool(gates.get("package_script_policy")) is True
    assert bool(gates.get("package_smoke")) is True

