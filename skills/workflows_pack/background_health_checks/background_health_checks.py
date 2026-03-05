from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
from urllib import error as urlerror
from urllib import request as urlrequest


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from chintu_backend.core.config import get_config
from chintu_backend.core.events import Event, EventType, get_event_bus
from chintu_backend.core.scheduler import get_scheduler


def _today_key() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_doctor() -> Dict[str, Any]:
    cmd = [sys.executable, str(REPO_ROOT / "scripts" / "chintu_doctor.py")]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=240, check=False)
    return {
        "ok": proc.returncode == 0,
        "returncode": int(proc.returncode),
        "stdout_tail": "\n".join((proc.stdout or "").splitlines()[-30:]),
        "stderr_tail": "\n".join((proc.stderr or "").splitlines()[-20:]),
    }


def _gpu_health() -> Dict[str, Any]:
    cmd = [
        "nvidia-smi",
        "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total",
        "--format=csv,noheader,nounits",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=False)
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}
    if proc.returncode != 0:
        return {"ok": False, "reason": (proc.stderr or proc.stdout or "").strip()[:240]}
    rows = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
    return {"ok": True, "rows": rows}


def _ollama_status() -> Dict[str, Any]:
    cfg = get_config()
    base = str(getattr(cfg, "ollama_host", "http://localhost:11434") or "http://localhost:11434").rstrip("/")
    url = f"{base}/api/tags"
    req = urlrequest.Request(url, method="GET")
    try:
        with urlrequest.urlopen(req, timeout=4) as response:
            payload = json.loads(response.read().decode("utf-8", errors="ignore"))
    except (urlerror.URLError, TimeoutError, OSError, ValueError) as exc:
        return {"ok": False, "reason": str(exc)}
    models = []
    for item in payload.get("models", []) or []:
        if isinstance(item, dict) and item.get("name"):
            models.append(str(item["name"]))
    return {"ok": True, "model_count": len(models), "models": models[:20]}


def _disk_free() -> Dict[str, Any]:
    cfg = get_config()
    target = Path(getattr(cfg, "data_dir", REPO_ROOT))
    usage = shutil.disk_usage(str(target))
    gb = 1024 * 1024 * 1024
    return {
        "path": str(target),
        "total_gb": round(float(usage.total) / gb, 2),
        "used_gb": round(float(usage.used) / gb, 2),
        "free_gb": round(float(usage.free) / gb, 2),
    }


def _publish_health_notification(
    *,
    report_path: Path,
    doctor: Dict[str, Any],
    gpu: Dict[str, Any],
    ollama: Dict[str, Any],
    disk: Dict[str, Any],
) -> None:
    try:
        doctor_ok = bool(doctor.get("ok"))
        gpu_ok = bool(gpu.get("ok"))
        ollama_ok = bool(ollama.get("ok"))
        free_gb = disk.get("free_gb")
        status = "ok" if (doctor_ok and gpu_ok and ollama_ok) else "degraded"
        message = (
            f"Health check {status}: doctor={doctor_ok}, gpu={gpu_ok}, "
            f"ollama={ollama_ok}, free_gb={free_gb}"
        )
        bus = get_event_bus()
        bus.publish_sync(
            Event(
                type=EventType.NOTIFICATION,
                source="workflow:background_health_checks",
                data={
                    "title": "Daily health check",
                    "message": message,
                    "status": status,
                    "report_path": str(report_path),
                    "workflow": "background_health_checks",
                },
            )
        )
    except Exception:
        # Best-effort only; health report writing should still succeed.
        return


def write_health_report() -> Path:
    cfg = get_config()
    out_dir = Path(cfg.data_dir) / "health"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"{_today_key()}.md"

    doctor = _run_doctor()
    gpu = _gpu_health()
    ollama = _ollama_status()
    disk = _disk_free()

    lines = [
        f"# Background Health Check ({_today_key()})",
        "",
        f"- Generated UTC: {_utc_now()}",
        "",
        "## Doctor",
        f"- OK: {doctor.get('ok')}",
        f"- Return code: {doctor.get('returncode')}",
        "",
        "```text",
        str(doctor.get("stdout_tail") or "").strip(),
        "```",
        "",
        "## GPU",
    ]
    if gpu.get("ok"):
        rows = gpu.get("rows") or []
        if rows:
            for row in rows:
                lines.append(f"- {row}")
        else:
            lines.append("- nvidia-smi returned no rows.")
    else:
        lines.append(f"- Unavailable: {gpu.get('reason', 'unknown')}")

    lines.extend(
        [
            "",
            "## Ollama",
            f"- OK: {ollama.get('ok')}",
        ]
    )
    if ollama.get("ok"):
        lines.append(f"- Models: {ollama.get('model_count', 0)}")
        for name in ollama.get("models", []):
            lines.append(f"  - {name}")
    else:
        lines.append(f"- Reason: {ollama.get('reason', 'unknown')}")

    lines.extend(
        [
            "",
            "## Disk",
            f"- Path: {disk.get('path')}",
            f"- Free: {disk.get('free_gb')} GB",
            f"- Used: {disk.get('used_gb')} GB",
            f"- Total: {disk.get('total_gb')} GB",
            "",
        ]
    )
    report_path.write_text("\n".join(lines), encoding="utf-8")
    _publish_health_notification(
        report_path=report_path,
        doctor=doctor,
        gpu=gpu,
        ollama=ollama,
        disk=disk,
    )
    return report_path


def ensure_daily_schedule() -> Dict[str, Any]:
    scheduler = get_scheduler()
    workflow_text = "run background health checks"
    for task in scheduler.list_tasks():
        if str(getattr(task, "workflow", "")).strip().lower() == workflow_text:
            return {"scheduled": True, "created": False, "task_id": str(getattr(task, "id", ""))}
    task = scheduler.schedule(
        name="Background health checks",
        workflow=workflow_text,
        schedule_type="daily",
        schedule_time="09:00",
    )
    return {"scheduled": True, "created": True, "task_id": str(task.id)}


def run(request_text: str) -> Dict[str, Any]:
    low = str(request_text or "").lower()
    wants_schedule = any(token in low for token in ["set up", "setup", "schedule", "daily"])
    run_now = "schedule only" not in low

    result: Dict[str, Any] = {
        "workflow": "background_health_checks",
        "requested_schedule": bool(wants_schedule),
        "requested_run_now": bool(run_now),
        "timestamp_utc": _utc_now(),
    }
    if wants_schedule:
        result["schedule"] = ensure_daily_schedule()
    if run_now:
        report_path = write_health_report()
        result["report_path"] = str(report_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Background health checks workflow.")
    parser.add_argument("--request", default="")
    args = parser.parse_args()
    print(json.dumps(run(args.request), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
