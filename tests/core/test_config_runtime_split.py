from __future__ import annotations

from pathlib import Path

from chintu_backend.core.config import Config
from chintu_backend.core.config_runtime import initialize_runtime_paths


def test_config_fast_defaults_still_populate_key_paths(tmp_path):
    cfg = Config(data_dir=tmp_path)
    assert cfg.models_dir == tmp_path / "models"
    assert cfg.learning_adapter_dir == tmp_path / "models" / "adapters"
    assert cfg.learning_pending_activation_path == (
        tmp_path / "training" / "pending_adapter_activation.json"
    )
    assert cfg.learning_phase29_reports_dir == Path.cwd() / "generated_reports"
    assert cfg.phase15_dir == tmp_path / "self_improvement"


def test_initialize_runtime_paths_creates_expected_directories(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = Config(data_dir=tmp_path)
    initialize_runtime_paths(cfg)

    assert (tmp_path / "models").exists()
    assert (tmp_path / "models" / "adapters").exists()
    assert (tmp_path / "training").exists()
    assert (tmp_path / "history").exists()
    assert (tmp_path / "workspace" / "receipts").exists()
    assert Path(cfg.browser_profiles_dir).exists()
