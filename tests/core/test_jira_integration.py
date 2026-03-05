from pathlib import Path

from chintu_backend.integrations.integration_store import (
    JiraConfig,
    get_jira_config,
    load_integrations,
    upsert_jira_config,
)
from chintu_backend.integrations.jira import get_jira_runtime_config


def test_integration_store_roundtrip_jira(tmp_path: Path):
    store_path = tmp_path / "integrations.json"
    cfg = JiraConfig(
        base_url="https://example.atlassian.net",
        email="user@example.com",
        project_key="CHINTU",
        issue_type="Task",
    )
    ok, _msg = upsert_jira_config(cfg, path=store_path)
    assert ok is True
    data = load_integrations(store_path)
    loaded = get_jira_config(data)
    assert loaded is not None
    assert loaded.base_url == "https://example.atlassian.net"
    assert loaded.project_key == "CHINTU"


def test_jira_runtime_config_requires_required_fields(monkeypatch):
    monkeypatch.delenv("CHINTU_JIRA_BASE_URL", raising=False)
    monkeypatch.delenv("CHINTU_JIRA_EMAIL", raising=False)
    monkeypatch.delenv("CHINTU_JIRA_API_TOKEN", raising=False)
    monkeypatch.delenv("CHINTU_JIRA_PROJECT_KEY", raising=False)
    from chintu_backend.core import config as cfg_mod

    cfg_mod._config = None
    ok, _cfg, err = get_jira_runtime_config()
    assert ok is False
    assert "Missing Jira configuration" in err
