from __future__ import annotations

from pathlib import Path

import chintu_backend.automation.skills.third_party as tp
from chintu_backend.automation.skills.third_party import (
    AutoImportBatchResult,
    GithubRepoCandidate,
    GithubRepoRanked,
    import_skill_from_github,
    rank_github_skill_repos,
    scout_github_skill_repos,
    auto_import_top_ranked_repos,
)


class _MockResponse:
    def __init__(self, *, status_code: int = 200, json_data=None, text: str = ""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        return self._json_data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


def test_scout_github_skill_repos(monkeypatch) -> None:
    payload = {
        "items": [
            {
                "full_name": "agenthub/agent-skills",
                "html_url": "https://github.com/agenthub/agent-skills",
                "description": "skills",
                "stargazers_count": 123,
                "updated_at": "2026-02-20T00:00:00Z",
            }
        ]
    }

    def _mock_get(*args, **kwargs):
        return _MockResponse(status_code=200, json_data=payload)

    monkeypatch.setattr("chintu_backend.automation.skills.third_party.requests.get", _mock_get)
    rows = scout_github_skill_repos("agent skills", limit=5)
    assert len(rows) == 1
    assert rows[0].full_name == "agenthub/agent-skills"
    assert rows[0].stars == 123


def test_import_github_skill_blocked_without_approve(monkeypatch, tmp_path: Path) -> None:
    skill_md = """---
name: external demo skill
description: test third-party import
triggers:
  - external demo
command: python {SKILL_DIR}/demo.py "{request}"
args:
  - request
type: shell
---
"""

    def _mock_get(*args, **kwargs):
        return _MockResponse(status_code=200, text=skill_md)

    monkeypatch.setattr("chintu_backend.automation.skills.third_party.requests.get", _mock_get)
    result = import_skill_from_github(
        repo="example/skills",
        path_in_repo="SKILL.md",
        ref="main",
        approved=False,
        target_root=tmp_path,
    )
    assert result.ok is False
    assert result.blocked is True
    assert any("explicit approval" in issue.lower() for issue in result.issues)


def test_import_github_skill_can_pass_with_approve(monkeypatch, tmp_path: Path) -> None:
    skill_md = """---
name: external approved skill
description: test third-party import with approval
triggers:
  - external approved
command: python {SKILL_DIR}/demo.py "{request}"
args:
  - request
type: shell
---
"""

    def _mock_get(*args, **kwargs):
        return _MockResponse(status_code=200, text=skill_md)

    monkeypatch.setattr("chintu_backend.automation.skills.third_party.requests.get", _mock_get)
    result = import_skill_from_github(
        repo="example/skills",
        path_in_repo="SKILL.md",
        ref="main",
        approved=True,
        target_root=tmp_path,
    )
    assert result.blocked is False
    assert Path(result.skill_path).exists()
    assert "ready for load" in result.note.lower()


def test_import_github_skill_suggests_paths_on_404(monkeypatch, tmp_path: Path) -> None:
    def _mock_get(url, *args, **kwargs):
        if "raw.githubusercontent.com" in url:
            return _MockResponse(status_code=404, text="")
        if "/git/trees/" in url:
            return _MockResponse(
                status_code=200,
                json_data={
                    "tree": [
                        {"type": "blob", "path": "skills/web/SKILL.md"},
                        {"type": "blob", "path": "README.md"},
                    ]
                },
            )
        return _MockResponse(status_code=404, text="")

    monkeypatch.setattr("chintu_backend.automation.skills.third_party.requests.get", _mock_get)
    result = import_skill_from_github(
        repo="example/skills",
        path_in_repo="SKILL.md",
        ref="main",
        approved=False,
        target_root=tmp_path,
    )
    assert result.ok is False
    assert any("try one of" in issue.lower() for issue in result.issues)


def test_rank_github_skill_repos_prefers_importable(monkeypatch) -> None:
    def _mock_scout(*args, **kwargs):
        return [
            GithubRepoCandidate(
                full_name="good/skills",
                html_url="https://github.com/good/skills",
                description="agent skills repository",
                stars=300,
                updated_at="2026-02-23T00:00:00Z",
            ),
            GithubRepoCandidate(
                full_name="noise/chat-app",
                html_url="https://github.com/noise/chat-app",
                description="chat app",
                stars=20000,
                updated_at="2026-02-23T00:00:00Z",
            ),
        ]

    def _mock_discover(repo: str, **kwargs):
        if repo == "good/skills":
            return ["skills/core/SKILL.md"]
        return []

    monkeypatch.setattr(tp, "scout_github_skill_repos", _mock_scout)
    monkeypatch.setattr(tp, "discover_skill_paths", _mock_discover)
    ranked = rank_github_skill_repos("agent skills", limit=10)
    assert len(ranked) == 2
    assert ranked[0].full_name == "good/skills"
    assert ranked[0].importable is True
    assert ranked[0].score > ranked[1].score


def test_auto_import_top_ranked_repos_threshold(monkeypatch) -> None:
    ranked_rows = [
        GithubRepoRanked(
            full_name="good/skills",
            html_url="https://github.com/good/skills",
            description="skills",
            stars=100,
            updated_at="2026-02-23T00:00:00Z",
            score=88.0,
            importable=True,
            discovered_paths=["skills/core/SKILL.md"],
            reasons=[],
        ),
        GithubRepoRanked(
            full_name="mid/skills",
            html_url="https://github.com/mid/skills",
            description="skills",
            stars=100,
            updated_at="2026-02-23T00:00:00Z",
            score=49.0,
            importable=True,
            discovered_paths=["skills/core/SKILL.md"],
            reasons=[],
        ),
    ]

    def _mock_rank(*args, **kwargs):
        return ranked_rows

    def _mock_import(**kwargs):
        return tp.ThirdPartyImportResult(
            ok=True,
            import_dir="x",
            skill_path="x/skill.md",
            names=["demo"],
            blocked=False,
            issues=[],
            source_repo=str(kwargs.get("repo") or ""),
            source_ref=str(kwargs.get("ref") or ""),
            source_path=str(kwargs.get("path_in_repo") or ""),
            approved=bool(kwargs.get("approved")),
            note="Imported and ready for load.",
        )

    monkeypatch.setattr(tp, "rank_github_skill_repos", _mock_rank)
    monkeypatch.setattr(tp, "import_skill_from_github", _mock_import)
    result = auto_import_top_ranked_repos(
        "skills",
        limit=10,
        top=2,
        score_threshold=60.0,
    )
    assert isinstance(result, AutoImportBatchResult)
    assert len(result.selected) == 1
    assert result.selected[0].full_name == "good/skills"
    assert len(result.imported) == 1
