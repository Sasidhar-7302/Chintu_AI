# Developer Onboarding Guide

This guide is for engineers joining the Chintu codebase.
It focuses on practical setup, debugging, and safe contribution workflow.

## 1) Prerequisites

Windows baseline:
- Python 3.11+
- Git
- Node/Flutter (only if working on UI)
- Optional: Docker Desktop (sandbox workflows)
- Optional: Ollama (local model runtime)

Recommended machine profile:
- 16 GB+ RAM
- NVIDIA GPU (local model and vision workflows improve significantly)

## 2) Repository Setup

From repo root:

```powershell
python -m venv venv
venv\Scripts\python.exe -m pip install --upgrade pip
venv\Scripts\python.exe -m pip install -r requirements.txt
```

Alternative:

```powershell
scripts\setup_env.bat
```

## 3) Start the System

Backend only:

```powershell
venv\Scripts\python.exe -m chintu_backend
```

Launcher path:

```powershell
scripts\start_chintu.bat
```

CLI diagnostics:

```powershell
venv\Scripts\python.exe scripts\chintu_cli.py
venv\Scripts\python.exe scripts\chintu_doctor.py
```

## 4) Configuration

Primary configuration is managed through:
- `.env`
- `chintu_backend/core/config.py`

Typical toggles to check:
- model routing and provider flags
- browser automation toggles
- safety and approval defaults
- watchdog and timeout configuration

Never commit private credentials.

## 5) Core Files to Understand First

Start here in this order:
1. `chintu_backend/core/command_handler.py`
2. `chintu_backend/core/action_dispatcher.py`
3. `chintu_backend/core/capabilities.py`
4. `chintu_backend/core/capability_loader.py`
5. `chintu_backend/core/run_manager.py`
6. `chintu_backend/core/model_router.py`
7. `chintu_backend/brain/memory/`
8. `chintu_backend/security/`

Then read:
- `docs/ARCHITECTURE.md`
- `docs/TECHNICAL_OVERVIEW.md`
- `docs/PLANS/chintu_ultimate_plan.md`

## 6) Contribution Workflow

For each change:
1. define expected behavior and risk class
2. implement minimal code changes
3. add or update targeted tests
4. run affected tests locally
5. update docs in same change set
6. record any policy-impacting changes in plan/lock docs

Do not ship behavior changes without tests and docs updates.

## 7) Testing Workflow

Run baseline:

```powershell
venv\Scripts\python.exe -m pytest -q
```

Targeted tests:

```powershell
venv\Scripts\python.exe -m pytest -q tests\core\test_action_interceptor.py
```

Scenario benchmark:

```powershell
venv\Scripts\python.exe scripts\chintu_50_realistic_benchmark.py --live
```

Manual QA matrix:
- `docs/MANUAL_QA_MATRIX.md`

## 8) Debugging and Observability

Where to look:
- runtime logs: `logs/`
- run receipts: `~/.chintu/runs/<run_id>/receipt.md`
- run events: `~/.chintu/runs/<run_id>/events.jsonl`
- benchmark outputs: `tests/reports/` and `generated_reports/`

Vision debug:

```powershell
$env:PYTHONPATH='.'
python scripts/vision_debug_probe.py
```

## 9) Safety Checklist Before Merge

- destructive actions still require explicit confirmation
- payment and checkout actions remain blocked
- login/publish/send flows are gated
- no sensitive data leakage in logs or spoken output
- no false success without evidence

## 10) Documentation Update Rules

If you change behavior, update at least one of:
- `docs/TECHNICAL_OVERVIEW.md`
- `docs/ARCHITECTURE.md`
- `docs/INDEX.md`
- `docs/TESTING.md`

For roadmap-impacting changes:
- update `docs/PLANS/chintu_ultimate_plan.md`
- update the relevant phase lock report

