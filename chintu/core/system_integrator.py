"""
System Integration Layer for Chintu AI Assistant.
Integrates all distributed computing, device registration, error reporting,
health monitoring, and logging systems with graceful degradation.
"""

import logging
import sys
from typing import Optional, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)


class SystemIntegrator:
    """
    Integrates all system components with graceful degradation.
    Ensures system works even if some components fail.
    """
    
    def __init__(self):
        self._initialized = False
        self._errors: list[str] = []
        
        # System components
        self.platform_detector = None
        self.device_registry = None
        self.error_reporter = None
        self.health_monitor = None
        self.distributed_state = None
        self.training_pipeline = None
        
        logger.info("System integrator created")
    
    def initialize(self) -> Dict[str, Any]:
        """
        Initialize all system components with graceful degradation.
        
        Returns:
            Dictionary with initialization status
        """
        status = {
            "platform": False,
            "device_registry": False,
            "error_reporter": False,
            "health_monitor": False,
            "distributed_state": False,
            "training_pipeline": False,
            "errors": [],
        }
        
        try:
            # 1. Platform Detection (always succeeds, degrades gracefully)
            try:
                from ..platform import get_platform
                self.platform_detector = get_platform()
                status["platform"] = True
                platform_value = getattr(self.platform_detector, "platform_type", None)
                if platform_value is not None:
                    logger.info(f"Platform detected: {platform_value.value}")
                else:
                    logger.info("Platform detected (type unavailable)")
            except Exception as e:
                error_msg = f"Platform detection failed: {e}"
                status["errors"].append(error_msg)
                logger.error(error_msg, exc_info=True)
            
            # 2. Error Reporter (critical - always initialize, degrades gracefully)
            try:
                from .error_reporter import get_error_reporter
                self.error_reporter = get_error_reporter()
                status["error_reporter"] = True
                logger.info("Error reporter initialized")
            except Exception as e:
                error_msg = f"Error reporter initialization failed: {e}"
                status["errors"].append(error_msg)
                logger.error(error_msg, exc_info=True)
                # Create minimal error reporter
                self.error_reporter = self._create_minimal_error_reporter()
            
            # 3. Device Registry (degrades gracefully - works locally if registration fails)
            try:
                from ..device.registration import get_device_registry
                self.device_registry = get_device_registry()
                
                # Auto-register current device
                try:
                    device = self.device_registry.auto_register_current_device()
                    logger.info(f"Auto-registered device: {device.name} ({device.device_id[:8]}...)")
                except Exception as e:
                    logger.warning(f"Auto-registration failed: {e} (continuing in local mode)")
                
                status["device_registry"] = True
            except Exception as e:
                error_msg = f"Device registry initialization failed: {e}"
                status["errors"].append(error_msg)
                if self.error_reporter:
                    self.error_reporter.report_error(
                        e,
                        component="system_integrator",
                        context={"step": "device_registry"},
                    )
                logger.warning(error_msg)
            
            # 4. Distributed State (degrades gracefully - works locally if sync fails)
            try:
                from ..distributed.state_sync import get_distributed_state
                self.distributed_state = get_distributed_state()
                
                # Set device ID if registry available
                if self.device_registry:
                    try:
                        devices = self.device_registry.get_all_devices()
                        if devices:
                            self.distributed_state.set_device_id(devices[0].device_id)
                    except Exception as e:
                        logger.warning(f"Failed to set device ID for state sync: {e}")
                
                status["distributed_state"] = True
                logger.info("Distributed state initialized")
            except Exception as e:
                error_msg = f"Distributed state initialization failed: {e}"
                status["errors"].append(error_msg)
                if self.error_reporter:
                    self.error_reporter.report_error(
                        e,
                        component="system_integrator",
                        context={"step": "distributed_state"},
                    )
                logger.warning(error_msg)
            
            # 5. Health Monitor (degrades gracefully - monitoring is optional)
            try:
                from .health_monitor import get_health_monitor
                self.health_monitor = get_health_monitor(check_interval=30.0)
                
                # Register error reporter callback
                if self.error_reporter:
                    self.health_monitor.register_callback(
                        lambda health: self._on_health_change(health)
                    )
                
                # Start monitoring
                try:
                    self.health_monitor.start_monitoring()
                    logger.info("Health monitoring started")
                except Exception as e:
                    logger.warning(f"Health monitoring start failed: {e} (monitoring disabled)")
                
                status["health_monitor"] = True
            except Exception as e:
                error_msg = f"Health monitor initialization failed: {e}"
                status["errors"].append(error_msg)
                if self.error_reporter:
                    self.error_reporter.report_error(
                        e,
                        component="system_integrator",
                        context={"step": "health_monitor"},
                    )
                logger.warning(error_msg)
            
            # 6. Training Pipeline (degrades gracefully - training is optional)
            try:
                from ..training.pipeline import get_training_pipeline
                self.training_pipeline = get_training_pipeline()
                status["training_pipeline"] = True
                logger.info("Training pipeline initialized")
            except Exception as e:
                error_msg = f"Training pipeline initialization failed: {e}"
                status["errors"].append(error_msg)
                if self.error_reporter:
                    self.error_reporter.report_error(
                        e,
                        component="system_integrator",
                        context={"step": "training_pipeline"},
                    )
                logger.warning(error_msg)
            
            # Setup UI/voice callbacks for error reporting
            self._setup_error_callbacks()
            
            self._initialized = True
            logger.info(f"System integrator initialized (errors: {len(status['errors'])})")
        
        except Exception as e:
            error_msg = f"System integrator initialization failed: {e}"
            status["errors"].append(error_msg)
            logger.critical(error_msg, exc_info=True)
        
        return status
    
    def _create_minimal_error_reporter(self):
        """Create minimal error reporter if full initialization fails."""
        class MinimalErrorReporter:
            def report_error(self, *args, **kwargs):
                logger.error(f"Error: {args}, {kwargs}")
        return MinimalErrorReporter()
    
    def _setup_error_callbacks(self):
        """Setup UI and voice callbacks for error reporting."""
        if not self.error_reporter:
            return
        
        # UI callback (send to WebSocket server if available)
        def ui_callback(report):
            try:
                from .events import EventType, Event, get_event_bus
                event_bus = get_event_bus()
                event_bus.publish_sync(Event(
                    type=EventType.ERROR,
                    data={
                        "error_id": report.error_id,
                        "severity": report.severity.value,
                        "message": report.user_message or report.message,
                        "component": report.component,
                    },
                    source="error_reporter",
                ))
            except Exception as e:
                logger.debug(f"UI error callback failed: {e}")
        
        # Voice callback (speak error via TTS if available)
        def voice_callback(report):
            try:
                # Only speak critical errors
                if report.severity.value == "critical":
                    message = report.user_message or "A critical error has occurred. Please check the logs."
                    # Try to speak via TTS (will degrade gracefully if not available)
                    try:
                        from ..audio.text_to_speech import TextToSpeech
                        tts = TextToSpeech()
                        if tts.is_available():
                            tts.speak_async(message)
                    except Exception:
                        pass  # TTS not available, degrade gracefully
            except Exception as e:
                logger.debug(f"Voice error callback failed: {e}")
        
        try:
            self.error_reporter.register_ui_callback(ui_callback)
            self.error_reporter.register_voice_callback(voice_callback)
            logger.debug("Error callbacks registered")
        except Exception as e:
            logger.warning(f"Failed to register error callbacks: {e}")
    
    def _on_health_change(self, health):
        """Handle health status change."""
        from .error_reporter import ErrorSeverity
        
        # Report unhealthy status as warning/error
        if health.status.value in ("unhealthy", "critical"):
            severity = ErrorSeverity.ERROR if health.status.value == "critical" else ErrorSeverity.WARNING
            if self.error_reporter:
                self.error_reporter.report_error(
                    Exception(health.message),
                    severity=severity,
                    component=health.component,
                    context=health.details,
                    user_message=f"{health.component.title()} is {health.status.value}. {health.message}",
                    notify_voice=(health.status.value == "critical"),
                )
    
    def get_status_message(self) -> str:
        """Get comprehensive system status message."""
        messages = ["=== Chintu System Status ===", ""]

        # Platform
        if self.platform_detector:
            messages.append(self.platform_detector.get_status_message())
        else:
            messages.append("[FAIL] Platform Detection: Failed")

        messages.append("")

        # Device Registry
        if self.device_registry:
            messages.append(self.device_registry.get_status_message())
        else:
            messages.append("[FAIL] Device Registry: Not Available")

        messages.append("")

        # Health Monitor
        if self.health_monitor:
            messages.append(self.health_monitor.get_status_message())
        else:
            messages.append("[WARN] Health Monitor: Not Available")

        messages.append("")

        # Error Summary
        if self.error_reporter:
            summary = self.error_reporter.get_error_summary()
            messages.append("Error Summary:")
            messages.append(f"  Total Errors: {summary['total_errors']}")
            messages.append(f"  Critical: {summary['by_severity']['critical']}")
            messages.append(f"  Errors: {summary['by_severity']['error']}")
            messages.append(f"  Warnings: {summary['by_severity']['warning']}")

        messages.append("")

        # Overall Status
        if self._initialized:
            messages.append("[OK] System Status: Initialized")
        else:
            messages.append("[WARN] System Status: Initialization Incomplete")

        return "\n".join(messages)
    
    def shutdown(self):
        """Shutdown all system components gracefully."""
        logger.info("Shutting down system integrator...")
        
        try:
            if self.health_monitor:
                self.health_monitor.stop_monitoring()
        except Exception as e:
            logger.warning(f"Error stopping health monitor: {e}")
        
        logger.info("System integrator shut down")


# Global system integrator instance
_system_integrator: Optional[SystemIntegrator] = None


def get_system_integrator() -> SystemIntegrator:
    """Get or create the global system integrator."""
    global _system_integrator
    if _system_integrator is None:
        _system_integrator = SystemIntegrator()
    return _system_integrator


