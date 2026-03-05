# Testing

This project uses unit tests, targeted subsystem suites, and end-to-end scenario benchmarks.

## Unit tests

```powershell
venv\Scripts\python.exe -m pytest -q
```

Pytest discovery is scoped to `tests/` via `pytest.ini`.

## Targeted stability suites

Use these while iterating on a specific subsystem:

```powershell
$env:PYTHONPATH='.'
pytest -q tests/core/test_action_interceptor.py
pytest -q tests/core/test_hardware_optimizer.py
pytest -q tests/core/test_runtime_hardware_adapter.py
```

## Scenario suite (50 daily workflows)

```powershell
venv\Scripts\python.exe scripts\chintu_50_realistic_benchmark.py --live
```

## Manual test inputs

See `docs/MANUAL_QA_MATRIX.md` for suggested prompts and expected outcomes.

## Vision probe

Inspect exactly what the active vision backend/model extracts:

```powershell
$env:PYTHONPATH='.'
python scripts/vision_debug_probe.py
```

Or analyze a specific screenshot:

```powershell
$env:PYTHONPATH='.'
python scripts/vision_debug_probe.py --image "C:\Users\<you>\.chintu\screenshots\screenshot_YYYYMMDD_HHMMSS.png"
```

This writes `generated_reports\vision_probe_*.json`.

## Reports

Parity and validation outputs are written under `generated_reports\`.

