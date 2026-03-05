"""Focused tests for deterministic autonomy workflow routing and handling."""

import sys
import types
from pathlib import Path

from chintu_backend.automation import automation_capabilities as ac
from chintu_backend.core.action_dispatcher import ActionDispatcher
from chintu_backend.core.capabilities import ActionResult, Capability, CapabilityRegistry, CapabilityType


def test_autonomy_pdf_workflow_dry_run(tmp_path: Path):
    downloads = tmp_path / "Downloads"
    desktop = tmp_path / "Desktop"
    downloads.mkdir(parents=True)
    desktop.mkdir(parents=True)
    (downloads / "paper1.pdf").write_bytes(b"%PDF-1.4\n")

    response = ac.handle_autonomy_workflow(
        "Find all PDFs in my Downloads folder from the last 7 days, summarize them into a single Markdown file, and move the originals to a new folder named Recent Research.",
        {
            "dry_run": True,
            "_user_downloads_dir": str(downloads),
            "_user_desktop_dir": str(desktop),
            "workspace_dir": str(tmp_path),
        },
    )

    assert response.success is True
    assert "DRY RUN" in response.message
    assert "Recent Research" in response.message
    assert ".md" in response.message


def test_autonomy_workflow_route_bypasses_decompose(monkeypatch):
    registry = CapabilityRegistry()
    registry.register(
        Capability(
            name="autonomy_workflow",
            triggers=["record my screen for the next 5 minutes"],
            handler=lambda _t, _c: ActionResult.ok("ok", capability="autonomy_workflow"),
            requires_confirmation=False,
            capability_type=CapabilityType.AUTOMATION,
        )
    )
    dispatcher = ActionDispatcher(registry, llm_client=None)
    calls = {"forced": 0}

    def _fake_execute_with_loop_guard(capability, text, context):
        assert capability.name == "autonomy_workflow"
        calls["forced"] += 1
        return ActionResult.ok(text, capability="autonomy_workflow")

    def _fail_decompose(_text):
        raise AssertionError("decompose() should not run for autonomy workflow requests")

    monkeypatch.setattr(dispatcher, "_execute_with_loop_guard", _fake_execute_with_loop_guard)
    monkeypatch.setattr(dispatcher.tool_router, "decompose", _fail_decompose)

    prompt = "Record my screen for the next 5 minutes while I demonstrate a bug in my code. Analyze the video, explain what went wrong, and suggest a fix."
    result = dispatcher.dispatch(prompt, {})

    assert result.success is True
    assert result.capability_name == "autonomy_workflow"
    assert calls["forced"] == 1


def test_autonomy_jira_returns_blocked_plan_when_not_configured():
    result = ac.handle_autonomy_workflow(
        "Search our past conversations from last month. What were the 3 main features I wanted for the YouTube Shorts Bot? Create a Jira ticket for each of them.",
        {"dry_run": False},
    )

    assert result.success is False
    assert "Blocked with unblock plan" in result.message
    assert "Jira" in result.message


def test_autonomy_pdf_no_files_mentions_recent_research(tmp_path: Path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir(parents=True)
    result = ac.handle_autonomy_workflow(
        "Find all PDFs in my Downloads folder from the last 7 days and move to Recent Research.",
        {"dry_run": False, "_user_downloads_dir": str(downloads)},
    )
    assert result.success is True
    assert "Recent Research" in result.message


def test_autonomy_thermal_guard_block_mentions_close_action():
    result = ac.handle_autonomy_workflow(
        "Check my i5-12600K thermals. If temperature exceeds 80C while gaming, close background AI processes.",
        {},
    )
    assert result.success is False
    assert "close" in result.message.lower()


def test_autonomy_sop_block_mentions_data_science_phd_and_courses(tmp_path: Path):
    result = ac.handle_autonomy_workflow(
        "Based on my Statement of Purpose draft and my resume, identify 3 gaps for a Data Science PhD and suggest courses.",
        {"workspace_dir": str(tmp_path)},
    )
    assert result.success is False
    assert "Data Science PhD" in result.message
    assert "courses" in result.message.lower()


def test_autonomy_screen_bug_response_mentions_fix():
    result = ac.handle_autonomy_workflow(
        "Record my screen for the next 5 minutes and analyze the video for a bug.",
        {},
    )
    assert "5 minute" in result.message
    assert "fix" in result.message.lower()


def test_autonomy_unmatched_request_returns_missing_capability_block():
    result = ac.handle_autonomy_workflow("Plan my vacation to Japan with a budget split.", {})
    assert result.success is False
    assert "Missing capability" in result.message


def test_autonomy_github_rate_limited_response_keeps_visa_context(monkeypatch):
    class _Resp:
        status_code = 403

        @staticmethod
        def json():
            return {}

    monkeypatch.setattr(ac.requests, "get", lambda *a, **k: _Resp())
    result = ac.handle_autonomy_workflow(
        "Research the top 3 trending open-source projects for Automated Visa Bots on GitHub.",
        {"dry_run": False},
    )
    assert "visa" in result.message.lower()


def test_autonomy_github_compare_rate_limit_falls_back_to_web(monkeypatch):
    class _Resp:
        status_code = 403

        @staticmethod
        def json():
            return {}

    class _FakeDDGS:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def text(self, *_args, **_kwargs):
            return [
                {"href": "https://github.com/example/visa-bot", "body": "Automation and appointment tracking"},
                {"href": "https://github.com/acme/visa-assistant", "body": "Visa notifications and status"},
                {"href": "https://github.com/test/consulate-bot", "body": "Bot for visa slots"},
            ]

    monkeypatch.setattr(ac.requests, "get", lambda *a, **k: _Resp())
    monkeypatch.setitem(sys.modules, "ddgs", types.SimpleNamespace(DDGS=_FakeDDGS))
    result = ac.handle_autonomy_workflow(
        "Research the top 3 trending open-source projects for Automated Visa Bots on GitHub.",
        {"dry_run": False},
    )
    assert result.success is True
    assert "Top 3 GitHub projects" in result.message
    assert "github.com/example/visa-bot" in result.message


def test_autonomy_youtube_shorts_jira_writes_draft_when_not_configured(tmp_path: Path, monkeypatch):
    import chintu_backend.integrations.jira as jira_mod

    monkeypatch.setattr(
        jira_mod,
        "get_jira_runtime_config",
        lambda: (False, {}, "Missing Jira configuration for tests."),
    )
    desktop = tmp_path / "Desktop"
    result = ac.handle_autonomy_workflow(
        "Search our past conversations from last month. What were the 3 main features I wanted for the YouTube Shorts Bot? Create a Jira ticket for each of them.",
        {"_user_desktop_dir": str(desktop)},
    )
    draft = desktop / "youtube_shorts_bot_jira_drafts.md"
    assert result.success is False
    assert "Jira" in result.message
    assert draft.exists()
