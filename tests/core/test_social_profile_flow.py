"""Tests for social profile/channel setup flow."""

import pytest

from chintu_backend.automation import social_content_capabilities as scc


class _FakePageInfo:
    def __init__(self, url: str):
        self.url = url
        self.title = "YouTube"


class _FakeController:
    def __init__(self, *, open_url: str = "", title: str = ""):
        self.opened = []
        self._url = open_url
        self._title = title or "YouTube"
        self._is_open = bool(open_url)

    @property
    def is_open(self):
        return self._is_open

    def open_url(self, url: str, **kwargs):
        self.opened.append(url)
        self._url = url
        self._is_open = True
        return _FakePageInfo(url)

    def get_page_info(self):
        return _FakePageInfo(self._url)

    def list_interactive_elements(self, max_elements: int = 180):
        return {"elements": []}

    def fill_input(self, selector_or_label: str, value: str):
        return True

    def fill_visible_textbox(self, value: str, hint: str = ""):
        return True

    def click_text_force(self, target_text: str):
        return False

    def wait_for_text(self, text: str, timeout_ms: int = 5000):
        return True

    def act_by_ref(self, ref: str, action: str = "click", value=None, screenshot_after: bool = True):
        return {"success": True, "ref": ref, "action": action, "screenshot": ""}

    def get_page_content(self, max_length: int = 2000):
        return "YouTube Studio"

    def google_sign_in(self, email: str, password: str, timeout_ms: int = 20000):
        self._url = "https://www.youtube.com/"
        return {"success": True, "url": self._url, "needs_user_action": False}


@pytest.fixture(autouse=True)
def _disable_open_controller_reuse(monkeypatch):
    monkeypatch.setattr(
        "chintu_backend.automation.browser.browser_controller.get_open_browser_controller",
        lambda **kwargs: None,
    )


def test_social_stage_upload_uses_loggedin_profile(monkeypatch):
    captured = {"profile": None}
    fake = _FakeController()

    def _fake_get_browser_controller(*, headless=False, profile_name=None):
        captured["profile"] = profile_name
        return fake

    monkeypatch.setattr(
        "chintu_backend.automation.browser.browser_controller.get_browser_controller",
        _fake_get_browser_controller,
    )

    result = scc.handle_social_stage_upload("stage upload for youtube", {})

    assert result.success is True
    assert captured["profile"] in {"assistant_accounts", "research", "assistant_accounts"}
    assert "browser profile" in result.message.lower()


def test_social_youtube_channel_setup_waits_for_user_and_resume(monkeypatch):
    monkeypatch.setattr(
        scc,
        "_verify_channel_created",
        lambda controller, channel_name: {"verified": True, "reason": "test", "url": "https://studio.youtube.com/"},
    )
    follow = scc.handle_social_youtube_channel_setup(
        "done, continue channel setup",
        {"browser_profile": "assistant_accounts", "_resume_waiting_input": True},
    )
    assert follow.success is True
    assert follow.capability_name == "social_youtube_channel_setup"
    assert "verified youtube channel setup" in follow.message.lower()
    assert (follow.data or {}).get("awaiting_user_action") is False


def test_social_youtube_resume_requires_name_match(monkeypatch):
    monkeypatch.setattr(
        scc,
        "_verify_channel_created",
        lambda controller, channel_name: {
            "verified": False,
            "reason": "name_not_found",
            "url": "https://studio.youtube.com/",
        },
    )
    follow = scc.handle_social_youtube_channel_setup(
        "done, continue channel setup",
        {
            "browser_profile": "Profile 1",
            "_resume_waiting_input": True,
            "_waiting_input_meta": {"channel_name": "Chintu Founder Labs"},
        },
    )
    assert follow.success is True
    assert follow.capability_name == "social_youtube_channel_setup"
    assert (follow.data or {}).get("awaiting_user_action") is True
    assert "could not verify the channel as created" in follow.message.lower()


def test_social_youtube_setup_does_not_open_three_urls(monkeypatch):
    fake = _FakeController()

    monkeypatch.setattr(
        "chintu_backend.automation.browser.browser_controller.get_browser_controller",
        lambda **kwargs: fake,
    )

    result = scc.handle_social_youtube_channel_setup(
        "Create YouTube channel named Chintu Founder Labs",
        {"browser_profile": "Profile 1"},
    )

    assert result.success is True
    assert len(fake.opened) <= 3
    assert (result.data or {}).get("awaiting_user_action") is True


