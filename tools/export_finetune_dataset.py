"""Export approved interactions into a JSONL file for LoRA fine-tuning."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterator


def _load_entries(path: Path) -> Iterator[Dict[str, object]]:
    if not path.exists():
        return iter(())
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _default_output(base_dir: Path) -> Path:
    stamp = datetime.utcnow().strftime("%Y%m%d")
    return base_dir / f"finetune_{stamp}.jsonl"


def main() -> int:
    from chintu.core.config import get_config

    config = get_config()
    parser = argparse.ArgumentParser(description="Export Chintu training dataset")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path(config.training_log_path),
        help="Path to interactions JSONL log",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=_default_output(Path(config.training_exports_dir)),
        help="Output JSONL file path",
    )
    parser.add_argument(
        "--include-unapproved",
        action="store_true",
        help="Include entries that are not approved",
    )
    parser.add_argument(
        "--min-length",
        type=int,
        default=8,
        help="Minimum assistant response length to include",
    )
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)

    exported = 0
    with args.output.open("w", encoding="utf-8") as handle:
        for entry in _load_entries(args.input):
            if not args.include_unapproved and not entry.get("approved", False):
                continue
            assistant_text = str(entry.get("assistant", "")).strip()
            user_text = str(entry.get("user", "")).strip()
            if len(assistant_text) < args.min_length or not user_text:
                continue
            payload = {
                "instruction": user_text,
                "input": "",
                "output": assistant_text,
                "metadata": {
                    "timestamp": entry.get("timestamp"),
                    "source": entry.get("source"),
                    "model_source": entry.get("model_source"),
                    "command_type": entry.get("command_type"),
                    "tags": entry.get("tags", []),
                },
            }
            handle.write(json.dumps(payload, ensure_ascii=True) + "\n")
            exported += 1

    print(f"Exported {exported} entries to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
