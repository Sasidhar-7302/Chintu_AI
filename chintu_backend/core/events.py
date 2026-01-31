"""Event bus for inter-module communication."""

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from enum import Enum
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class EventType(Enum):
    """Types of events in the system."""
    # Wake Word Events
    WAKE_WORD_DETECTED = "wake_word_detected"
    
    # Speech Events
    SPEECH_START = "speech_start"
    SPEECH_END = "speech_end"
    TRANSCRIPT_READY = "transcript_ready"
    TRANSCRIPT_PARTIAL = "transcript_partial"
    PUSH_TO_TALK_START = "push_to_talk_start"
    PUSH_TO_TALK_STOP = "push_to_talk_stop"
    
    # Gesture Events
    GESTURE_DETECTED = "gesture_detected"
    HAND_DETECTED = "hand_detected"
    HAND_LOST = "hand_lost"
    
    # Command Events
    COMMAND_RECOGNIZED = "command_recognized"
    COMMAND_EXECUTED = "command_executed"
    COMMAND_FAILED = "command_failed"
    
    # LLM Events
    LLM_REQUEST = "llm_request"
    LLM_RESPONSE = "llm_response"
    LLM_STREAMING = "llm_streaming"
    
    # State Events
    STATE_CHANGED = "state_changed"
    
    # UI Events
    UI_CONNECTED = "ui_connected"
    UI_DISCONNECTED = "ui_disconnected"
    ERROR = "error"
    NOTIFICATION = "notification"

    # Wake Word Training
    WAKE_WORD_RECORD_REQUEST = "wake_word_record_request"
    WAKE_WORD_STATUS_REQUEST = "wake_word_status_request"
    WAKE_WORD_TRAIN_REQUEST = "wake_word_train_request"
    
    # Audio Level (for waveform)
    AUDIO_LEVEL = "audio_level"
    
    # Code Approval
    CODE_APPROVAL_RESPONSE = "code_approval_response"

    # A2UI (Agent-to-UI) actions
    A2UI_ACTION = "a2ui_action"


@dataclass
class Event:
    """Event data structure."""
    type: EventType
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    source: str = "system"


class EventBus:
    """Central event bus for async event handling."""
    
    def __init__(self):
        self._handlers: Dict[EventType, List[Callable]] = {}
        self._async_handlers: Dict[EventType, List[Callable]] = {}
        self._queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
    
    def subscribe(self, event_type: EventType, handler: Callable, is_async: bool = False):
        """Subscribe a handler to an event type."""
        if is_async:
            if event_type not in self._async_handlers:
                self._async_handlers[event_type] = []
            self._async_handlers[event_type].append(handler)
        else:
            if event_type not in self._handlers:
                self._handlers[event_type] = []
            self._handlers[event_type].append(handler)
        logger.debug(f"Subscribed handler to {event_type.value}")
    
    def unsubscribe(self, event_type: EventType, handler: Callable):
        """Unsubscribe a handler from an event type."""
        if event_type in self._handlers:
            self._handlers[event_type] = [h for h in self._handlers[event_type] if h != handler]
        if event_type in self._async_handlers:
            self._async_handlers[event_type] = [h for h in self._async_handlers[event_type] if h != handler]
    
    async def publish(self, event: Event):
        """Publish an event to all subscribers."""
        logger.debug(f"Publishing event: {event.type.value}")
        
        # Call sync handlers
        for handler in self._handlers.get(event.type, []):
            try:
                handler(event)
            except Exception as e:
                logger.error(f"Error in sync handler for {event.type.value}: {e}")
        
        # Call async handlers
        for handler in self._async_handlers.get(event.type, []):
            try:
                await handler(event)
            except Exception as e:
                logger.error(f"Error in async handler for {event.type.value}: {e}")
    
    def publish_sync(self, event: Event):
        """Publish an event synchronously (for use in threads)."""
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._queue.put_nowait, event)
        else:
            self._queue.put_nowait(event)
    
    async def process_queue(self):
        """Process events from the queue."""
        self._running = True
        self._loop = asyncio.get_running_loop()
        while self._running:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=0.1)
                await self.publish(event)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Error processing event queue: {e}")
    
    def stop(self):
        """Stop the event queue processor."""
        self._running = False


# Global event bus instance
_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Get or create the global event bus instance."""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus
