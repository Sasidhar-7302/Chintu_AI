"""Routing state machine for command handling."""

from __future__ import annotations

from enum import Enum


class RoutingState(str, Enum):
    RECEIVED = "received"
    VALIDATED = "validated"
    PENDING_CONFIRM = "pending_confirm"
    EXECUTING = "executing"
    RESPONDED = "responded"
    ERROR = "error"


class RoutingStateMachine:
    def __init__(self):
        self.state = RoutingState.RECEIVED

    def transition(self, new_state: RoutingState) -> None:
        self.state = new_state
