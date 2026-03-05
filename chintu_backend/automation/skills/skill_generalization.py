"""Helpers for auto-generalizing and de-duplicating learned skill proposals."""

from __future__ import annotations

import copy
import logging
import re
import shlex
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from chintu_backend.automation.skills.skill_registry import SkillSpec, parse_skills_from_markdown

logger = logging.getLogger(__name__)

_SPECIFIC_ENTITY_TERMS: Set[str] = {
    "ssd",
    "nvme",
    "monitor",
    "gpu",
    "cpu",
    "ram",
    "router",
    "phone",
    "iphone",
    "android",
    "laptop",
    "motherboard",
    "keyboard",
    "mouse",
    "groceries",
    "utensils",
    "samsung",
    "apple",
    "amd",
    "nvidia",
    "intel",
}

_STOP_WORDS: Set[str] = {
    "a",
    "an",
    "the",
    "to",
    "for",
    "of",
    "and",
    "or",
    "on",
    "with",
    "from",
    "any",
    "all",
    "best",
    "new",
    "across",
    "using",
    "skill",
}

_PARAM_PLACEHOLDERS = ("{request}", "{args}", "{query}", "{input}")

_FAMILY_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "price_compare": {
        "keywords": [
            "price",
            "prices",
            "compare",
            "comparison",
            "deal",
            "deals",
            "shipping",
            "retailer",
        ],
        "generic_name": "price compare",
        "generic_description": (
            "Compares prices for any product across major retailers and trusted web sources, "
            "then returns a normalized markdown comparison."
        ),
        "generic_triggers": [
            "price compare",
            "compare prices",
            "best price for",
            "price comparison table",
            "compare products",
            "deal finder",
        ],
        "enforce_parameterized_command": True,
    },
    "research": {
        "keywords": [
            "research",
            "summarize",
            "summary",
            "analyze",
            "analysis",
            "topic",
            "insights",
            "report",
        ],
        "generic_name": "agentic research",
        "generic_description": "Researches any topic and returns structured, source-aware summaries.",
        "generic_triggers": ["research topic", "summarize topic", "analyze topic", "deep research"],
        "enforce_parameterized_command": True,
    },
    "organizer": {
        "keywords": [
            "organize",
            "cleanup",
            "clean up",
            "folder",
            "files",
            "downloads",
            "sort",
            "move",
        ],
        "generic_name": "file organizer",
        "generic_description": "Organizes files using configurable routing rules and target folders.",
        "generic_triggers": ["organize files", "organize downloads", "sort files", "cleanup folder"],
        "enforce_parameterized_command": True,
    },
    "installer": {
        "keywords": [
            "install",
            "installer",
            "dependency",
            "dependencies",
            "pip",
            "npm",
            "package",
            "module",
        ],
        "generic_name": "dependency installer",
        "generic_description": "Installs missing dependencies and validates the fix with rerun checks.",
        "generic_triggers": ["install dependency", "fix module error", "install package", "missing dependency"],
        "enforce_parameterized_command": True,
    },
    "automation": {
        "keywords": [
            "automate",
            "workflow",
            "schedule",
            "pipeline",
            "run task",
            "job",
            "execute",
            "trigger",
        ],
        "generic_name": "workflow automation",
        "generic_description": "Automates multi-step workflows with policy checks and verification.",
        "generic_triggers": ["automate workflow", "run workflow", "schedule workflow", "automation task"],
        "enforce_parameterized_command": True,
    },
}


def get_skill_family_taxonomy() -> Dict[str, Dict[str, Any]]:
    """Expose a stable copy of the current skill-family taxonomy."""
    return copy.deepcopy(_FAMILY_DEFINITIONS)


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", str(text or "").lower())


def _contains_model_like_token(text: str) -> bool:
    return re.search(r"\b[a-z]{1,4}\d{2,}[a-z0-9-]*\b", str(text or "").lower()) is not None


def _contains_specific_entity(text: str) -> bool:
    tokens = set(_tokenize(text))
    return bool(tokens & _SPECIFIC_ENTITY_TERMS) or _contains_model_like_token(text)


def _detect_skill_family(name: str, description: str, triggers: List[str], command: str) -> str:
    joined = " ".join([name or "", description or "", " ".join(triggers or []), command or ""]).lower()
    best_family = "generic"
    best_score = 0
    for family, details in _FAMILY_DEFINITIONS.items():
        keywords = details.get("keywords", []) if isinstance(details, dict) else []
        score = sum(1 for kw in keywords if str(kw).lower() in joined)
        if score > best_score:
            best_family = family
            best_score = score
    return best_family if best_score >= 2 else "generic"


def _split_frontmatter(content: str) -> Tuple[Optional[str], str]:
    text = str(content or "")
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return None, text
    parts = stripped.split("---", 2)
    if len(parts) < 3:
        return None, text
    return parts[1].strip(), parts[2].lstrip("\n")


