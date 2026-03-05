# Content Studio: 30-Second YouTube Short (Local, Verified)

## Goal
Generate a real 30-second vertical (9:16) YouTube Short video locally, with a script, TTS audio, subtitles, and a rendered `short.mp4`.

Publishing/upload is intentionally out of scope and must remain gated (high risk + OAuth).

## Prerequisites
- Ollama running (local-first model routing).
- `ffmpeg` and `ffprobe` on PATH.
- Optional but recommended: working TTS backend (so audio is generated instead of script-only output).

## Generate Assets
From a Chintu session, trigger the generator:
- Example: `build short video about local LLM workflows, duration 30 seconds`

Outputs are written under:
- default: `~/.chintu/content_studio/youtube_shorts/<stamp>_<slug>/`
- benchmark: under the benchmark `{out_dir}` when provided by the benchmark runner

Expected files (best-effort):
- `script.txt`
- `voice.mp3` (if TTS succeeds)
- `captions.srt` (if audio duration can be measured)
- `short.mp4` (if ffmpeg is available and audio exists)
- `metadata.json`

## Verify Duration
Command:

```powershell
ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 short.mp4
```

Expected:
- Duration is approximately 30 seconds (benchmark tolerance may allow a small window).

## Safety Boundaries
- No uploading, no OAuth-driven publish steps.
- Any "publish" request must require explicit confirmation and remain blocked by policy unless approved.

