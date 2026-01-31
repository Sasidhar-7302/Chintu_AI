
import pytest
import sys
from unittest.mock import patch, MagicMock
from pathlib import Path

# Add project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from chintu_backend.core.state import get_state_manager
from chintu_backend.core.capability_handlers import handle_open_app, handle_get_last_opened_app
from chintu_backend.vision.app_listing import handle_close_app

class TestStateAndApps:
    def setup_method(self):
        # Reset state
        get_state_manager()._state.last_opened_app = None

    @patch('chintu_backend.core.capability_handlers.webbrowser.open')
    def test_open_url_updates_state(self, mock_browser):
        # Test "open URL" path in handle_open_app
        handle_open_app("open example.com", {})
        state = get_state_manager().state
        # Should treat as URL/website since "example" is not an app
        # Logic: if not found as app, checks websites or URL
        # "example.com" -> looks like URL -> state set to target "example.com"
        assert state.last_opened_app == "example.com"

    def test_get_last_opened(self):
        get_state_manager().set_last_opened_app("TestApp")
        result = handle_get_last_opened_app("what did you open", {})
        assert result.success is True
        assert "TestApp" in result.message

    def test_get_last_opened_empty(self):
        result = handle_get_last_opened_app("what did you open", {})
        assert result.success is True
        assert "haven't opened" in result.message

    def test_close_app_by_name(self):
        # Mock pygetwindow
        mock_gw = MagicMock()
        mock_win = MagicMock()
        mock_win.title = "Notepad"
        mock_win.visible = True
        mock_gw.getWindowsWithTitle.return_value = [mock_win]
        
        with patch.dict(sys.modules, {'pygetwindow': mock_gw}):
            result = handle_close_app("close notepad", {})
            assert result.success is True
            # Output uses user query 'notepad' or target 'notepad'
            assert "notepad" in result.message.lower() 
            mock_win.close.assert_called_once()

    def test_close_last_opened(self):
        # Set state
        get_state_manager().set_last_opened_app("Calculator")
        
        # Mock pygetwindow
        mock_gw = MagicMock()
        mock_win = MagicMock()
        mock_win.title = "Calculator"
        mock_win.visible = True
        mock_gw.getWindowsWithTitle.return_value = [mock_win]

        with patch.dict(sys.modules, {'pygetwindow': mock_gw}):
            result = handle_close_app("close it", {})
            assert result.success is True
            assert "Calculator" in result.message
            mock_win.close.assert_called_once()
