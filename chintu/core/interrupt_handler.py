"""
Central Interrupt Handler for Chintu AI Assistant.
Provides hard interrupt capability for barge-in and stop commands.
"""

import logging
import threading
from typing import Optional, Callable, List
from enum import Enum

logger = logging.getLogger(__name__)


class InterruptType(Enum):
    """Types of interrupts."""
    WAKE_WORD = "wake_word"      # User said wake word during TTS
    STOP_COMMAND = "stop"        # User said "stop", "cancel", etc.
    USER_INPUT = "user_input"    # Any user input during processing
    TIMEOUT = "timeout"          # Operation timed out


class InterruptHandler:
    """
    Central coordinator for hard interrupts.
    
    This singleton ensures that wake word detection and stop commands
    can immediately kill TTS, workflows, and other operations.
    """
    
    # Acoustic stop phrases - matched BEFORE any LLM/policy routing
    STOP_PHRASES = frozenset([
        "stop",
        "cancel", 
        "chintu stop",
        "shut up",
        "be quiet",
        "quiet",
        "enough",
        "stop talking",
        "stop it",
        "okay stop",
        "that's enough",
    ])
    
    def __init__(self):
        self._lock = threading.Lock()
        self._interrupt_event = threading.Event()
        self._tts_kill_callback: Optional[Callable[[], None]] = None
        self._workflow_kill_callbacks: List[Callable[[], None]] = []
        self._on_interrupt_callbacks: List[Callable[[InterruptType], None]] = []
        self._last_interrupt_type: Optional[InterruptType] = None
        
    def register_tts_kill(self, callback: Callable[[], None]):
        """Register the TTS kill function."""
        self._tts_kill_callback = callback
        logger.debug("TTS kill callback registered")
        
    def register_workflow_kill(self, callback: Callable[[], None]):
        """Register a workflow kill function."""
        self._workflow_kill_callbacks.append(callback)
        
    def register_on_interrupt(self, callback: Callable[[InterruptType], None]):
        """Register a callback to be notified on any interrupt."""
        self._on_interrupt_callbacks.append(callback)
        
    def trigger_interrupt(self, interrupt_type: InterruptType) -> bool:
        """
        Trigger a hard interrupt.
        
        This immediately:
        1. Sets the interrupt event
        2. Kills TTS playback
        3. Kills any registered workflows
        4. Notifies all listeners
        
        Returns True if interrupt was triggered, False if already interrupted.
        """
        with self._lock:
            if self._interrupt_event.is_set():
                logger.debug(f"Interrupt already active, skipping {interrupt_type}")
                return False
                
            self._interrupt_event.set()
            self._last_interrupt_type = interrupt_type
            logger.info(f"INTERRUPT triggered: {interrupt_type.value}")
        
        # Kill TTS immediately
        if self._tts_kill_callback:
            try:
                self._tts_kill_callback()
                logger.debug("TTS killed by interrupt")
            except Exception as e:
                logger.warning(f"Error killing TTS: {e}")
        
        # Kill workflows
        for callback in self._workflow_kill_callbacks:
            try:
                callback()
            except Exception as e:
                logger.warning(f"Error killing workflow: {e}")
        
        # Notify listeners
        for callback in self._on_interrupt_callbacks:
            try:
                callback(interrupt_type)
            except Exception as e:
                logger.warning(f"Error in interrupt callback: {e}")
                
        return True
    
    def clear_interrupt(self):
        """Clear the interrupt state to allow normal operation."""
        with self._lock:
            self._interrupt_event.clear()
            self._last_interrupt_type = None
            
    def is_interrupted(self) -> bool:
        """Check if an interrupt is currently active."""
        return self._interrupt_event.is_set()
    
    def wait_for_interrupt(self, timeout: Optional[float] = None) -> bool:
        """Wait for an interrupt event. Returns True if interrupted."""
        return self._interrupt_event.wait(timeout=timeout)
    
    @property
    def last_interrupt_type(self) -> Optional[InterruptType]:
        """Get the type of the last interrupt."""
        return self._last_interrupt_type
    
    def is_stop_phrase(self, text: str) -> bool:
        """
        Check if text contains a stop phrase.
        This is called BEFORE any LLM/policy routing.
        """
        if not text:
            return False
            
        text_lower = text.lower().strip()
        
        # Direct match
        if text_lower in self.STOP_PHRASES:
            return True
            
        # Starts with stop phrase
        for phrase in self.STOP_PHRASES:
            if text_lower.startswith(phrase + " ") or text_lower.startswith(phrase + ","):
                return True
                
        return False
    
    def handle_acoustic_stop(self, text: str) -> bool:
        """
        Handle acoustic stop command.
        
        If text is a stop phrase:
        1. Trigger interrupt
        2. Return True (caller should NOT process further)
        
        Returns True if stop was handled, False otherwise.
        """
        if self.is_stop_phrase(text):
            self.trigger_interrupt(InterruptType.STOP_COMMAND)
            logger.info(f"Acoustic stop handled: '{text}'")
            return True
        return False


# Singleton instance
_handler: Optional[InterruptHandler] = None


def get_interrupt_handler() -> InterruptHandler:
    """Get or create the global interrupt handler."""
    global _handler
    if _handler is None:
        _handler = InterruptHandler()
    return _handler
