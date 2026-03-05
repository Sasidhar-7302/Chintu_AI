# Chintu Release Checklist (Phase 0)

This checklist is the must-not-break gate for every smart-upgrade release.

## Prerequisites

- Run from repository root.
- Use project venv Python (`venv\Scripts\python.exe` on Windows).
- Ensure Ollama is running and required local models are installed.
- Ensure MCP dependencies are installed if MCP is enabled.

## Gate 1: Unit/Integration Tests

Command:

```powershell
venv\Scripts\python.exe -m pytest -q
```

Expected:

- Exit code `0`.
- Output ends with all tests passing (for example: `N passed` and no failures).

Sanity command (path-resolution parity on Windows):

```powershell
pytest -q
```

Expected:

- Exit code `0`.
- Same pass/fail outcome as `python -m pytest -q`.

## Gate 2: Doctor Health Check

Command:

```powershell
venv\Scripts\python.exe scripts\chintu_doctor.py
```

Expected:

- Exit code `0`.
- Summary JSON contains:
  - `"hard_fail": false`
  - `"log_warnings": []` (or only explicitly accepted non-critical warnings).
- MCP checks pass:
  - runtime active
  - tool coverage includes required browser/files/vision tools
  - tool smoke test passes

## Gate 2.5: Docs Integrity Check

Command:

```powershell
venv\Scripts\python.exe scripts\docs_check.py
```

Expected:
- Exit code `0`.
- Output contains `[OK] docs_check passed`.

## Gate 3: Realistic 50-Task Live Benchmark

Command:

```powershell
venv\Scripts\python.exe scripts\chintu_50_realistic_benchmark.py --preflight --strict --scenarios tests\scenarios\chintu_50_personal_daily.py
venv\Scripts\python.exe scripts\chintu_50_realistic_benchmark.py --live --strict --verify-side-effects --interactive-checkpoints --scenarios tests\scenarios\chintu_50_personal_daily.py --out-dir generated_reports
```

Expected:

- Exit code `0`.
- Report summary shows:
  - `"total": 50`
  - `"pass": 50`
  - `"review": 0`
  - `"fail": 0`
  - `"pass_rate": 1.0`
- Side-effect verifications in report are successful for verifiable tasks.
- Evidence artifacts exist under `generated_reports/bench_live/<stamp>/`.

## Release Decision Rule

Release only when all gates pass in the same environment without manual patch-ups between runs.

## One-Command Local Gate Runner

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_quality_gates.ps1
```
