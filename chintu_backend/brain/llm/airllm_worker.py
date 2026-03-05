"""Isolated AirLLM worker process for crash-safe generation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

from .airllm_client import AirLLMClient


def _emit(payload: Dict[str, Any]) -> None:
    line = json.dumps(payload, ensure_ascii=True)
    print(f"{AirLLMClient._WORKER_RESPONSE_PREFIX}{line}", flush=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run AirLLM inference worker for Chintu.")
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--cache-dir", default="")
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--compression", default="auto")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--allow-download", type=int, default=0)
    parser.add_argument("--download-timeout-seconds", type=int, default=3600)
    return parser.parse_args()


def _build_client(args: argparse.Namespace) -> AirLLMClient:
    cache_dir = str(args.cache_dir or "").strip()
    return AirLLMClient(
        model_id=str(args.model_id or "").strip(),
        cache_dir=Path(cache_dir).expanduser().resolve() if cache_dir else None,
        max_tokens=max(16, int(args.max_tokens or 2048)),
        temperature=float(args.temperature or 0.2),
        compression=str(args.compression or "auto"),
        device=str(args.device or "auto"),
        allow_download=bool(int(args.allow_download or 0)),
        download_timeout_seconds=max(60, int(args.download_timeout_seconds or 3600)),
        runtime_mode="inprocess",
    )


def main() -> int:
    args = _parse_args()
    client = _build_client(args)

    for raw_line in sys.stdin:
        line = str(raw_line or "").strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except Exception as exc:
            _emit({"id": "", "ok": False, "error": f"invalid_json: {exc}"})
            continue

        request_id = str(request.get("id") or "")
        command = str(request.get("cmd") or "").strip().lower()

        if command == "ping":
            _emit({"id": request_id, "ok": True, "pong": True})
            continue
        if command == "shutdown":
            _emit({"id": request_id, "ok": True, "shutdown": True})
            return 0
        if command != "generate":
            _emit({"id": request_id, "ok": False, "error": f"unsupported_command:{command}"})
            continue

        prompt = str(request.get("prompt") or "")
        system_prompt = str(request.get("system_prompt") or "")
        try:
            text = client.generate(prompt=prompt, system_prompt=system_prompt)
            _emit({"id": request_id, "ok": True, "text": str(text or "")})
        except Exception as exc:
            _emit({"id": request_id, "ok": False, "error": str(exc)})

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
