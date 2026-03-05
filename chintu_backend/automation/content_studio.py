"""Night-time automation pipelines: YouTube Shorts + Idea-to-App builder.

These are designed to run unattended (usually via Orchestrator) and to be safe:
- Writes outputs under `~/.chintu/` or `Chintus_Library/` by default
- Upload/publish is a separate, high-risk step (requires explicit approval + OAuth)
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from chintu_backend.core.config import get_config

logger = logging.getLogger(__name__)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def _safe_slug(value: str) -> str:
    raw = (value or "").strip().lower()
    raw = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    return raw or "project"


def _get_router_from_context(context: Optional[Dict[str, Any]] = None):
    router = None
    if context and context.get("model_router"):
        router = context.get("model_router")
    if router:
        return router
    try:
        from chintu_backend.core.model_router import get_router

        return get_router()
    except Exception:
        return None


def _generate_text(router, prompt: str, system: str = "") -> str:
    if not router:
        return ""
    try:
        # Most router impls expose route_and_execute(prompt, ...)
        if hasattr(router, "route_and_execute"):
            resp, _src = router.route_and_execute(prompt, system_prompt=system)  # type: ignore[arg-type]
            return str(resp or "").strip()
    except TypeError:
        # Older signature: route_and_execute(text, memory_context=..., behavior_context=...)
        try:
            resp, _src = router.route_and_execute(prompt)  # type: ignore[misc]
            return str(resp or "").strip()
        except Exception:
            return ""
    except Exception:
        return ""
    return ""


def _estimate_audio_seconds(path: Path) -> Optional[float]:
    if not path.exists() or not _ffprobe_available():
        return None
    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=8.0,
            check=False,
        )
        if proc.returncode != 0:
            return None
        value = (proc.stdout or "").strip()
        return float(value) if value else None
    except Exception:
        return None


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def _download_background_asset(topic: str, run_dir: Path) -> Tuple[bool, str]:
    """Best-effort Wikimedia/Wikipedia background image fetch."""
    query = (topic or "").strip() or "Technology"
    title = query.replace(" ", "_")
    summary_url = "https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(title, safe="_")
    req = urllib.request.Request(summary_url, headers={"User-Agent": "ChintuAI/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception:
        return False, ""

    image_url = ""
    if isinstance(payload, dict):
        original = payload.get("originalimage") if isinstance(payload.get("originalimage"), dict) else {}
        thumb = payload.get("thumbnail") if isinstance(payload.get("thumbnail"), dict) else {}
        image_url = str(original.get("source") or thumb.get("source") or "").strip()
    if not image_url:
        return False, ""

    try:
        parsed = urllib.parse.urlparse(image_url)
        suffix = Path(parsed.path).suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
            suffix = ".jpg"
        bg_path = run_dir / f"background_asset{suffix}"
        img_req = urllib.request.Request(image_url, headers={"User-Agent": "ChintuAI/1.0"})
        with urllib.request.urlopen(img_req, timeout=12) as resp:
            blob = resp.read()
        if not blob or len(blob) < 8_192:
            return False, ""
        bg_path.write_bytes(blob)
        return True, str(bg_path)
    except Exception:
        return False, ""


def _split_caption_lines(text: str, max_chars: int = 34) -> List[str]:
    words = (text or "").strip().split()
    if not words:
        return []
    lines: List[str] = []
    current: List[str] = []
    current_len = 0
    for w in words:
        add = len(w) + (1 if current else 0)
        if current_len + add > max_chars and current:
            lines.append(" ".join(current))
            current = [w]
            current_len = len(w)
        else:
            current.append(w)
            current_len += add
    if current:
        lines.append(" ".join(current))
    return lines


def _write_basic_srt(path: Path, lines: List[str], total_seconds: float) -> None:
    if not lines or total_seconds <= 0:
        return

    chunk = max(0.8, total_seconds / max(1, len(lines)))

    def fmt(ts: float) -> str:
        ms = int(round(ts * 1000))
        h = ms // (3600 * 1000)
        ms -= h * 3600 * 1000
        m = ms // (60 * 1000)
        ms -= m * 60 * 1000
        s = ms // 1000
        ms -= s * 1000
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    out: List[str] = []
    for i, line in enumerate(lines, start=1):
        start = (i - 1) * chunk
        end = min(total_seconds, i * chunk)
        out.append(str(i))
        out.append(f"{fmt(start)} --> {fmt(end)}")
        out.append(line)
        out.append("")

    path.write_text("\n".join(out), encoding="utf-8")


# ---------------------------------------------------------------------------
# YouTube Shorts (local generation)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ShortRun:
    run_dir: Path
    title: str
    script_path: Path
    audio_path: Optional[Path] = None
    subtitles_path: Optional[Path] = None
    video_path: Optional[Path] = None
    metadata_path: Optional[Path] = None


def generate_youtube_short(
    *,
    topic: str,
    voice: str = "default",
    style: str = "fast, informative, punchy",
    duration_seconds: int = 60,
    output_dir: Optional[Path] = None,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Generate a local YouTube Short (script + TTS + basic video render).

    Upload/publishing is intentionally not included (high risk + OAuth).
    """

    config = get_config()
    base_dir = Path(output_dir or (Path(config.data_dir) / "content_studio" / "youtube_shorts"))
    stamp = _utc_stamp()
    slug = _safe_slug(topic)[:42]
    run_dir = base_dir / f"{stamp}_{slug}"
    run_dir.mkdir(parents=True, exist_ok=True)

    router = _get_router_from_context(context)

    research = ""
    try:
        from chintu_backend.search.deep_search import deep_search

        research = deep_search(topic, sources=["news", "web"])
    except Exception:
        research = ""

    system = (
        "You write high-retention YouTube Shorts. "
        "Constraints: 9:16, 45-75 seconds, strong hook in first 1-2 seconds, simple language, no fluff."
    )
    prompt = f"""
Topic: {topic}
Style: {style}
Target Duration: ~{duration_seconds}s

Use this research as grounding (optional, don't quote verbatim):
{research[:2200]}

Return JSON only:
{{
  "title": "short punchy title",
  "script": "voiceover script (no scene labels)",
  "caption_lines": ["short on-screen lines, 3-8 words each"],
  "tags": ["tag1","tag2"],
  "description": "1-2 sentence description"
}}
""".strip()
    raw = _generate_text(router, prompt, system=system)

    parsed: Dict[str, Any] = {}
    if raw:
        try:
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                parsed = json.loads(raw[start : end + 1])
        except Exception:
            parsed = {}

    # If the local model struggles to follow the JSON contract, retry once with explicit cloud routing.
    # This keeps the pipeline reliable on small local models while remaining local-first by default.
    if router and (not parsed or not str(parsed.get("script") or "").strip()):
        retry = _generate_text(router, "cloud: " + prompt, system=system)
        if retry:
            try:
                start = retry.find("{")
                end = retry.rfind("}")
                if start >= 0 and end > start:
                    parsed_retry = json.loads(retry[start : end + 1])
                    if isinstance(parsed_retry, dict) and str(parsed_retry.get("script") or "").strip():
                        raw = retry
                        parsed = parsed_retry
            except Exception:
                pass

    title = str(parsed.get("title") or f"{topic}".strip()).strip()[:120]
    script = str(parsed.get("script") or "").strip()
    if not script:
        # Fallback if JSON parse fails.
        script = raw.strip() if raw else f"{topic}. (script generation failed)"

    script_path = run_dir / "script.txt"
    script_path.write_text(script, encoding="utf-8")

    caption_lines = parsed.get("caption_lines")
    if not isinstance(caption_lines, list) or not caption_lines:
        caption_lines = _split_caption_lines(script, max_chars=34)[:36]
    caption_lines = [str(x).strip() for x in caption_lines if str(x).strip()]

    background_asset_used, background_asset_path = _download_background_asset(topic, run_dir)
    bg_path = Path(background_asset_path) if background_asset_used and background_asset_path else None

    audio_path = run_dir / "voice.mp3"
    audio_ok = False
    try:
        from chintu_backend.audio import get_tts

        tts = get_tts()
        if tts and hasattr(tts, "synthesize_to_file"):
            tts.synthesize_to_file(script, audio_path)
            audio_ok = audio_path.exists()
    except Exception:
        audio_ok = False

    subtitles_path = None
    total = float(duration_seconds)
    if audio_ok:
        dur = _estimate_audio_seconds(audio_path)
        if dur and dur > 3:
            total = float(dur)
        subtitles_path = run_dir / "captions.srt"
        _write_basic_srt(subtitles_path, caption_lines, total)

    metadata = {
        "title": title,
        "topic": topic,
        "style": style,
        "duration_seconds": int(duration_seconds),
        "tags": parsed.get("tags") if isinstance(parsed.get("tags"), list) else [],
        "description": str(parsed.get("description") or "").strip(),
        "created_at_utc": stamp,
        "research_used": bool(research),
        "background_asset_used": bool(background_asset_used),
        "background_asset_path": str(background_asset_path or ""),
    }
    metadata_path = run_dir / "metadata.json"
    _write_json(metadata_path, metadata)

    video_path = None
    if _ffmpeg_available() and audio_ok:
        video_path = run_dir / "short.mp4"
        # Render a simple vertical background + burned-in captions if available.
        vf_filters: List[str] = []
        if bg_path and bg_path.exists():
            inputs = [
                "-loop",
                "1",
                "-i",
                str(bg_path),
                "-i",
                str(audio_path),
            ]
            vf_filters.extend(
                [
                    "scale=1080:1920:force_original_aspect_ratio=increase",
                    "crop=1080:1920",
                ]
            )
        else:
            inputs = [
                "-f",
                "lavfi",
                "-i",
                f"color=c=0x0b0f14:s=1080x1920:d={total:.2f}",
                "-i",
                str(audio_path),
            ]
            vf_filters.extend(
                [
                    "scale=1080:1920:force_original_aspect_ratio=decrease",
                    "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=0x0b0f14",
                ]
            )
        if subtitles_path and subtitles_path.exists():
            # Requires libass (common). If missing, ffmpeg will fail and we degrade gracefully.
            sub_path = str(subtitles_path).replace("\\", "/").replace(":", "\\:")
            vf_filters.append(
                f"subtitles='{sub_path}':force_style='FontName=Arial,FontSize=54,Outline=2,Shadow=1'"
            )

        preferred_codecs = ["h264_nvenc", "libx264"] if shutil.which("nvidia-smi") else ["libx264"]
        rendered = False
        for codec in preferred_codecs:
            cmd = [
                "ffmpeg",
                "-y",
                *inputs,
                "-vf",
                ",".join(vf_filters),
                "-shortest",
                "-c:v",
                codec,
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                str(video_path),
            ]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=240, check=False)
                if proc.returncode == 0 and video_path.exists():
                    rendered = True
                    break
            except Exception:
                continue
        if not rendered:
            video_path = None

    return {
        "dir": str(run_dir),
        "title": title,
        "script": str(script_path),
        "audio": str(audio_path) if audio_ok else "",
        "subtitles": str(subtitles_path) if subtitles_path and subtitles_path.exists() else "",
        "video": str(video_path) if video_path and video_path.exists() else "",
        "metadata": str(metadata_path),
    }


