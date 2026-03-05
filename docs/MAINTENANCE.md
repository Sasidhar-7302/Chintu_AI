# Maintenance Guide

This document defines repository hygiene checks, cleanup routines, and refactor guardrails.

## 1) Run Hygiene Audit (First Step)

Run the repository audit before cleanup or refactor work:

```powershell
$env:PYTHONPATH='.'
python scripts/audit_codebase_hygiene.py
```

Outputs:
- `generated_reports/codebase_hygiene_audit_YYYYMMDD_HHMMSS.json`
- `generated_reports/codebase_hygiene_audit_YYYYMMDD_HHMMSS.md`

The audit highlights:
- oversized files,
- generated artifact directories,
- empty directories,
- script archive candidates.

## 2) Generated Reports Retention

Keep only recent, useful reports and remove stale duplicates:

```powershell
$env:PYTHONPATH='.'
python scripts/cleanup_generated_reports.py
```

Preview without deleting:

```powershell
$env:PYTHONPATH='.'
python scripts/cleanup_generated_reports.py --dry-run
```

Cleanup report path:
- `generated_reports/generated_reports_cleanup_YYYYMMDD_HHMMSS.md`

## 3) Vision Debug Artifacts

Generate probes only when diagnosing OCR/screen routing issues:

```powershell
$env:PYTHONPATH='.'
python scripts/vision_debug_probe.py
```

Expected output:
- `generated_reports/vision_probe_YYYYMMDD_HHMMSS.json`

Delete old probes through standard report cleanup.

## 4) Monolith Control Policy

To keep the codebase maintainable:

- Target new modules at `< 400` lines.
- Avoid adding new files over `800` lines unless unavoidable.
- For existing large files, extract cohesive modules (parsing, policy, IO, rendering).
- Add focused tests for each extraction.

Current highest-priority split targets:
- `chintu_backend/core/command_handler.py`
- `chintu_backend/core/model_router.py`
- `chintu_backend/automation/automation_capabilities.py`
- `chintu_backend/core/capability_handlers.py`
- `chintu_ui/lib/widgets/control_center_panel.dart`
- `chintu_ui/lib/widgets/dashboard_panel.dart`

## 5) Script Hygiene Rules

- Keep production scripts in `scripts/` with stable names and docs.
- Move one-off validation scripts to `scripts/archive/legacy/` before deletion.
- Prefer deterministic benchmark scripts over ad-hoc "verify_*" scripts.
- Any cleanup deletion should be preceded by an audit report entry.

## 6) Safe Refactor Workflow

1. Extract one cohesive section at a time.
2. Preserve public interfaces while moving internals.
3. Run targeted tests for the touched subsystem.
4. Run targeted scenario checks (not full benchmark unless required).
5. Update docs in the same change set after tests pass.
