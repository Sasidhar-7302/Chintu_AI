import logging
import asyncio
from typing import Dict, Any

from chintu_backend.core.events import EventBus, EventType
from chintu_backend.core.state import StateManager
from chintu_backend.sdk.node import ChintuNode

logger = logging.getLogger("GatewayBridge")

class GatewayStateBridge:
    """
    Bridges internal Core events (EventBus) to the Gateway (via ChintuNode).
    Ensures the UI (connected to Gateway) gets all state updates.
    """
    def __init__(self, core_node: ChintuNode, event_bus: EventBus, state_manager: StateManager):
        self.node = core_node
        self.event_bus = event_bus
        self.state_manager = state_manager
        self._setup_listeners()

    def _setup_listeners(self):
        # 1. State Updates (Broad)
        self.event_bus.subscribe(EventType.STATE_CHANGED, self._on_state_changed)
        
        # 2. Transcript Updates (Live)
        self.event_bus.subscribe(EventType.TRANSCRIPT_READY, self._on_transcript)
        
        # 3. Audio Level (High Frequency - maybe throttle?)
        # Audio level is typically polled or pushed directly from App. 
        # For now, we rely on state_manager updates or pushed events.
        
        # 4. Assistant Response (Speech/Text)
        self.event_bus.subscribe(EventType.LLM_RESPONSE, self._on_response)

        # 5. Live Canvas updates
        self.event_bus.subscribe(EventType.CANVAS_UPDATE, self._on_canvas_update)

        # 6. Orchestrator updates (projects + approvals)
        self.event_bus.subscribe(EventType.ORCHESTRATOR_UPDATE, self._on_orchestrator_update)
        self.event_bus.subscribe(EventType.ORCHESTRATOR_REQUEST, self._on_orchestrator_request)
        self.event_bus.subscribe(EventType.ORCHESTRATOR_SNAPSHOT, self._on_orchestrator_snapshot)

        # 7. Run lifecycle (interactive runs + evidence timeline)
        self.event_bus.subscribe(EventType.RUN_UPDATE, self._on_run_update)
        self.event_bus.subscribe(EventType.RUN_SNAPSHOT, self._on_run_snapshot)

    def _on_state_changed(self, event):
        """Forward full state snapshot to Gateway."""
        # The UI expects "state_update" event
        state_data = event.data.get("state") or self.state_manager.to_dict()
        asyncio.create_task(self.node.emit("state_update", state_data))

    def _on_transcript(self, event):
        """Forward live transcription."""
        text = event.data.get("text")
        is_final = event.data.get("is_final", False)
        # UI expects separate "transcript" event or merged in state
        asyncio.create_task(self.node.emit("transcript", {
            "text": text,
            "is_final": is_final
        }))

    def _on_response(self, event):
        """Forward assistant response."""
        text = event.data.get("text")
        asyncio.create_task(self.node.emit("response", {
            "text": text
        }))

    def _on_canvas_update(self, event):
        """Forward live canvas updates to Gateway."""
        payload = event.data or {}
        asyncio.create_task(self.node.emit("canvas_update", payload))

    def _on_orchestrator_update(self, event):
        """Forward orchestrator state updates (project/step changes)."""
        payload = event.data or {}
        asyncio.create_task(self.node.emit("orchestrator_update", payload))

    def _on_orchestrator_request(self, event):
        """Forward orchestrator requests (approvals, missing inputs)."""
        payload = event.data or {}
        asyncio.create_task(self.node.emit("orchestrator_request", payload))

    def _on_orchestrator_snapshot(self, event):
        """Forward orchestrator snapshots (full current view)."""
        payload = event.data or {}
        asyncio.create_task(self.node.emit("orchestrator_snapshot", payload))

    def _on_run_update(self, event):
        """Forward run updates (status changes, step events, verification, evidence)."""
        payload = event.data or {}
        asyncio.create_task(self.node.emit("run_update", payload))

    def _on_run_snapshot(self, event):
        """Forward run snapshots (UI refresh)."""
        payload = event.data or {}
        asyncio.create_task(self.node.emit("run_snapshot", payload))

    def update_audio_level(self, level: float):
        """Call this manually or via callback to push audio levels."""
        # Throttle logic could go here if needed
        asyncio.create_task(self.node.emit("audio_level", {"level": level}))
