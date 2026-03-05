# Usage Guide

This guide explains how to start Chintu and how to use the most important features.

## Start

Recommended (backend plus UI launcher):

```powershell
scripts\start_chintu.bat
```

On first launch, complete the UI onboarding card once. After that, Chintu opens directly to the main screen.

Backend only (no UI):

```powershell
venv\Scripts\python.exe -m chintu_backend
```

## Onboarding and Health Checks

Onboarding wizard (sets names and optionally stores API keys in the Identity Vault):

```powershell
venv\Scripts\python.exe scripts\chintu_cli.py onboard
```

Doctor (basic health checks):

```powershell
venv\Scripts\python.exe scripts\chintu_cli.py doctor
```

## Safety Model (What Requires Approval)

Chintu is designed to be high-autonomy but not reckless.

- Allowed without approval: read-only web research, summarization, non-destructive system queries.
- Requires approval: shell execution, editing files, deleting/moving large batches of files, shutdown/restart.
- Never do: payments or purchases (Chintu will stop at checkout).

## Common Commands

### Morning briefing
- "Give me my morning briefing"

### Inbox triage
- "Summarize my unread emails and list action items"

### Focus mode
- "Enable focus mode"

### Deal finder (price compare)
- "I need a new 2TB NVMe SSD. Find the best price on Amazon and Newegg right now."

### YouTube digest
- "Summarize this YouTube video: <url>"

### File hunter
- "Find the PDF about distributed computing from last week and open it"

## UI Panels

Depending on your build, the UI exposes a dashboard for:

- Runs: what Chintu is doing right now, with status and logs
- Evidence: screenshots, DOM snapshots, and run artifacts
- Approvals: pending approvals and an approval ledger
- Schedules: upcoming jobs, night-run windows, pause/resume
- Memory: facts, notes, and retrieval traces
- Integrations: connect Google Calendar, Gmail/IMAP, and provider API keys

## Notes

- Browser automation uses Playwright. If it fails, reinstall the browser runtime:
  `venv\Scripts\python.exe -m playwright install chromium`
- For cloud LLM routing, prefer storing keys in the Identity Vault via UI/CLI.
