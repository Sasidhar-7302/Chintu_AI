"""
Safe Command Executor - Centralized secure command execution.

Eliminates shell=True injection vulnerabilities by:
1. Command allowlist enforcement
2. Argument validation
3. Approval requirements for dangerous operations
4. Comprehensive logging
"""

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from chintu_backend.core.config import get_config

logger = logging.getLogger(__name__)


class CommandRisk(Enum):
    """Risk level for commands."""
    LOW = "low"        # Safe, no approval needed
    MEDIUM = "medium"  # Requires logging
    HIGH = "high"      # Requires explicit approval


@dataclass
class ExecutionResult:
    """Result of command execution."""
    success: bool
    return_code: int
    stdout: str
    stderr: str
    command: List[str]
    execution_time: float
    approved: bool = True
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "return_code": self.return_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "command": self.command,
            "execution_time": self.execution_time,
            "error": self.error
        }


# Command allowlist with risk levels
COMMAND_ALLOWLIST: Dict[str, CommandRisk] = {
    # Package managers (HIGH - can install malware)
    "npm": CommandRisk.HIGH,
    "pip": CommandRisk.HIGH,
    "pip3": CommandRisk.HIGH,
    "poetry": CommandRisk.HIGH,
    "pnpm": CommandRisk.HIGH,
    "yarn": CommandRisk.HIGH,
    "bun": CommandRisk.HIGH,
    
    # Build/test tools (MEDIUM - arbitrary code execution)
    "python": CommandRisk.MEDIUM,
    "python3": CommandRisk.MEDIUM,
    "pytest": CommandRisk.MEDIUM,
    "node": CommandRisk.MEDIUM,
    "tsc": CommandRisk.MEDIUM,
    "eslint": CommandRisk.LOW,
    "prettier": CommandRisk.LOW,
    
    # Version control (low risk)
    "git": CommandRisk.LOW,
    
    # Deployment CLIs (high - affects production)
    "vercel": CommandRisk.HIGH,
    "flyctl": CommandRisk.HIGH,
    "fly": CommandRisk.HIGH,
    "railway": CommandRisk.HIGH,
    "netlify": CommandRisk.HIGH,
    "render": CommandRisk.HIGH,
    "docker": CommandRisk.HIGH,
    
    # System info (low risk)
    "nvidia-smi": CommandRisk.LOW,
    "tasklist": CommandRisk.LOW,
    "wmic": CommandRisk.LOW,
    "where": CommandRisk.LOW,
    "which": CommandRisk.LOW,
    
    # Chintu-specific
    "ollama": CommandRisk.LOW,
}

# Dangerous argument patterns to block (for shell commands only)
BLOCKED_PATTERNS: Set[str] = {
    ";", "&&", "||", "|", "`", "$(", "${",  # Shell operators
    "rm -rf", "del /f", "format c:",       # Destructive commands
    "--exec", "-exec", "system(", "popen(", # Arbitrary execution
    "__import__", "eval(", "exec("         # Python-in-shell injection
}


