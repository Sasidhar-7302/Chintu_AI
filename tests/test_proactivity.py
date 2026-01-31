"""
Extensive Unit Tests for Proactivity Engine.
Tests SignalManager, RuleEngine, and overall ProactivityManager logic.

These tests are designed to be robust:
- If optional dependencies like ``psutil`` are missing, SignalManager
  degrades gracefully and certain tests are skipped instead of erroring.
"""

import threading
import time
import pytest
import concurrent.futures
from unittest.mock import MagicMock, patch

try:
    import psutil  # type: ignore
    _HAS_PSUTIL = True
except Exception:
    psutil = None  # type: ignore
    _HAS_PSUTIL = False

from chintu_backend.proactivity.signals import SignalManager, get_signal_manager
from chintu_backend.proactivity.rules import RuleEngine, Rule, get_rule_engine
from chintu_backend.proactivity.manager import ProactivityManager, get_proactivity_manager
from chintu_backend.core.websocket_server import WebSocketServer

# =============================================================================
# 1. Signal Manager Tests
# =============================================================================

@pytest.fixture
def signal_manager():
    """Create a fresh SignalManager for testing."""
    return SignalManager(interval=0.1)

def test_signal_manager_initialization(signal_manager):
    """Test that SignalManager initializes with empty signals."""
    assert signal_manager._signals == {}
    assert not signal_manager._running
    assert signal_manager._thread is None

@pytest.mark.skipif(not _HAS_PSUTIL, reason="psutil not installed; psutil-backed signals unavailable")
@patch("chintu_backend.proactivity.signals.psutil.sensors_battery")
@patch("chintu_backend.proactivity.signals.psutil.cpu_percent")
def test_signal_gathering(mock_cpu, mock_battery, signal_manager):
    """Test gathering of system signals."""
    # Mock system returns
    mock_battery.return_value = MagicMock(percent=85, power_plugged=True)
    mock_cpu.return_value = 15.5
    
    # Run one update manually
    signal_manager._update_signals()
    signals = signal_manager.get_signals()
    
    # Check values
    assert signals["battery_percent"] == 85
    assert signals["is_plugged_in"] is True
    assert signals["cpu_percent"] == 15.5
    assert "hour" in signals
    assert "is_weekday" in signals

def test_signal_manager_thread_lifecycle(signal_manager):
    """Test starting and stopping the background thread."""
    with patch.object(signal_manager, "_update_signals") as mock_update:
        signal_manager.start()
        assert signal_manager._running
        assert signal_manager._thread.is_alive()
        
        # Give it time to run a loop
        time.sleep(0.2)
        assert mock_update.call_count >= 1
        
        signal_manager.stop()
        assert not signal_manager._running
        assert not signal_manager._thread.is_alive()

# =============================================================================
# 2. Rule Engine Tests
# =============================================================================

@pytest.fixture
def rule_engine():
    """Create a fresh RuleEngine for testing."""
    engine = RuleEngine()
    # Mock the signal manager dependency
    patcher = patch("chintu_backend.proactivity.rules.get_signal_manager")
    mock_get_sm = patcher.start()
    mock_sm = MagicMock()
    mock_get_sm.return_value = mock_sm
    
    yield (engine, mock_sm)
    patcher.stop()

def test_rule_evaluation_logic(rule_engine):
    """Test that rules trigger correctly based on signals."""
    engine, mock_sm = rule_engine
    
    # Define a test rule
    mock_condition = MagicMock(return_value=True)
    rule = Rule(
        id="test_rule",
        name="Test Rule",
        condition=mock_condition,
        suggestion_text="Test Suggestion",
        priority=10
    )
    engine.add_rule(rule)
    
    # Set mock signals
    mock_sm.get_signals.return_value = {"cpu": 90}
    
    # Evaluate
    suggestions = engine.evaluate()
    
    # Assertions
    assert len(suggestions) == 1
    assert suggestions[0].text == "Test Suggestion"
    mock_condition.assert_called_once_with({"cpu": 90})

def test_rule_cooldown(rule_engine):
    """Test that rules respect the cooldown period."""
    engine, mock_sm = rule_engine
    
    # Rule with 1 hour cooldown
    rule = Rule(
        id="cooldown_rule",
        name="Cooldown Rule",
        condition=lambda s: True,
        suggestion_text="Cooldown",
        cooldown_seconds=3600
    )
    engine.add_rule(rule)
    mock_sm.get_signals.return_value = {}
    
    # First Trigger
    suggestions1 = engine.evaluate()
    assert len(suggestions1) == 1
    
    # Second Trigger (Immediate) - Should be blocked
    suggestions2 = engine.evaluate()
    assert len(suggestions2) == 0

