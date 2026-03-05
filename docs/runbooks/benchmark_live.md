# Live Benchmark Runbook (Strict + Evidence)

## Goal
Run Chintu's strict daily 50-task benchmark in live mode with deterministic verification and evidence artifacts.

This runbook covers:
- preflight (setup readiness) checks
- live strict benchmark execution
- sandboxed safety tasks (no real payments, no real Downloads deletion)
- where to find proof artifacts

## Prerequisites
- Run from repo root.
- Use project venv Python (`venv\\Scripts\\python.exe` on Windows).
- Ollama running with required models installed:
  - `qwen3.5:4b`
  - `qwen3.5:9b`
- Playwright installed and Chromium available.
- Browser profile exists: `~/.chintu/browser_profiles/assistant_accounts`
- Google Calendar authenticated (token available).
- Email IMAP configured (host/user/password via Identity Vault).
- `ffmpeg` and `ffprobe` available on PATH (required for video duration verification).

## Preflight
Command:

```powershell
venv\Scripts\python.exe scripts\chintu_50_realistic_benchmark.py --preflight --strict --scenarios tests\scenarios\chintu_50_personal_daily.py
```

Expected:
- Exit code `0`.
- A setup report is written under `generated_reports/`.
- No blockers are listed.

## Live Strict Run
Command:

```powershell
venv\Scripts\python.exe scripts\chintu_50_realistic_benchmark.py --live --strict --verify-side-effects --interactive-checkpoints --scenarios tests\scenarios\chintu_50_personal_daily.py --out-dir generated_reports
```

Notes:
- `--interactive-checkpoints` may pause for manual actions (for example, login) and then resume.
- Safety boundary tasks are sandboxed:
  - payment attempt uses deterministic "checkout phrase" blocking
  - Downloads delete attempt uses a sandbox Downloads directory inside the benchmark output folder

Expected:
- Summary shows `pass=50`, `fail=0`, `review=0`.
- Every task row has `verification.ok=true`.

## Evidence Locations
- Benchmark folder: `generated_reports/bench_live/<stamp>/`
- The benchmark report:
  - `generated_reports/bench_live/<stamp>/chintu_50_realistic.md`
  - `generated_reports/bench_live/<stamp>/chintu_50_realistic.json`
- Run receipts and evidence refs:
  - `~/.chintu/runs/<run_id>/receipt.md`

## Troubleshooting
- Preflight fails on `ffmpeg`:
  - Install ffmpeg and ensure `ffmpeg` and `ffprobe` are on PATH, then rerun preflight.
- Browser steps fail:
  - Confirm `assistant_accounts` profile exists and you can access the sites in that profile.
- Calendar/email steps fail:
  - Rerun `python scripts\chintu_doctor.py` and follow the integration setup instructions it prints.
