"""Pre-flight dependency checks for start_chintu.bat.

Exit codes:
0 = all good
1 = Python dependencies missing (pip install needed)
2 = critical failure
3 = ffmpeg missing (installer can handle this path)
"""

from __future__ import annotations

import importlib
import shutil
import sys


REQUIRED_MODULES = [
    "requests",
    "pydantic",
    "pydantic_settings",
    "websockets",
]


def main() -> int:
    if shutil.which("ffmpeg") is None:
        print("[WARN] ffmpeg not found in PATH.")
        return 3

    missing = []
    for module in REQUIRED_MODULES:
        try:
            importlib.import_module(module)
        except Exception:
            missing.append(module)

    if missing:
        print("[WARN] Missing Python modules: " + ", ".join(sorted(missing)))
        return 1

    print("[OK] Dependency pre-flight checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
