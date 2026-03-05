"""Deployment preflight gate for local release/deploy readiness."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / "generated_reports"


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _required_paths() -> List[str]:
    return [
        "scripts/start_chintu.bat",
        "scripts/setup_env.bat",
        "scripts/package_release.ps1",
        "scripts/quality_gate.ps1",
        "scripts/safety/rollback_manager.py",
        "docs/runbooks/RELEASE_PACKAGING.md",
        "docs/runbooks/INCIDENT_RESPONSE.md",
        "docs/runbooks/DISASTER_RECOVERY.md",
    ]


def _check_required_paths() -> Dict[str, Any]:
    missing = [p for p in _required_paths() if not (REPO_ROOT / p).exists()]
    return {"ok": len(missing) == 0, "missing": missing}


def _check_python_version(min_major: int = 3, min_minor: int = 10) -> Dict[str, Any]:
    ver = sys.version_info
    ok = bool((ver.major, ver.minor) >= (min_major, min_minor))
    return {
        "ok": ok,
        "python_version": f"{ver.major}.{ver.minor}.{ver.micro}",
        "minimum": f"{min_major}.{min_minor}",
    }


def _check_commands() -> Dict[str, Any]:
    cmds = {
        "python": shutil.which("python"),
        "git": shutil.which("git"),
        "powershell": shutil.which("powershell") or shutil.which("pwsh"),
    }
    missing = [name for name, path in cmds.items() if not path]
    return {"ok": len(missing) == 0, "paths": cmds, "missing": missing}


def _check_env_template() -> Dict[str, Any]:
    env_file = REPO_ROOT / ".env.example"
    if not env_file.exists():
        return {"ok": False, "error": "missing .env.example"}
    text = env_file.read_text(encoding="utf-8", errors="ignore")
    required_keys = [
        "CHINTU_OLLAMA_HOST=",
        "CHINTU_OLLAMA_MODEL=",
        "GROQ_API_KEY=",
        "GOOGLE_AI_KEY=",
        "DEEPSEEK_API_KEY=",
        "NVIDIA_API_KEY=",
        "TELEGRAM_BOT_TOKEN=",
    ]
    missing = [key for key in required_keys if key not in text]
    return {"ok": len(missing) == 0, "missing_keys": missing}


def _check_writable_reports_dir() -> Dict[str, Any]:
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        probe = OUTPUT_DIR / f"preflight_probe_{_utc_stamp()}.tmp"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return {"ok": True, "path": str(OUTPUT_DIR)}
    except Exception as exc:
        return {"ok": False, "path": str(OUTPUT_DIR), "error": str(exc)}


def _run_doctor() -> Dict[str, Any]:
    cmd = [sys.executable, str(REPO_ROOT / "scripts" / "chintu_doctor.py")]
    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = str(proc.stdout or "")
    err = str(proc.stderr or "")
    tail = (out + ("\n" + err if err else "")).splitlines()[-40:]
    code = int(proc.returncode)
    hard_fail = code == 2
    # doctor uses 1 for warning state; keep as non-blocking signal.
    return {
        "ok": not hard_fail,
        "hard_fail": hard_fail,
        "warning_state": code == 1,
        "returncode": code,
        "command": " ".join(cmd),
        "output_tail": tail,
    }


def _run_docker_check(strict: bool = False) -> Dict[str, Any]:
    docker_bin = shutil.which("docker")
    if not docker_bin:
        return {
            "ok": (not strict),
            "strict": bool(strict),
            "error": "docker_not_found",
            "command": "docker info",
        }
    cmd = [docker_bin, "info"]
    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    out = str(proc.stdout or "")
    err = str(proc.stderr or "")
    tail = (out + ("\n" + err if err else "")).splitlines()[-30:]
    ready = int(proc.returncode) == 0
    return {
        "ok": bool(ready or (not strict)),
        "strict": bool(strict),
        "docker_ready": bool(ready),
        "returncode": int(proc.returncode),
        "command": " ".join(cmd),
        "output_tail": tail,
    }


def run_deployment_preflight_gate(
    *,
    run_doctor_check: bool = False,
    run_docker_check: bool = False,
    strict_docker: bool = False,
) -> Dict[str, Any]:
    checks: Dict[str, Any] = {
        "required_paths": _check_required_paths(),
        "python_version": _check_python_version(),
        "commands": _check_commands(),
        "env_template": _check_env_template(),
        "writable_reports_dir": _check_writable_reports_dir(),
        "doctor": {"ok": True, "skipped": True, "reason": "disabled_by_default"},
        "docker": {"ok": True, "skipped": True, "reason": "disabled_by_default"},
    }
    if run_doctor_check:
        checks["doctor"] = _run_doctor()
    if run_docker_check:
        checks["docker"] = _run_docker_check(strict=strict_docker)

    gates = {
        "required_paths": bool(checks["required_paths"].get("ok")),
        "python_version": bool(checks["python_version"].get("ok")),
        "commands": bool(checks["commands"].get("ok")),
        "env_template": bool(checks["env_template"].get("ok")),
        "writable_reports_dir": bool(checks["writable_reports_dir"].get("ok")),
        "doctor": bool(checks["doctor"].get("ok")),
        "docker": bool(checks["docker"].get("ok")),
    }
    overall_ok = all(bool(v) for v in gates.values())
    return {
        "phase": "deployment_preflight",
        "timestamp_utc": _utc_iso(),
        "gates": gates,
        "overall_ok": overall_ok,
        "checks": checks,
    }


def _render_md(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# Deployment Preflight Gate")
    lines.append("")
    lines.append(f"- Timestamp (UTC): `{report.get('timestamp_utc', '')}`")
    lines.append(f"- Overall pass: `{report.get('overall_ok')}`")
    lines.append("")
    lines.append("## Gate Summary")
    for key, value in (report.get("gates") or {}).items():
        lines.append(f"- {key}: `{value}`")
    lines.append("")
    checks = report.get("checks") if isinstance(report, dict) else {}
    if isinstance(checks, dict):
        req = checks.get("required_paths")
        if isinstance(req, dict):
            lines.append("## Required Paths")
            lines.append(f"- ok: `{req.get('ok')}`")
            for row in (req.get("missing") or []):
                lines.append(f"- missing: `{row}`")
            lines.append("")
        env = checks.get("env_template")
        if isinstance(env, dict):
            lines.append("## Env Template")
            lines.append(f"- ok: `{env.get('ok')}`")
            for row in (env.get("missing_keys") or []):
                lines.append(f"- missing key: `{row}`")
            lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deployment preflight gate.")
    parser.add_argument("--run-doctor", action="store_true", help="Run scripts/chintu_doctor.py as part of preflight")
    parser.add_argument("--run-docker-check", action="store_true", help="Run docker daemon readiness check")
    parser.add_argument("--strict-docker", action="store_true", help="Treat unavailable docker as gate failure")
    args = parser.parse_args()

    report = run_deployment_preflight_gate(
        run_doctor_check=bool(args.run_doctor),
        run_docker_check=bool(args.run_docker_check),
        strict_docker=bool(args.strict_docker),
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _utc_stamp()
    json_path = OUTPUT_DIR / f"deployment_preflight_gate_{stamp}.json"
    md_path = OUTPUT_DIR / f"deployment_preflight_gate_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    md_path.write_text(_render_md(report), encoding="utf-8")
    print(f"Wrote: {json_path}")
    print(f"Wrote: {md_path}")
    return 0 if bool(report.get("overall_ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())

