from __future__ import annotations

import json
from pathlib import Path

from chintu_backend.automation.skills.bootstrap import (
    apply_skill_bootstrap_plan,
    build_skill_bootstrap_plan,
)
from chintu_backend.automation.skills.catalog import list_catalog_entries


def test_initial_catalog_contains_core_entries() -> None:
    entries = list_catalog_entries(stage="initial")
    ids = {entry.skill_id for entry in entries}
    expected = {
        "repo_search_rg",
        "web_reader_jina",
        "web_search_searxng",
        "system_monitor",
        "git_ops",
        "docker_ops",
    }
    assert expected.issubset(ids)


def test_bootstrap_dry_run_does_not_write_files(tmp_path: Path) -> None:
    report = build_skill_bootstrap_plan(
        workspace_dir=tmp_path,
        stage="initial",
        selected_ids=["repo_search_rg"],
    )
    assert report.apply is False
    assert any(action.skill_id == "repo_search_rg" for action in report.actions)
    assert not (tmp_path / "bootstrap").exists()


def test_bootstrap_apply_installs_and_validates(tmp_path: Path) -> None:
    receipt = tmp_path / "bootstrap_receipt.json"
    report = apply_skill_bootstrap_plan(
        workspace_dir=tmp_path,
        stage="initial",
        selected_ids=["repo_search_rg"],
        receipt_path=receipt,
    )
    target = tmp_path / "bootstrap" / "repo-search-rg" / "skill.md"
    assert report.apply is True
    assert target.exists()
    assert target.read_text(encoding="utf-8").strip() != ""
    assert report.validation.get("loaded_count", 0) >= 1
    assert receipt.exists()
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload.get("apply") is True


def test_bootstrap_skips_when_skill_already_available(tmp_path: Path) -> None:
    report = build_skill_bootstrap_plan(
        workspace_dir=tmp_path,
        stage="initial",
        selected_ids=["repo_search_rg"],
        existing_skill_names=["ripgrep"],
    )
    action = next(action for action in report.actions if action.skill_id == "repo_search_rg")
    assert action.action == "already_installed"
