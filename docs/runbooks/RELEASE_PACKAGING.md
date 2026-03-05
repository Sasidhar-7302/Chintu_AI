# Release Packaging Runbook

Use this runbook to generate a distributable Chintu package for testers or new machines.

## Goal

Create:
- a clean staging folder under `dist/`,
- a zip archive with runtime, UI, docs, and required scripts,
- no local runtime artifacts (`venv`, `logs`, `generated_reports`, local data).

## Command

From repository root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\package_release.ps1 -Version v1.0.0
```

Without version label:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\package_release.ps1
```

## Output

The script writes:
- `dist\chintu_release_<version-or-timestamp>\`
- `dist\chintu_release_<version-or-timestamp>.zip`

It also writes:
- `RELEASE_MANIFEST.txt` inside the staging folder.

## Validation Checklist

1. Confirm package exists:
   - `dist\...\scripts\start_chintu.bat`
   - `dist\...\requirements.txt`
   - `dist\...\docs\INDEX.md`
2. Confirm local-only folders are not included:
   - `venv`
   - `logs`
   - `generated_reports`
   - `data`
3. Open `RELEASE_MANIFEST.txt` and verify generated timestamp/version.
4. Smoke-test on a clean machine:
   - run `scripts\setup_env.bat`
   - run `scripts\start_chintu.bat`
   - run `venv\Scripts\python.exe scripts\chintu_doctor.py`

## Security Notes

- `.env` is not packaged automatically. Users must create it from `.env.example`.
- Rotate all shared secrets (Telegram token, API keys) before any external distribution.
- Never include `~/.chintu` contents from your local machine in releases.

