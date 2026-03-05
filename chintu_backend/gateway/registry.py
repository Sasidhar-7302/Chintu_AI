from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import time
import logging
from ..protocol.enums import Role

logger = logging.getLogger("NodeRegistry")

@dataclass
class NodeEntry:
    node_id: str
    role: Role
    capabilities: List[str]
    session_id: str
    websocket: Any 
    connected_at: float
    metadata: Dict[str, Any]

class NodeRegistry:
    """
    Manages the lifecycle and lookup of connected Gateway Nodes.
    """
    def __init__(self):
        self._nodes: Dict[str, NodeEntry] = {}  # node_id -> NodeEntry

    def register(self, node_id: str, role: Role, capabilities: List[str], session_id: str, websocket: Any, metadata: Dict = None) -> NodeEntry:
        entry = NodeEntry(
            node_id=node_id,
            role=role,
            capabilities=capabilities or [],
            session_id=session_id,
            websocket=websocket,
            connected_at=time.time(),
            metadata=metadata or {}
        )
        self._nodes[node_id] = entry
        logger.info(f"Registered Node: {node_id} ({role}) Caps: {len(entry.capabilities)}")
        return entry

    def unregister(self, node_id: str):
        if node_id in self._nodes:
            del self._nodes[node_id]
            logger.info(f"Unregistered Node: {node_id}")

    def get(self, node_id: str) -> Optional[NodeEntry]:
        return self._nodes.get(node_id)

    def find_by_role(self, role: Role) -> List[NodeEntry]:
        return [node for node in self._nodes.values() if node.role == role]
    
    def find_by_capability(self, capability: str) -> List[NodeEntry]:
        """Find all nodes that declare a specific capability."""
        return [node for node in self._nodes.values() if capability in node.capabilities]

    def all_nodes(self) -> List[NodeEntry]:
        return list(self._nodes.values())