def test_rule_priority_sorting(rule_engine):
    """Test that suggestions are sorted by priority."""
    engine, mock_sm = rule_engine
    
    rule_low = Rule(id="low", name="Low", condition=lambda s: True, suggestion_text="Low", priority=1)
    rule_high = Rule(id="high", name="High", condition=lambda s: True, suggestion_text="High", priority=10)
    
    # Manually adding simplified objects for brevity since dataclass structure is known
    # But using real class is safer:
    rule_low = Rule("low", "Low", lambda s: True, "Low", 1)
    rule_high = Rule("high", "High", lambda s: True, "High", 10)
    
    engine.add_rule(rule_low)
    engine.add_rule(rule_high)
    mock_sm.get_signals.return_value = {}
    
    suggestions = engine.evaluate()
    
    assert len(suggestions) == 2
    assert suggestions[0].rule_id == "high" # Highest first
    assert suggestions[1].rule_id == "low"

# =============================================================================
# 3. Default Rules Logic Tests
# =============================================================================

from chintu_backend.proactivity.default_rules import battery_low_condition, work_start_condition

def test_battery_condition():
    """Test battery low logic."""
    # Case 1: Battery Low & Unplugged -> True
    assert battery_low_condition({"battery_percent": 19, "is_plugged_in": False}) is True
    
    # Case 2: Battery Low but Plugged -> False
    assert battery_low_condition({"battery_percent": 10, "is_plugged_in": True}) is False
    
    # Case 3: Battery High -> False
    assert battery_low_condition({"battery_percent": 50, "is_plugged_in": False}) is False

def test_work_start_condition():
    """Test morning routine logic."""
    # Case 1: Weekday at 9:00 -> True
    assert work_start_condition({"is_weekday": True, "hour": 9, "minute": 0}) is True
    
    # Case 2: Weekend -> False
    assert work_start_condition({"is_weekday": False, "hour": 9, "minute": 0}) is False
    
    # Case 3: Wrong time -> False
    assert work_start_condition({"is_weekday": True, "hour": 10, "minute": 0}) is False

# =============================================================================
# 4. Integration Manager Tests
# =============================================================================

@pytest.fixture
def proactivity_manager():
    """Create a ProactivityManager with mocks."""
    with patch("chintu_backend.proactivity.manager.get_signal_manager") as mock_get_sm, \
         patch("chintu_backend.proactivity.manager.get_rule_engine") as mock_get_re, \
         patch("chintu_backend.proactivity.manager.get_ws_server") as mock_get_ws:
         
        mock_sm = MagicMock()
        mock_re = MagicMock()
        mock_ws = MagicMock()
        
        mock_get_sm.return_value = mock_sm
        mock_get_re.return_value = mock_re
        mock_get_ws.return_value = mock_ws
        
        manager = ProactivityManager(evaluation_interval=0.1)
        yield manager, mock_sm, mock_re, mock_ws

def test_manager_lifecycle(proactivity_manager):
    """Test start/stop sequence."""
    manager, mock_sm, _, _ = proactivity_manager
    
    with patch.object(manager, "_run_loop"):
        manager.start()
        assert manager._running
        mock_sm.start.assert_called_once()
        
        manager.stop()
        assert not manager._running
        mock_sm.stop.assert_called_once()

def test_manager_broadcast_logic(proactivity_manager):
    """Test that suggestions are broadcast via WebSocket."""
    manager, _, mock_re, mock_ws = proactivity_manager
    
    # Setup Engine to return a suggestion
    suggestion = MagicMock(text="Do this", rule_id="1", priority=5)
    mock_re.evaluate.return_value = [suggestion]
    
    # Setup Websocket Loop
    mock_ws._loop = MagicMock()
    mock_ws._loop.is_running.return_value = True
    
    # Run one cycle
    with patch("asyncio.run_coroutine_threadsafe") as mock_run_async:
        manager._evaluate_and_broadcast()
        
        # Verify broadcast
        mock_ws.broadcast_suggestion.assert_called_once_with(
            suggestion_text="Do this",
            rule_id="1",
            priority=5
        )
        mock_run_async.assert_called_once()
