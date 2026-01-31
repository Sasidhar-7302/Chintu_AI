"""
Action Dispatcher.
Decouples execution logic from CommandHandler.
Responsible for finding and running clean capabilities via the Registry.
"""

import logging
from typing import Optional, Dict, Any
from .capabilities import CapabilityRegistry, ActionResult

logger = logging.getLogger(__name__)

class ActionDispatcher:
    """
    Dispatches parsed commands to the appropriate Capability.
    """

    def __init__(self, registry: CapabilityRegistry):
        self.registry = registry

    def dispatch(self, text: str, context: Dict[str, Any] = None) -> ActionResult:
        """
        Finds the best capability for the text and executes it.
        Returns ActionResult.
        """
        context = context or {}
        
        # 1. Match Capability
        capability = self.registry.match(text)
        if not capability:
            # No direct capability match found
            return ActionResult.fail("No matching capability found.")

        logger.info(f"Dispatching to capability: {capability.name}")

        # 2. Execute via Registry (handles Policy/Confirmation)
        result = self.registry.execute(capability, text, context)
        
        return result

    def get_pending_confirmation(self):
        return self.registry._pending_confirmation

    def confirm_pending(self):
        return self.registry.confirm_pending()

    def cancel_pending(self):
        return self.registry.cancel_pending()
