"""
SandboxManager: Manages Docker-based Shadow Workspace for code verification.
"""

import logging
import subprocess
import tempfile
import os
import time
import shutil
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

class SandboxManager:
    """
    Manages a persistent Docker container ('chintu-sandbox') for safe code execution.
    """
    _autostart_attempted: bool = False
    
    def __init__(self, image: str = "python:3.11-slim"):
        self.image = image
        self.container_name = "chintu-sandbox"
        self.enabled = True
        self.disable_reason = ""
        self._check_docker_runtime()
        self._ensure_container_running()

    @staticmethod
    def _probe_docker_info(timeout: int = 6) -> tuple[bool, str]:
        docker_bin = shutil.which("docker")
        if not docker_bin:
            return False, "docker executable not found"
        try:
            probe = subprocess.run(
                [docker_bin, "info"],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            if probe.returncode == 0:
                return True, ""
            err = (probe.stderr or probe.stdout or "docker daemon unavailable").strip()
            return False, err
        except Exception as exc:
            return False, str(exc)

    @staticmethod
    def _try_start_docker_desktop(wait_seconds: int = 45) -> bool:
        if os.name != "nt":
            return False
        docker_desktop_path = "C:\\Program Files\\Docker\\Docker\\Docker Desktop.exe"
        if not os.path.exists(docker_desktop_path):
            return False
        try:
            logger.info("Docker daemon unavailable. Attempting Docker Desktop auto-start...")
            creationflags = 0
            if hasattr(subprocess, "DETACHED_PROCESS"):
                creationflags |= subprocess.DETACHED_PROCESS
            if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
                creationflags |= subprocess.CREATE_NEW_PROCESS_GROUP
            subprocess.Popen(
                [docker_desktop_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        except Exception as exc:
            logger.warning("Docker Desktop auto-start failed: %s", exc)
            return False

        deadline = time.time() + max(10, int(wait_seconds))
        while time.time() < deadline:
            healthy, _ = SandboxManager._probe_docker_info(timeout=6)
            if healthy:
                logger.info("Docker daemon became ready after auto-start.")
                return True
            time.sleep(2)
        return False

    def _disable(self, reason: str) -> None:
        low = str(reason or "").lower()
        if "dockerdesktoplinuxengine" in low or "daemon is running" in low or "daemon unavailable" in low:
            reason = "Docker daemon is not running. Start Docker Desktop."
        self.enabled = False
        self.disable_reason = str(reason or "docker sandbox unavailable").strip()
        logger.warning("Docker sandbox disabled: %s", self.disable_reason)

    def _can_retry_later(self) -> bool:
        low = str(self.disable_reason or "").lower()
        return any(
            token in low
            for token in [
                "daemon",
                "dockerdesktoplinuxengine",
                "timed out",
                "timeout",
                "not responding",
            ]
        )

    def _check_docker_runtime(self) -> None:
        """Disable sandbox early when Docker is unavailable; auto-start Docker Desktop on Windows once."""
        healthy, err = self._probe_docker_info(timeout=6)
        if healthy:
            self.enabled = True
            self.disable_reason = ""
            return

        if os.name == "nt" and not SandboxManager._autostart_attempted:
            SandboxManager._autostart_attempted = True
            if self._try_start_docker_desktop(wait_seconds=45):
                self.enabled = True
                self.disable_reason = ""
                return

        self._disable(err)

    def _try_reenable_if_docker_ready(self) -> None:
        """Recover automatically if Docker becomes available later in the same session."""
        if self.enabled or not self._can_retry_later():
            return
        healthy, err = self._probe_docker_info(timeout=4)
        if healthy:
            self.enabled = True
            self.disable_reason = ""
            logger.info("Docker sandbox re-enabled after daemon recovery.")
            self._ensure_container_running()
            return
        self.disable_reason = err

    def _ensure_container_running(self):
        """Check if sandbox is running, start it if not."""
        if not self.enabled:
            return
        try:
            # Check if running
            check = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", self.container_name],
                capture_output=True, text=True
            )
            
            if check.returncode == 0 and "true" in check.stdout.lower():
                return # Already running
                
            # Remove if stopped/exited
            subprocess.run(["docker", "rm", "-f", self.container_name], 
                         capture_output=True, check=False)
            
            # Start new container (sleep infinity to keep it alive)
            logger.info(f"Starting Shadow Workspace ({self.container_name})...")
            subprocess.run([
                "docker", "run", "-d", 
                "--name", self.container_name, 
                "--memory=512m", # Limit memory for safety
                "--cpus=1.0",    # Limit CPU
                self.image, 
                "sleep", "infinity"
            ], check=True, capture_output=True)
            
            # Install basic utils if needed (pip install not recommended in runtime loop but ok for setup)
            # For now, we assume standard python lib is enough.
            
        except subprocess.CalledProcessError as e:
            self.enabled = False
            self.disable_reason = str(e)
            logger.warning("Docker sandbox disabled after startup failure: %s", e)
        except FileNotFoundError:
            self.enabled = False
            self.disable_reason = "docker executable not found"
            logger.warning("Docker sandbox disabled: docker executable not found.")

    def run_python(self, code: str, timeout: int = 10) -> Tuple[str, str, int]:
        """
        Run Python code in the sandbox.
        Returns: (stdout, stderr, exit_code)
        """
        self._try_reenable_if_docker_ready()
        if not self.enabled:
            reason = self.disable_reason or "docker sandbox unavailable"
            return "", f"Sandbox disabled: {reason}", 1
        self._ensure_container_running()
        
        try:
            # 1. Write code to a file inside container
            # We use `docker exec -i ... cat > script.py` pattern
            cmd_write = ["docker", "exec", "-i", self.container_name, "sh", "-c", "cat > /tmp/script.py"]
            
            # Popen allows us to pipe stdin
            process = subprocess.Popen(
                cmd_write, 
                stdin=subprocess.PIPE, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE,
                text=True
            )
            process.communicate(input=code)
            
            if process.returncode != 0:
                return "", "Failed to write code to sandbox", 1

            # 2. Run the script
            # We use `docker exec` to run python
            cmd_run = ["docker", "exec", self.container_name, "python", "/tmp/script.py"]
            
            run_result = subprocess.run(
                cmd_run,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            return run_result.stdout, run_result.stderr, run_result.returncode
            
        except subprocess.TimeoutExpired:
            return "", "Execution Timed Out", 124
        except Exception as e:
            return "", str(e), 1

# Global
_sandbox = None

def get_sandbox_manager() -> SandboxManager:
    global _sandbox
    if not _sandbox:
        _sandbox = SandboxManager()
    return _sandbox
