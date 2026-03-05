"""Prepare local AirLLM model shards with explicit progress and reports."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from chintu_backend.brain.llm.airllm_client import AirLLMClient
from chintu_backend.core.config import get_config


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _ensure_snapshot_metadata(model_id: str, token: str) -> Path:
    import importlib

    hub = importlib.import_module("huggingface_hub")
    snapshot_download = getattr(hub, "snapshot_download", None)
    if not callable(snapshot_download):
        raise RuntimeError("huggingface_hub.snapshot_download is unavailable.")

    kwargs: Dict[str, Any] = {
        "allow_patterns": ["*.json", "tokenizer*", "*.model", "*.txt", "*.py"],
        "resume_download": True,
    }
    if token:
        kwargs["token"] = token
    path = Path(snapshot_download(model_id, **kwargs))
    return path


def run_prepare(*, model_id: str, max_files: int = 0) -> Dict[str, Any]:
    hf_token = (
        os.environ.get("HF_TOKEN")
        or os.environ.get("HUGGING_FACE_HUB_TOKEN")
        or os.environ.get("HUGGINGFACE_HUB_TOKEN")
        or ""
    )
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    snapshot = _ensure_snapshot_metadata(model_id, hf_token)
    missing = AirLLMClient._missing_weight_files(snapshot)  # noqa: SLF001
    if max_files > 0:
        missing = missing[: int(max_files)]

    started = time.time()
    downloaded: List[Dict[str, Any]] = []
    if missing:
        import importlib

        hub = importlib.import_module("huggingface_hub")
        hf_hub_download = getattr(hub, "hf_hub_download", None)
        if not callable(hf_hub_download):
            raise RuntimeError("huggingface_hub.hf_hub_download is unavailable.")
        for idx, filename in enumerate(missing, start=1):
            t0 = time.time()
            kwargs: Dict[str, Any] = {
                "repo_id": model_id,
                "filename": filename,
                "resume_download": True,
            }
            if hf_token:
                kwargs["token"] = hf_token
            path = hf_hub_download(**kwargs)
            size = -1
            try:
                size = int(Path(path).stat().st_size)
            except Exception:
                size = -1
            downloaded.append(
                {
                    "index": idx,
                    "filename": filename,
                    "latency_s": round(time.time() - t0, 2),
                    "size_bytes": size,
                }
            )

    remaining = AirLLMClient._missing_weight_files(snapshot)  # noqa: SLF001
    return {
        "timestamp_utc": _utc_iso(),
        "model_id": model_id,
        "snapshot_path": str(snapshot),
        "requested_download_count": len(missing),
        "downloaded": downloaded,
        "remaining_missing_count": len(remaining),
        "remaining_missing_preview": remaining[:8],
        "elapsed_s": round(time.time() - started, 2),
        "ready": len(remaining) == 0,
    }


def _render_md(report: Dict[str, Any]) -> str:
    lines = [
        "# AirLLM Model Prepare Report",
        "",
        f"- timestamp_utc: {report.get('timestamp_utc', '')}",
        f"- model_id: {report.get('model_id', '')}",
        f"- snapshot_path: {report.get('snapshot_path', '')}",
        f"- requested_download_count: {report.get('requested_download_count', 0)}",
        f"- remaining_missing_count: {report.get('remaining_missing_count', 0)}",
        f"- elapsed_s: {report.get('elapsed_s', 0.0)}",
        f"- ready: {report.get('ready', False)}",
        "",
        "## Downloads",
        "",
        "| # | File | Latency (s) | Size (bytes) |",
        "|---:|---|---:|---:|",
    ]
    for row in report.get("downloaded", []) if isinstance(report.get("downloaded"), list) else []:
        if not isinstance(row, dict):
            continue
        lines.append(
            "| {i} | {f} | {lat} | {size} |".format(
                i=row.get("index", ""),
                f=str(row.get("filename", "")).replace("|", "\\|"),
                lat=row.get("latency_s", 0.0),
                size=row.get("size_bytes", -1),
            )
        )
    if int(report.get("remaining_missing_count", 0) or 0) > 0:
        lines.append("")
        lines.append("## Remaining Missing")
        for name in report.get("remaining_missing_preview", []) if isinstance(report.get("remaining_missing_preview"), list) else []:
            lines.append(f"- {name}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Download missing AirLLM model shards into local HuggingFace cache.")
    parser.add_argument("--model-id", default="")
    parser.add_argument("--max-files", type=int, default=0, help="Optional cap on number of missing shards to download.")
    parser.add_argument("--out-dir", default=str(REPO_ROOT / "generated_reports"))
    args = parser.parse_args()

    cfg = get_config()
    model_id = str(args.model_id or getattr(cfg, "airllm_model_id", "") or "").strip()
    if not model_id:
        print(json.dumps({"ok": False, "error": "Missing model id. Set CHINTU_AIRLLM_MODEL_ID or pass --model-id."}))
        return 2

    report = run_prepare(model_id=model_id, max_files=max(0, int(args.max_files or 0)))

    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _utc_stamp()
    json_path = out_dir / f"chintu_airllm_prepare_{stamp}.json"
    md_path = out_dir / f"chintu_airllm_prepare_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    md_path.write_text(_render_md(report), encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": bool(report.get("ready")),
                "json_report": str(json_path),
                "markdown_report": str(md_path),
                "remaining_missing_count": int(report.get("remaining_missing_count", 0) or 0),
                "elapsed_s": float(report.get("elapsed_s", 0.0) or 0.0),
            },
            ensure_ascii=True,
        )
    )
    return 0 if bool(report.get("ready")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
