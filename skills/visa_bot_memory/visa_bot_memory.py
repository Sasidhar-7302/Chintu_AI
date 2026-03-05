from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from chintu_backend.brain.memory.facade import MemoryFacade


NOISE_PATTERNS = [
    "i need your confirmation",
    "side effects",
    "executed capability",
    "i apologize",
    "as an ai",
    "i don't have access",
    "=== visa bot recall ===",
]


def _normalize_item(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text.strip(" .-"))
    return cleaned


def _is_noise(text: str) -> bool:
    lowered = text.lower().strip()
    if not lowered:
        return True
    if "|" in lowered or len(lowered) > 140:
        return True
    return any(pattern in lowered for pattern in NOISE_PATTERNS)


def _extract_feature_items(text: str) -> List[str]:
    content = text.strip()
    if ":" in content:
        content = content.split(":", 1)[1]
    parts = [p.strip() for p in re.split(r",|;", content) if p.strip()]
    items = []
    for part in parts:
        normalized = _normalize_item(part)
        if len(normalized) < 3 or _is_noise(normalized):
            continue
        items.append(normalized)
    return items


def _extract_todo_items(text: str) -> List[str]:
    numbered = re.findall(r"\d+\)\s*([^0-9]+?)(?=\d+\)|$)", text)
    items = []
    for item in numbered:
        normalized = _normalize_item(item)
        if normalized and not _is_noise(normalized):
            items.append(normalized)
    if items:
        return items

    parts = [p.strip() for p in re.split(r",|;", text) if p.strip()]
    fallback = []
    for part in parts:
        normalized = _normalize_item(part)
        if len(normalized) < 3 or _is_noise(normalized):
            continue
        fallback.append(normalized)
    return fallback


def main() -> None:
    print("=== Visa Bot Recall ===")

    facade = MemoryFacade()
    notes = facade.get_notes(query="Visa Bot", limit=20)
    if not notes:
        notes = facade.get_notes(query="visa", limit=20)

    if not notes:
        print("No memories about Visa Bot were found yet.")
        return

    features: List[str] = []
    todos: List[str] = []

    prioritized_feature_notes = [
        note.content or ""
        for note in notes
        if "visa bot project feature list" in (note.content or "").lower()
    ]
    prioritized_todo_notes = [
        note.content or ""
        for note in notes
        if "visa bot todo" in (note.content or "").lower()
    ]

    if prioritized_feature_notes:
        for text in prioritized_feature_notes:
            for item in _extract_feature_items(text):
                if item not in features:
                    features.append(item)
    if prioritized_todo_notes:
        for text in prioritized_todo_notes:
            for item in _extract_todo_items(text):
                if item not in todos:
                    todos.append(item)

    if not features or not todos:
        for note in notes:
            text = note.content or ""
            lower = text.lower()
            if not features and "feature" in lower:
                for item in _extract_feature_items(text):
                    if item not in features:
                        features.append(item)
            if not todos and ("todo" in lower or "to-do" in lower):
                for item in _extract_todo_items(text):
                    if item not in todos:
                        todos.append(item)

    # Fallback extraction if structured tags are missing.
    if not features:
        for note in notes:
            for item in _extract_feature_items(note.content or ""):
                if item not in features:
                    features.append(item)
    if not todos:
        todos = [f"Finalize: {item}" for item in features[:5]]

    print("Project recalled: Visa Bot")
    print("")
    print("Feature list we agreed on:")
    for idx, feature in enumerate(features[:8], start=1):
        print(f"- {feature}")

    print("")
    print("Formatted To-Do list:")
    for idx, task in enumerate(todos[:10], start=1):
        print(f"{idx}. [ ] {task}")


if __name__ == "__main__":
    main()