def test_social_youtube_setup_auth_page_keeps_same_session(monkeypatch):
    fake = _FakeController(
        open_url="https://accounts.google.com/signin/v2/identifier?service=youtube",
        title="Sign in - Google Accounts",
    )

    monkeypatch.setattr(
        "chintu_backend.automation.browser.browser_controller.get_browser_controller",
        lambda **kwargs: fake,
    )

    result = scc.handle_social_youtube_channel_setup(
        "Create YouTube channel named Chintu Founder Labs",
        {"browser_profile": "Profile 1"},
    )

    assert result.success is True
    assert len(fake.opened) == 0
    assert (result.data or {}).get("manual_login_required") is True
    assert "same browser session" in result.message.lower()


def test_social_youtube_setup_uses_assistant_credentials_for_auto_login(monkeypatch):
    fake = _FakeController(
        open_url="https://accounts.google.com/signin/v2/identifier?service=youtube",
        title="Sign in - Google Accounts",
    )

    monkeypatch.setattr(
        "chintu_backend.automation.browser.browser_controller.get_browser_controller",
        lambda **kwargs: fake,
    )

    result = scc.handle_social_youtube_channel_setup(
        "Create YouTube channel named Chintu Founder Labs",
        {
            "browser_profile": "Profile 1",
            "assistant_google_email": "assistant@example.com",
            "assistant_google_password": "secret",
        },
    )

    assert result.success is True
    # Auto-login path should move past auth prompt flow.
    assert "complete sign-in" not in result.message.lower()


def test_youtube_state_machine_switch_account_path(monkeypatch):
    states = iter(
        [
            {
                "needs_auth": False,
                "is_feed_you": True,
                "has_switch_account": True,
                "has_view_all_channels": False,
                "has_create_entry": False,
                "has_name_field": False,
                "has_submit_create": False,
            },
            {
                "needs_auth": False,
                "is_feed_you": True,
                "has_switch_account": False,
                "has_view_all_channels": True,
                "has_create_entry": False,
                "has_name_field": False,
                "has_submit_create": False,
            },
            {
                "needs_auth": False,
                "is_feed_you": True,
                "has_switch_account": False,
                "has_view_all_channels": False,
                "has_create_entry": True,
                "has_name_field": False,
                "has_submit_create": False,
            },
            {
                "needs_auth": False,
                "is_feed_you": True,
                "has_switch_account": False,
                "has_view_all_channels": False,
                "has_create_entry": False,
                "has_name_field": True,
                "has_submit_create": True,
            },
        ]
    )
    clicked = []

    monkeypatch.setattr(scc, "_read_youtube_state", lambda controller: next(states))
    monkeypatch.setattr(
        scc,
        "_click_by_tokens",
        lambda controller, tokens: clicked.append(tokens[0]) or True,
    )

    result = scc._advance_to_channel_form(controller=object(), opened_urls=[])
    assert result["stage"] == "form_ready"
    assert clicked == ["Switch account", "View all channels", "Create a channel"]


def test_youtube_state_machine_detects_existing_channel(monkeypatch):
    monkeypatch.setattr(
        scc,
        "_read_youtube_state",
        lambda controller: {
            "needs_auth": False,
            "is_feed_you": True,
            "has_switch_account": False,
            "has_view_all_channels": False,
            "has_create_entry": False,
            "has_name_field": False,
            "has_submit_create": False,
            "has_customize_channel": True,
            "has_manage_videos": True,
        },
    )
    result = scc._advance_to_channel_form(controller=object(), opened_urls=[])
    assert result["stage"] == "existing_channel"


def test_youtube_state_machine_detects_auth_text_without_google_url(monkeypatch):
    monkeypatch.setattr(scc, "_read_current_page", lambda controller: {"url": "https://www.youtube.com/"})
    monkeypatch.setattr(
        scc,
        "_safe_page_text",
        lambda controller, max_length=9000: "Sign in\nEmail or phone\nTo continue to YouTube",
    )
    controller = object()
    state = scc._read_youtube_state(controller)
    assert state["needs_auth"] is True


def test_youtube_setup_manual_stage_does_not_fill_name(monkeypatch):
    fake = _FakeController(open_url="https://www.youtube.com/feed/you")
    called = {"fill": 0}

    monkeypatch.setattr(
        "chintu_backend.automation.browser.browser_controller.get_browser_controller",
        lambda **kwargs: fake,
    )
    monkeypatch.setattr(scc, "_advance_to_channel_form", lambda controller, opened_urls: {"stage": "manual_required", "state": {}})

    def _count_fill(controller, channel_name):
        called["fill"] += 1
        return True

    monkeypatch.setattr(scc, "_try_fill_channel_name", _count_fill)

    result = scc.handle_social_youtube_channel_setup(
        "Create YouTube channel named Chintu Founder Labs",
        {"browser_profile": "Profile 1"},
    )
    assert result.success is True
    assert called["fill"] == 0
    assert (result.data or {}).get("awaiting_user_action") is True
