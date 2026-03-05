# Codebase Audit and Hygiene Policy

Last updated: 2026-02-24

This file is the persistent hygiene policy and status summary for the repository.
It avoids one-off historical noise and keeps only actionable maintenance guidance.

## 1) Audit Commands

Run the codebase audit:

```powershell
$env:PYTHONPATH='.'
python scripts/audit_codebase_hygiene.py
```

Run report cleanup:

```powershell
$env:PYTHONPATH='.'
python scripts/cleanup_generated_reports.py
```

## 2) Current Hygiene Baseline

- Documentation entrypoint is `docs/INDEX.md`.
- Architectural references are split cleanly:
  - `docs/ARCHITECTURE.md` for system flow diagrams
  - `docs/TECHNICAL_OVERVIEW.md` for implementation details
- PRD is maintained at `docs/PRD/PRODUCT_REQUIREMENTS.md`.
- Canonical test/report artifacts belong in `tests/reports/`.
- `generated_reports/` is treated as ephemeral output.
- Legacy one-off scripts have been moved to `scripts/archive/legacy/`.

## 3) Known Refactor Backlog

High-value modularization targets:

- `chintu_backend/core/command_handler.py`
- `chintu_backend/core/model_router.py`
- `chintu_backend/core/capability_handlers.py`
- `chintu_backend/automation/automation_capabilities.py`
- `chintu_backend/automation/browser/browser_capabilities.py`
- `chintu_backend/files/file_capabilities.py`

UI split targets:

- `chintu_ui/lib/widgets/control_center_panel.dart`
- `chintu_ui/lib/widgets/dashboard_panel.dart`
- `chintu_ui/lib/services/websocket_service.dart`

## 4) Repository Hygiene Rules

- Keep new modules small and cohesive.
- Avoid growing existing monolith files unless unavoidable.
- Any behavior change requires matching tests and docs updates.
- Do not keep duplicate docs with overlapping ownership.
- Keep legacy planning drafts out of active docs if phase lock reports exist.

## 5) Safe Cleanup Criteria

A doc or script is safe to remove when all are true:

1. not referenced by `README.md`, `docs/INDEX.md`, or active runbooks
2. superseded by a newer source-of-truth document
3. not required for an active phase lock contract

## 6) Mandatory Quality Gate Before Major Changes

1. run hygiene audit
2. run targeted tests for touched modules
3. verify no generated artifacts are being treated as source
4. update affected docs in the same change set
5. record architecture-impacting decisions in plan/lock documents

## 7) Latest Cleanup Actions

- Removed duplicate root PRD draft file:
  - `product_requirements.txt`
- Archived non-operational one-off scripts from `scripts/` to:
  - `scripts/archive/legacy/`
- Purged Python cache artifacts (`__pycache__`, `*.pyc`, `.pytest_cache`) from workspace.
- Cleaned stale temporary workspace under `.tmp/` and removed empty scaffolds.
