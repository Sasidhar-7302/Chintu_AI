"""Unit tests for deployment preflight gate."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parents[2]
    target = root / "scripts" / "deployment_preflight_gate.py"
    spec = importlib.util.spec_from_file_location("deployment_preflight_gate_module", target)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


def test_preflight_gate_static_checks_pass():
    module = _load_module()
    report = module.run_deployment_preflight_gate(  # type: ignore[attr-defined]
        run_doctor_check=False,
        run_docker_check=False,
        strict_docker=False,
    )
    gates = report.get("gates") or {}
    assert bool(report.get("overall_ok")) is True
    assert bool(gates.get("required_paths")) is True
    assert bool(gates.get("python_version")) is True
    assert bool(gates.get("commands")) is True
    assert bool(gates.get("env_template")) is True
    assert bool(gates.get("writable_reports_dir")) is True

