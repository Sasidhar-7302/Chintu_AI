"""Docker-based sandbox execution with safe defaults."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union

logger = logging.getLogger(__name__)

CommandInput = Union[str, Sequence[str]]


@dataclass
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    command: List[str]


class SandboxSession:
    """Long-lived container session for multiple exec calls."""

    def __init__(self, container_name: str, sandbox: "DockerSandbox"):
        self.container_name = container_name
        self._sandbox = sandbox

    def exec(self, command: CommandInput, timeout: Optional[float] = None) -> SandboxResult:
        cmd = self._sandbox.build_exec_command(
            self.container_name,
            command,
            workdir=self._sandbox.workdir,
            env=None,
        )
        return self._sandbox._run_command(cmd, timeout)

    def copy_to(self, src: Path, dest: str) -> SandboxResult:
        cmd = self._sandbox.build_copy_command(src, f"{self.container_name}:{dest}")
        return self._sandbox._run_command(cmd, timeout=self._sandbox.timeout)

    def copy_from(self, src: str, dest: Path) -> SandboxResult:
        cmd = self._sandbox.build_copy_command(f"{self.container_name}:{src}", dest)
        return self._sandbox._run_command(cmd, timeout=self._sandbox.timeout)

    def stop(self) -> SandboxResult:
        cmd = ["docker", "stop", self.container_name]
        return self._sandbox._run_command(cmd, timeout=self._sandbox.timeout)


class DockerSandbox:
    """Run commands inside an isolated Docker container."""

    def __init__(
        self,
        image: str = "python:3.11-slim",
        workdir: str = "/app",
        timeout: float = 120.0,
        network_mode: str = "none",
    ):
        self.image = image
        self.workdir = workdir
        self.timeout = timeout
        self.network_mode = network_mode

    def run(
        self,
        command: CommandInput,
        workspace_dir: Optional[Path] = None,
        env: Optional[Dict[str, str]] = None,
        network_mode: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> SandboxResult:
        self._ensure_docker()
        workspace = self._resolve_workspace(workspace_dir)
        cmd = self.build_run_command(
            command=command,
            workspace_dir=workspace,
            env=env,
            network_mode=network_mode or self.network_mode,
        )
        return self._run_command(cmd, timeout or self.timeout)

    def start(
        self,
        workspace_dir: Optional[Path] = None,
        env: Optional[Dict[str, str]] = None,
        network_mode: Optional[str] = None,
    ) -> SandboxSession:
        self._ensure_docker()
        workspace = self._resolve_workspace(workspace_dir)
        container_name = f"chintu-sandbox-{uuid.uuid4().hex[:8]}"
        cmd = self.build_start_command(
            container_name=container_name,
            workspace_dir=workspace,
            env=env,
            network_mode=network_mode or self.network_mode,
        )
        result = self._run_command(cmd, timeout=self.timeout)
        if result.exit_code != 0:
            raise RuntimeError(f"Failed to start container: {result.stderr}")
        return SandboxSession(container_name, self)

    def build_run_command(
        self,
        command: CommandInput,
        workspace_dir: Path,
        env: Optional[Dict[str, str]],
        network_mode: str,
    ) -> List[str]:
        cmd = ["docker", "run", "--rm", "--network", network_mode]
        cmd.extend(["-v", f"{workspace_dir}:{self.workdir}"])
        cmd.extend(["-w", self.workdir])
        cmd.extend(self._format_env(env))
        cmd.append(self.image)
        cmd.extend(self._format_command(command))
        return cmd

    def build_start_command(
        self,
        container_name: str,
        workspace_dir: Path,
        env: Optional[Dict[str, str]],
        network_mode: str,
    ) -> List[str]:
        cmd = [
            "docker",
            "run",
            "--rm",
            "-d",
            "--name",
            container_name,
            "--network",
            network_mode,
        ]
        cmd.extend(["-v", f"{workspace_dir}:{self.workdir}"])
        cmd.extend(["-w", self.workdir])
        cmd.extend(self._format_env(env))
        cmd.append(self.image)
        cmd.extend(["sleep", "infinity"])
        return cmd

    def build_exec_command(
        self,
        container_name: str,
        command: CommandInput,
        workdir: str,
        env: Optional[Dict[str, str]],
    ) -> List[str]:
        cmd = ["docker", "exec", "-w", workdir]
        cmd.extend(self._format_env(env))
        cmd.append(container_name)
        cmd.extend(self._format_command(command))
        return cmd

    @staticmethod
    def build_copy_command(src: Union[str, Path], dest: Union[str, Path]) -> List[str]:
        return ["docker", "cp", str(src), str(dest)]

    def _run_command(self, cmd: List[str], timeout: Optional[float]) -> SandboxResult:
        start = time.time()
        logger.info("Sandbox command: %s", " ".join(cmd))
        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return SandboxResult(
                exit_code=completed.returncode,
                stdout=completed.stdout or "",
                stderr=completed.stderr or "",
                duration_seconds=time.time() - start,
                command=cmd,
            )
        except subprocess.TimeoutExpired as exc:
            return SandboxResult(
                exit_code=124,
                stdout=exc.stdout or "",
                stderr=exc.stderr or "Timed out",
                duration_seconds=time.time() - start,
                command=cmd,
            )

    @staticmethod
    def _ensure_docker() -> None:
        docker_bin = shutil.which("docker")
        if not docker_bin:
            raise RuntimeError("Docker CLI not found. Please install Docker Desktop.")

        healthy, message = DockerSandbox.health_check()
        if healthy:
            return

        # On Windows, try starting Docker Desktop automatically before failing.
        if os.name == "nt":
            if DockerSandbox._try_start_docker_desktop():
                healthy, message = DockerSandbox.health_check()
                if healthy:
                    return

        raise RuntimeError(message or "Docker sandbox unavailable on this machine session.")

    @staticmethod
    def _try_start_docker_desktop(wait_seconds: int = 45) -> bool:
        """Best-effort Docker Desktop auto-start for Windows sessions."""
        docker_desktop_path = Path("C:/Program Files/Docker/Docker/Docker Desktop.exe")
        if not docker_desktop_path.exists():
            return False
        try:
            subprocess.Popen([str(docker_desktop_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            return False

        deadline = time.time() + max(10, int(wait_seconds))
        while time.time() < deadline:
            healthy, _ = DockerSandbox.health_check()
            if healthy:
                return True
            time.sleep(2)
        return False

    @staticmethod
    def health_check() -> tuple[bool, str]:
        """
        Comprehensive Docker health check.

        Returns:
            Tuple of (is_healthy, message)
        """
        # Check if docker CLI exists
        if not shutil.which("docker"):
            return False, "Docker CLI not found. Please install Docker Desktop."

        # Check if Docker daemon is running
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode != 0:
                if "Is the docker daemon running" in result.stderr:
                    return False, "Docker daemon is not running. Please start Docker Desktop."
                if "dockerDesktopLinuxEngine" in result.stderr:
                    return False, "Docker daemon is not running. Start Docker Desktop and wait for engine initialization."
                return False, f"Docker error: {result.stderr.strip()}"
        except subprocess.TimeoutExpired:
            return False, "Docker daemon not responding (timeout)"
        except Exception as e:
            return False, f"Docker check failed: {e}"

        # Check if we can pull/access images
        try:
            result = subprocess.run(
                ["docker", "images", "-q", "python:3.11-slim"],
                capture_output=True,
                text=True,
                timeout=10
            )
            image_available = bool(result.stdout.strip())

            if image_available:
                return True, "Docker is healthy. Sandbox ready."
            else:
                return True, "Docker is healthy but python:3.11-slim image not cached (will be pulled on first use)"
        except Exception as e:
            return True, f"Docker daemon running but image check failed: {e}"

    @staticmethod
    def is_available() -> bool:
        """Quick check if Docker is available for use."""
        healthy, _ = DockerSandbox.health_check()
        return healthy

    def _resolve_workspace(self, workspace_dir: Optional[Path]) -> Path:
        workspace = workspace_dir or Path.cwd()
        workspace = Path(workspace).resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace

    @staticmethod
    def _format_env(env: Optional[Dict[str, str]]) -> List[str]:
        if not env:
            return []
        args: List[str] = []
        for key, value in env.items():
            args.extend(["-e", f"{key}={value}"])
        return args

    @staticmethod
    def _format_command(command: CommandInput) -> List[str]:
        if isinstance(command, str):
            return ["sh", "-lc", command]
        return list(command)
