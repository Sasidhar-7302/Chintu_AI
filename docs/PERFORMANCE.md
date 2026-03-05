# Performance Guide

This guide covers practical performance tuning for Chintu on Windows.

## Baseline Assumptions

- Local brain is hosted by Ollama (`CHINTU_OLLAMA_HOST`).
- Heavy lifting (coding, planning) should prefer the RTX 3060.
- Background and always-on tasks should stay lightweight.

## Recommended Models (Local)

Pick one good default brain model and keep it stable.

- Default brain (fast + capable): `qwen3.5:4b`
- If you can afford more VRAM and want higher quality: `qwen3.5:9b` (or a 14B coder model quantized to Q4)

Set in `.env`:

```env
CHINTU_OLLAMA_MODEL=qwen3.5:4b
CHINTU_OLLAMA_MODEL_STRONG=qwen3.5:9b
```

## Speech-to-Text (Whisper)

If you run STT locally, prefer a smaller model for latency:

```env
CHINTU_WHISPER_MODEL=small.en
CHINTU_WHISPER_DEVICE=auto
```

If you want faster response, try `tiny.en`.

## Browser Automation (Playwright)

Install the Chromium runtime once:

```powershell
venv\Scripts\python.exe -m playwright install chromium
```

For shopping sites and other anti-bot pages, reliability is best with a persistent browser profile.
Chintu stores Playwright profiles under `~\.chintu\browser_profiles` by default.

## Night Runs and Scheduling

Chintu can run heavier workflows during a night window.
Tune these in `.env` (hours are 0-24):

```env
CHINTU_NIGHT_RUN_START_HOUR=1
CHINTU_NIGHT_RUN_END_HOUR=6
```

If you want Chintu to only run when the PC is idle:

```env
CHINTU_ORCHESTRATOR_REQUIRE_IDLE=true
CHINTU_ORCHESTRATOR_IDLE_MIN_SECONDS=600
CHINTU_ORCHESTRATOR_IDLE_MAX_CPU_PERCENT=30
CHINTU_ORCHESTRATOR_IDLE_MAX_GPU_UTIL_PERCENT=25
```

## Cloud Routing (Optional)

Cloud models can be used for complex research and vision tasks when local hardware is limited.
Configure provider keys via the Identity Vault (recommended) or `.env`.

```env
GROQ_API_KEY=
GOOGLE_AI_KEY=
DEEPSEEK_API_KEY=
NVIDIA_API_KEY=
```

## How to Start

```powershell
scripts\start_chintu.bat
```

## Common Problems

- Ollama slow: make sure you are using a quantized model and not running other GPU-heavy apps.
- Browser automation missing: run `python -m playwright install chromium` in the venv.
- Audio features not working: install FFmpeg and ensure it is in PATH.
