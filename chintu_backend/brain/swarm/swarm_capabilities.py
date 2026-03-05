
"""
Swarm Capabilities: Entry points for the Intent System.
"""
import logging
from typing import Dict, Any
from chintu_backend.brain.swarm.orchestrator import SwarmOrchestrator
from chintu_backend.brain.swarm.agents.coder import AutonCoder
from chintu_backend.brain.swarm.agents.shopper import ShoppingAgent
from chintu_backend.brain.swarm.agents.task_master import TaskMaster
from chintu_backend.brain.swarm.agents.librarian import LibrarianAgent
from chintu_backend.brain.swarm.agents.ambient_agent import AmbientAgent

logger = logging.getLogger(__name__)

from chintu_backend.core.capabilities import ActionResult

def handle_swarm_task(goal: str, context: Dict[str, Any] = None) -> ActionResult:
    """
    Handler for complex reasoning/swarm tasks.
    Triggers the Swarm Orchestrator.
    """
    orchestrator = SwarmOrchestrator()
    
    # Register Workers
    orchestrator.register_agent(AutonCoder())
    orchestrator.register_agent(ShoppingAgent())
    orchestrator.register_agent(TaskMaster())
    orchestrator.register_agent(LibrarianAgent())
    orchestrator.register_agent(AmbientAgent())
    
    logger.info(f"Swarm activated for goal: {goal}")
    res = orchestrator.run(goal, context)
    
    if res.get("success"):
        return ActionResult.ok(
            f"Swarm complete. Plan executed: {len(res.get('results', []))} steps.",
            {"results": res.get("results"), "goal": goal},
            "autonomous_swarm"
        )
    return ActionResult.fail(f"Swarm failed: {res.get('error')}", "autonomous_swarm")

def register_swarm_capabilities():
    """Register Swarm capabilities with the central registry."""
    from chintu_backend.core.capabilities import get_registry, Capability, CapabilityType
    
    registry = get_registry()
    
    registry.register(Capability(
        name="autonomous_swarm",
        handler=handle_swarm_task,
        triggers=[
            "build an app", "create a python script", "plan a vacation",
            "research and code", "buy a gaming mouse", "find the best laptop",
            "manage my project", "build a website", "execute plan",
            "update skills", "search for latest tech", "proactive status"
        ],
        description="Complex goal execution using multi-agent swarm",
        capability_type=CapabilityType.AI_AGENT,
        examples=["Build an app", "Plan a trip"]
    ))

