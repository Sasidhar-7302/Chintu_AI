"""
Proactivity Manager: Orchestrates Signals, Rules, and UI Broadcasts.
"""

import logging
import asyncio
import threading
import time
from typing import Optional

from .signals import get_signal_manager
from .rules import get_rule_engine, Rule
from .default_rules import get_default_rules
from ..core.websocket_server import get_ws_server

logger = logging.getLogger(__name__)

class ProactivityManager:
    """
    Main controller for the Proactivity Engine.
    1. Starts SignalManager.
    2. Runs RuleEngine periodic evaluation.
    3. Broadcasts suggestions via WebSocket.
    """
    
    def __init__(self, evaluation_interval: float = 60.0):
        self.signal_manager = get_signal_manager()
        self.rule_engine = get_rule_engine()
        self.interval = evaluation_interval
        self._running = False
        self._stop_event = threading.Event()  # For interruptible sleep
        self._thread: Optional[threading.Thread] = None
        
        # Load default rules
        self._load_defaults()
        
    def _load_defaults(self):
        """Load default safe rules."""
        for rule in get_default_rules():
            self.rule_engine.add_rule(rule)
        logger.info(f"Loaded {len(self.rule_engine.rules)} proactive rules")
        
    def start(self):
        """Start the Proactivity Engine."""
        if self._running:
            return
            
        # Start signal collection
        self.signal_manager.start()
        
        # Start evaluation loop
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="ProactivityManager")
        self._thread.start()
        logger.info("ProactivityManager started")
        
    def stop(self):
        """Stop the Proactivity Engine."""
        self._running = False
        self._stop_event.set()  # Signal thread to wake up
        self.signal_manager.stop()
        if self._thread:
            self._thread.join(timeout=1.0)
        logger.info("ProactivityManager stopped")
        
    def _run_loop(self):
        """Main evaluation loop."""
        while self._running:
            try:
                self._evaluate_and_broadcast()
            except Exception as e:
                logger.error(f"Error in ProactivityManager loop: {e}")
            
            # Sleep for interval (default 60s)
            self._stop_event.wait(self.interval)  # Interruptible sleep
            
    def _evaluate_and_broadcast(self):
        """Evaluate rules and broadcast top suggestion."""
        suggestions = self.rule_engine.evaluate()
        if not suggestions:
            return
            
        # Get top priority suggestion
        top_suggestion = suggestions[0]
        
        logger.info(f"Proposing suggestion: {top_suggestion.text}")
        
        # Broadcast to UI (via WebSocket)
        ws_server = get_ws_server()
        if ws_server:
            # We need to call the async method from this sync thread
            loop = ws_server._loop
            if loop and loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    ws_server.broadcast_suggestion(
                        suggestion_text=top_suggestion.text,
                        rule_id=top_suggestion.rule_id,
                        priority=top_suggestion.priority
                    ),
                    loop
                )
        else:
            logger.warning("WebSocket server not available to broadcast suggestion")

# Singleton
_manager = None

def get_proactivity_manager():
    global _manager
    if _manager is None:
        _manager = ProactivityManager()
    return _manager
