"""Third-party skill scouting/import helpers."""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from chintu_backend.automation.skills.skill_registry import parse_skills_from_markdown, slugify
from chintu_backend.automation.skills.supply_chain import evaluate_skill_supply_chain
from chintu_backend.core.config import get_config


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class GithubRepoCandidate:
    full_name: str
    html_url: str
    description: str
    stars: int
    updated_at: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ThirdPartyImportResult:
    ok: bool
    import_dir: str
    skill_path: str
    names: List[str]
    blocked: bool
    issues: List[str]
    source_repo: str
    source_ref: str
    source_path: str
    approved: bool
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GithubRepoRanked:
    full_name: str
    html_url: str
    description: str
    stars: int
    updated_at: str
    score: float
    importable: bool
    discovered_paths: List[str]
    reasons: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AutoImportBatchResult:
    query: str
    generated_at_utc: str
    threshold: float
    top: int
    ranked: List[GithubRepoRanked]
    selected: List[GithubRepoRanked]
    imported: List[ThirdPartyImportResult]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "generated_at_utc": self.generated_at_utc,
            "threshold": self.threshold,
            "top": self.top,
            "ranked": [row.to_dict() for row in self.ranked],
            "selected": [row.to_dict() for row in self.selected],
            "imported": [row.to_dict() for row in self.imported],
        }


def scout_github_skill_repos(query: str, *, limit: int = 10, token: str = "") -> List[GithubRepoCandidate]:
    q = str(query or "").strip()
    if not q:
        q = "agent skills"
    limit = max(1, min(int(limit), 50))
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = requests.get(
        "https://api.github.com/search/repositories",
        params={"q": q, "per_page": str(limit), "sort": "stars", "order": "desc"},
        headers=headers,
        timeout=20,
    )
    resp.raise_for_status()
    payload = resp.json() if isinstance(resp.json(), dict) else {}
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    out: List[GithubRepoCandidate] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        out.append(
            GithubRepoCandidate(
                full_name=str(item.get("full_name") or "").strip(),
                html_url=str(item.get("html_url") or "").strip(),
                description=str(item.get("description") or "").strip(),
                stars=int(item.get("stargazers_count") or 0),
                updated_at=str(item.get("updated_at") or "").strip(),
            )
        )
    return out


def _days_since_iso(timestamp: str) -> float:
    text = str(timestamp or "").strip()
    if not text:
        return 9999.0
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return 9999.0
    return max((datetime.now(timezone.utc) - dt).total_seconds() / 86400.0, 0.0)


def _score_candidate(
    candidate: GithubRepoCandidate,
    *,
    query_tokens: List[str],
    discovered_paths: List[str],
) -> GithubRepoRanked:
    name_low = candidate.full_name.lower()
    desc_low = candidate.description.lower()
    stars = max(int(candidate.stars), 0)
    days = _days_since_iso(candidate.updated_at)

    stars_score = min((math.log10(stars + 1.0) / 5.0) * 35.0, 35.0)
    if days <= 14:
        recency_score = 25.0
    elif days <= 30:
        recency_score = 20.0
    elif days <= 90:
        recency_score = 12.0
    elif days <= 180:
        recency_score = 6.0
    else:
        recency_score = 2.0

    relevance_score = 0.0
    if "skill" in name_low or "skill" in desc_low:
        relevance_score += 10.0
    if "agent" in name_low or "agent" in desc_low:
        relevance_score += 6.0
    if "agent-skills" in name_low:
        relevance_score += 4.0
    token_hits = 0
    for token in query_tokens:
        if len(token) < 3:
            continue
        if token in name_low or token in desc_low:
            token_hits += 1
    relevance_score += min(float(token_hits) * 1.5, 5.0)
    relevance_score = min(relevance_score, 25.0)

    path_count = len(discovered_paths)
    if path_count >= 5:
        structure_score = 15.0
    elif path_count >= 1:
        structure_score = 8.0
    else:
        structure_score = 0.0

    penalty = 0.0
    if path_count == 0:
        penalty += 20.0
    if "awesome-" in name_low:
        penalty += 10.0
    if "chatgpt" in name_low and path_count == 0:
        penalty += 5.0

    score = max(min(stars_score + recency_score + relevance_score + structure_score - penalty, 100.0), 0.0)
    reasons = [
        f"stars={stars} (score={stars_score:.1f})",
        f"updated_days={days:.1f} (score={recency_score:.1f})",
        f"relevance_score={relevance_score:.1f}",
        f"skill_paths={path_count} (score={structure_score:.1f})",
    ]
    if penalty > 0:
        reasons.append(f"penalty={penalty:.1f}")

    return GithubRepoRanked(
        full_name=candidate.full_name,
        html_url=candidate.html_url,
        description=candidate.description,
        stars=candidate.stars,
        updated_at=candidate.updated_at,
        score=round(score, 2),
        importable=path_count > 0,
        discovered_paths=discovered_paths,
        reasons=reasons,
    )


