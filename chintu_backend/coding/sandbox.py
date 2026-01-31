"""
SandboxManager: Manages Docker-based Shadow Workspace for code verification.
"""

import logging
import subprocess
import tempfile
import os
import time
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

class SandboxManager:
    """
    Manages a persistent Docker container ('chintu-sandbox') for safe code execution.
    """
    
    def __init__(self, image: str = "python:3.11-slim"):
        self.image = image
        self.container_name = "chintu-sandbox"
        self._ensure_container_running()
        
    def _ensure_container_running(self):
        """Check if sandbox is running, start it if not."""
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
            logger.error(f"Failed to start sandbox: {e}")
        except FileNotFoundError:
            logger.error("Docker executable not found. Shadow Workspace disabled.")

    def run_python(self, code: str, timeout: int = 10) -> Tuple[str, str, int]:
        """
        Run Python code in the sandbox.
        Returns: (stdout, stderr, exit_code)
        """
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