# ---------------------------------------------------------------------------
# App Builder (docs + backend scaffold)
# ---------------------------------------------------------------------------


def _default_product_brief(idea: str) -> Dict[str, Any]:
    topic = str(idea or "new app").strip()
    return {
        "problem": f"Users need a simpler way to achieve: {topic}.",
        "users": ["Primary end users", "Admin/operator"],
        "requirements": [
            "Clear onboarding and core task flow",
            "Reliable data persistence for core entities",
            "Basic analytics/usage visibility",
        ],
        "constraints": [
            "Solo-developer friendly implementation",
            "MVP scope with short release timeline",
            "Use maintainable open-source tooling",
        ],
        "success_metrics": [
            "Core user action completion rate >= 80%",
            "Weekly active users growth after launch",
            "Median API response time under 300ms for key paths",
        ],
    }


def _default_milestones() -> List[Dict[str, Any]]:
    return [
        {
            "id": "M1",
            "title": "Foundations",
            "goal": "Project scaffolding and health endpoint.",
            "acceptance_criteria": [
                "Repo scaffold exists",
                "Health endpoint returns 200",
            ],
            "checkpoint_tests": [
                "pytest tests/test_health.py -q",
            ],
        },
        {
            "id": "M2",
            "title": "Core CRUD",
            "goal": "Primary entities and CRUD APIs are available.",
            "acceptance_criteria": [
                "Core CRUD endpoints respond with expected schema",
                "Basic smoke tests pass",
            ],
            "checkpoint_tests": [
                "pytest tests/test_crud_smoke.py -q",
            ],
        },
        {
            "id": "M3",
            "title": "Runnable Build",
            "goal": "Dependencies installed and app runs locally.",
            "acceptance_criteria": [
                "Dependencies install in project venv",
                "Checkpoint tests pass",
                "Run command documented",
            ],
            "checkpoint_tests": [
                "pytest -q",
            ],
        },
    ]