def _as_trigger_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return []


def _build_frontmatter(data: Dict[str, Any], body: str) -> str:
    try:
        import yaml
    except Exception:
        return ""
    rendered = yaml.safe_dump(data, sort_keys=False, allow_unicode=False).strip()
    return f"---\n{rendered}\n---\n{body.strip()}\n"


def _merge_generic_triggers(triggers: List[str], family: str) -> List[str]:
    details = _FAMILY_DEFINITIONS.get(family, {})
    generic = [str(t).strip() for t in details.get("generic_triggers", []) if str(t).strip()]
    cleaned: List[str] = []
    seen: Set[str] = set()
    for trigger in triggers:
        value = str(trigger).strip()
        if not value:
            continue
        low = value.lower()
        if _contains_specific_entity(low):
            continue
        if low in seen:
            continue
        seen.add(low)
        cleaned.append(value)
    for trigger in generic:
        low = trigger.lower()
        if low in seen:
            continue
        seen.add(low)
        cleaned.append(trigger)
    return cleaned[:12]


def _normalize_command_for_family(command: str, family: str) -> Tuple[str, bool]:
    updated = str(command or "").strip()
    changed = False
    if family == "price_compare" and updated:
        new_value = re.sub(r"compare_[a-z0-9_]+\.py", "compare_prices.py", updated, flags=re.IGNORECASE)
        if new_value != updated:
            updated = new_value
            changed = True
    return updated, changed


def _ensure_parameterized_command(command: str, args_list: List[str]) -> Tuple[str, bool]:
    cmd = str(command or "").strip()
    if not cmd:
        return cmd, False
    if any(token in cmd for token in _PARAM_PLACEHOLDERS):
        return cmd, False
    if any(str(arg).strip().lower() == "request" for arg in args_list):
        return f'{cmd} "{{request}}"', True
    return cmd, False


def autogeneralize_skill_markdown(content: str) -> Tuple[str, List[str]]:
    """Rewrite narrowly-scoped frontmatter skills into reusable families when possible."""
    frontmatter, body = _split_frontmatter(content)
    if not frontmatter:
        return content, []

    try:
        import yaml

        data = yaml.safe_load(frontmatter) or {}
    except Exception:
        return content, []
    if not isinstance(data, dict):
        return content, []

    name = str(data.get("name") or "").strip()
    description = str(data.get("description") or "").strip()
    triggers = _as_trigger_list(data.get("triggers") or data.get("trigger"))
    command = str(data.get("command") or "").strip()
    family = _detect_skill_family(name, description, triggers, command)
    notes: List[str] = []

    if family == "generic":
        return content, notes

    details = _FAMILY_DEFINITIONS.get(family, {})
    generic_name = str(details.get("generic_name") or "").strip()
    generic_description = str(details.get("generic_description") or "").strip()

    if generic_name and _contains_specific_entity(name):
        data["name"] = generic_name
        notes.append(f"Renamed skill to generic family name: '{generic_name}'.")

    if generic_description and (_contains_specific_entity(description) or not description):
        data["description"] = generic_description
        notes.append(f"Generalized description for family '{family}'.")

    data["triggers"] = _merge_generic_triggers(triggers, family)

    command_out, command_changed = _normalize_command_for_family(command, family)
    if command_changed:
        data["command"] = command_out
        notes.append("Updated command path to generic family handler.")

    args_raw = data.get("args")
    args_list = _as_trigger_list(args_raw)
    if not args_list:
        args_list = ["request"]
        data["args"] = args_list
    elif "request" not in [x.lower() for x in args_list]:
        args_list.append("request")
        data["args"] = args_list

    effective_command = str(data.get("command") or "").strip()
    normalized_command, added_param = _ensure_parameterized_command(effective_command, args_list)
    if added_param:
        data["command"] = normalized_command
        notes.append("Appended request passthrough to command.")

    metadata = data.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    metadata.setdefault("family", family)
    metadata.setdefault("evolution_policy", "extend_existing_family")
    data["metadata"] = metadata

    rebuilt = _build_frontmatter(data, body)
    if not rebuilt:
        return content, notes
    return rebuilt, notes


def _signature_tokens(spec: SkillSpec) -> Set[str]:
    source = " ".join(
        [
            str(spec.name or ""),
            str(spec.description or ""),
            " ".join(spec.triggers or []),
        ]
    )
    tokens = {
        t
        for t in _tokenize(source)
        if len(t) >= 3 and t not in _STOP_WORDS and t not in _SPECIFIC_ENTITY_TERMS
    }
    if not tokens:
        tokens = {t for t in _tokenize(source) if len(t) >= 3 and t not in _STOP_WORDS}
    return tokens


