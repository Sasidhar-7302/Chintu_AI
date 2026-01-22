"""
Health Monitoring System for Chintu AI Assistant.
Monitors system health and reports issues via UI/voice/logs.
"""

import logging
import time
import threading
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """Health status levels."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    CRITICAL = "critical"


@dataclass
class HealthCheck:
    """Health check result."""
    component: str
    status: HealthStatus
    message: str
    timestamp: str
    details: Dict[str, Any] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "component": self.component,
            "status": self.status.value,
            "message": self.message,
            "timestamp": self.timestamp,
            "details": self.details or {},
        }


class HealthMonitor:
    """
    System health monitor with graceful degradation.
    Monitors components and reports issues via UI/voice/logs.
    """
    
    def __init__(self, check_interval: float = 30.0):
        self.check_interval = check_interval
        self._health_checks: Dict[str, HealthCheck] = {}
        self._callbacks: List[Callable[[HealthCheck], None]] = []
        self._monitoring = False
        self._monitor_thread: Optional[threading.Thread] = None
        
        # Component health thresholds
        self._thresholds = {
            "audio": {"unhealthy": 3, "critical": 5},  # Failed checks
            "llm": {"unhealthy": 2, "critical": 4},
            "memory": {"unhealthy": 1, "critical": 2},
        }
        
        logger.info(f"Health monitor initialized (check interval: {check_interval}s)")
    
    def start_monitoring(self):
        """Start health monitoring thread."""
        if self._monitoring:
            logger.warning("Health monitoring already started")
            return
        
        self._monitoring = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        logger.info("Health monitoring started")
    
    def stop_monitoring(self):
        """Stop health monitoring thread."""
        self._monitoring = False
        self._stop_event.set()  # Signal thread to wake up
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5.0)
        logger.info("Health monitoring stopped")
    
    def _monitor_loop(self):
        """Main monitoring loop."""
        consecutive_failures: Dict[str, int] = {}
        
        while self._monitoring:
            try:
                # Check audio
                audio_health = self._check_audio()
                self._update_health("audio", audio_health, consecutive_failures)
                
                # Check LLM
                llm_health = self._check_llm()
                self._update_health("llm", llm_health, consecutive_failures)
                
                # Check memory
                memory_health = self._check_memory()
                self._update_health("memory", memory_health, consecutive_failures)
                
                # Sleep until next check
                self._stop_event.wait(self.check_interval)  # Interruptible sleep
            
            except Exception as e:
                logger.error(f"Error in health monitor loop: {e}", exc_info=True)
                self._stop_event.wait(self.check_interval)  # Still sleep to avoid tight loop
    
    def _update_health(
        self,
        component: str,
        health: HealthCheck,
        consecutive_failures: Dict[str, int]
    ):
        """Update health check and notify if status changed."""
        old_health = self._health_checks.get(component)
        
        # Track consecutive failures
        if health.status != HealthStatus.HEALTHY:
            consecutive_failures[component] = consecutive_failures.get(component, 0) + 1
            
            # Escalate if too many failures
            threshold = self._thresholds.get(component, {"unhealthy": 3, "critical": 5})
            if consecutive_failures[component] >= threshold["critical"]:
                health.status = HealthStatus.CRITICAL
            elif consecutive_failures[component] >= threshold["unhealthy"]:
                health.status = HealthStatus.UNHEALTHY
        else:
            consecutive_failures[component] = 0
        
        # Update health check
        self._health_checks[component] = health
        
        # Notify if status changed
        if old_health is None or old_health.status != health.status:
            self._notify_health_change(health)
    
    def _notify_health_change(self, health: HealthCheck):
        """Notify about health status change."""
        logger.info(f"Health status change: {health.component} -> {health.status.value}: {health.message}")
        
        # Notify callbacks
        for callback in self._callbacks:
            try:
                callback(health)
            except Exception as e:
                logger.warning(f"Error in health callback: {e}")
    
    def _check_audio(self) -> HealthCheck:
        """Check audio component health."""
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            
            if not devices:
                return HealthCheck(
                    component="audio",
                    status=HealthStatus.UNHEALTHY,
                    message="No audio devices found",
                    timestamp=datetime.now().isoformat(),
                    details={"device_count": 0},
                )
            
            # Check if default input device is available
            default_input = sd.default.device[0]
            if default_input is None:
                return HealthCheck(
                    component="audio",
                    status=HealthStatus.DEGRADED,
                    message="No default input device",
                    timestamp=datetime.now().isoformat(),
                    details={"device_count": len(devices)},
                )
            
            return HealthCheck(
                component="audio",
                status=HealthStatus.HEALTHY,
                message="Audio devices available",
                timestamp=datetime.now().isoformat(),
                details={"device_count": len(devices), "default_input": default_input},
            )
        
        except ImportError:
            return HealthCheck(
                component="audio",
                status=HealthStatus.DEGRADED,
                message="sounddevice not installed",
                timestamp=datetime.now().isoformat(),
            )
        except Exception as e:
            return HealthCheck(
                component="audio",
                status=HealthStatus.UNHEALTHY,
                message=f"Audio check failed: {e}",
                timestamp=datetime.now().isoformat(),
                details={"error": str(e)},
            )
    
    def _check_llm(self) -> HealthCheck:
        """Check LLM component health."""
        try:
            # Try to connect to Ollama
            import requests
            from ..core.config import Config
            
            config = Config()
            response = requests.get(f"{config.ollama_host}/api/tags", timeout=2.0)
            
            if response.status_code == 200:
                return HealthCheck(
                    component="llm",
                    status=HealthStatus.HEALTHY,
                    message="Ollama is available",
                    timestamp=datetime.now().isoformat(),
                    details={"ollama_host": config.ollama_host},
                )
            else:
                return HealthCheck(
                    component="llm",
                    status=HealthStatus.UNHEALTHY,
                    message=f"Ollama returned status {response.status_code}",
                    timestamp=datetime.now().isoformat(),
                )
        
        except ImportError:
            return HealthCheck(
                component="llm",
                status=HealthStatus.DEGRADED,
                message="requests not installed",
                timestamp=datetime.now().isoformat(),
            )
        except Exception as e:
            return HealthCheck(
                component="llm",
                status=HealthStatus.DEGRADED,
                message=f"Ollama check failed: {e}",
                timestamp=datetime.now().isoformat(),
                details={"error": str(e)},
            )
    
    def _check_memory(self) -> HealthCheck:
        """Check memory component health."""
        try:
            import psutil
            
            memory = psutil.virtual_memory()
            available_gb = memory.available / (1024 ** 3)
            
            if available_gb < 1.0:
                return HealthCheck(
                    component="memory",
                    status=HealthStatus.CRITICAL,
                    message=f"Low memory: {available_gb:.1f}GB available",
                    timestamp=datetime.now().isoformat(),
                    details={"available_gb": available_gb, "percent": memory.percent},
                )
            elif available_gb < 2.0:
                return HealthCheck(
                    component="memory",
                    status=HealthStatus.UNHEALTHY,
                    message=f"Low memory: {available_gb:.1f}GB available",
                    timestamp=datetime.now().isoformat(),
                    details={"available_gb": available_gb, "percent": memory.percent},
                )
            else:
                return HealthCheck(
                    component="memory",
                    status=HealthStatus.HEALTHY,
                    message=f"Memory available: {available_gb:.1f}GB",
                    timestamp=datetime.now().isoformat(),
                    details={"available_gb": available_gb, "percent": memory.percent},
                )
        
        except ImportError:
            return HealthCheck(
                component="memory",
                status=HealthStatus.HEALTHY,  # Assume healthy if psutil not available
                message="Memory check unavailable (psutil not installed)",
                timestamp=datetime.now().isoformat(),
            )
        except Exception as e:
            return HealthCheck(
                component="memory",
                status=HealthStatus.DEGRADED,
                message=f"Memory check failed: {e}",
                timestamp=datetime.now().isoformat(),
                details={"error": str(e)},
            )
    
    def register_callback(self, callback: Callable[[HealthCheck], None]):
        """Register callback for health status changes."""
        self._callbacks.append(callback)
        logger.debug("Registered health monitor callback")
    
    def get_health_status(self, component: Optional[str] = None) -> Dict[str, Any]:
        """Get health status for component or all components."""
        if component:
            health = self._health_checks.get(component)
            if health:
                return health.to_dict()
            return {"component": component, "status": "unknown"}
        
        # Return all health checks
        return {
            component: health.to_dict()
            for component, health in self._health_checks.items()
        }
    
    def get_overall_status(self) -> HealthStatus:
        """Get overall system health status."""
        if not self._health_checks:
            return HealthStatus.HEALTHY  # Assume healthy if no checks yet
        
        statuses = [health.status for health in self._health_checks.values()]
        
        if HealthStatus.CRITICAL in statuses:
            return HealthStatus.CRITICAL
        elif HealthStatus.UNHEALTHY in statuses:
            return HealthStatus.UNHEALTHY
        elif HealthStatus.DEGRADED in statuses:
            return HealthStatus.DEGRADED
        else:
            return HealthStatus.HEALTHY
    
    def get_status_message(self) -> str:
        """Get human-readable status message."""
        overall = self.get_overall_status()
        messages = [f"System Health: {overall.value.title()}"]

        status_labels = {
            HealthStatus.HEALTHY: "[OK]",
            HealthStatus.DEGRADED: "[WARN]",
            HealthStatus.UNHEALTHY: "[FAIL]",
            HealthStatus.CRITICAL: "[CRIT]",
        }

        for component, health in self._health_checks.items():
            label = status_labels.get(health.status, "[INFO]")
            messages.append(
                f"  {label} {component.title()}: {health.status.value} - {health.message}"
            )

        return "\n".join(messages)


# Global health monitor instance
_health_monitor: Optional[HealthMonitor] = None


def get_health_monitor(check_interval: float = 30.0) -> HealthMonitor:
    """Get or create the global health monitor."""
    global _health_monitor
    if _health_monitor is None:
        _health_monitor = HealthMonitor(check_interval=check_interval)
    return _health_monitor