def _write_markdown_list(lines: List[str]) -> str:
    out: List[str] = []
    for item in lines:
        text = str(item or "").strip()
        if text:
            out.append(f"- {text}")
    return "\n".join(out)


def _render_product_brief_md(brief: Dict[str, Any]) -> str:
    problem = str(brief.get("problem") or "TBD").strip()
    users = brief.get("users") if isinstance(brief.get("users"), list) else []
    requirements = brief.get("requirements") if isinstance(brief.get("requirements"), list) else []
    constraints = brief.get("constraints") if isinstance(brief.get("constraints"), list) else []
    success_metrics = brief.get("success_metrics") if isinstance(brief.get("success_metrics"), list) else []
    return "\n".join(
        [
            "# Product Brief",
            "",
            "## Problem",
            problem or "TBD",
            "",
            "## Users",
            _write_markdown_list([str(x) for x in users]) or "- TBD",
            "",
            "## Requirements",
            _write_markdown_list([str(x) for x in requirements]) or "- TBD",
            "",
            "## Constraints",
            _write_markdown_list([str(x) for x in constraints]) or "- TBD",
            "",
            "## Success Metrics",
            _write_markdown_list([str(x) for x in success_metrics]) or "- TBD",
            "",
        ]
    )


def _normalize_milestones(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, list):
        return _default_milestones()
    rows: List[Dict[str, Any]] = []
    for idx, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            continue
        milestone_id = str(item.get("id") or f"M{idx}").strip() or f"M{idx}"
        title = str(item.get("title") or f"Milestone {idx}").strip() or f"Milestone {idx}"
        goal = str(item.get("goal") or "").strip()
        acceptance = item.get("acceptance_criteria") if isinstance(item.get("acceptance_criteria"), list) else []
        checkpoints = item.get("checkpoint_tests") if isinstance(item.get("checkpoint_tests"), list) else []
        row = {
            "id": milestone_id,
            "title": title,
            "goal": goal or "TBD",
            "acceptance_criteria": [str(x).strip() for x in acceptance if str(x).strip()],
            "checkpoint_tests": [str(x).strip() for x in checkpoints if str(x).strip()],
        }
        if not row["acceptance_criteria"]:
            row["acceptance_criteria"] = ["Define acceptance criteria."]
        if not row["checkpoint_tests"]:
            row["checkpoint_tests"] = ["pytest -q"]
        rows.append(row)
    return rows or _default_milestones()


