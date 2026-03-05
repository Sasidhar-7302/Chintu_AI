# Installation Guide (Windows)

This guide sets up Chintu on Windows for local-first execution with optional cloud LLMs.

## Prerequisites

1. Python 3.10+ (added to PATH)
1. FFmpeg (recommended, used by audio/video features)
1. Ollama (recommended, used as the local brain model host)
1. A microphone (optional, for voice input)
1. Flutter SDK (optional, only if you want to run the UI from source)

## Quick Setup (Recommended)

1. Create a virtual environment and install dependencies:

```powershell
scripts\setup_env.bat
```

1. Install Playwright Chromium (for browser automation):

```powershell
venv\Scripts\python.exe -m playwright install chromium
```

1. Configure basics and API keys (recommended: Identity Vault):

```powershell
venv\Scripts\python.exe scripts\chintu_cli.py onboard
```

If you prefer `.env`, copy the template:

```powershell
copy .env.example .env
```

1. Start Chintu (backend plus UI launcher):

```powershell
scripts\start_chintu.bat
```

1. Complete the first-run UI onboarding card (appears once after splash).
   - this stores a local onboarding marker and opens the main workspace.

## Manual Setup

```powershell
python -m venv venv
venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install chromium
copy .env.example .env
scripts\start_chintu.bat
```

## Troubleshooting

- Python not recognized: reinstall Python and enable Add to PATH.
- C++ build tools errors: install Microsoft C++ Build Tools.
- No voice input: check Windows Sound settings and ensure a default input device exists.
- Browser automation errors: re-run `python -m playwright install chromium` inside the venv.
