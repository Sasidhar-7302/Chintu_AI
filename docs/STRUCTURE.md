# Project Structure Map

This is a quick map of what lives where and what you can safely edit.

## Entry Points

- `scripts\setup_env.bat` (one-click venv plus dependencies)
- `scripts\start_chintu.bat` (launcher: backend plus UI)
- `python -m chintu_backend` (backend entry point)
- `scripts\chintu_cli.py` (onboarding and health checks)
- `scripts\chintu_doctor.py` (runtime health checks)
- `scripts\audit_codebase_hygiene.py` (codebase hygiene audit)
- `scripts\archive\legacy\` (non-operational historical scripts; not part of runtime)
- `chintu_ui\` (Flutter UI)

## Core Backend

- `chintu_backend\core\command_handler.py` (main routing, approvals, policy enforcement)
- `chintu_backend\core\capability_loader.py` (capability registration order)
- `chintu_backend\core\capabilities.py` (registry and matching)
- `chintu_backend\core\config.py` (defaults, feature flags, paths)
- `chintu_backend\core\events.py` (central EventBus and EventType enum)
- `chintu_backend\core\run_manager.py` (run lifecycle, queueing, receipts, watchdog)

## Capabilities (Features)

- `chintu_backend\automation\` (OS and workflow automation)
- `chintu_backend\automation\browser\` (Playwright browser tools and evidence)
- `chintu_backend\automation\deal_finder_capabilities.py` (price compare: read-only)
- `chintu_backend\brain\memory\` (hybrid memory, temporal memory, image ingest)
- `chintu_backend\files\` (file IO, parsing, document helpers)
- `chintu_backend\orchestrator\` (multi-step project execution)
- `chintu_backend\security\` (Identity Vault, credential detection, approvals)
- `chintu_backend\tasks\task_manager.py` (reminders, todos, deferred actions with retries/dead-letter)

## Skills

- `chintu_backend\automation\skills\bundled\` (built-in skills)
- `skills\` (workspace skills, highest priority overrides)
- `~\.chintu\skills\` and `~\.chintu\skills_learned\` (user/imported and learned skills)

## Runtime Data

- `logs\` (backend and UI logs from the launcher)
- `tests\reports\` (canonical stored validation/benchmark artifacts)
- `generated_reports\` (ephemeral output target; safe to clean when mirrored to `tests\reports\`)
- `.tmp\` (temporary runtime/debug artifacts; safe to clean periodically)
- `~\.chintu\` (per-user state: runs, evidence, memory DB, vault metadata)
- `scripts\cleanup_generated_reports.py` (retention cleanup for report artifacts)

## Docs

- `docs\PRD\PRODUCT_REQUIREMENTS.md` (product requirements)
- `docs\INDEX.md` (system guide)
- `docs\DEVELOPER_ONBOARDING.md` (new-contributor setup and workflow)
- `docs\ARCHITECTURE.md` (runtime/system flow diagrams)
- `docs\TECHNICAL_OVERVIEW.md` (implementation-level technical reference)
- `docs\guides\` (installation and usage)
- `docs\MAINTENANCE.md` (repo hygiene and monolith control policy)
- `docs\CODEBASE_AUDIT.md` (latest hygiene findings and cleanup decisions)
- `docs\PLANS\chintu_ultimate_plan.md` (active roadmap)

## Avoid Editing Unless You Know Why

- `venv\` (Python environment)
- `docker\` (sandbox images/config)
- `.GCC\` (internal learning/context artifacts, if enabled)
