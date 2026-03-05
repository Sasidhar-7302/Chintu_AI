"""Phase 6 voice QA replay harness (STT + Smart TTS)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from chintu_backend.audio.speech_to_text import SpeechToText
from chintu_backend.core.app import ChintuAssistant
from chintu_backend.core.capability_handlers import handle_read_response
from chintu_backend.core.command_handler import sanitize_for_tts


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def run_replay() -> dict:
    default_text = (
        "=== Daily Briefing ===\n"
        "1. Model update announced - https://example.com/model [1]\n"
        "Saved to C:\\Users\\yepur\\Desktop\\briefing.md\n"
    )
    sanitized = sanitize_for_tts(default_text)
    preserve = sanitize_for_tts(default_text, preserve_links=True)
    summary = sanitize_for_tts(
        (
            "Task completed. Created report and validated checkpoints. "
            "Uploaded artifacts and generated release notes. "
            "Next step: say read exact output for full logs."
        ),
        summarize=True,
        max_sentences=2,
        max_words=14,
    )

    handler = SimpleNamespace(_last_response=default_text)
    links_result = handle_read_response("read links and citations", {"command_handler": handler})
    exact_result = handle_read_response("read exact output", {"command_handler": handler})

    # STT generation guard and low-confidence noise gate.
    original_load_model = SpeechToText._load_model
    try:
        SpeechToText._load_model = lambda self: setattr(self, "_backend", "simulation")
        stt = SpeechToText(min_confidence=0.4)
        callbacks: list[str] = []
        stt.set_transcript_callback(lambda text, is_final: callbacks.append(text if is_final else ""))

        def fake_transcribe(_audio, is_partial=False):
            stt._last_confidence = 0.12
            return "" if is_partial else "h n 2 h n 2 h n 2 h n 2"

        stt._transcribe = fake_transcribe  # type: ignore[assignment]
        stt.start_listening()
        stale = stt._listen_generation
        stt.start_listening()
        current = stt._listen_generation
        stt._run_final_transcription(np.zeros(24, dtype=np.float32), generation=stale)
        stale_ignored = len(callbacks) == 0
        stt._run_final_transcription(np.zeros(24, dtype=np.float32), generation=current)
        noise_dropped = bool(callbacks) and callbacks[-1] == ""
    finally:
        SpeechToText._load_model = original_load_model

    calibrated = ChintuAssistant._compute_calibrated_stt_threshold(
        [0.004, 0.005, 0.006, 0.008, 0.010, 0.012],
        base_threshold=0.02,
        noise_multiplier=3.0,
    )

    checks = {
        "default_tts_suppresses_links": "https://" not in sanitized.lower(),
        "default_tts_suppresses_paths": "c:" not in sanitized.lower(),
        "read_links_mode_preserves_links": bool(links_result.data.get("speak_preserve_links")),
        "read_exact_mode_is_verbatim": bool(exact_result.data.get("speak_verbatim")),
        "summary_mode_adds_read_more_prompt": "i can read more details if you want" in summary.lower(),
        "preserve_links_keeps_url": "https://example.com/model" in preserve,
        "stt_stale_generation_ignored": stale_ignored,
        "stt_low_confidence_noise_dropped": noise_dropped,
        "stt_calibration_threshold_clamped": 0.02 <= calibrated <= 0.20,
    }
    success = all(checks.values())

    return {
        "phase": "phase6",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "success": success,
        "checks": checks,
        "metrics": {
            "calibrated_threshold": calibrated,
            "sanitized_preview": sanitized[:240],
            "summary_preview": summary[:240],
        },
    }


def main() -> int:
    report = run_replay()
    reports_dir = Path("generated_reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"phase6_voice_qa_replay_{_stamp()}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote replay report: {path}")
    if report.get("success"):
        print("Phase 6 replay: PASS")
        return 0
    print("Phase 6 replay: FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
