"""
Unit tests for Chintu Capability System.
Tests that all actions go through capability handlers, not LLM directly.
"""

import pytest
import sys
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from chintu_backend.core.capabilities import (
    Capability, CapabilityType, ActionResult, 
    CapabilityRegistry, get_registry
)
from chintu_backend.core.capability_handlers import (
    handle_open_app, handle_open_url, handle_system_info, 
    handle_note_taking, handle_conversation, register_core_capabilities
)


class TestActionResult:
    """Tests for ActionResult dataclass."""
    
    def test_ok_result(self):
        result = ActionResult.ok("Success!", {"key": "value"}, "test_cap")
        assert result.success is True
        assert result.message == "Success!"
        assert result.data == {"key": "value"}
        assert result.capability_name == "test_cap"
    
    def test_fail_result(self):
        result = ActionResult.fail("Failed!", "test_cap")
        assert result.success is False
        assert result.message == "Failed!"
        assert result.capability_name == "test_cap"
    
    def test_confirm_result(self):
        pending = lambda: ActionResult.ok("Confirmed!")
        result = ActionResult.confirm("Please confirm", pending, "test_cap")
        assert result.success is True
        assert result.requires_confirmation is True
        assert result.pending_action is not None


class TestCapabilityRegistry:
    """Tests for CapabilityRegistry."""
    
    def setup_method(self):
        """Reset registry for each test."""
        from chintu_backend.core.capabilities import _registry
        global _registry
        _registry = None
    
    def test_register_capability(self):
        registry = CapabilityRegistry()
        cap = Capability(
            name="test",
            triggers=["test", "testing"],
            handler=lambda t, c: ActionResult.ok("Test!"),
        )
        registry.register(cap)
        assert registry.get("test") is not None
    
    def test_match_capability(self):
        registry = CapabilityRegistry()
        cap = Capability(
            name="open_app",
            triggers=["open", "launch"],
            handler=lambda t, c: ActionResult.ok("Opening!"),
        )
        registry.register(cap)
        
        matched = registry.match("open chrome")
        assert matched is not None
        assert matched.name == "open_app"
    
    def test_no_match_returns_none(self):
        registry = CapabilityRegistry()
        cap = Capability(
            name="open_app",
            triggers=["open", "launch"],
            handler=lambda t, c: ActionResult.ok("Opening!"),
        )
        registry.register(cap)
        
        matched = registry.match("tell me a joke")
        assert matched is None  # Should route to LLM
    
    def test_confirmation_system(self):
        registry = CapabilityRegistry()
        
        def pending_handler():
            return ActionResult.ok("Action executed!")
        
        cap = Capability(
            name="delete",
            triggers=["delete"],
            handler=lambda t, c: ActionResult.confirm("Confirm?", pending_handler, "delete"),
            requires_confirmation=True,
        )
        registry.register(cap)
        
        # Execute - should return confirmation request
        result = registry.execute(cap, "delete my files", {})
        assert result.requires_confirmation is True
        assert registry.has_pending() is True
        
        # Confirm pending
        confirmed = registry.confirm_pending()
        assert confirmed is not None
        assert confirmed.message == "Confirm?"
        assert registry.has_pending() is True
        
        confirmed_again = registry.confirm_pending()
        assert confirmed_again is not None
        assert confirmed_again.message == "Action executed!"
        assert registry.has_pending() is False




class TestOpenAppCapability:
    """Tests for open_app capability."""
    
    @patch('chintu_backend.platform.app_discovery.subprocess.Popen')
    @patch('chintu_backend.platform.app_discovery.os.startfile', create=True)
    def test_open_chrome(self, mock_startfile, mock_popen):
        result = handle_open_app("open chrome", {})
        assert result.success is True
        assert "chrome" in result.message.lower()
        # Either popen or startfile called depending on discovery
        assert mock_popen.called or mock_startfile.called
    
    @patch('chintu_backend.platform.app_discovery.subprocess.Popen')
    @patch('chintu_backend.platform.app_discovery.os.startfile', create=True)
    def test_open_notepad(self, mock_startfile, mock_popen):
        result = handle_open_app("launch notepad", {})
        assert result.success is True
        assert "notepad" in result.message.lower()
        # Either popen or startfile called
        assert mock_popen.called or mock_startfile.called
    
    @patch('chintu_backend.core.capability_handlers.webbrowser.open')
    def test_unknown_app(self, mock_browser):
        result = handle_open_app("open foobar123", {})
        assert result.success is True  # Fails back to Google search
        assert result.data.get("fallback") is True
        mock_browser.assert_called_once()


class TestOpenUrlCapability:
    """Tests for open_url capability."""
    
    @patch('chintu_backend.core.capability_handlers.webbrowser.open')
    @patch('chintu_backend.core.capability_handlers.subprocess.Popen')
    @patch('chintu_backend.memory.preferences.get_preference_manager')
    def test_open_google(self, mock_prefs, mock_popen, mock_browser):
        prefs = SimpleNamespace(default_browser="chrome", confirmation_required=False)
        mock_prefs.return_value = SimpleNamespace(preferences=prefs, track_site_usage=lambda site: None)
        result = handle_open_url("go to google", {})
        assert result.success is True
        args, _kwargs = mock_popen.call_args
        assert args[0][0] == "chrome"
        assert args[0][1] == "https://www.google.com"
    
    @patch('chintu_backend.core.capability_handlers.webbrowser.open')
    @patch('chintu_backend.core.capability_handlers.subprocess.Popen')
    @patch('chintu_backend.memory.preferences.get_preference_manager')
    def test_open_youtube(self, mock_prefs, mock_popen, mock_browser):
        prefs = SimpleNamespace(default_browser="chrome", confirmation_required=False)
        mock_prefs.return_value = SimpleNamespace(preferences=prefs, track_site_usage=lambda site: None)
        result = handle_open_url("open youtube", {})
        assert result.success is True
        args, _kwargs = mock_popen.call_args
        assert args[0][0] == "chrome"
        assert args[0][1] == "https://www.youtube.com"


class TestSystemInfoCapability:
    """Tests for system_info capability."""
    
    def test_get_time(self):
        result = handle_system_info("what time is it", {})
        assert result.success is True
        assert "time" in result.message.lower()
    
    def test_get_date(self):
        result = handle_system_info("what's today's date", {})
        assert result.success is True
        assert any(word in result.message.lower() for word in ["today", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"])


class TestNoteTakingCapability:
    """Tests for note_taking capability."""
    
    def test_take_note(self):
        result = handle_note_taking("take a note: buy groceries", {})
        assert result.success is True
        assert "saved" in result.message.lower()
    
    def test_list_notes_empty(self):
        # Clear notes first
        handle_note_taking("clear notes", {})
        result = handle_note_taking("show my notes", {})
        assert result.success is True


class TestConversationCapability:
    """Tests for conversation (LLM routing) capability."""
    
    def test_routes_to_llm(self):
        result = handle_conversation("tell me a joke", {})
        assert result.success is True
        assert result.data.get("use_llm") is True


class TestCoreCapabilitiesRegistration:
    """Tests that all core capabilities are registered."""
    
    def setup_method(self):
        """Reset registry for each test."""
        from chintu_backend.core import capabilities
        capabilities._registry = None
    
    def test_all_capabilities_registered(self):
        register_core_capabilities()
        registry = get_registry()
        caps = registry.list_capabilities()
        
        cap_names = [c["name"] for c in caps]
        assert "open_app" in cap_names
        assert "open_url" in cap_names
        assert "system_info" in cap_names
        assert "note_taking" in cap_names
        assert "conversation" in cap_names
        

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
