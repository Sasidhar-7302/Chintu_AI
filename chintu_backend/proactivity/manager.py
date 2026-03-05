"""
Proactivity Manager: Orchestrates Signals, Rules, and UI Broadcasts.
"""

import logging
import asyncio
import threading
import time
import os
from typing import Optional

from .signals import get_signal_manager
from .rules import get_rule_engine, Rule
from .default_rules import get_default_rules
from ..gateway.server import GatewayServer


def get_ws_server():
    """Compatibility accessor for WebSocket server (tests patch this)."""
    try:
        from ..core.websocket_server import get_ws_server as _get_ws_server

        return _get_ws_server()
    except Exception:
        return None

logger = logging.getLogger(__name__)

class ProactivityManager:
    """
    Main controller for the Proactivity Engine.
    Orchestrates the new Hive-based SignalBus and Observers.
    """
    
    def __init__(self, evaluation_interval: float = 60.0):
        # Legacy Rule Engine (Keep for compatibility)
        self.signal_manager = get_signal_manager()
        self.rule_engine = get_rule_engine()
        self.interval = evaluation_interval
        
        # New Hive Components
        from .signal_bus import get_signal_bus
        from .system_observer import SystemObserver
        from .project_observer import ProjectObserver
        from ..brain.swarm.agents.ambient_agent import AmbientAgent
        
        self.bus = get_signal_bus()
        self.system_observer = SystemObserver()
        # Default to current project root
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        self.project_observer = ProjectObserver(workspace_path=project_root)
        self.ambient_agent = AmbientAgent()
        
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # Bridge AmbientAgent to WebSocket
        self.ambient_agent.set_notification_callback(self._on_agent_suggestion)
        
        # Load default rules
        self._load_defaults()
        
    def _load_defaults(self):
        """Load default safe rules."""
        for rule in get_default_rules():
            self.rule_engine.add_rule(rule)
        logger.info(f"Loaded {len(self.rule_engine.rules)} proactive rules")
        
    def start(self):
        """Start the Proactivity Engine and Observers."""
        if self._running:
            return
            
        # 1. Start Legacy systems
        self.signal_manager.start()
        
        # 2. Start Hive Systems
        loop = None
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            asyncio.create_task(self.system_observer.start())
            asyncio.create_task(self.project_observer.start())
            self.ambient_agent.start()
        else:
            logger.warning("Event loop not running, Hive Observers will start in loop later.")
        
        # 3. Start evaluation loop for legacy rules
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="ProactivityManager")
        self._thread.start()
        logger.info("ProactivityManager started (Legacy + Hive components)")
        
    def stop(self):
        """Stop the Proactivity Engine."""
        self._running = False
        self._stop_event.set()
        self.signal_manager.stop()
        
        # Stop observers (best effort)
        loop = None
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            asyncio.create_task(self.system_observer.stop())
            asyncio.create_task(self.project_observer.stop())

        if self._thread:
            self._thread.join(timeout=1.0)
        logger.info("ProactivityManager stopped")
        
    async def _on_agent_suggestion(self, message: str, meta: Optional[dict] = None):
        """Handle suggestion from AmbientAgent."""
        logger.info(f"Agent Suggestion: {message}")
        self._broadcast_to_ui(
            text=message, 
            rule_id="agent_proactive", 
            priority=2, 
            needs_consent=True,
            metadata=meta
        )

    def _run_loop(self):
        """Main evaluation loop for legacy rules."""
        while self._running:
            try:
                self._evaluate_and_broadcast()
            except Exception as e:
                logger.error(f"Error in ProactivityManager loop: {e}")
            
            self._stop_event.wait(self.interval)
            
    def _evaluate_and_broadcast(self):
        """Evaluate rules and broadcast top suggestion."""
        suggestions = self.rule_engine.evaluate()
        if not suggestions:
            return
            
        top_suggestion = suggestions[0]
        # Legacy rules also need consent in the new security model
        self._broadcast_to_ui(
            text=top_suggestion.text, 
            rule_id=top_suggestion.rule_id, 
            priority=top_suggestion.priority,
            needs_consent=True
        )

    def _broadcast_to_ui(self, text: str, rule_id: str, priority: int, needs_consent: bool = True, metadata: dict = None):
        """Broadcast suggestion to UI via WebSocket/Gateway."""
        ws = get_ws_server()
        if ws:
            try:
                coro = ws.broadcast_suggestion(
                    suggestion_text=text,
                    rule_id=rule_id,
                    priority=priority,
                )
                loop = getattr(ws, "_loop", None)
                if loop and loop.is_running():
                    asyncio.run_coroutine_threadsafe(coro, loop)
                elif asyncio.iscoroutine(coro):
                    asyncio.run(coro)
                return
            except Exception as exc:
                logger.warning(f"WebSocket broadcast failed: {exc}")

        from ..gateway.server import get_gateway_server
        gateway = get_gateway_server()

        if gateway:
            suggestion_frame = {
                "type": "proactive_suggestion",
                "suggestion_id": f"sug_{int(time.time())}",
                "rule_id": rule_id,
                "text": text,
                "priority": priority,
                "needs_consent": needs_consent,
                "created_at": time.time(),
                "metadata": metadata or {},
            }
            try:
                coro = gateway.broadcast(suggestion_frame)
                if asyncio.iscoroutine(coro):
                    loop = None
                    try:
                        loop = asyncio.get_event_loop()
                    except RuntimeError:
                        loop = None
                    if loop and loop.is_running():
                        asyncio.run_coroutine_threadsafe(coro, loop)
                    else:
                        asyncio.run(coro)
                return
            except Exception as exc:
                logger.warning(f"Gateway broadcast failed: {exc}")
        else:
            logger.warning("Gateway Server not available to broadcast suggestion")

# Singleton
_manager = None

def get_proactivity_manager():
    global _manager
    if _manager is None:
        _manager = ProactivityManager()
    return _manager