def generate_app_builder_docs(
    *,
    idea: str,
    output_dir: Optional[Path] = None,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    config = get_config()
    library_root = Path(getattr(config, "library_root_dir", Path.cwd() / "Chintus_Library"))
    base_dir = Path(output_dir or (library_root / "app_builder"))
    stamp = _utc_stamp()
    slug = _safe_slug(idea)[:50]
    proj_dir = base_dir / f"{stamp}_{slug}"
    proj_dir.mkdir(parents=True, exist_ok=True)

    router = _get_router_from_context(context)
    system = (
        "You are a senior product manager + tech lead. "
        "You produce crisp, structured deliverables that a solo developer can execute."
    )
    prompt = f"""
Idea: {idea}

Constraints:
- Build for a solo developer.
- Produce: product brief, PRD, architecture, UX/app flow (Mermaid), tech stack, frontend guidelines, backend schema, API contracts, implementation plan.
- Include milestone plan with acceptance criteria + checkpoint tests.
- Include a machine-readable data model JSON suitable for scaffolding a backend.

Return JSON only:
{{
  "name": "project name",
  "product_brief": {{
    "problem": "...",
    "users": ["..."],
    "requirements": ["..."],
    "constraints": ["..."],
    "success_metrics": ["..."]
  }},
  "prd_md": "...",
  "architecture_md": "...",
  "ux_flow_mermaid": "flowchart/sequence mermaid (no backticks)",
  "tech_stack_md": "...",
  "frontend_guidelines_md": "...",
  "backend_schema_md": "...",
  "api_contracts_md": "...",
  "milestones": [
    {{
      "id": "M1",
      "title": "milestone title",
      "goal": "...",
      "acceptance_criteria": ["..."],
      "checkpoint_tests": ["pytest ..."]
    }}
  ],
  "implementation_plan_md": "...",
  "data_model": {{
     "entities": [
        {{
          "name": "EntityName",
          "fields": [{{"name":"field","type":"string|int|bool|float|datetime|uuid","required":true}}],
          "notes": "optional"
        }}
     ]
  }}
}}
""".strip()
    raw = _generate_text(router, prompt, system=system)
    data: Dict[str, Any] = {}
    try:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            data = json.loads(raw[start : end + 1])
    except Exception:
        data = {}

    # Retry once with cloud routing if JSON could not be parsed (keeps local-first but improves robustness).
    if router and not data:
        retry = _generate_text(router, "cloud: " + prompt, system=system)
        if retry:
            try:
                start = retry.find("{")
                end = retry.rfind("}")
                if start >= 0 and end > start:
                    parsed_retry = json.loads(retry[start : end + 1])
                    if isinstance(parsed_retry, dict) and parsed_retry:
                        raw = retry
                        data = parsed_retry
            except Exception:
                pass

    if not data and raw:
        # Degrade gracefully: keep the raw LLM output as PRD notes so nothing is lost.
        data = {
            "name": "New App",
            "product_brief": _default_product_brief(idea),
            "prd_md": raw.strip(),
            "architecture_md": "",
            "ux_flow_mermaid": "",
            "tech_stack_md": "",
            "frontend_guidelines_md": "",
            "backend_schema_md": "",
            "api_contracts_md": "",
            "milestones": _default_milestones(),
            "implementation_plan_md": "",
            "data_model": {},
        }

    name = str(data.get("name") or "New App").strip()[:120]
    product_brief = data.get("product_brief") if isinstance(data.get("product_brief"), dict) else _default_product_brief(idea)
    if not product_brief:
        product_brief = _default_product_brief(idea)
    milestones = _normalize_milestones(data.get("milestones"))

    (proj_dir / "IDEA.txt").write_text(idea.strip() + "\n", encoding="utf-8")
    (proj_dir / "PRODUCT_BRIEF.md").write_text(_render_product_brief_md(product_brief), encoding="utf-8")
    (proj_dir / "PRD.md").write_text(str(data.get("prd_md") or "TBD").strip() + "\n", encoding="utf-8")
    (proj_dir / "ARCHITECTURE.md").write_text(str(data.get("architecture_md") or "TBD").strip() + "\n", encoding="utf-8")
    (proj_dir / "TECH_STACK.md").write_text(str(data.get("tech_stack_md") or "TBD").strip() + "\n", encoding="utf-8")
    (proj_dir / "FRONTEND_GUIDELINES.md").write_text(str(data.get("frontend_guidelines_md") or "TBD").strip() + "\n", encoding="utf-8")
    (proj_dir / "BACKEND_SCHEMA.md").write_text(str(data.get("backend_schema_md") or "TBD").strip() + "\n", encoding="utf-8")
    (proj_dir / "API_CONTRACTS.md").write_text(str(data.get("api_contracts_md") or "TBD").strip() + "\n", encoding="utf-8")
    (proj_dir / "IMPLEMENTATION_PLAN.md").write_text(str(data.get("implementation_plan_md") or "TBD").strip() + "\n", encoding="utf-8")
    _write_json(proj_dir / "MILESTONES.json", {"milestones": milestones})

    mermaid = str(data.get("ux_flow_mermaid") or "").strip()
    if mermaid:
        (proj_dir / "UI_FLOW.mmd").write_text(mermaid + "\n", encoding="utf-8")

    model = data.get("data_model") if isinstance(data.get("data_model"), dict) else {}
    model_dict = model if isinstance(model, dict) else {}
    entities = model_dict.get("entities") if isinstance(model_dict.get("entities"), list) else []
    if not entities:
        model_dict = {
            "entities": [
                {
                    "name": "Item",
                    "fields": [
                        {"name": "title", "type": "string", "required": True},
                        {"name": "created_at", "type": "datetime", "required": False},
                    ],
                    "notes": "Fallback entity because the model output did not include a data model.",
                }
            ]
        }
    _write_json(proj_dir / "data_model.json", model_dict)

    summary = (
        f"Project: {name}\n"
        f"Folder: {proj_dir}\n"
        "\n"
        "Next: review the docs. When approved, run the build step to scaffold code,"
        " install dependencies, and execute checkpoint tests."
    )
    (proj_dir / "SUMMARY.txt").write_text(summary + "\n", encoding="utf-8")

    return {
        "name": name,
        "dir": str(proj_dir),
        "product_brief": str(proj_dir / "PRODUCT_BRIEF.md"),
        "prd": str(proj_dir / "PRD.md"),
        "architecture": str(proj_dir / "ARCHITECTURE.md"),
        "flow": str(proj_dir / "UI_FLOW.mmd") if mermaid else "",
        "tech_stack": str(proj_dir / "TECH_STACK.md"),
        "frontend_guidelines": str(proj_dir / "FRONTEND_GUIDELINES.md"),
        "backend_schema": str(proj_dir / "BACKEND_SCHEMA.md"),
        "api_contracts": str(proj_dir / "API_CONTRACTS.md"),
        "milestones": str(proj_dir / "MILESTONES.json"),
        "plan": str(proj_dir / "IMPLEMENTATION_PLAN.md"),
        "data_model": str(proj_dir / "data_model.json"),
    }


def scaffold_fastapi_backend(project_dir: Path) -> Dict[str, Any]:
    """Create a runnable FastAPI backend skeleton from data_model.json.

    This is intentionally simple: in-memory storage + CRUD endpoints.
    It is a strong "MVP starter" and can be upgraded to a real DB later.
    """

    project_dir = Path(project_dir).resolve()
    model_path = project_dir / "data_model.json"
    if not model_path.exists():
        raise FileNotFoundError(f"Missing data model: {model_path}")

    try:
        model = json.loads(model_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Invalid JSON in data_model.json: {exc}") from exc

    entities = model.get("entities") if isinstance(model, dict) else None
    if not isinstance(entities, list) or not entities:
        raise ValueError("data_model.json missing 'entities' list.")

    backend_dir = project_dir / "backend"
    app_dir = backend_dir / "app"
    tests_dir = backend_dir / "tests"
    app_dir.mkdir(parents=True, exist_ok=True)
    tests_dir.mkdir(parents=True, exist_ok=True)

    (backend_dir / "requirements.txt").write_text(
        "\n".join(
            [
                "fastapi>=0.110",
                "uvicorn[standard]>=0.27",
                "pydantic>=2.0",
                "pytest>=7.0",
                "httpx>=0.24",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    (app_dir / "__init__.py").write_text("", encoding="utf-8")

    # Minimal CRUD per entity (in-memory store).
    # We generate schemas + router in one file for readability.
    code = _render_fastapi_app(entities)
    (app_dir / "main.py").write_text(code, encoding="utf-8")

    (tests_dir / "test_health.py").write_text(
        "\n".join(
            [
                "from fastapi.testclient import TestClient",
                "",
                "from app.main import app",
                "",
                "",
                "def test_health():",
                "    client = TestClient(app)",
                "    resp = client.get('/health')",
                "    assert resp.status_code == 200",
                "    assert resp.json().get('ok') is True",
                "",
            ]
        ),
        encoding="utf-8",
    )

    first = str(entities[0].get("name") or "Item").strip()
    first_plural = _pluralize(first).lower()
    (tests_dir / "test_crud_smoke.py").write_text(
        "\n".join(
            [
                "from fastapi.testclient import TestClient",
                "",
                "from app.main import app",
                "",
                "",
                "def test_crud_smoke():",
                "    client = TestClient(app)",
                f"    resp = client.get('/{first_plural}')",
                "    assert resp.status_code == 200",
                "    assert isinstance(resp.json(), list)",
                "",
            ]
        ),
        encoding="utf-8",
    )

    return {
        "backend_dir": str(backend_dir),
        "main": str(app_dir / "main.py"),
        "requirements": str(backend_dir / "requirements.txt"),
        "tests": [str(t) for t in sorted(tests_dir.glob('test_*.py'))],
    }


def _run_build_command(
    command: List[str],
    cwd: Path,
    timeout_seconds: int = 600,
) -> Dict[str, Any]:
    proc = subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=max(10, int(timeout_seconds)),
        check=False,
        shell=False,
    )
    return {
        "command": command,
        "return_code": int(proc.returncode),
        "stdout_preview": (proc.stdout or "")[:2000],
        "stderr_preview": (proc.stderr or "")[:2000],
    }


def execute_app_builder_build(
    project_dir: Path,
    *,
    install_deps: bool = True,
    run_tests: bool = True,
    runner: Optional[Callable[[List[str], Path, int], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Phase 4.5 build executor.

    Executes scaffold -> dependency install -> checkpoint tests and records
    deterministic checkpoint artifacts.
    """

    project_dir = Path(project_dir).resolve()
    run_cmd = runner or _run_build_command
    backend_info: Dict[str, Any]
    checkpoints: List[Dict[str, Any]] = []
    command_log: List[Dict[str, Any]] = []

    backend_dir = project_dir / "backend"
    app_main = backend_dir / "app" / "main.py"
    requirements = backend_dir / "requirements.txt"

    scaffold_needed = not (backend_dir.exists() and app_main.exists() and requirements.exists())
    if scaffold_needed:
        backend_info = scaffold_fastapi_backend(project_dir)
        checkpoints.append(
            {
                "id": "scaffold",
                "status": "passed",
                "detail": "Backend scaffold generated from data_model.json.",
                "acceptance": bool(Path(backend_info["main"]).exists() and Path(backend_info["requirements"]).exists()),
            }
        )
    else:
        backend_info = {
            "backend_dir": str(backend_dir),
            "main": str(app_main),
            "requirements": str(requirements),
            "tests": [str(path) for path in sorted((backend_dir / "tests").glob("test_*.py"))],
        }
        checkpoints.append(
            {
                "id": "scaffold",
                "status": "passed",
                "detail": "Existing backend scaffold reused.",
                "acceptance": True,
            }
        )

    python_exe = Path(sys.executable).resolve()
    venv_python = backend_dir / ".venv" / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")

    if install_deps:
        if not venv_python.exists():
            create_venv = run_cmd([str(python_exe), "-m", "venv", ".venv"], backend_dir, 300)
            command_log.append(create_venv)
            if int(create_venv.get("return_code", 1)) != 0:
                checkpoints.append(
                    {
                        "id": "install_deps",
                        "status": "failed",
                        "detail": "Failed to create backend virtual environment.",
                        "acceptance": False,
                    }
                )
                receipt = {
                    "timestamp_utc": _utc_now_iso(),
                    "status": "failed",
                    "project_dir": str(project_dir),
                    "checkpoints": checkpoints,
                    "commands": command_log,
                    "run_command": "",
                }
                receipt_path = project_dir / "BUILD_EXECUTION.json"
                receipt_path.write_text(json.dumps(receipt, indent=2, ensure_ascii=True), encoding="utf-8")
                return {
                    "success": False,
                    "backend_dir": str(backend_dir),
                    "checkpoints": checkpoints,
                    "commands": command_log,
                    "receipt": str(receipt_path),
                    "run_command": "",
                }

        install = run_cmd([str(venv_python), "-m", "pip", "install", "-r", "requirements.txt"], backend_dir, 900)
        command_log.append(install)
        install_ok = int(install.get("return_code", 1)) == 0
        checkpoints.append(
            {
                "id": "install_deps",
                "status": "passed" if install_ok else "failed",
                "detail": "Dependencies installed in backend virtual environment." if install_ok else "Dependency installation failed.",
                "acceptance": install_ok,
            }
        )
        if not install_ok:
            receipt = {
                "timestamp_utc": _utc_now_iso(),
                "status": "failed",
                "project_dir": str(project_dir),
                "checkpoints": checkpoints,
                "commands": command_log,
                "run_command": "",
            }
            receipt_path = project_dir / "BUILD_EXECUTION.json"
            receipt_path.write_text(json.dumps(receipt, indent=2, ensure_ascii=True), encoding="utf-8")
            return {
                "success": False,
                "backend_dir": str(backend_dir),
                "checkpoints": checkpoints,
                "commands": command_log,
                "receipt": str(receipt_path),
                "run_command": "",
            }
    else:
        checkpoints.append(
            {
                "id": "install_deps",
                "status": "skipped",
                "detail": "Dependency install skipped by request.",
                "acceptance": True,
            }
        )

    tests_ok = True
    if run_tests:
        test_python = str(venv_python if venv_python.exists() else python_exe)
        tests = run_cmd([test_python, "-m", "pytest", "-q"], backend_dir, 900)
        command_log.append(tests)
        tests_ok = int(tests.get("return_code", 1)) == 0
        checkpoints.append(
            {
                "id": "checkpoint_tests",
                "status": "passed" if tests_ok else "failed",
                "detail": "Checkpoint tests passed." if tests_ok else "Checkpoint tests failed.",
                "acceptance": tests_ok,
            }
        )
    else:
        checkpoints.append(
            {
                "id": "checkpoint_tests",
                "status": "skipped",
                "detail": "Checkpoint tests skipped by request.",
                "acceptance": True,
            }
        )

    run_python = str(venv_python if venv_python.exists() else python_exe)
    run_command = f"{run_python} -m uvicorn app.main:app --reload"
    status = "success" if tests_ok else "failed"
    receipt_payload = {
        "timestamp_utc": _utc_now_iso(),
        "status": status,
        "project_dir": str(project_dir),
        "backend_dir": str(backend_dir),
        "checkpoints": checkpoints,
        "commands": command_log,
        "run_command": run_command,
    }
    receipt_path = project_dir / "BUILD_EXECUTION.json"
    receipt_path.write_text(json.dumps(receipt_payload, indent=2, ensure_ascii=True), encoding="utf-8")

    return {
        "success": tests_ok,
        "backend_dir": str(backend_dir),
        "main": str(Path(backend_info.get("main", ""))),
        "requirements": str(Path(backend_info.get("requirements", ""))),
        "checkpoints": checkpoints,
        "commands": command_log,
        "receipt": str(receipt_path),
        "run_command": run_command,
    }


def _pluralize(name: str) -> str:
    word = (name or "").strip()
    if not word:
        return "items"
    if word.lower().endswith("s"):
        return word + "es"
    return word + "s"


def _py_type(field_type: str) -> str:
    t = (field_type or "string").strip().lower()
    if t in {"int", "integer"}:
        return "int"
    if t in {"float", "number"}:
        return "float"
    if t in {"bool", "boolean"}:
        return "bool"
    if t in {"datetime", "date"}:
        return "str"
    if t in {"uuid"}:
        return "str"
    return "str"


def _render_fastapi_app(entities: List[dict]) -> str:
    lines: List[str] = []
    lines.append("from __future__ import annotations")
    lines.append("")
    lines.append("import uuid")
    lines.append("from typing import Dict, List, Optional")
    lines.append("")
    lines.append("from fastapi import FastAPI, HTTPException")
    lines.append("from pydantic import BaseModel, Field")
    lines.append("")
    lines.append("app = FastAPI(title='Chintu App Builder Backend')")
    lines.append("")
    lines.append("@app.get('/health')")
    lines.append("def health():")
    lines.append("    return {'ok': True}")
    lines.append("")
    lines.append("# In-memory stores per entity. Replace with a DB layer when ready.")
    lines.append("_STORE: Dict[str, Dict[str, dict]] = {}")
    lines.append("")

    for ent in entities:
        name = str(ent.get("name") or "").strip()
        if not name:
            continue
        fields = ent.get("fields") if isinstance(ent.get("fields"), list) else []
        class_base = f"{name}Base"
        class_create = f"{name}Create"
        class_update = f"{name}Update"
        class_read = f"{name}"

        lines.append(f"class {class_base}(BaseModel):")
        if not fields:
            lines.append("    pass")
        else:
            for f in fields:
                fname = str((f or {}).get("name") or "").strip()
                if not fname or fname.lower() == "id":
                    continue
                ftype = _py_type(str((f or {}).get("type") or "string"))
                required = bool((f or {}).get("required", True))
                default = "..." if required else "None"
                ann = ftype if required else f"Optional[{ftype}]"
                lines.append(f"    {fname}: {ann} = {default}")
        lines.append("")

        lines.append(f"class {class_create}({class_base}):")
        lines.append("    pass")
        lines.append("")

        lines.append(f"class {class_update}(BaseModel):")
        if not fields:
            lines.append("    pass")
        else:
            for f in fields:
                fname = str((f or {}).get("name") or "").strip()
                if not fname or fname.lower() == "id":
                    continue
                ftype = _py_type(str((f or {}).get("type") or "string"))
                lines.append(f"    {fname}: Optional[{ftype}] = None")
        lines.append("")

        lines.append(f"class {class_read}({class_base}):")
        lines.append("    id: str = Field(default_factory=lambda: str(uuid.uuid4()))")
        lines.append("")

        route = _pluralize(name).lower()
        lines.append("def _get_bucket(kind: str) -> Dict[str, dict]:")
        lines.append("    bucket = _STORE.get(kind)")
        lines.append("    if bucket is None:")
        lines.append("        bucket = {}")
        lines.append("        _STORE[kind] = bucket")
        lines.append("    return bucket")
        lines.append("")

        lines.append(f"@app.get('/{route}', response_model=List[{class_read}])")
        lines.append(f"def list_{route}():")
        lines.append(f"    bucket = _get_bucket('{name}')")
        lines.append("    return list(bucket.values())")
        lines.append("")

        lines.append(f"@app.post('/{route}', response_model={class_read})")
        lines.append(f"def create_{name.lower()}(payload: {class_create}):")
        lines.append(f"    bucket = _get_bucket('{name}')")
        lines.append(f"    item = {class_read}(**payload.model_dump())")
        lines.append("    bucket[item.id] = item.model_dump()")
        lines.append("    return item")
        lines.append("")

        lines.append(f"@app.get('/{route}/{{item_id}}', response_model={class_read})")
        lines.append(f"def get_{name.lower()}(item_id: str):")
        lines.append(f"    bucket = _get_bucket('{name}')")
        lines.append("    item = bucket.get(item_id)")
        lines.append("    if not item:")
        lines.append("        raise HTTPException(status_code=404, detail='Not found')")
        lines.append(f"    return {class_read}(**item)")
        lines.append("")

        lines.append(f"@app.put('/{route}/{{item_id}}', response_model={class_read})")
        lines.append(f"def update_{name.lower()}(item_id: str, payload: {class_update}):")
        lines.append(f"    bucket = _get_bucket('{name}')")
        lines.append("    item = bucket.get(item_id)")
        lines.append("    if not item:")
        lines.append("        raise HTTPException(status_code=404, detail='Not found')")
        lines.append("    updates = payload.model_dump(exclude_unset=True)")
        lines.append("    item.update(updates)")
        lines.append("    bucket[item_id] = item")
        lines.append(f"    return {class_read}(**item)")
        lines.append("")

        lines.append(f"@app.delete('/{route}/{{item_id}}')")
        lines.append(f"def delete_{name.lower()}(item_id: str):")
        lines.append(f"    bucket = _get_bucket('{name}')")
        lines.append("    if item_id not in bucket:")
        lines.append("        raise HTTPException(status_code=404, detail='Not found')")
        lines.append("    bucket.pop(item_id, None)")
        lines.append("    return {'ok': True}")
        lines.append("")

    return "\n".join(lines) + "\n"
