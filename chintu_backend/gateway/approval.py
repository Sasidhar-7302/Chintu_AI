import uuid
import time
import logging
from typing import Dict, Any, Optional, Callable, Awaitable
from dataclasses import dataclass

logger = logging.getLogger("ApprovalManager")

@dataclass
class PendingRequest:
    request_id: str
    source_node: str
    action_type: str
    description: str
    payload: Dict[str, Any]
    created_at: float
    on_resolve: Callable[[bool], Awaitable[None]]

class ApprovalManager:
    """
    Manages the queue of actions waiting for user approval.
    """
    def __init__(self):
        self._pending: Dict[str, PendingRequest] = {} # request_id -> PendingRequest

    def create_request(self, source_node: str, action_type: str, description: str, payload: Dict[str, Any], on_resolve: Callable[[bool], Awaitable[None]]) -> str:
        request_id = str(uuid.uuid4())
        req = PendingRequest(
            request_id=request_id,
            source_node=source_node,
            action_type=action_type,
            description=description,
            payload=payload,
            created_at=time.time(),
            on_resolve=on_resolve
        )
        self._pending[request_id] = req
        logger.info(f"Created Approval Request [{request_id}] for {action_type}")
        return request_id

    async def resolve(self, request_id: str, approved: bool):
        if request_id not in self._pending:
            logger.warning(f"Attempted to resolve unknown request: {request_id}")
            return
        
        req = self._pending.pop(request_id)
        logger.info(f"Resolving Request [{request_id}]: {'APPROVED' if approved else 'DENIED'}")
        await req.on_resolve(approved)

    def get_pending_count(self) -> int:
        return len(self._pending)
