from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parents[2]
    target = root / "scripts" / "phase17_maintainability_gate.py"
    spec = importlib.util.spec_from_file_location("phase17_gate_module", target)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


def test_type_gate_detects_missing_annotations(tmp_path):
    module = _load_module()
    file_path = tmp_path / "sample.py"
    file_path.write_text(
        "def typed(a: int) -> int:\n    return a\n\n"
        "def untyped(a):\n    return a\n",
        encoding="utf-8",
    )

    result = module._type_gate(tmp_path, [file_path.name])  # noqa: SLF001
    assert result["passed"] is False
    assert "untyped" in (result["violations"][file_path.name])


def test_phase17_gate_passes_for_typed_target(tmp_path):
    module = _load_module()
    typed = tmp_path / "typed_mod.py"
    typed.write_text(
        "def hello(name: str) -> str:\n    return f'hi {name}'\n",
        encoding="utf-8",
    )

    result = module.run_phase17_gate(  # type: ignore[attr-defined]
        root=tmp_path,
        top_n=3,
        large_file_threshold=1200,
        typed_targets=[typed.name],
    )
    assert result.type_gate["passed"] is True
    assert isinstance(result.error_taxonomy_gate, dict)
