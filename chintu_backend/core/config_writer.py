"""
Config writer for safe .env updates.
Requires explicit confirmation at capability level.
"""

from pathlib import Path
from typing import Optional, Dict
import logging

logger = logging.getLogger(__name__)

ALLOWED_PREFIXES = ("CHINTU_", "GROQ_API_KEY", "GOOGLE_AI_KEY", "DEEPSEEK_API_KEY", "NVIDIA_API_KEY")


def _load_env(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    data: Dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line or line.strip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def set_env_key(key: str, value: str, env_path: Optional[Path] = None) -> bool:
    if not key:
        return False
    if not key.startswith(ALLOWED_PREFIXES):
        return False
    path = env_path or Path.cwd() / ".env"
    data = _load_env(path)
    data[key] = value
    lines = []
    for k, v in data.items():
        lines.append(f"{k}={v}")
    content = "\n".join(lines) + "\n"
    path.write_text(content, encoding="utf-8")
    logger.info("Updated .env key: %s", key)
    return True
