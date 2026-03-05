"""Model fit analysis helpers for local routing and doctor/report checks."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from chintu_backend.core.config import get_config


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_command(cmd: List[str], timeout_s: float = 10.0) -> Dict[str, Any]:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=float(timeout_s),
            check=False,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc), "command": cmd, "stdout": "", "stderr": ""}
    return {
        "ok": bool(proc.returncode == 0),
        "command": cmd,
        "returncode": int(proc.returncode),
        "stdout": str(proc.stdout or ""),
        "stderr": str(proc.stderr or ""),
    }


def _collect_system_info() -> Dict[str, Any]:
    cpu_threads = int(os.cpu_count() or 0)
    ram_gb: Optional[float] = None
    try:
        import psutil  # type: ignore

        ram_gb = round(float(psutil.virtual_memory().total) / (1024 ** 3), 2)
    except Exception:
        ram_gb = None

    nvidia = _run_command(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,memory.used,utilization.gpu,driver_version",
            "--format=csv,noheader,nounits",
        ],
        timeout_s=4.0,
    )
    gpus: List[Dict[str, Any]] = []
    if nvidia.get("ok"):
        for line in str(nvidia.get("stdout") or "").splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) < 5:
                continue
            try:
                total_mb = int(float(parts[1]))
            except Exception:
                total_mb = 0
            try:
                used_mb = int(float(parts[2]))
            except Exception:
                used_mb = 0
            try:
                util_percent = float(parts[3])
            except Exception:
                util_percent = 0.0
            gpus.append(
                {
                    "name": parts[0],
                    "memory_total_mb": total_mb,
                    "memory_used_mb": used_mb,
                    "util_percent": util_percent,
                    "driver_version": parts[4],
                }
            )

    return {
        "cpu_threads": cpu_threads,
        "ram_gb": ram_gb,
        "gpu_count": len(gpus),
        "gpus": gpus,
        "nvidia_smi_raw": nvidia,
    }


def _parse_ollama_list(stdout: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    lines = [line.rstrip() for line in str(stdout or "").splitlines() if line.strip()]
    if not lines:
        return rows
    for line in lines[1:]:
        parts = line.split()
        if not parts:
            continue
        name = parts[0].strip()
        if not name:
            continue
        size = ""
        modified = ""
        if len(parts) >= 2:
            size = parts[-2]
            modified = parts[-1]
        rows.append({"name": name, "size": size, "modified": modified})
    return rows


def _collect_ollama_info(max_show_models: int = 6) -> Dict[str, Any]:
    list_result = _run_command(["ollama", "list"], timeout_s=10.0)
    parsed = _parse_ollama_list(str(list_result.get("stdout") or ""))
    installed_names = [row.get("name", "") for row in parsed if row.get("name")]

    cfg = get_config()
    candidate_models: List[str] = []
    for name in [
        str(getattr(cfg, "ollama_model", "") or "").strip(),
        str(getattr(cfg, "ollama_model_strong", "") or "").strip(),
        str(getattr(cfg, "vision_ollama_model", "") or "").strip(),
    ]:
        if name and name not in candidate_models:
            candidate_models.append(name)
    for name in list(getattr(cfg, "llm_local_fallback_models", []) or []):
        model_name = str(name or "").strip()
        if model_name and model_name not in candidate_models:
            candidate_models.append(model_name)

    show_targets: List[str] = []
    for model_name in candidate_models + installed_names:
        if model_name and model_name not in show_targets:
            show_targets.append(model_name)
        if len(show_targets) >= max(1, int(max_show_models)):
            break

    show_results: Dict[str, Dict[str, Any]] = {}
    for model_name in show_targets:
        show_results[model_name] = _run_command(["ollama", "show", model_name], timeout_s=10.0)

    return {
        "list_command": list_result,
        "models": parsed,
        "installed_names": installed_names,
        "show_results": show_results,
    }


def _has_model(installed: List[str], target: str) -> bool:
    model = str(target or "").strip().lower()
    if not model:
        return False
    target_base = model.split(":", 1)[0]
    for name in installed:
        low = str(name or "").strip().lower()
        if low == model:
            return True
        if low.split(":", 1)[0] == target_base:
            return True
        if low.startswith(f"{target_base}:"):
            return True
    return False


def _pick_from_candidates(installed: List[str], candidates: List[str]) -> str:
    for candidate in candidates:
        if _has_model(installed, candidate):
            return candidate
    return str(installed[0]) if installed else ""


def _pick_strong_model(installed: List[str], fallback_candidates: List[str]) -> str:
    for candidate in fallback_candidates:
        low = candidate.lower()
        if any(token in low for token in ["32b", "27b", "14b", "13b", "12b", "9b", "8b", "7b"]) and _has_model(
            installed, candidate
        ):
            return candidate
    for name in installed:
        low = str(name).lower()
        if any(token in low for token in ["32b", "27b", "14b", "13b", "12b", "9b", "8b", "7b"]):
            return str(name)
    return _pick_from_candidates(installed, fallback_candidates)


def _pick_vision_model(installed: List[str], configured: str) -> str:
    if _has_model(installed, configured):
        return configured
    for name in installed:
        low = str(name).lower()
        if any(token in low for token in ["vl", "vision", "llava", "moondream"]):
            return str(name)
    return configured if configured else ""


def recommend_model_settings(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    cfg = get_config()
    installed = list(snapshot.get("ollama", {}).get("installed_names", []) or [])
    fallback_candidates = [str(name) for name in list(getattr(cfg, "llm_local_fallback_models", []) or []) if str(name)]

    base_recommended = _pick_from_candidates(installed, [str(getattr(cfg, "ollama_model", "") or "")] + fallback_candidates)
    strong_recommended = _pick_strong_model(
        installed,
        [str(getattr(cfg, "ollama_model_strong", "") or "")] + fallback_candidates,
    )
    vision_recommended = _pick_vision_model(installed, str(getattr(cfg, "vision_ollama_model", "") or ""))

    gpus = list(snapshot.get("system", {}).get("gpus", []) or [])
    vram_top_mb = max([int(g.get("memory_total_mb", 0) or 0) for g in gpus] or [0])
    if vram_top_mb >= 20_000:
        llm_num_gpu_recommended = 60
    elif vram_top_mb >= 10_000:
        llm_num_gpu_recommended = 40
    elif vram_top_mb >= 6_000:
        llm_num_gpu_recommended = 20
    else:
        llm_num_gpu_recommended = 0

    mismatches: List[str] = []
    configured_base = str(getattr(cfg, "ollama_model", "") or "")
    configured_strong = str(getattr(cfg, "ollama_model_strong", "") or "")
    configured_vision = str(getattr(cfg, "vision_ollama_model", "") or "")
    configured_num_gpu = int(getattr(cfg, "llm_num_gpu", 0) or 0)

    if installed and configured_base and not _has_model(installed, configured_base):
        mismatches.append(f"Configured base model not installed: {configured_base}")
    if installed and configured_strong and not _has_model(installed, configured_strong):
        mismatches.append(f"Configured strong model not installed: {configured_strong}")
    if configured_vision and installed and not _has_model(installed, configured_vision):
        mismatches.append(f"Configured vision model not installed: {configured_vision}")
    if abs(configured_num_gpu - llm_num_gpu_recommended) >= 20:
        mismatches.append(
            f"Configured llm_num_gpu={configured_num_gpu} differs from recommended {llm_num_gpu_recommended}"
        )

    return {
        "recommended": {
            "ollama_model": base_recommended,
            "ollama_model_strong": strong_recommended,
            "vision_ollama_model": vision_recommended,
            "llm_num_gpu": llm_num_gpu_recommended,
        },
        "configured": {
            "ollama_model": configured_base,
            "ollama_model_strong": configured_strong,
            "vision_ollama_model": configured_vision,
            "llm_num_gpu": configured_num_gpu,
        },
        "mismatches": mismatches,
    }


def collect_model_fit_snapshot(max_show_models: int = 6) -> Dict[str, Any]:
    snapshot = {
        "timestamp_utc": _utc_now(),
        "system": _collect_system_info(),
        "ollama": _collect_ollama_info(max_show_models=max_show_models),
    }
    snapshot["fit"] = recommend_model_settings(snapshot)
    return snapshot


def _render_markdown(snapshot: Dict[str, Any]) -> str:
    system = snapshot.get("system", {}) or {}
    ollama = snapshot.get("ollama", {}) or {}
    fit = snapshot.get("fit", {}) or {}
    rec = fit.get("recommended", {}) or {}
    cfg = fit.get("configured", {}) or {}
    mismatches = list(fit.get("mismatches", []) or [])

    lines = [
        "# Chintu Model Fit Report",
        "",
        f"- Generated UTC: {snapshot.get('timestamp_utc', '')}",
        f"- CPU threads: {system.get('cpu_threads', 0)}",
        f"- RAM (GB): {system.get('ram_gb', 'unknown')}",
        f"- GPU count: {system.get('gpu_count', 0)}",
        "",
        "## Installed Ollama Models",
    ]
    installed = list(ollama.get("installed_names", []) or [])
    if installed:
        for name in installed[:30]:
            lines.append(f"- {name}")
    else:
        lines.append("- None detected via `ollama list`.")

    lines.extend(
        [
            "",
            "## Recommended Settings",
            f"- Base model: {rec.get('ollama_model', '')}",
            f"- Strong model: {rec.get('ollama_model_strong', '')}",
            f"- Vision model: {rec.get('vision_ollama_model', '')}",
            f"- llm_num_gpu: {rec.get('llm_num_gpu', '')}",
            "",
            "## Current Settings",
            f"- Base model: {cfg.get('ollama_model', '')}",
            f"- Strong model: {cfg.get('ollama_model_strong', '')}",
            f"- Vision model: {cfg.get('vision_ollama_model', '')}",
            f"- llm_num_gpu: {cfg.get('llm_num_gpu', '')}",
            "",
            "## Alignment",
        ]
    )
    if mismatches:
        for msg in mismatches:
            lines.append(f"- [WARN] {msg}")
    else:
        lines.append("- [OK] Current model settings match recommended fit.")
    lines.append("")
    return "\n".join(lines)


def write_model_fit_reports(snapshot: Dict[str, Any], output_dir: Path) -> Tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"chintu_model_fit_{stamp}.json"
    md_path = output_dir / f"chintu_model_fit_{stamp}.md"

    json_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=True), encoding="utf-8")
    md_path.write_text(_render_markdown(snapshot), encoding="utf-8")
    return json_path, md_path

