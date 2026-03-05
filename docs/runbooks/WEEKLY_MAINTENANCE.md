# Weekly Maintenance Runbook

## Goal

Keep Chintu stable, clean, and auditable without running unnecessary full-system tests.

## Preconditions

- Run from repository root.
- Use project Python environment when available.

## Steps

1. **Health checks**
   ```powershell
   python scripts/chintu_doctor.py
   ```

2. **Codebase hygiene audit**
   ```powershell
   python scripts/audit_codebase_hygiene.py
   ```

3. **Generated report cleanup**
   ```powershell
   python scripts/cleanup_generated_reports.py
   ```

4. **Targeted regression checks (no full suite)**
   ```powershell
   python -m pytest tests/test_docker_sandbox_autostart.py tests/test_targeted_truncation_and_unicode_regressions.py -q
   ```

5. **Document outcomes**
   - Update `docs/CODEBASE_AUDIT.md` if there are new cleanup decisions.
   - Record any unresolved warnings and next actions.

## Escalation Conditions

- Any new policy/security warning in doctor output.
- Any repeated fallback/error string in recent logs.
- Any capability that reports completion without evidence.

