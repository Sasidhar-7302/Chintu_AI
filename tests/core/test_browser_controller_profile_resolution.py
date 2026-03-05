"""Tests for browser controller profile resolution/caching behavior."""

from types import SimpleNamespace

import chintu_backend.automation.browser.browser_controller as bc


def test_resolve_profile_prefers_explicit():
    assert bc._resolve_profile_name("Profile 7", headless=False) == "Profile 7"


def test_resolve_profile_interactive_uses_loggedin_profile(monkeypatch):
    monkeypatch.setattr(
        "chintu_backend.core.config.get_config",
        lambda: SimpleNamespace(
            browser_default_profile_enabled=True,
            research_browser_loggedin_profile="Profile 1",
            research_browser_default_profile="research",
        ),
    )
    assert bc._resolve_profile_name(None, headless=False) == "Profile 1"
    assert bc._resolve_profile_name(None, headless=True) is None


def test_get_browser_controller_uses_resolved_profile_cache(monkeypatch):
    created = []

    class _FakeController:
        def __init__(self, headless=True, profile_name=None):
            self.headless = headless
            self.profile_name = profile_name
            created.append((headless, profile_name))

    monkeypatch.setattr(
        "chintu_backend.core.config.get_config",
        lambda: SimpleNamespace(
            browser_default_profile_enabled=True,
            research_browser_loggedin_profile="Profile 1",
            research_browser_default_profile="research",
        ),
    )
    monkeypatch.setattr(bc, "BrowserController", _FakeController)
    bc._browser_controllers.clear()

    one = bc.get_browser_controller(headless=False, profile_name=None)
    two = bc.get_browser_controller(headless=False, profile_name=None)

    assert one is two
    assert created == [(False, "Profile 1")]


def test_get_open_browser_controller_prefers_exact(monkeypatch):
    class _FakeController:
        def __init__(self, headless=True, profile_name=None, is_open=False):
            self.headless = headless
            self.profile_name = profile_name
            self.is_open = is_open

    monkeypatch.setattr(
        "chintu_backend.core.config.get_config",
        lambda: SimpleNamespace(
            browser_default_profile_enabled=True,
            research_browser_loggedin_profile="Profile 1",
            research_browser_default_profile="research",
        ),
    )
    bc._browser_controllers.clear()
    bc._browser_controllers[("Profile 1", False)] = _FakeController(headless=False, profile_name="Profile 1", is_open=True)
    bc._browser_controllers[("Profile 2", False)] = _FakeController(headless=False, profile_name="Profile 2", is_open=True)

    chosen = bc.get_open_browser_controller(headless=False, profile_name=None)
    assert chosen is bc._browser_controllers[("Profile 1", False)]


def test_get_open_browser_controller_fallbacks_to_any_open(monkeypatch):
    class _FakeController:
        def __init__(self, headless=True, profile_name=None, is_open=False):
            self.headless = headless
            self.profile_name = profile_name
            self.is_open = is_open

    monkeypatch.setattr(
        "chintu_backend.core.config.get_config",
        lambda: SimpleNamespace(
            browser_default_profile_enabled=True,
            research_browser_loggedin_profile="Profile 1",
            research_browser_default_profile="research",
        ),
    )
    bc._browser_controllers.clear()
    bc._browser_controllers[("Profile 1", False)] = _FakeController(headless=False, profile_name="Profile 1", is_open=False)
    bc._browser_controllers[("Profile X", False)] = _FakeController(headless=False, profile_name="Profile X", is_open=True)

    chosen = bc.get_open_browser_controller(headless=False, profile_name=None)
    assert chosen is bc._browser_controllers[("Profile X", False)]
