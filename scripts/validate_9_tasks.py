"""
Validate the 9 requested real-world tasks through Chintu's CommandHandler.

This validator uses semantic checks on Chintu's actual response, not just
capability labels or loose marker matching.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = REPO_ROOT / "generated_reports"
VALIDATION_INPUT_DIR = REPORT_DIR / "validation_inputs"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@dataclass
class TaskCase:
    task_id: int
    name: str
    prompt: str
    expected_capabilities: List[str]
    expected_markers: List[str]
    extra_check: Optional[str] = None


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_capability(handler: Any) -> str:
    try:
        return str(handler.state_manager.state.last_capability or "")
    except Exception:
        return ""


def _marker_check(response: str, markers: List[str]) -> bool:
    low = response.lower()
    return all(marker.lower() in low for marker in markers)


def _extra_check(path_str: Optional[str]) -> bool:
    if not path_str:
        return True
    return Path(path_str).exists()


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _looks_like_python_code(response: str) -> bool:
    low = response.lower()
    if "```python" in low:
        return True
    indicators = [
        "from pathlib import path",
        "import shutil",
        "glob(\"*.pdf\")",
        "glob(\"*.exe\")",
        "if __name__ == \"__main__\"",
    ]
    hits = sum(1 for token in indicators if token in low)
    return hits >= 3


def _semantic_check(task_id: int, response: str, fixture: Dict[str, str]) -> Tuple[bool, str]:
    low = _normalize_text(response)
    if not low:
        return False, "empty response"

    if task_id == 1:
        headline_matches = re.findall(r"(?m)^\s*\d{2}\.\s+\[([A-Za-z]+)\]\s+.+$", response)
        age_hits = len(re.findall(r"\b(?:just now|\d+h ago|\d+d ago)\b", low))
        categories = {c.lower() for c in headline_matches}
        required = {"tech", "finance", "healthcare"}
        if len(headline_matches) < 20:
            return False, f"expected 20 headlines, found {len(headline_matches)}"
        if len(required.intersection(categories)) < 2:
            return False, "headlines missing category spread"
        if "read more about" not in low:
            return False, "missing follow-up detail prompt"
        if age_hits < 10:
            return False, "freshness markers missing in most headlines"
        return True, "20 fresh categorized headlines with read-more flow"

    if task_id == 2:
        has_gpu = ("rtx 3060" in low) or ("gpu 0" in low)
        has_temp = re.search(r"\b\d{1,3}\s*c\b", low) is not None
        has_vram = re.search(r"\b\d+\s*/\s*\d+\s*mib\b", low) is not None
        has_decision = ("idle" in low) or ("keep the current brain model" in low) or ("switch" in low)
        if not has_gpu:
            return False, "missing RTX 3060 / GPU status"
        if not has_temp:
            return False, "missing GPU temperature"
        if not has_vram:
            return False, "missing VRAM usage"
        if not has_decision:
            return False, "missing model-routing decision"
        return True, "contains GPU telemetry and model decision"

    if task_id == 3:
        if not _looks_like_python_code(response):
            return False, "response does not include python code"
        if ".pdf" not in low or ".exe" not in low:
            return False, "file extension rules missing"
        if "documents" not in low or "installers" not in low:
            return False, "destination folders missing"
        if "don't run" not in low and "dry run" not in low:
            return False, "missing explicit non-execution note"
        return True, "returns code with correct move rules and dry-run note"

    if task_id == 4:
        script_name = Path(fixture["pandas_probe_script"]).name.lower()
        has_install = "pandas" in low and ("install" in low or "pip" in low)
        has_rerun = ("rerun" in low) or ("run again" in low) or ("would rerun" in low)
        skipped = ("skipped" in low) and ("rerun" in low)
        if not has_install:
            return False, "missing pandas install evidence"
        if skipped:
            return False, "rerun was skipped"
        if not has_rerun:
            return False, "missing rerun verification evidence"
        if script_name not in low:
            return False, f"rerun does not reference fixture script ({script_name})"
        return True, "installs pandas and verifies by rerunning script"

    if task_id == 5:
        row_count = len(re.findall(r"(?m)^\|\s*[^|]+\s*\|\s*[^|]+\s*\|\s*[^|]+\s*\|\s*[^|]+\s*\|\s*[^|]+\s*\|\s*[^|]+\s*\|$", response))
        if "| store | product | price | shipping speed | total | link |" not in low:
            return False, "missing markdown comparison table header"
        if row_count < 4:
            return False, f"expected table with at least 2 vendor rows, found {max(0, row_count - 2)}"
        if "saved comparison table" not in low:
            return False, "missing saved-file confirmation"
        return True, "table generated with multiple vendor rows and save confirmation"

    if task_id == 6:
        bullets = len(re.findall(r"(?m)^\s*[-*]\s+", response))
        has_topic = "langgraph" in low
        has_memory_apply = "memory" in low and "chintu" in low
        if bullets < 3:
            return False, "expected at least 3 bullets"
        if not has_topic:
            return False, "missing LangGraph concepts"
        if not has_memory_apply:
            return False, "missing Chintu memory application"
        return True, "contains LangGraph bullets plus memory application"

    if task_id == 7:
        feature_items = len(re.findall(r"(?m)^\s*-\s+.+$", response))
        todo_items = len(re.findall(r"(?m)^\s*\d+\.\s+\[\s*\]\s+.+$", response))
        if "visa bot" not in low:
            return False, "missing project recall name"
        if feature_items < 3:
            return False, "feature list is too short"
        if todo_items < 3:
            return False, "to-do list is too short"
        return True, "recalls project and renders feature/todo lists"

    if task_id == 8:
        has_core = "12gb" in low and "vram" in low
        has_cta = any(
            token in low
            for token in ["cta", "follow", "subscribe", "like this", "check out", "see you next"]
        )
        if not has_core:
            return False, "missing 12GB VRAM core topic"
        if len(response.strip()) < 250:
            return False, "script too short for a 60-second segment"
        if not has_cta:
            return False, "missing call-to-action style ending"
        return True, "contains full short-form script with CTA"

    if task_id == 9:
        checks = [
            "minimize" in low,
            ("25%" in low) or ("volume to 25" in low),
            "spotify" in low,
            ("visual studio code" in low) or ("vscode" in low),
        ]
        if not all(checks):
            return False, "missing one or more focus actions"
        return True, "includes all focus protocol actions"

    return False, "no semantic rule defined"


def _seed_memory() -> None:
    try:
        from chintu_backend.brain.memory.facade import MemoryFacade

        facade = MemoryFacade()
        facade.save_note(
            "Visa Bot project feature list: document checklist, status tracker, interview scheduler, reminders."
        )
        facade.save_note(
            "Visa Bot todo: 1) Build intake form 2) Add progress dashboard 3) Add embassy slot alerts"
        )
    except Exception:
        pass


def _prepare_fixtures() -> Dict[str, str]:
    VALIDATION_INPUT_DIR.mkdir(parents=True, exist_ok=True)
    pandas_probe = VALIDATION_INPUT_DIR / "pandas_probe.py"
    pandas_probe.write_text(
        "import pandas as pd\n"
        "print('pandas_probe_ok', getattr(pd, '__version__', 'unknown'))\n",
        encoding="utf-8",
    )
    return {"pandas_probe_script": str(pandas_probe)}


def _build_tasks(fixture: Dict[str, str]) -> List[TaskCase]:
    pandas_probe = fixture["pandas_probe_script"]
    return [
        TaskCase(
            task_id=1,
            name="Daily Briefing",
            prompt=(
                "Good morning, Chintu. Give me my daily briefing: check my calendar and provide 20 fresh "
                "headlines across tech, finance, and healthcare. Read only headlines and ask if I want any topic in detail."
            ),
            expected_capabilities=["skill::daily-briefing", "compound_command"],
            expected_markers=["daily briefing", "top 20 headlines", "read more about"],
        ),
        TaskCase(
            task_id=2,
            name="Hardware Health",
            prompt=(
                "Check the current temperature and VRAM usage of my RTX 3060. "
                "If it's idle, switch the 'Brain Model' to the 3060 for better performance."
            ),
            expected_capabilities=["skill::hardware-health"],
            expected_markers=["hardware health", "gpu"],
        ),
        TaskCase(
            task_id=3,
            name="Boilerplate Builder",
            prompt=(
                "I want to build a Python script that organizes my Downloads folder. Write the code "
                "to move all .pdf files to a Documents folder and .exe files to an Installers folder. "
                "Don't run it yet-just show me the code."
            ),
            expected_capabilities=["skill::downloads-organizer", "organize_downloads"],
            expected_markers=["downloads organizer", "code"],
        ),
        TaskCase(
            task_id=4,
            name="Error Fixer",
            prompt=(
                "I am getting a ModuleNotFoundError for pandas in my current VS Code project script "
                f"{pandas_probe}. Fix it by installing the package, then run the script again to verify."
            ),
            expected_capabilities=["skill::module-installer", "compound_command"],
            expected_markers=["pandas", "rerun"],
        ),
        TaskCase(
            task_id=5,
            name="Product Comparison",
            prompt=(
                "Find the best price for a Samsung 990 Pro 2TB on Amazon and Newegg. Create a markdown "
                "table comparing the price and shipping speed, and save it to my Desktop as ssd_prices.md."
            ),
            expected_capabilities=["skill::price-compare", "deal_finder"],
            expected_markers=["saved comparison table", "| store | product | price |"],
            extra_check=str(Path.home() / "Desktop" / "ssd_prices.md"),
        ),
        TaskCase(
            task_id=6,
            name="Learning Assistant",
            prompt=(
                "Research Agentic Workflows using LangGraph. Summarize the key concepts into three bullet "
                "points and explain how we could use it for Chintu's memory system."
            ),
            expected_capabilities=["skill::agentic-research"],
            expected_markers=["langgraph", "memory"],
        ),
        TaskCase(
            task_id=7,
            name="Recall Test",
            prompt=(
                "What was the name of the Visa Bot project we discussed last Tuesday? Retrieve the feature "
                "list we decided on and create a formatted To-Do list from it."
            ),
            expected_capabilities=["skill::visa-bot-memory"],
            expected_markers=["visa bot", "to-do"],
        ),
        TaskCase(
            task_id=8,
            name="Content Creator",
            prompt=(
                "Generate a 60-second script for a YouTube Short about Why 12GB VRAM is enough for AI. "
                "Make it funny and engaging."
            ),
            expected_capabilities=["skill::creative-short"],
            expected_markers=["12gb", "vram"],
        ),
        TaskCase(
            task_id=9,
            name="Focus Protocol",
            prompt=(
                "I need to focus. Minimize all open windows, set system volume to 25%, open Spotify, "
                "and launch Visual Studio Code."
            ),
            expected_capabilities=["skill::os-focus"],
            expected_markers=["focus protocol", "25%", "spotify", "visual studio code"],
        ),
    ]


def run_validation() -> Dict[str, Any]:
    os.environ.setdefault("CHINTU_VALIDATE_DRY_RUN", "1")
    os.environ.setdefault("CHINTU_SKILLS_ENABLED", "true")
    os.environ.setdefault("CHINTU_SKILLS_ALLOW_SHELL", "true")
    os.environ.setdefault("CHINTU_LLM_TOOL_ROUTING_ENABLED", "false")

    from chintu_backend.core.command_handler import CommandHandler

    fixture = _prepare_fixtures()
    tasks = _build_tasks(fixture)
    _seed_memory()

    handler = CommandHandler(mock_mode=False)
    session_prefix = f"task9:{_utc_stamp()}"
    rows: List[Dict[str, Any]] = []
    started = time.perf_counter()

    for task in tasks:
        session_id = f"{session_prefix}:{task.task_id}"
        context: Dict[str, Any] = {"session_id": session_id, "workspace_dir": str(REPO_ROOT)}
        t0 = time.perf_counter()
        response = str(handler.handle(task.prompt, source="validation", context=context) or "")
        pending_caps: List[str] = []

        # Auto-confirm pending skill commands.
        for _ in range(4):
            pending = {}
            try:
                pending = handler.action_dispatcher.get_pending_confirmation() or {}
            except Exception:
                pending = {}
            if pending.get("capability"):
                pending_caps.append(str(pending["capability"]))
            if not pending and "Do you want to proceed?" not in response:
                break
            follow_ctx = {"session_id": session_id, "workspace_dir": str(REPO_ROOT), "is_follow_up": True}
            follow = str(handler.handle("yes", source="validation", context=follow_ctx) or "")
            if follow:
                response = (response + "\n" + follow).strip()

        cap = _safe_capability(handler)
        if not cap and pending_caps:
            cap = pending_caps[-1]

        capability_ok = cap in task.expected_capabilities
        marker_ok = _marker_check(response, task.expected_markers)
        semantic_ok, semantic_detail = _semantic_check(task.task_id, response, fixture)
        extra_ok = _extra_check(task.extra_check)
        passed = capability_ok and marker_ok and semantic_ok and extra_ok

        fail_reasons: List[str] = []
        if not capability_ok:
            fail_reasons.append(f"capability mismatch: {cap!r}")
        if not marker_ok:
            fail_reasons.append("marker check failed")
        if not semantic_ok:
            fail_reasons.append(f"semantic check failed: {semantic_detail}")
        if not extra_ok:
            fail_reasons.append(f"artifact missing: {task.extra_check}")

        rows.append(
            {
                "id": task.task_id,
                "name": task.name,
                "prompt": task.prompt,
                "expected_capabilities": task.expected_capabilities,
                "actual_capability": cap,
                "capability_ok": capability_ok,
                "marker_ok": marker_ok,
                "semantic_ok": semantic_ok,
                "semantic_detail": semantic_detail,
                "extra_ok": extra_ok,
                "passed": passed,
                "fail_reasons": fail_reasons,
                "latency_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                "response": response[:4000],
            }
        )

    total = len(rows)
    passed = sum(1 for row in rows if row["passed"])
    failed = total - passed
    report = {
        "timestamp_utc": _utc_iso(),
        "session_id": session_prefix,
        "fixtures": fixture,
        "summary": {
            "total": total,
            "pass": passed,
            "fail": failed,
            "pass_rate": round((passed / total) if total else 0.0, 3),
            "elapsed_s": round(time.perf_counter() - started, 2),
        },
        "tasks": rows,
    }
    return report


def main() -> int:
    report = run_validation()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _utc_stamp()
    out_path = REPORT_DIR / f"chintu_9_task_validation_{stamp}.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    print(f"Saved validation report: {out_path}")
    print(json.dumps(report["summary"], indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
