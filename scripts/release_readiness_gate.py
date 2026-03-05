"""Release-readiness gate for packaging/ops hardening contracts."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import zipfile
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
        "scripts/package_release.ps1",
        "docs/runbooks/RELEASE_PACKAGING.md",
        "docs/runbooks/INCIDENT_RESPONSE.md",
        "docs/runbooks/DISASTER_RECOVERY.md",
        ".github/workflows/quality-gates.yml",
    ]


def _check_required_paths() -> Dict[str, Any]:
    missing = [p for p in _required_paths() if not (REPO_ROOT / p).exists()]
    return {"ok": len(missing) == 0, "missing": missing}


def _check_package_script_policy() -> Dict[str, Any]:
    script = REPO_ROOT / "scripts" / "package_release.ps1"
    if not script.exists():
        return {"ok": False, "error": "missing_package_script"}
    text = script.read_text(encoding="utf-8", errors="ignore")

    required_prunes = [".git", "venv", "logs", "generated_reports", "data"]
    missing_prunes = [token for token in required_prunes if token not in text]

    required_manifest_tokens = [
        "RELEASE_MANIFEST.txt",
        "Security:",
        "Keep .env local",
        "Rotate Telegram/API tokens",
    ]
    missing_manifest_tokens = [token for token in required_manifest_tokens if token not in text]

    return {
        "ok": len(missing_prunes) == 0 and len(missing_manifest_tokens) == 0,
        "missing_prunes": missing_prunes,
        "missing_manifest_tokens": missing_manifest_tokens,
    }


def _resolve_powershell() -> List[str]:
    pwsh = shutil.which("pwsh")
    if pwsh:
        return [pwsh]
    ps = shutil.which("powershell")
    if ps:
        return [ps]
    if sys.platform.startswith("win"):
        return ["powershell"]
    return []


def _run_package_smoke() -> Dict[str, Any]:
    shell = _resolve_powershell()
    if not shell:
        return {"ok": False, "error": "powershell_not_found"}

    stamp = _utc_stamp()
    version = f"gate_probe_{stamp}"
    output_root_rel = "generated_reports/release_smoke"
    script = REPO_ROOT / "scripts" / "package_release.ps1"
    cmd = shell + [
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-Version",
        version,
        "-OutputRoot",
        output_root_rel,
    ]
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
    if int(proc.returncode) != 0:
        return {
            "ok": False,
            "returncode": int(proc.returncode),
            "command": " ".join(cmd),
            "output_tail": tail,
            "error": "package_script_failed",
        }

    smoke_root = REPO_ROOT / "generated_reports" / "release_smoke"
    release_name = f"chintu_release_{version}"
    staging = smoke_root / release_name
    zip_path = smoke_root / f"{release_name}.zip"
    if not staging.exists() or not zip_path.exists():
        return {
            "ok": False,
            "returncode": int(proc.returncode),
            "command": " ".join(cmd),
            "output_tail": tail,
            "error": "release_artifacts_missing",
            "staging": str(staging),
            "zip_path": str(zip_path),
        }

    forbidden_prefixes = [".git/", "venv/", "logs/", "generated_reports/", "data/"]
    zip_forbidden_hits: List[str] = []
    manifest_text = ""
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = [str(name).replace("\\", "/") for name in zf.namelist()]
        for name in names:
            if any(name.startswith(prefix) for prefix in forbidden_prefixes):
                zip_forbidden_hits.append(name)
        try:
            manifest_text = zf.read("RELEASE_MANIFEST.txt").decode("utf-8", errors="ignore")
        except Exception:
            manifest_text = ""

    manifest_ok = bool("Security:" in manifest_text and "Keep .env local" in manifest_text)
    ok = len(zip_forbidden_hits) == 0 and manifest_ok
    return {
        "ok": ok,
        "returncode": int(proc.returncode),
        "command": " ".join(cmd),
        "output_tail": tail,
        "staging": str(staging),
        "zip_path": str(zip_path),
        "zip_forbidden_hits": zip_forbidden_hits[:20],
        "manifest_ok": manifest_ok,
    }


def run_release_readiness_gate(*, run_package_smoke: bool = False) -> Dict[str, Any]:
    required = _check_required_paths()
    policy = _check_package_script_policy()
    smoke = (
        _run_package_smoke()
        if run_package_smoke
        else {"ok": True, "skipped": True, "reason": "disabled_by_default"}
    )

    gates = {
        "required_paths": bool(required.get("ok")),
        "package_script_policy": bool(policy.get("ok")),
        "package_smoke": bool(smoke.get("ok")),
    }
    overall_ok = all(bool(v) for v in gates.values())
    return {
        "phase": "release_readiness",
        "timestamp_utc": _utc_iso(),
        "gates": gates,
        "overall_ok": overall_ok,
        "checks": {
            "required_paths": required,
            "package_script_policy": policy,
            "package_smoke": smoke,
        },
    }


def _render_md(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# Release Readiness Gate")
    lines.append("")
    lines.append(f"- Timestamp (UTC): `{report.get('timestamp_utc', '')}`")
    lines.append(f"- Overall pass: `{report.get('overall_ok')}`")
    lines.append("")
    lines.append("## Gate Summary")
    for key, value in (report.get("gates") or {}).items():
        lines.append(f"- {key}: `{value}`")
    lines.append("")
    checks = report.get("checks") if isinstance(report, dict) else {}
    required = (checks or {}).get("required_paths") if isinstance(checks, dict) else {}
    if isinstance(required, dict):
        lines.append("## Required Paths")
        lines.append(f"- ok: `{required.get('ok')}`")
        missing = required.get("missing") if isinstance(required.get("missing"), list) else []
        if missing:
            for row in missing:
                lines.append(f"- missing: `{row}`")
        lines.append("")
    policy = (checks or {}).get("package_script_policy") if isinstance(checks, dict) else {}
    if isinstance(policy, dict):
        lines.append("## Package Script Policy")
        lines.append(f"- ok: `{policy.get('ok')}`")
        for row in (policy.get("missing_prunes") or []):
            lines.append(f"- missing prune token: `{row}`")
        for row in (policy.get("missing_manifest_tokens") or []):
            lines.append(f"- missing manifest token: `{row}`")
        lines.append("")
    smoke = (checks or {}).get("package_smoke") if isinstance(checks, dict) else {}
    if isinstance(smoke, dict):
        lines.append("## Package Smoke")
        lines.append(f"- ok: `{smoke.get('ok')}`")
        if smoke.get("skipped"):
            lines.append("- skipped: `True`")
            lines.append(f"- reason: `{smoke.get('reason', '')}`")
        else:
            lines.append(f"- command: `{smoke.get('command', '')}`")
            lines.append(f"- returncode: `{smoke.get('returncode', '')}`")
            lines.append(f"- zip_path: `{smoke.get('zip_path', '')}`")
            lines.append(f"- manifest_ok: `{smoke.get('manifest_ok')}`")
            for row in (smoke.get("zip_forbidden_hits") or []):
                lines.append(f"- forbidden hit: `{row}`")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run release-readiness gate.")
    parser.add_argument(
        "--run-package-smoke",
        action="store_true",
        help="Run package_release.ps1 smoke test (slower, creates dist artifacts).",
    )
    args = parser.parse_args()

    report = run_release_readiness_gate(run_package_smoke=bool(args.run_package_smoke))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _utc_stamp()
    json_path = OUTPUT_DIR / f"release_readiness_gate_{stamp}.json"
    md_path = OUTPUT_DIR / f"release_readiness_gate_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    md_path.write_text(_render_md(report), encoding="utf-8")
    print(f"Wrote: {json_path}")
    print(f"Wrote: {md_path}")
    return 0 if bool(report.get("overall_ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())

