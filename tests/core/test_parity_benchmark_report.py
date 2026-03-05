"""Unit tests for parity benchmark baseline comparison helpers."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parents[2]
    target = root / "scripts" / "parity_benchmark.py"
    spec = importlib.util.spec_from_file_location("parity_benchmark_module", target)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


def test_extract_baseline_summary_from_results_shape():
    module = _load_module()
    payload = {
        "results": [
            {"case": "fs_write_file", "verdict": "PASS"},
            {"case": "fs_read_file", "verdict": "FAIL"},
        ]
    }
    summary = module._extract_baseline_summary(payload)
    assert summary["total"] == 2
    assert summary["passed"] == 1


def test_build_case_compare_matches_named_cases():
    module = _load_module()
    chintu_results = [
        {"case": "fs_write_file", "ok": True},
        {"case": "memory_read", "ok": False},
    ]
    baseline_payload = {
        "results": [
            {"case": "fs_write_file", "verdict": "PASS"},
            {"case": "memory_read", "verdict": "PASS"},
        ]
    }
    rows = module._build_case_compare(chintu_results, baseline_payload)
    assert len(rows) == 2
    first = next(r for r in rows if r["case"] == "fs_write_file")
    second = next(r for r in rows if r["case"] == "memory_read")
    assert first["delta"] == 0
    assert second["delta"] == -1
