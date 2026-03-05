from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from chintu_backend.vision.omniparser import get_omniparser
from chintu_backend.vision.screen_capture import get_screen_manager


def run_probe(image_path: str | None, out_dir: str) -> Path:
    parser = get_omniparser()
    screenshot_path = image_path

    if not screenshot_path:
        screen = get_screen_manager().capture_screen(save=True)
        if not screen or not screen.path:
            raise RuntimeError("Failed to capture screen.")
        screenshot_path = str(screen.path)

    analysis = parser.analyze_screen(image_path=screenshot_path)

    payload = {
        "timestamp_utc": datetime.utcnow().isoformat() + "Z",
        "backend": parser.backend,
        "model": parser.ollama_model,
        "capture_path": screenshot_path,
        "analysis": analysis,
    }

    output_dir = Path(out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"vision_probe_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    output_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture/analyze screen and dump full vision extraction JSON.")
    parser.add_argument("--image", help="Optional image path to analyze instead of capturing live screen.")
    parser.add_argument("--out-dir", default="generated_reports", help="Output directory for JSON report.")
    args = parser.parse_args()

    output_file = run_probe(args.image, args.out_dir)
    print(output_file)


if __name__ == "__main__":
    main()