def rank_github_skill_repos(
    query: str,
    *,
    limit: int = 20,
    token: str = "",
    ref: str = "main",
) -> List[GithubRepoRanked]:
    candidates = scout_github_skill_repos(query=query, limit=limit, token=token)
    query_tokens = [x.strip().lower() for x in re.split(r"[^a-zA-Z0-9]+", str(query or "")) if x.strip()]
    ranked: List[GithubRepoRanked] = []
    for row in candidates:
        paths = discover_skill_paths(row.full_name, ref=ref, token=token)
        ranked.append(_score_candidate(row, query_tokens=query_tokens, discovered_paths=paths))
    ranked.sort(key=lambda item: item.score, reverse=True)
    return ranked


def auto_import_top_ranked_repos(
    query: str,
    *,
    limit: int = 20,
    top: int = 3,
    score_threshold: float = 55.0,
    token: str = "",
    ref: str = "main",
    approved: bool = False,
    target_root: Optional[Path] = None,
) -> AutoImportBatchResult:
    ranked = rank_github_skill_repos(query=query, limit=limit, token=token, ref=ref)
    threshold = float(score_threshold)
    chosen: List[GithubRepoRanked] = []
    for row in ranked:
        if len(chosen) >= max(1, int(top)):
            break
        if not row.importable:
            continue
        if float(row.score) < threshold:
            continue
        chosen.append(row)

    imported: List[ThirdPartyImportResult] = []
    for row in chosen:
        best_path = row.discovered_paths[0]
        imported.append(
            import_skill_from_github(
                repo=row.full_name,
                path_in_repo=best_path,
                ref=ref,
                approved=approved,
                target_root=target_root,
            )
        )

    return AutoImportBatchResult(
        query=str(query or ""),
        generated_at_utc=_now_iso(),
        threshold=threshold,
        top=max(1, int(top)),
        ranked=ranked,
        selected=chosen,
        imported=imported,
    )


def _inject_provenance_frontmatter(
    markdown: str,
    *,
    repo: str,
    ref: str,
    path_in_repo: str,
    approved: bool,
) -> str:
    text = str(markdown or "")
    match = re.match(r"^\s*---\s*\n(.*?)\n---\s*\n?(.*)$", text, flags=re.DOTALL)
    if not match:
        return text
    try:
        import yaml

        front_raw = match.group(1)
        body = match.group(2)
        front = yaml.safe_load(front_raw) or {}
        if not isinstance(front, dict):
            front = {}
        metadata = front.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        supply_chain = metadata.get("supply_chain")
        if not isinstance(supply_chain, dict):
            supply_chain = {}
        supply_chain.update(
            {
                "repo": repo,
                "pinned_ref": ref,
                "path": path_in_repo,
                "approved": bool(approved),
                "imported_at_utc": _now_iso(),
            }
        )
        metadata["supply_chain"] = supply_chain
        front["metadata"] = metadata
        front_new = yaml.safe_dump(front, sort_keys=False).strip()
        return f"---\n{front_new}\n---\n{body.lstrip()}"
    except Exception:
        return text


