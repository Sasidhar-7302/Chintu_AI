# Disaster Recovery Runbook

## Goal
Restore Chintu runtime state and quality-gate posture after data loss, host failure, or severe corruption.

## Critical Paths
- Runtime data: `data/`
- Evidence artifacts: `generated_reports/`
- Logs: `logs/`
- Plans/specs: `docs/PLANS/`, `docs/PRD/`

## Backup Procedure (Daily/Before Major Changes)
1. Snapshot repository and runtime folders.
2. Preserve latest gate artifacts:
   - `python -m chintu_backend.cli gates all`
3. Archive backup to secure storage (encrypted at rest).

## Recovery Procedure
1. Restore repository to known-good commit/tag.
2. Restore `data/`, `generated_reports/`, and `logs/` from latest valid backup.
3. Verify environment:
   - `python -m pytest -q tests/core`
   - `flutter test` (from `chintu_ui/`)
4. Re-verify roadmap gates:
   - `python -m chintu_backend.cli gates all`
   - `python -m chintu_backend.cli gates ci --skip-flutter-tests`

## Validation Exit Criteria
- All Python core tests pass.
- Flutter widget tests pass.
- Phase gates pass with fresh receipts in `generated_reports/`.
- No pending adapter is activated without approval.
- Control-plane approval flows still require signed payload validation.

## Rollback Procedure
If recovery build fails gates:
1. Revert to previous recovery point.
2. Restore previous backup snapshot.
3. Re-run validation sequence.

