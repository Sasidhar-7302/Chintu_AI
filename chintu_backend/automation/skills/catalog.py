"""Curated skill catalog for safe bootstrap installs.

This catalog is intentionally split into:
- initial: installable now from trusted local bundled packs
- later: reference-only entries that require manual review/import
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional


_BUNDLED_DIR = Path(__file__).resolve().parent / "bundled"


@dataclass(frozen=True)
class SkillCatalogEntry:
    skill_id: str
    name: str
    stage: str  # initial | later
    summary: str
    install_strategy: str  # bundled_copy | reference_only
    source_label: str  # bundled | curated | community
    source_path: str = ""
    reference_url: str = ""
    risk: str = "low"
    tags: List[str] = field(default_factory=list)
    target_dir_name: str = ""

    def bundled_file(self) -> Optional[Path]:
        if self.install_strategy != "bundled_copy":
            return None
        if not self.source_path:
            return None
        return _BUNDLED_DIR / self.source_path

    def effective_target_dir_name(self) -> str:
        return self.target_dir_name or self.skill_id.replace("_", "-")


_CATALOG: List[SkillCatalogEntry] = [
    SkillCatalogEntry(
        skill_id="repo_search_rg",
        name="Repo Search (ripgrep)",
        stage="initial",
        summary="Fast codebase search with ripgrep for debugging and implementation tasks.",
        install_strategy="bundled_copy",
        source_label="bundled",
        source_path="skill_ripgrep.md",
        risk="low",
        tags=["dev", "search", "core"],
    ),
    SkillCatalogEntry(
        skill_id="web_reader_jina",
        name="Web Reader (Jina)",
        stage="initial",
        summary="Fetch clean article text for grounded research and summarization.",
        install_strategy="bundled_copy",
        source_label="bundled",
        source_path="skill_jina_reader.md",
        risk="low",
        tags=["research", "web", "core"],
    ),
    SkillCatalogEntry(
        skill_id="web_search_searxng",
        name="Web Search (SearxNG)",
        stage="initial",
        summary="Meta-search over multiple engines for broad, current discovery.",
        install_strategy="bundled_copy",
        source_label="bundled",
        source_path="skill_searxng.md",
        risk="low",
        tags=["research", "web", "core"],
    ),
    SkillCatalogEntry(
        skill_id="system_monitor",
        name="System Monitor",
        stage="initial",
        summary="Host telemetry checks for CPU/memory/GPU aware task routing.",
        install_strategy="bundled_copy",
        source_label="bundled",
        source_path="skill_system_monitor.md",
        risk="low",
        tags=["ops", "hardware", "core"],
    ),
    SkillCatalogEntry(
        skill_id="git_ops",
        name="Git Ops",
        stage="initial",
        summary="Structured git read-only and safe workflow commands.",
        install_strategy="bundled_copy",
        source_label="bundled",
        source_path="skill_git.md",
        risk="low",
        tags=["dev", "git", "core"],
    ),
    SkillCatalogEntry(
        skill_id="docker_ops",
        name="Docker Ops",
        stage="initial",
        summary="Container execution path for isolation and reproducible tool runs.",
        install_strategy="bundled_copy",
        source_label="bundled",
        source_path="skill_docker.md",
        risk="medium",
        tags=["ops", "sandbox", "isolation"],
    ),
    SkillCatalogEntry(
        skill_id="http_curl",
        name="HTTP Curl",
        stage="initial",
        summary="HTTP probing and API inspection for integrations and diagnostics.",
        install_strategy="bundled_copy",
        source_label="bundled",
        source_path="skill_curl.md",
        risk="low",
        tags=["api", "ops", "debug"],
    ),
    SkillCatalogEntry(
        skill_id="json_jq",
        name="JSON jq",
        stage="initial",
        summary="Deterministic JSON extraction and transformation.",
        install_strategy="bundled_copy",
        source_label="bundled",
        source_path="skill_jq.md",
        risk="low",
        tags=["data", "json", "core"],
    ),
    SkillCatalogEntry(
        skill_id="units_convert",
        name="Units Conversion",
        stage="initial",
        summary="Deterministic unit conversion tool for engineering and finance workflows.",
        install_strategy="bundled_copy",
        source_label="bundled",
        source_path="skill_units.md",
        risk="low",
        tags=["utility", "math"],
    ),
    SkillCatalogEntry(
        skill_id="finance_yahoo",
        name="Yahoo Finance",
        stage="initial",
        summary="Read-only market snapshots for portfolio analysis workflows.",
        install_strategy="bundled_copy",
        source_label="bundled",
        source_path="skill_yahoo_finance.md",
        risk="low",
        tags=["finance", "read-only"],
    ),
    SkillCatalogEntry(
        skill_id="media_ffmpeg",
        name="Media FFmpeg",
        stage="initial",
        summary="Media conversion/transcoding for content pipeline automation.",
        install_strategy="bundled_copy",
        source_label="bundled",
        source_path="skill_ffmpeg.md",
        risk="medium",
        tags=["media", "content"],
    ),
    SkillCatalogEntry(
        skill_id="media_yt_dlp",
        name="Media yt-dlp",
        stage="initial",
        summary="Content retrieval utility for draft/edit workflows (policy-gated).",
        install_strategy="bundled_copy",
        source_label="bundled",
        source_path="skill_yt_dlp.md",
        risk="medium",
        tags=["media", "content", "web"],
    ),
    SkillCatalogEntry(
        skill_id="file_find_fd",
        name="File Finder (fd)",
        stage="initial",
        summary="Fast recursive file discovery to support coding/debug workflows.",
        install_strategy="bundled_copy",
        source_label="bundled",
        source_path="skill_fd_find.md",
        risk="low",
        tags=["dev", "files", "search"],
    ),
    SkillCatalogEntry(
        skill_id="markdown_convert",
        name="Markdown Convert",
        stage="initial",
        summary="Document conversion helper for research and reporting workflows.",
        install_strategy="bundled_copy",
        source_label="bundled",
        source_path="skill_markitdown.md",
        risk="low",
        tags=["docs", "research"],
    ),
    SkillCatalogEntry(
        skill_id="curated_skill_registry_review",
        name="Curated Skill Registry Review",
        stage="later",
        summary="Review and selectively import vetted community skills from curated registry sources.",
        install_strategy="reference_only",
        source_label="curated",
        reference_url="https://github.com/topics/agent-skills",
        risk="medium",
        tags=["community", "review", "manual"],
    ),
    SkillCatalogEntry(
        skill_id="curated_agent_skills_review",
        name="Curated Agent Skills Review",
        stage="later",
        summary="Evaluate open-source skill packs for fit, then import via sandboxed approval flow.",
        install_strategy="reference_only",
        source_label="curated",
        reference_url="https://github.com/search?q=agent+skills&type=repositories",
        risk="medium",
        tags=["community", "review", "manual"],
    ),
    SkillCatalogEntry(
        skill_id="community_skill_index_review",
        name="Community Skill Index Review",
        stage="later",
        summary="Mine public skill indexes for candidates and import only with provenance and tests.",
        install_strategy="reference_only",
        source_label="community",
        reference_url="https://github.com/topics/ai-agents",
        risk="medium",
        tags=["community", "review", "manual"],
    ),
    SkillCatalogEntry(
        skill_id="moltworker_builtin_review",
        name="Moltworker Built-ins Review",
        stage="later",
        summary="Review Moltworker built-in skill patterns for safe, composable adaptations.",
        install_strategy="reference_only",
        source_label="community",
        reference_url="https://github.com/moltworker/moltworker",
        risk="low",
        tags=["patterns", "architecture", "manual"],
    ),
]


def list_catalog_entries(
    *,
    stage: str = "all",
    selected_ids: Optional[Iterable[str]] = None,
) -> List[SkillCatalogEntry]:
    selected = {str(x).strip().lower() for x in (selected_ids or []) if str(x).strip()}
    stage_key = str(stage or "all").strip().lower()
    out: List[SkillCatalogEntry] = []
    for entry in _CATALOG:
        if stage_key != "all" and entry.stage != stage_key:
            continue
        if selected and entry.skill_id.lower() not in selected:
            continue
        out.append(entry)
    return out


def get_catalog_index() -> Dict[str, SkillCatalogEntry]:
    return {entry.skill_id: entry for entry in _CATALOG}
