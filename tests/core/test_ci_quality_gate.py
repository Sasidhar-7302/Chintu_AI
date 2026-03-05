"""Unit tests for CI quality gate script."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


def _load_module():
    root = Path(__file__).resolve().parents[2]
    target = root / "scripts" / "ci_quality_gate.py"
    spec = importlib.util.spec_from_file_location("ci_quality_gate_module", target)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


def test_ci_quality_gate_reports_success_with_mocked_subprocess(monkeypatch):
    module = _load_module()

    def _fake_run(*args, **kwargs):
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr(module.subprocess, "run", _fake_run)  # type: ignore[attr-defined]
    report = module.run_ci_quality_gate(run_flutter_tests=False)  # type: ignore[attr-defined]
    assert bool(report.get("overall_ok")) is True
    steps = report.get("steps") or []
    assert len(steps) == 5
    assert all(bool(step.get("ok")) for step in steps)
