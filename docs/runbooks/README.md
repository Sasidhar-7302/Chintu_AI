# Runbooks

This folder contains operational runbooks for recurring tasks.

Examples:
- incident response for failed runs,
- model/provider outage fallback,
- Docker sandbox recovery,
- Telegram inbox backlog handling,
- weekly maintenance checklist.

Available runbooks:
- `docs/runbooks/WEEKLY_MAINTENANCE.md`
- `docs/runbooks/RELEASE_PACKAGING.md`
- `docs/runbooks/DEPLOYMENT_PREFLIGHT.md`
- `docs/runbooks/INCIDENT_RESPONSE.md`
- `docs/runbooks/DISASTER_RECOVERY.md`

Quality gate command:
- `powershell -ExecutionPolicy Bypass -File scripts/quality_gate.ps1`

Each runbook should include:
- trigger conditions,
- exact commands,
- expected output,
- rollback/escalation path.
