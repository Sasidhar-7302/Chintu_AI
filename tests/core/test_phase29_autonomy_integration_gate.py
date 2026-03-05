"""Unit tests for the Phase 29 autonomy integration gate runner."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parents[2]
    target = root / "scripts" / "phase29_autonomy_integration_gate.py"
    spec = importlib.util.spec_from_file_location("phase29_gate_module", target)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


def test_provider_outage_probe_opens_circuit():
    module = _load_module()
    probe = module._simulate_provider_outage()  # noqa: SLF001
    assert probe["ok"] is True
    assert probe["blocked_after_outage"] is True
    assert probe["state"]["state"] == "open"


def test_phase29_gate_writes_contract_artifacts_without_benchmark(tmp_path):
    module = _load_module()
    report = module.run_phase29_gate(  # type: ignore[attr-defined]
        out_dir=tmp_path,
        run_workflow_benchmark=False,
        include_eval_gate=False,
    )
    assert report["overall_ok"] is True
    checks = report["complex_contract"]["checks"]
    assert checks["local_attempt_failed"] is True
    assert checks["verified_completion"] is True
    assert checks["adapter_activation_blocked_until_approval"] is True
    assert Path(report["complex_contract"]["pending_activation_path"]).exists()

