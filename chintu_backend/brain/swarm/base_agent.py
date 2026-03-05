"""
Base Agent Interface for Chintu Swarm.
All specialized agents (Coder, Shopper, etc.) must inherit from this.
"""

import abc
import logging
import uuid
from typing import Dict, Any, Optional, List
from chintu_backend.brain.memory.hybrid_memory import get_hybrid_memory
from chintu_backend.brain.memory.agent_memory import AgentMemoryView
from chintu_backend.swarm.agent_runtime import AgentSessionStore

logger = logging.getLogger(__name__)

class AgentState:
    IDLE = "idle"
    PLANNING = "planning"
    EXECUTING = "executing"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"

class BaseAgent(abc.ABC):
    def __init__(self, name: str, description: str, runtime: Optional[object] = None):
        self.id = str(uuid.uuid4())
        self.name = name
        self.description = description
        self.state = AgentState.IDLE
        self.runtime = None
        self.workspace_dir = None
        self.session_dir = None
        self.state_dir = None
        self._raw_memory = get_hybrid_memory()
        self.memory = self._raw_memory
        self.context: Dict[str, Any] = {}
        if runtime is not None:
            self.attach_runtime(runtime)
        
    @abc.abstractmethod
    def run(self, goal: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Execute the agent's main workflow.
        Returns a result dictionary.
        """
        pass
    
    @abc.abstractmethod
    def stop(self):
        """
        Interrupt the agent's execution.
        """
        pass

    def attach_runtime(self, runtime: object) -> None:
        """Attach an agent runtime (workspace/session/policy) to this agent."""
        self.runtime = runtime
        # Pull standard attributes if available.
        for attr in ("workspace_dir", "session_dir", "state_dir"):
            if hasattr(runtime, attr):
                setattr(self, attr, getattr(runtime, attr))
        # Wrap memory view for per-agent isolation when possible.
        if self._raw_memory and hasattr(runtime, "agent_id"):
            try:
                self.memory = AgentMemoryView(self._raw_memory, runtime.agent_id)
            except Exception:
                self.memory = self._raw_memory

    def log_step(self, step: str, details: str = ""):
        """Log agent activity to memory and console."""
        msg = f"[{self.name}] {step}: {details}"
        logger.info(msg)
        # Store in shared memory for orchestration visibility
        try:
            self.memory.save_interaction(
                "system", 
                msg, 
                category="swarm_log", 
                source=self.name,
                meta={"agent_id": self.id, "state": self.state}
            )
        except Exception:
            pass
        if self.runtime and getattr(self.runtime, "session_dir", None):
            try:
                AgentSessionStore(self.runtime.session_dir).append_event(
                    {"event": "agent_log", "step": step, "details": details, "state": self.state}
                )
            except Exception:
                pass

    def update_state(self, new_state: str):
        self.state = new_state
        self.log_step("State Change", new_state)
