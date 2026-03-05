# Contributing

## Branching and commits
- Default branch is `main`.
- Keep changes small and focused by topic.
- Use clear commit messages in present tense.

## Local setup
1. Create and activate a virtual environment.
2. Install dependencies:
   - `pip install -r requirements.txt`
3. Run quality gates before opening a PR:
   - `powershell -ExecutionPolicy Bypass -File scripts/run_quality_gates.ps1`

## Required checks
- `python -m pytest -q`
- `python scripts/docs_check.py`
- `python scripts/chintu_doctor.py`
- `python scripts/chintu_50_realistic_benchmark.py --strict --allow-skips --verify-side-effects --scenarios tests/scenarios/chintu_50_personal_daily.py --out-dir generated_reports`

## Safety rules
- Do not implement payment/checkout completion flows.
- Do not permanently delete user files.
- Use quarantine moves under `~/.chintu/verify_delete/` for cleanup behavior.

## Documentation
- Add or update docs for behavior changes.
- Ensure new docs are linked from `docs/INDEX.md`.
- Keep runbooks executable with copy/paste commands.
