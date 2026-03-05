# Deployment Preflight Runbook

## Goal
Verify machine/runtime readiness before local deployment, release packaging, or major rollout.

## Baseline Command

```powershell
python -m chintu_backend.cli gates preflight
```

This runs non-destructive checks:
- required runtime/release files,
- Python version and command availability,
- `.env.example` key contract,
- writable `generated_reports` path.

## Optional Active Checks

Run doctor + docker checks:

```powershell
python -m chintu_backend.cli gates preflight --run-doctor --run-docker-check
```

Require Docker readiness as hard gate:

```powershell
python -m chintu_backend.cli gates preflight --run-docker-check --strict-docker
```

## Expected Artifacts
- `generated_reports/deployment_preflight_gate_*.json`
- `generated_reports/deployment_preflight_gate_*.md`

## Failure Handling
1. Fix missing paths/files immediately.
2. Resolve command/runtime issues (`python`, `git`, `powershell`).
3. Update `.env.example` key contract if drifted from current integration set.
4. Re-run `gates preflight` until pass before packaging/deploying.

