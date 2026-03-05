"""Unit tests for the Phase 19 workflow pack benchmark runner."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parents[2]
    target = root / "scripts" / "phase19_workflow_pack_benchmark.py"
    spec = importlib.util.spec_from_file_location("phase19_benchmark_module", target)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


def test_phase19_default_benchmark_cases_pass():
    module = _load_module()
    report = module.run_benchmark(module._default_cases())  # type: ignore[attr-defined]  # noqa: SLF001
    summary = report.get("summary") or {}
    assert int(summary.get("total", 0)) >= 4
    assert int(summary.get("passed", 0)) == int(summary.get("total", 0))


def test_phase19_content_studio_case_present():
    module = _load_module()
    cases = module._default_cases()  # type: ignore[attr-defined]  # noqa: SLF001
    names = {str(c.name) for c in cases}
    assert "content_studio_pack" in names
