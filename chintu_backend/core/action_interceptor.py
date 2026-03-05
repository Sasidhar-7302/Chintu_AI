"""
Action Interceptor for Human-in-the-Loop (HITL) workflows.
Intercepts high-risk actions and requests user approval from the gateway before proceeding.
"""

import asyncio
import logging
from typing import Dict, Any
from dataclasses import dataclass
from chintu_backend.core.events import get_event_bus, Event

logger = logging.getLogger(__name__)

@dataclass
class PendingAction:
    action_id: str
    action_type: str
    details: Dict[str, Any]
    approved: bool = False
    rejected: bool = False

class ActionInterceptor:
    def __init__(self):
        self.event_bus = get_event_bus()
        self.pending_actions: Dict[str, PendingAction] = {}
        
    async def request_approval(self, action_type: str, details: Dict[str, Any]) -> bool:
        """
        Request HITL approval for a specific action.
        Returns True if approved, False if rejected or timeout.
        """
        import uuid
        action_id = str(uuid.uuid4())
        
        pending = PendingAction(
            action_id=action_id,
            action_type=action_type,
            details=details
        )
        self.pending_actions[action_id] = pending
        
        # Publish request to the frontend/gateway
        approval_request = {
            "type": "action_approval",
            "action_id": action_id,
            "action_type": action_type,
            "details": details
        }
        
        logger.info(f"Requesting HITL approval for action: {action_id} ({action_type})")
        
        # Determine event type - assume string fallback works if Enum missing
        event_type = getattr(self.event_bus, 'EventType', None)
        evt_type_val = "action_approval_request"
        if event_type and hasattr(event_type, "ACTION_APPROVAL_REQUEST"):
             evt_type_val = event_type.ACTION_APPROVAL_REQUEST
             
        await self.event_bus.publish(Event(
            type=evt_type_val,
            data=approval_request
        ))
        
        # Wait for approval (5 mins timeout)
        timeout = 300 
        elapsed = 0
        while elapsed < timeout:
            if pending.approved:
                logger.info(f"Action {action_id} approved.")
                del self.pending_actions[action_id]
                return True
            if pending.rejected:
                logger.warning(f"Action {action_id} rejected.")
                del self.pending_actions[action_id]
                return False
            
            await asyncio.sleep(1)
            elapsed += 1
            
        logger.error(f"Action {action_id} timed out waiting for approval.")
        del self.pending_actions[action_id]
        return False
        
    def resolve_action(self, action_id: str, approved: bool):
        """Called by the gateway to resolve a pending action."""
        if action_id in self.pending_actions:
            if approved:
                self.pending_actions[action_id].approved = True
            else:
                self.pending_actions[action_id].rejected = True
            return True
        return False

# Singleton
_interceptor = None

def get_action_interceptor() -> ActionInterceptor:
    global _interceptor
    if _interceptor is None:
        _interceptor = ActionInterceptor()
    return _interceptor
