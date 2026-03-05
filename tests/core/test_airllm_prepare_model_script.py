"""Tests for AirLLM model prepare script helpers."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parents[2]
    target = root / "scripts" / "chintu_airllm_prepare_model.py"
    spec = importlib.util.spec_from_file_location("airllm_prepare_module", target)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


def test_run_prepare_ready_when_snapshot_complete(monkeypatch, tmp_path: Path):
    module = _load_module()
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir(parents=True, exist_ok=True)
    payload = {"weight_map": {"layer0": "model.safetensors-00001-of-00001.safetensors"}}
    (snapshot / "model.safetensors.index.json").write_text(json.dumps(payload), encoding="utf-8")
    (snapshot / "model.safetensors-00001-of-00001.safetensors").write_bytes(b"ok")

    monkeypatch.setattr(module, "_ensure_snapshot_metadata", lambda model_id, token: snapshot)
    report = module.run_prepare(model_id="Qwen/Qwen3.5-27B", max_files=0)
    assert report["ready"] is True
    assert int(report["remaining_missing_count"]) == 0
