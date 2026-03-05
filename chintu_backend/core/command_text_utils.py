"""Text-level response and context helpers for CommandHandler."""

from __future__ import annotations

import re
from typing import Optional, Tuple

from .response_rendering import ensure_readable_completion


_BLOCKED_RESPONSE_PREFIXES = (
    "nvidia api error:",
    "thinking mode failed:",
    "nvidia failed, falling back:",
    "high gpu load detected!",
    "no predefined contract found for capability:",
    "docker sandbox disabled:",
    "[error generating response:",
    "[error streaming response:",
    "llm generation error:",
)


def sanitize_internal_response(message: str) -> str:
    """Strip internal routing/debug tokens from user-visible responses."""
    clean_msg = str(message or "")
    if "__LLM_ROUTE__" in clean_msg:
        clean_msg = clean_msg.replace("__LLM_ROUTE__", "").strip()
    if "Note: Will use local model" in clean_msg:
        lines = clean_msg.splitlines()
        clean_msg = "\n".join(
            line for line in lines if not line.strip().startswith("Note: Will use local model")
        ).strip()

    filtered_lines = []
    in_traceback = False
    for raw_line in clean_msg.splitlines():
        line = str(raw_line or "").strip()
        if not line:
            if in_traceback:
                in_traceback = False
            filtered_lines.append(raw_line)
            continue

        low = line.lower()
        if low.startswith("traceback (most recent call last)"):
            in_traceback = True
            continue

        if in_traceback:
            if line.startswith("File ") or line.startswith("^") or low.startswith(("error:", "exception:")):
                continue
            in_traceback = False

        if any(low.startswith(prefix) for prefix in _BLOCKED_RESPONSE_PREFIXES):
            continue

        filtered_lines.append(raw_line)

    clean_msg = "\n".join(filtered_lines).strip()
    return ensure_readable_completion(clean_msg.strip())


def conversation_fallback_response(user_text: str) -> str:
    """Safe fallback when conversation output becomes empty after sanitization."""
    low = str(user_text or "").strip().lower()
    if "python" in low and "javascript" in low and ("compare" in low or "vs" in low or "versus" in low):
        return (
            "Python is strongest for automation, AI/data, and backend scripting. "
            "JavaScript is strongest for browser apps and full-stack web development with Node.js. "
            "Use Python for ML-heavy workflows and JavaScript for interactive web products."
        )
    compare_match = re.search(r"compare\s+(.+?)\s+(?:vs|versus)\s+(.+)", low)
    if compare_match:
        left = re.sub(r"[^a-z0-9 +.#-]", "", compare_match.group(1)).strip()
        right = re.sub(r"[^a-z0-9 +.#-]", "", compare_match.group(2)).strip()
        if left and right:
            return (
                f"{left.title()} vs {right.title()}: pick based on your primary use case, "
                "ecosystem support, performance constraints, and long-term maintenance cost. "
                "If you want, I can break this down by speed, developer experience, and deployment fit."
            )
    if "haiku" in low:
        topic = "coding"
        match = re.search(r"haiku\s+about\s+(.+)", low)
        if match and match.group(1).strip():
            topic = re.sub(r"[^a-z0-9 ]+", "", match.group(1)).strip() or topic
        return (
            f"Silent screens at dusk\n"
            f"{topic.title()} flows through steady loops\n"
            f"Morning tests all pass"
        )
    if "poem" in low:
        return "I can try again with a short poem. Tell me the topic and tone you want."
    return "I had trouble generating a clean response. Please try again."


def trim_context_to_budget(context_text: str, max_chars: int) -> str:
    """Trim context blocks to a strict character budget while preserving section order."""
    text = str(context_text or "").strip()
    if not text:
        return ""
    try:
        budget = max(80, int(max_chars))
    except Exception:
        budget = 3200
    if len(text) <= budget:
        return text

    blocks = [block.strip() for block in re.split(r"\n{2,}", text) if block.strip()]
    if not blocks:
        return text[: max(0, budget - 3)].rstrip() + "..."

    selected: list[str] = []
    used = 0
    for block in blocks:
        add_cost = len(block) + (2 if selected else 0)
        if used + add_cost <= budget:
            selected.append(block)
            used += add_cost
            continue
        remaining = budget - used - (2 if selected else 0)
        if remaining >= 80:
            selected.append(block[: max(0, remaining - 3)].rstrip() + "...")
        break

    if not selected:
        return text[: max(0, budget - 3)].rstrip() + "..."
    return "\n\n".join(selected)


def extract_numbered_followup_index(text: str) -> Optional[int]:
    low = str(text or "").lower()
    match = re.search(r"(?:#|(?:item|point|result|headline|source)\s+)(\d{1,3})", low)
    if match:
        try:
            value = int(match.group(1))
            return value if value > 0 else None
        except Exception:
            return None

    word_map = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }
    word_match = re.search(
        r"(?:item|point|result|headline|source)\s+(one|two|three|four|five|six|seven|eight|nine|ten)\b",
        low,
    )
    if not word_match:
        return None
    return int(word_map.get(word_match.group(1), 0) or 0) or None


def extract_compare_indices(text: str) -> Optional[Tuple[int, int]]:
    low = str(text or "").lower()
    match = re.search(
        r"(?:#|(?:item|point|result|headline|source)\s+)(\d{1,3})\s*(?:vs|versus)\s*(?:#|(?:item|point|result|headline|source)\s+)?(\d{1,3})",
        low,
    )
    if not match:
        return None
    try:
        left = int(match.group(1))
        right = int(match.group(2))
    except Exception:
        return None
    if left <= 0 or right <= 0:
        return None
    return (left, right)


def is_numbered_followup_request(text: str) -> bool:
    low = str(text or "").strip().lower()
    if not low:
        return False
    has_index = extract_numbered_followup_index(low) is not None or extract_compare_indices(low) is not None
    has_followup_phrase = any(
        token in low
        for token in (
            "read more",
            "more on",
            "detail",
            "deeper",
            "go deeper",
            "expand",
            "continue with",
            "tell me more",
            "open",
            "compare",
            "versus",
            " vs ",
            "save",
        )
    )
    return bool(has_index and has_followup_phrase)
