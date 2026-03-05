# Vision System

This document describes how Chintu captures the screen, runs vision analysis, and returns actionable UI context.

## 1) Runtime flow

1. `screen_capabilities.handle_whats_on_screen` captures the current screen.
2. `OmniParser` analyzes the image using the active backend.
3. Response is normalized into a stable schema:
   - `success`
   - `description`
   - `elements[]` (`name`, `type`, `location`, `text`)
   - `text_content`
   - `actions[]`
4. Chintu returns a human-style summary:
   - short description
   - key elements
   - available actions
   - readable text (short snippet)
   - running apps summary

Primary files:
- `chintu_backend/vision/screen_capabilities.py`
- `chintu_backend/vision/omniparser.py`
- `chintu_backend/vision/screen_capture.py`
- Prompt playbooks:
  - `chintu_backend/core/playbooks/vision.py`

## 2) Backend selection

Default is local-first for privacy and reliability.

- Local backend: Ollama vision models
- Cloud fallback: Gemini vision (if enabled/configured)

Environment controls:
- `CHINTU_VISION_PREFER_LOCAL=true` (recommended)
- `CHINTU_VISION_OLLAMA_MODEL=qwen3-vl:8b`
- `CHINTU_OLLAMA_HOST=http://localhost:11434`

## 3) Model priority

Current preferred order for local vision:

1. `qwen3-vl:8b`
2. `qwen2.5-vl:7b`
3. `llama3.2-vision:11b`
4. `qwen3-vl:4b`
5. `qwen3-vl:2b`
6. `qwen2.5-vl:3b`
7. `llava:7b`
8. `moondream`

If the first model times out or errors, Chintu retries with the next installed candidate.

## 4) Screenshot storage

Saved screenshots are written to:

- `C:\Users\<you>\.chintu\screenshots\`

Naming format:
- `screenshot_YYYYMMDD_HHMMSS.png`

Capture path is returned in capability metadata and can be logged in reports.

## 5) Vision output quality safeguards

Implemented safeguards:
- strict JSON extraction when available
- plain-text section parser fallback for non-JSON model output
- normalization of heterogeneous model responses into one schema
- placeholder filtering (drops junk values like `N/A`, `optional visible text`)
- bounded element/action counts to reduce noisy output

## 6) Policy behavior

Read-only screen capabilities are configured as low-risk and no-confirmation:
- `screen_query`
- `whats_on_screen`
- `read_screen_text`

This prevents unnecessary confirmation prompts for simple screen understanding.

## 7) TTS behavior with vision responses

TTS sanitization is designed to avoid reading raw URLs, paths, markdown syntax, or citations in normal mode.

Recent hardening:
- shutdown-safe handling for Edge-TTS runtime teardown
- controlled fallback to local TTS when available
- reduced fallback error spam when local fallback is unavailable

Primary file:
- `chintu_backend/audio/text_to_speech.py`

## 8) Debug and verification

Use this script to inspect raw extraction output:

```powershell
$env:PYTHONPATH='.'
python scripts/vision_debug_probe.py
```

Or analyze a specific screenshot:

```powershell
$env:PYTHONPATH='.'
python scripts/vision_debug_probe.py --image "C:\Users\<you>\.chintu\screenshots\screenshot_YYYYMMDD_HHMMSS.png"
```

Output:
- `generated_reports/vision_probe_YYYYMMDD_HHMMSS.json`

This JSON contains backend, model, capture path, normalized analysis, and raw model response.
