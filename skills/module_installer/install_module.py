import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Tuple


def infer_package(request: str) -> str:
    patterns = [
        r"modulenotfounderror[^a-zA-Z0-9_]+for[^a-zA-Z0-9_]+['\"]?([a-zA-Z0-9_.-]+)['\"]?",
        r"install[^a-zA-Z0-9_]+([a-zA-Z0-9_.-]+)",
        r"package[^a-zA-Z0-9_]+['\"]?([a-zA-Z0-9_.-]+)['\"]?",
        r"for[^a-zA-Z0-9_]+['\"]?([a-zA-Z0-9_.-]+)['\"]?",
    ]
    text = request.strip()
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            candidate = match.group(1).strip().strip(".")
            if candidate:
                return candidate
    return "pandas"


def infer_script(request: str) -> str | None:
    match = re.search(r"([A-Za-z0-9_./\\-]+\.py)", request)
    if match:
        return match.group(1)
    for fallback in ["main.py", "app.py", "script.py"]:
        if Path(fallback).exists():
            return fallback
    return None


def _project_venv_python() -> str:
    candidates = [
        Path.cwd() / "venv" / "Scripts" / "python.exe",
        Path.cwd() / ".venv" / "Scripts" / "python.exe",
        Path.cwd() / "venv" / "bin" / "python",
        Path.cwd() / ".venv" / "bin" / "python",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return ""


def _resolve_python_target(request: str) -> Tuple[str, str]:
    in_venv = bool(os.getenv("VIRTUAL_ENV")) or bool(getattr(sys, "base_prefix", sys.prefix) != sys.prefix)
    if in_venv:
        return sys.executable, "active venv"

    requested_venv = bool(re.search(r"\b(?:venv|virtualenv|virtual environment)\b", str(request or ""), flags=re.IGNORECASE))
    project_python = _project_venv_python()
    if project_python:
        if requested_venv:
            return project_python, "project venv (requested)"
        # Prefer project-local interpreter by default to avoid global drift.
        return project_python, "project venv"

    return sys.executable, "system python"


def install_package(package: str, request: str) -> Tuple[bool, str]:
    target_python, target_label = _resolve_python_target(request)
    lower_target = str(target_python or "").lower()
    in_venv_target = (
        bool(target_label.startswith("active venv"))
        or "/venv/" in Path(lower_target).as_posix()
        or "/.venv/" in Path(lower_target).as_posix()
        or "\\venv\\" in lower_target
        or "\\.venv\\" in lower_target
    )
    uv_bin = shutil.which("uv")
    allow_global = os.getenv("CHINTU_MODULE_INSTALL_ALLOW_GLOBAL", "").strip() == "1"
    if in_venv_target and uv_bin:
        install_cmd = [uv_bin, "pip", "install", "--python", target_python, package]
        install_label = f"uv ({target_label})"
    elif in_venv_target:
        install_cmd = [target_python, "-m", "pip", "install", package]
        install_label = f"pip ({target_label})"
    elif allow_global:
        install_cmd = [sys.executable, "-m", "pip", "install", package]
        install_label = "pip (global)"
    else:
        install_cmd = [sys.executable, "-m", "pip", "install", "--user", package]
        install_label = "pip --user"

    if os.getenv("CHINTU_VALIDATE_DRY_RUN", "").strip() == "1":
        print(f"[dry-run] Would install {package} via {install_label}.")
        return True, target_python
    print(f"Installing {package} via {install_label}...")
    result = subprocess.run(
        install_cmd,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        output = result.stdout.strip() or f"{package} installed."
        print(output)
        return True, target_python
    print(result.stderr.strip() or result.stdout.strip())
    return False, target_python


def verify_import(package: str, python_exe: str) -> bool:
    module = package.replace("-", "_")
    aliases = {"python-dotenv": "dotenv", "opencv-python": "cv2", "pyyaml": "yaml", "scikit-learn": "sklearn"}
    module = aliases.get(package, module)
    if os.getenv("CHINTU_VALIDATE_DRY_RUN", "").strip() == "1":
        print(f"[dry-run] Would verify import for {module}.")
        return True
    probe = subprocess.run(
        [python_exe or sys.executable, "-c", f"import {module}; print('ok')"],
        capture_output=True,
        text=True,
    )
    if probe.returncode == 0:
        print(f"Verified import: {module}")
        return True
    print(probe.stderr.strip() or probe.stdout.strip() or f"Import verification failed for {module}")
    return False


def rerun_script(path: str, python_exe: str) -> bool:
    if os.getenv("CHINTU_VALIDATE_DRY_RUN", "").strip() == "1":
        print(f"[dry-run] Would rerun {path} with Python.")
        return True
    print(f"Rerunning {path} with Python...")
    result = subprocess.run(
        [python_exe or sys.executable, path],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print(result.stdout.strip() or "Script executed successfully.")
        return True
    print(result.stderr.strip() or result.stdout.strip())
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Install a missing module and rerun script if available.")
    parser.add_argument("--request", help="Original natural-language request.")
    args, extras = parser.parse_known_args()

    request_parts = []
    if args.request:
        request_parts.append(args.request)
    request_parts.extend(extras)
    request = " ".join(request_parts).strip()
    if not request:
        request = "ModuleNotFoundError for pandas"

    package = infer_package(request)
    script = infer_script(request)

    success, python_target = install_package(package, request)
    if not success:
        print("Package installation failed; not rerunning.")
        return

    verify_import(package, python_target)

    if script:
        rerun_script(script, python_target)
    else:
        print("Package installed. No .py script found in request, so rerun step was skipped.")


if __name__ == "__main__":
    main()
