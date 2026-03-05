# Incident Response Runbook

## Trigger Conditions
- `chintu gates all` fails on local machine.
- `chintu gates ci` fails in CI.
- Operator reports silent execution, missing receipts, or approval bypass.
- Provider outage causes repeated task failures.

## Triage Checklist
1. Capture current gate receipts:
   - `generated_reports/phase17_maintainability_gate_*.md`
   - `generated_reports/phase18_ui_vnext_gate_*.md`
   - `generated_reports/phase19_workflow_pack_benchmark_*.md`
   - `generated_reports/phase27_persona_specialist_gate_*.md`
   - `generated_reports/phase28_telegram_control_plane_gate_*.md`
   - `generated_reports/phase29_autonomy_integration_gate_*.md`
2. Re-run gate chain:
   - `python -m chintu_backend.cli gates all`
3. Re-run CI chain:
   - `python -m chintu_backend.cli gates ci --skip-flutter-tests`
4. Confirm failing stage and timestamp from latest JSON report in `generated_reports/`.

## Containment
1. Freeze risky actions:
   - disable remote write actions by setting strict channel policy defaults.
2. Stop pending autonomous runs:
   - use gateway control plane cancel action on active runs.
3. Keep evidence immutable:
   - do not delete `generated_reports/` artifacts for failing runs.

## Recovery Steps
1. Fix failing component and add/adjust targeted test(s).
2. Validate locally:
   - `python -m pytest -q tests/core`
   - `flutter test` (from `chintu_ui/`)
3. Validate phase chain:
   - `python -m chintu_backend.cli gates all`
4. Validate CI chain:
   - `python -m chintu_backend.cli gates ci --skip-flutter-tests`

## Escalation
- If approval bypass/security issue is confirmed:
  - immediately disable external gateways until signed approval verification passes.
- If regression repeats twice in 24h:
  - require explicit rollback to last known good commit and re-run all gates.

