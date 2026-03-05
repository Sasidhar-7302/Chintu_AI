from __future__ import annotations

from types import SimpleNamespace

from chintu_backend.core.runtime_hardware_adapter import RuntimeHardwareAdapter


class _FakeOptimizer:
    def __init__(self, refresh_results):
        self._refresh_results = list(refresh_results)
        self.optimize_calls = 0

    def refresh_hardware(self):
        if not self._refresh_results:
            return {
                "changed": False,
                "previous": {},
                "current": {},
            }
        return self._refresh_results.pop(0)

    def optimize_config(self, _config):
        self.optimize_calls += 1
        return {"ollama_model": "qwen2.5-coder:7b"}


class _FakeStateManager:
    def __init__(self):
        self.feature_updates = []
        self.activity = []

    def update_feature(self, *args, **kwargs):
        self.feature_updates.append((args, kwargs))

    def log_activity(self, message: str):
        self.activity.append(message)


def _cfg(**overrides):
    base = {
        "hardware_adapt_runtime_enabled": True,
        "hardware_adapt_check_interval_seconds": 60.0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_runtime_hardware_adapter_applies_tuning_when_signature_changes():
    optimizer = _FakeOptimizer(
        [
            {
                "changed": False,
                "previous": {},
                "current": {"gpu_count": 2, "hardware_profile": "high_end_gpu"},
            },
            {
                "changed": True,
                "previous": {"gpu_count": 2, "hardware_profile": "high_end_gpu"},
                "current": {"gpu_count": 1, "hardware_profile": "mid_range"},
            },
        ]
    )
    state = _FakeStateManager()
    ticks = iter([100.0, 120.0, 181.0])
    adapter = RuntimeHardwareAdapter(
        config=_cfg(),
        optimizer=optimizer,
        state_manager=state,
        now_fn=lambda: next(ticks),
    )

    first = adapter.maybe_refresh(force=True)
    assert first is not None
    assert first["applied"] is False
    assert optimizer.optimize_calls == 0

    # interval not reached
    skipped = adapter.maybe_refresh()
    assert skipped is None

    second = adapter.maybe_refresh()
    assert second is not None
    assert second["applied"] is True
    assert optimizer.optimize_calls == 1
    assert state.feature_updates
    assert state.activity


def test_runtime_hardware_adapter_disabled_noop():
    optimizer = _FakeOptimizer([])
    adapter = RuntimeHardwareAdapter(
        config=_cfg(hardware_adapt_runtime_enabled=False),
        optimizer=optimizer,
        state_manager=None,
        now_fn=lambda: 100.0,
    )
    assert adapter.maybe_refresh(force=True) is None
    assert optimizer.optimize_calls == 0


def test_runtime_hardware_adapter_emits_callback_on_apply():
    optimizer = _FakeOptimizer(
        [
            {
                "changed": False,
                "previous": {},
                "current": {"gpu_count": 2, "hardware_profile": "high_end_gpu"},
            },
            {
                "changed": True,
                "previous": {"gpu_count": 2, "hardware_profile": "high_end_gpu"},
                "current": {"gpu_count": 1, "hardware_profile": "mid_range"},
            },
        ]
    )
    callbacks = []
    ticks = iter([100.0, 181.0])
    adapter = RuntimeHardwareAdapter(
        config=_cfg(hardware_adapt_check_interval_seconds=60.0),
        optimizer=optimizer,
        state_manager=None,
        now_fn=lambda: next(ticks),
        on_applied=lambda payload: callbacks.append(payload),
    )

    first = adapter.maybe_refresh(force=True)
    assert first is not None
    assert not callbacks

    second = adapter.maybe_refresh()
    assert second is not None
    assert len(callbacks) == 1
    assert callbacks[0]["applied"] is True
