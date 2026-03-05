from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from chintu_backend.brain.learning import weekly_trainer


class _DummyStore:
    def __init__(self) -> None:
        self._state = {}

    def load_state(self):
        return dict(self._state)

    def save_state(self, value):
        self._state = dict(value or {})


class _DummyEngine:
    def __init__(self) -> None:
        self.store = _DummyStore()


def _build_cfg(tmp_path: Path) -> SimpleNamespace:
    exports = tmp_path / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    adapter_dir = tmp_path / "adapters"
    adapter_dir.mkdir(parents=True, exist_ok=True)
    pending = tmp_path / "training" / "pending_adapter_activation.json"
    pending.parent.mkdir(parents=True, exist_ok=True)
    reports = tmp_path / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        training_exports_dir=exports,
        learning_weekly_min_events=2,
        learning_train_command=None,
        learning_train_enabled=True,
        learning_adapter_dir=adapter_dir,
        learning_base_model_id="Qwen/test-base",
        learning_activation_requires_approval=True,
        learning_auto_activate_adapter=False,
        learning_pending_activation_path=pending,
        learning_activation_require_phase29_gate=False,
        learning_phase29_reports_dir=reports,
        learning_phase29_gate_max_age_hours=168,
        learning_phase29_gate_file_prefix="phase29_autonomy_integration_gate_",
        learning_weekly_enabled=True,
        learning_schedule_days=14,
        learning_weekly_day=6,
        learning_weekly_hour=2,
        learning_require_night_window=False,
        learning_require_idle=False,
        eval_gate_enabled=False,
        eval_min_score=0.8,
        eval_cases_path=tmp_path / "cases.jsonl",
    )


def test_biweekly_training_produces_pending_activation(monkeypatch, tmp_path):
    cfg = _build_cfg(tmp_path)
    engine = _DummyEngine()

    style_path = tmp_path / "style.jsonl"
    style_path.write_text('{"messages":[{"role":"user","content":"x"},{"role":"assistant","content":"y"}]}\n', encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")
    candidate = tmp_path / "adapter_candidate"
    candidate.mkdir(parents=True, exist_ok=True)

    export_result = SimpleNamespace(
        style_count=3,
        facts_count=1,
        memory_count=1,
        style_path=style_path,
        manifest_path=manifest_path,
        latest_approved_timestamp="2026-03-03T00:00:00Z",
    )

    monkeypatch.setattr(weekly_trainer, "get_config", lambda: cfg)
    monkeypatch.setattr(weekly_trainer, "get_learning_engine", lambda: engine)
    monkeypatch.setattr(weekly_trainer, "export_biweekly_datasets", lambda since_timestamp=None: export_result)
    monkeypatch.setattr(
        weekly_trainer,
        "train_adapter",
        lambda dataset_path, output_dir, activate=False: SimpleNamespace(ok=True, message="ok", adapter_path=str(candidate)),
    )
    monkeypatch.setattr(weekly_trainer, "_run_eval_gate", lambda: (True, "Eval gate passed (0.95)"))

    status = weekly_trainer.run_biweekly_learning(force=False)
    assert status.ok is True
    assert status.trained is True
    assert status.activation_pending is True
    assert Path(cfg.learning_pending_activation_path).exists()
    assert not (cfg.learning_adapter_dir / "active_adapter.json").exists()

    pending = json.loads(Path(cfg.learning_pending_activation_path).read_text(encoding="utf-8"))
    assert pending["status"] == "pending"
    assert pending["adapter_path"] == str(candidate)


def test_approve_pending_adapter_activation_writes_active_adapter(monkeypatch, tmp_path):
    cfg = _build_cfg(tmp_path)
    engine = _DummyEngine()

    candidate = tmp_path / "adapter_candidate"
    candidate.mkdir(parents=True, exist_ok=True)
    pending_payload = {
        "status": "pending",
        "created_at": "2026-03-03T00:00:00Z",
        "adapter_path": str(candidate),
        "dataset_path": str(tmp_path / "style.jsonl"),
    }
    Path(cfg.learning_pending_activation_path).write_text(json.dumps(pending_payload, indent=2), encoding="utf-8")

    monkeypatch.setattr(weekly_trainer, "get_config", lambda: cfg)
    monkeypatch.setattr(weekly_trainer, "get_learning_engine", lambda: engine)

    ok, message, payload = weekly_trainer.approve_pending_adapter_activation(actor="unit-test")
    assert ok is True
    assert "approved" in message.lower()
    assert payload["status"] == "activated"
    assert payload["approved_by"] == "unit-test"

    active = cfg.learning_adapter_dir / "active_adapter.json"
    assert active.exists()
    active_payload = json.loads(active.read_text(encoding="utf-8"))
    assert active_payload["adapter_path"] == str(candidate)


def test_approve_pending_adapter_activation_blocks_when_phase29_gate_missing(monkeypatch, tmp_path):
    cfg = _build_cfg(tmp_path)
    cfg.learning_activation_require_phase29_gate = True
    engine = _DummyEngine()

    candidate = tmp_path / "adapter_candidate"
    candidate.mkdir(parents=True, exist_ok=True)
    pending_payload = {
        "status": "pending",
        "created_at": "2026-03-03T00:00:00Z",
        "adapter_path": str(candidate),
        "dataset_path": str(tmp_path / "style.jsonl"),
    }
    Path(cfg.learning_pending_activation_path).write_text(json.dumps(pending_payload, indent=2), encoding="utf-8")

    monkeypatch.setattr(weekly_trainer, "get_config", lambda: cfg)
    monkeypatch.setattr(weekly_trainer, "get_learning_engine", lambda: engine)

    ok, message, payload = weekly_trainer.approve_pending_adapter_activation(actor="unit-test")
    assert ok is False
    assert "phase 29 gate" in message.lower()
    assert isinstance(payload, dict)


def test_approve_pending_adapter_activation_allows_when_phase29_gate_passes(monkeypatch, tmp_path):
    cfg = _build_cfg(tmp_path)
    cfg.learning_activation_require_phase29_gate = True
    engine = _DummyEngine()

    candidate = tmp_path / "adapter_candidate"
    candidate.mkdir(parents=True, exist_ok=True)
    pending_payload = {
        "status": "pending",
        "created_at": "2026-03-03T00:00:00Z",
        "adapter_path": str(candidate),
        "dataset_path": str(tmp_path / "style.jsonl"),
    }
    Path(cfg.learning_pending_activation_path).write_text(json.dumps(pending_payload, indent=2), encoding="utf-8")

    report_path = cfg.learning_phase29_reports_dir / "phase29_autonomy_integration_gate_20260303_120000.json"
    report_payload = {
        "phase": "phase29",
        "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "overall_ok": True,
    }
    report_path.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")

    monkeypatch.setattr(weekly_trainer, "get_config", lambda: cfg)
    monkeypatch.setattr(weekly_trainer, "get_learning_engine", lambda: engine)

    ok, message, payload = weekly_trainer.approve_pending_adapter_activation(actor="unit-test")
    assert ok is True
    assert "approved" in message.lower()
    assert payload["status"] == "activated"
    assert payload["approved_by"] == "unit-test"
