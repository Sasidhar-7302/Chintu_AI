"""Lightweight skill loader for topic detection and listing."""

from __future__ import annotations

from typing import Dict, List, Optional

from chintu_backend.automation.skills.skill_registry import SkillRegistry
from chintu_backend.core.config import get_config


class SkillLoader:
    """Loads SKILL.md definitions for discovery helpers."""

    def __init__(self) -> None:
        self._registry = SkillRegistry()
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        config = get_config()
        sources = [
            (config.skills_bundled_dir, "bundled"),
            (config.skills_learned_dir, "learned"),
            (config.skills_user_dir, "user"),
            (config.skills_dir, "workspace"),
        ]
        sources = [(path, label) for path, label in sources if path]
        self._registry.load_sources(sources)
        self._loaded = True

    def list_skills(self) -> List[Dict[str, str]]:
        self._ensure_loaded()
        skills = []
        for spec in self._registry._skills.values():  # pylint: disable=protected-access
            skills.append(
                {
                    "name": spec.name,
                    "description": spec.description,
                    "triggers": ", ".join(spec.triggers),
                    "source": spec.source or "",
                }
            )
        return skills

    def detect_topic(self, query: str) -> Optional[str]:
        self._ensure_loaded()
        lowered = query.lower()
        for spec in self._registry._skills.values():  # pylint: disable=protected-access
            for trigger in spec.triggers:
                if trigger.lower() in lowered:
                    return spec.name
        return None


_loader: Optional[SkillLoader] = None


def get_skill_loader() -> SkillLoader:
    """Return a singleton skill loader instance."""
    global _loader
    if _loader is None:
        _loader = SkillLoader()
    return _loader
