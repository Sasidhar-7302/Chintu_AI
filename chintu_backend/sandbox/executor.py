"""Sandbox execution facade that can use MCP or direct Docker."""

from __future__ import annotations

import logging
from typing import Dict, Optional

from chintu_backend.core.config import get_config
from chintu_backend.interfaces.mcp import McpDockerClient, StdioMcpClient

from .docker_sandbox import DockerSandbox, SandboxResult, SandboxSession

logger = logging.getLogger(__name__)


class SandboxExecutor:
    def __init__(self):
        config = get_config()
        self.config = config
        self._client: Optional[McpDockerClient] = None
        self._sandbox: Optional[DockerSandbox] = None

        if config.mcp_docker_enabled:
            stdio = StdioMcpClient(
                command=config.mcp_docker_command,
                args=config.mcp_docker_args,
            )
            self._client = McpDockerClient(stdio)
            self._client.start()
            logger.info("Sandbox executor using MCP docker server")
        else:
            self._sandbox = DockerSandbox(
                image=config.docker_sandbox_image,
                workdir=config.docker_sandbox_workdir,
                network_mode=config.docker_sandbox_network_mode,
            )
            logger.info("Sandbox executor using direct Docker CLI")

    def run(
        self,
        command: str,
        workspace_dir: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        network_mode: Optional[str] = None,
    ) -> SandboxResult:
        if self._client:
            result = self._client.docker_run(
                command=command,
                workspace_dir=workspace_dir or str(self.config.docker_sandbox_workspace),
                image=self.config.docker_sandbox_image,
                network_mode=network_mode or self.config.docker_sandbox_network_mode,
                env=env,
            )
            return SandboxResult(
                exit_code=result.exit_code,
                stdout=result.stdout,
                stderr=result.stderr,
                duration_seconds=result.duration_seconds,
                command=["mcp", "docker_run", command],
            )
        if not self._sandbox:
            raise RuntimeError("Sandbox executor is not initialized")
        return self._sandbox.run(
            command=command,
            workspace_dir=workspace_dir or self.config.docker_sandbox_workspace,
            env=env,
            network_mode=network_mode,
        )

    def start_session(self) -> SandboxSession:
        if self._client:
            session_id = self._client.docker_start(
                workspace_dir=str(self.config.docker_sandbox_workspace),
                image=self.config.docker_sandbox_image,
                network_mode=self.config.docker_sandbox_network_mode,
            )
            raise RuntimeError(f"MCP session started: {session_id}. Use MCP exec directly.")
        if not self._sandbox:
            raise RuntimeError("Sandbox executor is not initialized")
        return self._sandbox.start(workspace_dir=self.config.docker_sandbox_workspace)

    def close(self) -> None:
        if self._client:
            self._client.stop()
