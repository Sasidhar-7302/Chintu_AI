"""
Event Bus for Chintu AI.
Decouples components via publish-subscribe pattern.
"""
import asyncio
import logging
from typing import Dict, List, Any, Callable, Awaitable, Union, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)

class EventType(Enum):
    # System events
    SYSTEM_STARTUP = "system_startup"
    SYSTEM_SHUTDOWN = "system_shutdown"
    
    # Task/Scheduler events
    TASK_SCHEDULED = "task_scheduled"
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    
    # Message events
    MESSAGE_RECEIVED = "message_received"
    MESSAGE_SENT = "message_sent"
    
    # Node events
    NODE_CONNECTED = "node_connected"
    NODE_DISCONNECTED = "node_disconnected"


@dataclass
class Event:
    type: EventType
    source: str
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    id: str = field(default_factory=lambda: datetime.now().isoformat())


class EventBus:
    """Async event bus."""
    
    def __init__(self):
        self._subscribers: Dict[EventType, List[Callable[[Event], Awaitable[None]]]] = {}
        
    def subscribe(self, event_type: EventType, handler: Callable[[Event], Awaitable[None]]):
        """Subscribe to an event type."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)
        logger.debug(f"Subscribed to {event_type.value}")
        
    def unsubscribe(self, event_type: EventType, handler: Callable):
        """Unsubscribe handler."""
        if event_type in self._subscribers:
            try:
                self._subscribers[event_type].remove(handler)
            except ValueError:
                pass

    async def publish(self, event: Event):
        """Publish an event to all subscribers."""
        if event.type in self._subscribers:
            handlers = self._subscribers[event.type]
            if not handlers:
                return
                
            # Run all handlers concurrently
            tasks = [h(event) for h in handlers]
            await asyncio.gather(*tasks, return_exceptions=True)
            logger.debug(f"Published {event.type.value} to {len(handlers)} handlers")


# Global instance
_event_bus: Optional[EventBus] = None

def get_event_bus() -> EventBus:
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus
