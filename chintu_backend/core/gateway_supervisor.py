"""
Gateway Supervisor - Production-grade gateway lifecycle management.

Features:
- Daemon lifecycle (start/stop/restart)
- Windows service installation
- Health checks and auto-restart
- Graceful shutdown with state preservation
"""

import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field
from enum import Enum
import threading

from chintu_backend.core.config import get_config

logger = logging.getLogger(__name__)


class DaemonStatus(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    RESTARTING = "restarting"
    FAILED = "failed"


@dataclass
class HealthReport:
    """Health check report."""
    healthy: bool
    timestamp: datetime = field(default_factory=datetime.now)
    checks: Dict[str, bool] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    uptime_seconds: float = 0
    memory_mb: float = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "healthy": self.healthy,
            "timestamp": self.timestamp.isoformat(),
            "checks": self.checks,
            "errors": self.errors,
            "uptime_seconds": self.uptime_seconds,
            "memory_mb": self.memory_mb
        }


@dataclass
class DaemonState:
    """Persisted daemon state."""
    status: DaemonStatus
    pid: Optional[int] = None
    started_at: Optional[datetime] = None
    last_health_check: Optional[datetime] = None
    restart_count: int = 0
    last_error: Optional[str] = None


class GatewaySupervisor:
    """
    Manages gateway lifecycle with production-grade features.
    
    - Start/stop/restart as daemon
    - Auto-restart on failure
    - Health checks
    - Windows service installation
    - Graceful shutdown
    """
    
    def __init__(self):
        self.config = get_config()
        self.data_dir = self.config.data_dir
        
        self.state_file = self.data_dir / "gateway_state.json"
        self.pid_file = self.data_dir / "gateway.pid"
        self.log_file = self.data_dir / "logs" / "gateway.log"
        
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        
        self._state = self._load_state()
        self._shutdown_event = threading.Event()
        self._health_check_interval = 30  # seconds
        self._max_restart_attempts = 5
        self._restart_delay = 5  # seconds
    
    # --- Service Installation (Windows) ---
    
    def install_service(self, service_name: str = "ChintuGateway") -> Dict[str, Any]:
        """
        Install as Windows service using NSSM or native sc.exe.
        
        Args:
            service_name: Name for the Windows service
            
        Returns:
            Installation result
        """
        if sys.platform != "win32":
            return {"success": False, "error": "Service installation only supported on Windows"}
        
        # Get Python executable and script paths
        python_exe = sys.executable
        gateway_script = Path(__file__).parent / "gateway.py"
        
        if not gateway_script.exists():
            # Try to find it
            gateway_script = Path(__file__).parent.parent / "gateway.py"
        
        try:
            # Try using NSSM (Non-Sucking Service Manager) if available
            nssm_result = subprocess.run(
                ["where", "nssm"],
                capture_output=True,
                text=True
            )
            
            if nssm_result.returncode == 0:
                # Use NSSM
                subprocess.run([
                    "nssm", "install", service_name,
                    python_exe, "-m", "chintu_backend.core.gateway"
                ], check=True)
                
                subprocess.run([
                    "nssm", "set", service_name, "AppDirectory",
                    str(self.data_dir)
                ], check=True)
                
                logger.info(f"Service installed with NSSM: {service_name}")
                return {
                    "success": True,
                    "method": "nssm",
                    "service_name": service_name
                }
            else:
                # Fallback to sc.exe (requires elevated permissions)
                cmd = f'"{python_exe}" -m chintu_backend.core.gateway'
                
                result = subprocess.run([
                    "sc", "create", service_name,
                    f"binPath={cmd}",
                    "start=auto"
                ], capture_output=True, text=True)
                
                if result.returncode == 0:
                    logger.info(f"Service installed with sc.exe: {service_name}")
                    
                    # Configure auto-restart on failure
                    subprocess.run([
                        "sc", "failure", service_name,
                        "reset=", "86400",
                        "actions=", "restart/1000/restart/5000/restart/60000"
                    ], capture_output=True)
                    
                    return {
                        "success": True,
                        "method": "sc.exe",
                        "service_name": service_name
                    }
                else:
                    return {
                        "success": False,
                        "error": result.stderr or "Failed to install service (need admin rights?)"
                    }
                    
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def uninstall_service(self, service_name: str = "ChintuGateway") -> Dict[str, Any]:
        """Uninstall Windows service."""
        if sys.platform != "win32":
            return {"success": False, "error": "Windows only"}
        
        try:
            # Stop first
            subprocess.run(["sc", "stop", service_name], capture_output=True)
            
            # Delete
            result = subprocess.run(
                ["sc", "delete", service_name],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                return {"success": True}
            else:
                return {"success": False, "error": result.stderr}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # --- Daemon Lifecycle ---
    
    def start_daemon(self, blocking: bool = False) -> Dict[str, Any]:
        """
        Start gateway as a daemon process.
        
        Args:
            blocking: If True, run in foreground (for debugging)
            
        Returns:
            Start result with PID
        """
        if self._is_running():
            return {
                "success": False,
                "error": "Gateway is already running",
                "pid": self._state.pid
            }
        
        self._state.status = DaemonStatus.STARTING
        self._save_state()
        
        if blocking:
            return self._run_foreground()
        
        try:
            # Start as subprocess
            python_exe = sys.executable
            
            if sys.platform == "win32":
                # Windows: use CREATE_NEW_PROCESS_GROUP
                process = subprocess.Popen(
                    [python_exe, "-m", "chintu_backend.core.gateway"],
                    stdout=open(self.log_file, "a"),
                    stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
                )
            else:
                # Unix: daemonize
                process = subprocess.Popen(
                    [python_exe, "-m", "chintu_backend.core.gateway"],
                    stdout=open(self.log_file, "a"),
                    stderr=subprocess.STDOUT,
                    start_new_session=True
                )
            
            # Write PID
            self.pid_file.write_text(str(process.pid))
            
            # Update state
            self._state.pid = process.pid
            self._state.status = DaemonStatus.RUNNING
            self._state.started_at = datetime.now()
            self._state.restart_count = 0
            self._save_state()
            
            logger.info(f"Gateway daemon started with PID: {process.pid}")
            
            return {
                "success": True,
                "pid": process.pid,
                "log_file": str(self.log_file)
            }
            
        except Exception as e:
            self._state.status = DaemonStatus.FAILED
            self._state.last_error = str(e)
            self._save_state()
            return {"success": False, "error": str(e)}
    
    def stop_daemon(self, graceful: bool = True) -> Dict[str, Any]:
        """
        Stop the gateway daemon.
        
        Args:
            graceful: If True, send SIGTERM and wait; else SIGKILL
            
        Returns:
            Stop result
        """
        if not self._is_running():
            return {"success": True, "message": "Gateway is not running"}
        
        self._state.status = DaemonStatus.STOPPING
        self._save_state()
        
        pid = self._state.pid
        
        try:
            if sys.platform == "win32":
                if graceful:
                    # Send CTRL_BREAK_EVENT
                    os.kill(pid, signal.CTRL_BREAK_EVENT)
                    time.sleep(5)
                
                # Force terminate
                subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
            else:
                os.kill(pid, signal.SIGTERM if graceful else signal.SIGKILL)
                if graceful:
                    time.sleep(5)
            
            # Clean up
            if self.pid_file.exists():
                self.pid_file.unlink()
            
            self._state.status = DaemonStatus.STOPPED
            self._state.pid = None
            self._save_state()
            
            logger.info(f"Gateway stopped (PID: {pid})")
            return {"success": True, "pid": pid}
            
        except ProcessLookupError:
            # Already dead
            self._state.status = DaemonStatus.STOPPED
            self._state.pid = None
            self._save_state()
            return {"success": True, "message": "Process already terminated"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def restart_daemon(self) -> Dict[str, Any]:
        """Restart the gateway daemon."""
        self._state.status = DaemonStatus.RESTARTING
        self._save_state()
        
        stop_result = self.stop_daemon(graceful=True)
        if not stop_result.get("success", False):
            return stop_result
        
        time.sleep(2)
        return self.start_daemon()
    
    def status(self) -> Dict[str, Any]:
        """Get current gateway status."""
        is_running = self._is_running()
        
        result = {
            "status": self._state.status.value if is_running else DaemonStatus.STOPPED.value,
            "pid": self._state.pid if is_running else None,
            "started_at": self._state.started_at.isoformat() if self._state.started_at else None,
            "restart_count": self._state.restart_count,
        }
        
        if is_running and self._state.started_at:
            result["uptime"] = str(datetime.now() - self._state.started_at)
        
        return result
    
    # --- Health Checks ---
    
    def health_check(self) -> HealthReport:
        """Perform comprehensive health check."""
        checks = {}
        errors = []
        
        # Check if process is running
        checks["process_running"] = self._is_running()
        if not checks["process_running"]:
            errors.append("Gateway process is not running")
        
        # Check LLM availability
        checks["llm_available"] = self._check_llm()
        if not checks["llm_available"]:
            errors.append("LLM service is not responding")
        
        # Check memory usage
        memory_mb = 0
        if self._state.pid:
            try:
                import psutil
                process = psutil.Process(self._state.pid)
                memory_mb = process.memory_info().rss / (1024 * 1024)
                checks["memory_ok"] = memory_mb < 2000  # < 2GB
                if not checks["memory_ok"]:
                    errors.append(f"High memory usage: {memory_mb:.0f}MB")
            except ImportError:
                checks["memory_ok"] = True  # Can't check without psutil
            except Exception:
                checks["memory_ok"] = True
        
        # Check disk space
        try:
            import shutil
            total, used, free = shutil.disk_usage(self.data_dir)
            free_gb = free / (1024**3)
            checks["disk_ok"] = free_gb > 1  # > 1GB free
            if not checks["disk_ok"]:
                errors.append(f"Low disk space: {free_gb:.1f}GB free")
        except Exception:
            checks["disk_ok"] = True
        
        # Calculate uptime
        uptime = 0
        if self._state.started_at:
            uptime = (datetime.now() - self._state.started_at).total_seconds()
        
        healthy = all(checks.values())
        
        report = HealthReport(
            healthy=healthy,
            checks=checks,
            errors=errors,
            uptime_seconds=uptime,
            memory_mb=memory_mb
        )
        
        self._state.last_health_check = datetime.now()
        self._save_state()
        
        return report
    
    def _check_llm(self) -> bool:
        """Check if LLM service is available."""
        try:
            import requests
            ollama_host = getattr(self.config, 'ollama_host', 'http://localhost:11434')
            response = requests.get(f"{ollama_host}/api/tags", timeout=5)
            return response.status_code == 200
        except Exception:
            return False
    
    # --- Auto-restart ---
    
    def start_watchdog(self):
        """Start background health check and auto-restart."""
        def watchdog_loop():
            while not self._shutdown_event.is_set():
                time.sleep(self._health_check_interval)
                
                if not self._is_running() and self._state.status == DaemonStatus.RUNNING:
                    logger.warning("Gateway crashed, attempting restart")
                    
                    if self._state.restart_count < self._max_restart_attempts:
                        self._state.restart_count += 1
                        self._save_state()
                        
                        time.sleep(self._restart_delay)
                        self.start_daemon()
                    else:
                        logger.error("Max restart attempts reached")
                        self._state.status = DaemonStatus.FAILED
                        self._save_state()
        
        thread = threading.Thread(target=watchdog_loop, daemon=True)
        thread.start()
        return thread
    
    # --- Private Methods ---
    
    def _is_running(self) -> bool:
        """Check if gateway process is actually running."""
        if not self._state.pid:
            return False
        
        try:
            if sys.platform == "win32":
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {self._state.pid}"],
                    capture_output=True,
                    text=True
                )
                return str(self._state.pid) in result.stdout
            else:
                os.kill(self._state.pid, 0)
                return True
        except (ProcessLookupError, PermissionError):
            return False
        except Exception:
            return False
    
    def _run_foreground(self) -> Dict[str, Any]:
        """Run gateway in foreground (blocking)."""
        self._state.status = DaemonStatus.RUNNING
        self._state.pid = os.getpid()
        self._state.started_at = datetime.now()
        self._save_state()
        
        try:
            from chintu_backend.core.gateway import run_gateway
            run_gateway()
            return {"success": True}
        except ImportError:
            return {"success": False, "error": "Gateway module not found"}
    
    def _load_state(self) -> DaemonState:
        """Load persisted state."""
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text())
                return DaemonState(
                    status=DaemonStatus(data.get("status", "stopped")),
                    pid=data.get("pid"),
                    started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None,
                    restart_count=data.get("restart_count", 0),
                    last_error=data.get("last_error")
                )
            except Exception:
                pass
        
        return DaemonState(status=DaemonStatus.STOPPED)
    
    def _save_state(self):
        """Save state to disk."""
        data = {
            "status": self._state.status.value,
            "pid": self._state.pid,
            "started_at": self._state.started_at.isoformat() if self._state.started_at else None,
            "restart_count": self._state.restart_count,
            "last_error": self._state.last_error
        }
        self.state_file.write_text(json.dumps(data, indent=2))


# Singleton
_supervisor: Optional[GatewaySupervisor] = None


def get_gateway_supervisor() -> GatewaySupervisor:
    """Get or create the gateway supervisor singleton."""
    global _supervisor
    if _supervisor is None:
        _supervisor = GatewaySupervisor()
    return _supervisor