def _command_signature(command: str) -> str:
    raw = str(command or "").strip()
    if not raw:
        return ""
    try:
        parts = shlex.split(raw, posix=False)
    except Exception:
        parts = raw.split()
    if not parts:
        return ""
    if len(parts) >= 2 and Path(parts[0]).name.lower().startswith("python"):
        return Path(parts[1]).name.lower()
    return Path(parts[0]).name.lower()


def _similarity(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return float(inter) / float(union) if union else 0.0


def load_existing_skill_specs(config) -> List[SkillSpec]:
    """Load currently available skills for duplicate checks."""
    specs: List[SkillSpec] = []
    dirs = [
        getattr(config, "skills_bundled_dir", None),
        getattr(config, "skills_user_dir", None),
        getattr(config, "skills_dir", None),
        getattr(config, "skills_learned_dir", None),
    ]
    seen: Set[Tuple[str, str]] = set()
    for base in dirs:
        if not base:
            continue
        root = Path(base)
        if not root.exists():
            continue
        for path in root.rglob("*.md"):
            if ".history" in path.parts:
                continue
            try:
                parsed = parse_skills_from_markdown(path.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue
            for spec in parsed:
                if not isinstance(spec, SkillSpec):
                    continue
                if not spec.name:
                    continue
                key = (str(spec.name).strip().lower(), _command_signature(spec.command))
                if key in seen:
                    continue
                seen.add(key)
                specs.append(spec)
    return specs


def analyze_proposal_generalization(
    spec: SkillSpec,
    existing_specs: Optional[List[SkillSpec]] = None,
    similarity_threshold: float = 0.78,
) -> List[str]:
    """Return policy issues for proposal-time generalization checks."""
    issues: List[str] = []
    family = _detect_skill_family(spec.name, spec.description, spec.triggers, spec.command)
    details = _FAMILY_DEFINITIONS.get(family, {})
    generic_name = str(details.get("generic_name") or "").strip()

    # Skill quality checklist.
    if not str(spec.test_command or "").strip():
        issues.append("Missing test command for proposal. Add a deterministic test (test or test-command).")

    if spec.kind == "shell" and str(spec.command or "").strip():
        has_placeholder = any(token in str(spec.command or "") for token in _PARAM_PLACEHOLDERS)
        if details.get("enforce_parameterized_command", False) and not has_placeholder:
            issues.append("Command is not parameterized. Use placeholders like {request} or {args}.")

    if family != "generic":
        if _contains_specific_entity(spec.name):
            suggestion = f" (e.g. '{generic_name}')" if generic_name else ""
            issues.append(
                f"Skill name is too specific for reusable family '{family}'. Use a generic family name{suggestion}."
            )
        if _contains_specific_entity(spec.description):
            issues.append("Description is entity-specific. Generalize it to family-level scope.")
        specific_triggers = [t for t in spec.triggers if _contains_specific_entity(t)]
        if spec.triggers and len(specific_triggers) == len(spec.triggers):
            issues.append("All triggers are entity-specific. Add generic triggers for reusable routing.")
        if not spec.triggers:
            issues.append("No triggers defined. Add generic triggers for this family.")

    if existing_specs:
        current_sig = _signature_tokens(spec)
        current_cmd_sig = _command_signature(spec.command)
        same_family_matches: List[SkillSpec] = []
        for other in existing_specs:
            if str(other.name or "").strip().lower() == str(spec.name or "").strip().lower():
                continue
            other_family = _detect_skill_family(other.name, other.description, other.triggers, other.command)
            if family != "generic" and family == other_family:
                same_family_matches.append(other)
                other_cmd_sig = _command_signature(other.command)
                if current_cmd_sig and other_cmd_sig and current_cmd_sig == other_cmd_sig:
                    issues.append(
                        f"Likely duplicate of existing skill '{other.name}' (same command family: {current_cmd_sig}). "
                        "Extend the existing skill family instead of creating a narrow clone."
                    )
                    break
            other_sig = _signature_tokens(other)
            sim = _similarity(current_sig, other_sig)
            if sim >= float(similarity_threshold):
                issues.append(
                    f"Likely duplicate of existing skill '{other.name}' (similarity={sim:.2f}). "
                    "Extend the existing skill family instead of creating a narrow clone."
                )
                break

        if family != "generic" and same_family_matches and _contains_specific_entity(spec.name):
            issues.append(
                f"Existing '{family}' family skill(s) already exist. Extend an existing family skill instead of creating a new narrow one."
            )

    # Dedupe messages while preserving order.
    deduped: List[str] = []
    seen_issue: Set[str] = set()
    for item in issues:
        msg = str(item).strip()
        if not msg or msg in seen_issue:
            continue
        seen_issue.add(msg)
        deduped.append(msg)
    return deduped