def import_skill_from_github(
    *,
    repo: str,
    path_in_repo: str = "SKILL.md",
    ref: str = "main",
    approved: bool = False,
    target_root: Optional[Path] = None,
) -> ThirdPartyImportResult:
    repo_norm = str(repo or "").strip().replace("https://github.com/", "").strip("/")
    if not repo_norm or "/" not in repo_norm:
        return ThirdPartyImportResult(
            ok=False,
            import_dir="",
            skill_path="",
            names=[],
            blocked=True,
            issues=["Invalid repo format. Use owner/repo."],
            source_repo=repo_norm,
            source_ref=ref,
            source_path=path_in_repo,
            approved=bool(approved),
            note="",
        )

    cfg = get_config()
    root = Path(target_root) if target_root else cfg.skills_user_dir
    root = root or (cfg.data_dir / "skills")
    import_id = f"{slugify(repo_norm)}-{slugify(path_in_repo)}-{slugify(ref)}"
    out_dir = root / "imported" / import_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_skill = out_dir / "skill.md"
    meta_path = out_dir / "import_meta.json"

    raw_url = f"https://raw.githubusercontent.com/{repo_norm}/{ref}/{path_in_repo.lstrip('/')}"
    response = requests.get(raw_url, timeout=20)
    if response.status_code >= 400:
        suggestions: List[str] = []
        if path_in_repo.strip().lower() == "skill.md":
            suggestions = discover_skill_paths(repo_norm, ref=ref)
        issue = f"Failed to fetch {raw_url} (HTTP {response.status_code})."
        if suggestions:
            issue += " Try one of: " + ", ".join(suggestions[:8])
        return ThirdPartyImportResult(
            ok=False,
            import_dir=str(out_dir),
            skill_path=str(out_skill),
            names=[],
            blocked=True,
            issues=[issue],
            source_repo=repo_norm,
            source_ref=ref,
            source_path=path_in_repo,
            approved=bool(approved),
            note="",
        )

    markdown = response.text
    markdown = _inject_provenance_frontmatter(
        markdown,
        repo=repo_norm,
        ref=ref,
        path_in_repo=path_in_repo,
        approved=bool(approved),
    )
    out_skill.write_text(markdown, encoding="utf-8")

    specs = parse_skills_from_markdown(markdown)
    names = [spec.name for spec in specs]
    if not names:
        issue = "No parseable skill spec found in file."
        result = ThirdPartyImportResult(
            ok=False,
            import_dir=str(out_dir),
            skill_path=str(out_skill),
            names=[],
            blocked=True,
            issues=[issue],
            source_repo=repo_norm,
            source_ref=ref,
            source_path=path_in_repo,
            approved=bool(approved),
            note="",
        )
        meta_path.write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=True), encoding="utf-8")
        return result

    issues: List[str] = []
    blocked = False
    for spec in specs:
        decision = evaluate_skill_supply_chain(
            spec=spec,
            skill_path=out_skill,
            source_label="user",
            config=cfg,
        )
        if decision.blocked:
            blocked = True
        issues.extend(decision.issues)
        issues.extend(decision.warnings)

    note = "Imported and ready for load." if not blocked else "Imported but blocked by supply-chain policy."
    result = ThirdPartyImportResult(
        ok=not blocked,
        import_dir=str(out_dir),
        skill_path=str(out_skill),
        names=names,
        blocked=blocked,
        issues=sorted(set(issues)),
        source_repo=repo_norm,
        source_ref=ref,
        source_path=path_in_repo,
        approved=bool(approved),
        note=note,
    )
    meta_path.write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=True), encoding="utf-8")
    return result


def discover_skill_paths(repo: str, *, ref: str = "main", token: str = "") -> List[str]:
    repo_norm = str(repo or "").strip().replace("https://github.com/", "").strip("/")
    if not repo_norm or "/" not in repo_norm:
        return []
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"https://api.github.com/repos/{repo_norm}/git/trees/{ref}"
    response = requests.get(url, params={"recursive": "1"}, headers=headers, timeout=20)
    if response.status_code >= 400:
        return []
    payload = response.json() if isinstance(response.json(), dict) else {}
    tree = payload.get("tree") if isinstance(payload.get("tree"), list) else []
    out: List[str] = []
    for item in tree:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "") != "blob":
            continue
        path = str(item.get("path") or "").strip()
        low = path.lower()
        if not path:
            continue
        if low.endswith("skill.md") or low.endswith(".skill.md"):
            out.append(path)
    return sorted(set(out))