class SafeExecutor:
    """
    Secure command executor with allowlist enforcement.
    
    Features:
    - Command allowlist with risk levels
    - Argument validation (blocks shell injection patterns)
    - Approval tracking for high-risk commands
    - Comprehensive execution logging
    - Never uses shell=True
    """
    
    def __init__(self, custom_allowlist: Optional[Dict[str, CommandRisk]] = None):
        self.allowlist = dict(COMMAND_ALLOWLIST)
        if custom_allowlist:
            self.allowlist.update(custom_allowlist)
        
        self._pending_approvals: Dict[str, List[str]] = {}
        self._execution_log: List[Dict[str, Any]] = []
        
        # Docker Configuration
        self.config = get_config()
        self.use_docker = getattr(self.config, "safe_exec_sandbox_enabled", False)
        self.docker_image = getattr(self.config, "safe_exec_docker_image", "python:3.10-slim")
        
    def _wrap_in_docker(self, command: List[str], cwd: Optional[Path]) -> List[str]:
        """Wrap command in docker run."""
        if not cwd:
            cwd = Path.cwd()
            
        docker_cmd = [
            "docker", "run", "--rm",
            "--network", "none", # Strict network isolation by default
            "-v", f"{cwd.resolve()}:/workspace",
            "-w", "/workspace",
            self.docker_image
        ]
        return docker_cmd + command
    
    def is_allowed(self, command: str) -> bool:
        """Check if a command is in the allowlist."""
        # Handle full paths
        cmd_name = Path(command).stem.lower()
        return cmd_name in self.allowlist or command.lower() in self.allowlist
    
    def get_risk_level(self, command: str) -> CommandRisk:
        """Get risk level for a command."""
        cmd_name = Path(command).stem.lower()
        return self.allowlist.get(cmd_name, self.allowlist.get(command.lower(), CommandRisk.HIGH))
    
    def validate_args(self, args: List[str]) -> tuple[bool, Optional[str]]:
        """
        Validate command arguments for injection attempts.
        
        Returns:
            (is_valid, error_message)
        """
        full_command = " ".join(args)
        
        for pattern in BLOCKED_PATTERNS:
            if pattern in full_command:
                return False, f"Blocked pattern detected: {pattern}"
        
        return True, None
    
    def run(
        self,
        command: List[str],
        cwd: Optional[Path] = None,
        env: Optional[Dict[str, str]] = None,
        timeout: int = 300,
        capture_output: bool = True,
        requires_approval: bool = False,
        approval_granted: bool = False
    ) -> ExecutionResult:
        """
        Execute a command securely.
        
        Args:
            command: Command as list of arguments (NEVER a shell string)
            cwd: Working directory
            env: Environment variables (merged with current env)
            timeout: Timeout in seconds
            capture_output: Whether to capture stdout/stderr
            requires_approval: Whether this command needs user approval
            approval_granted: Whether approval was already granted
        
        Returns:
            ExecutionResult with success status and output
        """
        if not command:
            return ExecutionResult(
                success=False, return_code=-1,
                stdout="", stderr="",
                command=command, execution_time=0,
                error="Empty command"
            )
        
        executable = command[0]
        
        # Check allowlist
        if not self.is_allowed(executable):
            logger.warning(f"Command not in allowlist: {executable}")
            return ExecutionResult(
                success=False, return_code=-1,
                stdout="", stderr="",
                command=command, execution_time=0,
                error=f"Command '{executable}' is not in the allowed commands list"
            )
        
        # Validate arguments
        valid, error = self.validate_args(command)
        if not valid:
            logger.warning(f"Invalid arguments: {error}")
            return ExecutionResult(
                success=False, return_code=-1,
                stdout="", stderr="",
                command=command, execution_time=0,
                error=error
            )
        
        # Check risk level and approval
        risk = self.get_risk_level(executable)
        if risk == CommandRisk.HIGH or requires_approval:
            if not approval_granted:
                logger.info(f"High-risk command requires approval: {command}")
                self._pending_approvals[str(command)] = command
                return ExecutionResult(
                    success=False, return_code=-1,
                    stdout="", stderr="",
                    command=command, execution_time=0,
                    approved=False,
                    error="This command requires explicit approval before execution"
                )
        
        # Prepare environment
        exec_env = os.environ.copy()
        if env:
            exec_env.update(env)
        # Windows consoles often default to cp1252 and can crash skill subprocesses
        # that emit Unicode output. Force UTF-8 for Python-based commands.
        exe_name = Path(executable).name.lower()
        force_utf8_python = exe_name in {"python", "python.exe", "python3", "python3.exe", "py", "py.exe"}
        if force_utf8_python:
            exec_env.setdefault("PYTHONIOENCODING", "utf-8")
            exec_env.setdefault("PYTHONUTF8", "1")
        
        # Find executable path (default to local resolution)
        exe_path = shutil.which(executable)
        
        # Docker Sandbox Logic
        final_command = command
        # Only sandbox "runnable" low-level tools (python, node), not system util/docker itself.
        sandbox_candidates = {"python", "python3", "node", "npm"} 
        
        if self.use_docker and executable in sandbox_candidates:
            # Check if docker is available first (cached check ideally)
            docker_path = shutil.which("docker")
            if docker_path:
                final_command = self._wrap_in_docker(command, cwd)
                exe_path = docker_path # Override executable to run docker
            else:
                 logger.warning("Docker sandbox enabled but docker not found. Falling back to local.")

        if not exe_path:
            return ExecutionResult(
                success=False, return_code=-1,
                stdout="", stderr="",
                command=command, execution_time=0,
                error=f"Executable not found: {executable}"
            )

        # Execute
        start_time = datetime.now()
        try:
            # Keep shell disabled for all executions to avoid shell injection.
            exec_command = [exe_path] + final_command[1:]
            run_kwargs: Dict[str, Any] = {
                "cwd": str(cwd) if cwd and final_command == command else None,  # Docker handles cwd via mount
                "env": exec_env,  # Note: env vars not passed to docker efficiently here (would need -e loop)
                "capture_output": capture_output,
                "text": True,
                "timeout": timeout,
                "shell": False,
            }
            if force_utf8_python:
                run_kwargs["encoding"] = "utf-8"
                run_kwargs["errors"] = "replace"

            result = subprocess.run(
                exec_command,
                **run_kwargs,
            )
            
            execution_time = (datetime.now() - start_time).total_seconds()
            
            exec_result = ExecutionResult(
                success=result.returncode == 0,
                return_code=result.returncode,
                stdout=result.stdout if capture_output else "",
                stderr=result.stderr if capture_output else "",
                command=command,
                execution_time=execution_time
            )
            
            # Log execution
            self._log_execution(exec_result)
            
            return exec_result
            
        except subprocess.TimeoutExpired:
            execution_time = (datetime.now() - start_time).total_seconds()
            return ExecutionResult(
                success=False, return_code=-1,
                stdout="", stderr="",
                command=command, execution_time=execution_time,
                error=f"Command timed out after {timeout}s"
            )
        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds()
            logger.error(f"Execution error: {e}")
            return ExecutionResult(
                success=False, return_code=-1,
                stdout="", stderr="",
                command=command, execution_time=execution_time,
                error=str(e)
            )
    
    def run_with_approval(
        self,
        command: List[str],
        approval_callback=None,
        **kwargs
    ) -> ExecutionResult:
        """
        Run a command that requires approval.
        
        Args:
            command: Command to execute
            approval_callback: Optional callback to request approval
            **kwargs: Additional args passed to run()
        """
        risk = self.get_risk_level(command[0]) if command else CommandRisk.HIGH
        
        if risk == CommandRisk.HIGH:
            if approval_callback:
                approved = approval_callback(command)
                if not approved:
                    return ExecutionResult(
                        success=False, return_code=-1,
                        stdout="", stderr="",
                        command=command, execution_time=0,
                        approved=False,
                        error="User declined approval"
                    )
            
            kwargs["approval_granted"] = True
        
        return self.run(command, **kwargs)
    
    def get_pending_approvals(self) -> List[List[str]]:
        """Get list of commands waiting for approval."""
        return list(self._pending_approvals.values())
    
    def approve_command(self, command_key: str) -> bool:
        """Mark a command as approved."""
        if command_key in self._pending_approvals:
            del self._pending_approvals[command_key]
            return True
        return False
    
    def _log_execution(self, result: ExecutionResult):
        """Log command execution for audit."""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "command": result.command,
            "success": result.success,
            "return_code": result.return_code,
            "execution_time": result.execution_time,
            "error": result.error
        }
        self._execution_log.append(log_entry)
        
        # Keep last 1000 entries
        if len(self._execution_log) > 1000:
            self._execution_log = self._execution_log[-1000:]
    
    def get_execution_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent execution log."""
        return self._execution_log[-limit:]


# Global executor instance
_safe_executor: Optional[SafeExecutor] = None


def get_safe_executor() -> SafeExecutor:
    """Get or create the global safe executor."""
    global _safe_executor
    if _safe_executor is None:
        _safe_executor = SafeExecutor()
    return _safe_executor


def safe_run(
    command: List[str],
    cwd: Optional[Path] = None,
    timeout: int = 300,
    **kwargs
) -> ExecutionResult:
    """Convenience function for safe command execution."""
    return get_safe_executor().run(command, cwd=cwd, timeout=timeout, **kwargs)
