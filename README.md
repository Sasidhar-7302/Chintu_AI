# Chintu AI

Local-first autonomous assistant for Windows with policy-gated execution, reusable skills, browser automation, memory, and multi-model orchestration.

## Repository Layout

- `chintu_backend/` - backend runtime, routing, policies, automation, memory
- `chintu_ui/` - Flutter desktop UI
- `skills/` - workspace skills (`SKILL.md` + handlers)
- `tests/` - regression and phase-level tests
- `scripts/` - operational tools, audits, benchmarks, doctors
- `docs/` - architecture, plans, maintenance, and runbooks

## Quick Start

```powershell
venv\Scripts\python.exe -m pytest -q
python scripts/chintu_doctor.py
```

Run targeted realistic benchmark:

```powershell
python scripts/chintu_50_realistic_benchmark.py --live
```

## Documentation

Start here:
- `docs/INDEX.md`

Important references:
- `docs/DEVELOPER_ONBOARDING.md`
- `docs/ARCHITECTURE.md`
- `docs/TECHNICAL_OVERVIEW.md`
- `docs/PLANS/chintu_ultimate_plan.md`
- `docs/MAINTENANCE.md`
- `docs/CODEBASE_AUDIT.md`

## Codebase Hygiene

Run hygiene audit:

```powershell
python scripts/audit_codebase_hygiene.py
```

Cleanup generated reports:

```powershell
python scripts/cleanup_generated_reports.py
```

Create a release package:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\package_release.ps1 -Version v1.0.0
```

Run a local quality gate:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\quality_gate.ps1
```
