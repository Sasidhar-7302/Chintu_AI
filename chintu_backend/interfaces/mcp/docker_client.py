"""MCP client wrapper for the docker sandbox server."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .stdio_client import McpResponse, StdioMcpClient

logger = logging.getLogger(__name__)


@dataclass
class McpDockerResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float


class McpDockerClient:
    """Client for MCP docker tools via stdio."""

    def __init__(self, stdio_client: StdioMcpClient):
        self.client = stdio_client

    def start(self) -> None:
        self.client.start()

    def stop(self) -> None:
        self.client.stop()

    def list_tools(self) -> McpResponse:
        return self.client.call("tools/list")

    def docker_run(
        self,
        command: str,
        workspace_dir: Optional[str] = None,
        image: Optional[str] = None,
        network_mode: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> McpDockerResult:
        params = {
            "name": "docker_run",
            "arguments": {
                "command": command,
                "workspace_dir": workspace_dir,
                "image": image,
                "network_mode": network_mode,
                "env": env,
            },
        }
        response = self.client.call("tools/call", params)
        return self._parse_result(response)

    def docker_start(
        self,
        workspace_dir: Optional[str] = None,
        image: Optional[str] = None,
        network_mode: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> str:
        params = {
            "name": "docker_start",
            "arguments": {
                "workspace_dir": workspace_dir,
                "image": image,
                "network_mode": network_mode,
                "env": env,
            },
        }
        response = self.client.call("tools/call", params)
        return str(response.result.get("session_id"))

    def docker_exec(self, session_id: str, command: str) -> McpDockerResult:
        params = {
            "name": "docker_exec",
            "arguments": {"session_id": session_id, "command": command},
        }
        response = self.client.call("tools/call", params)
        return self._parse_result(response)

    def docker_stop(self, session_id: str) -> McpDockerResult:
        params = {
            "name": "docker_stop",
            "arguments": {"session_id": session_id},
        }
        response = self.client.call("tools/call", params)
        return self._parse_result(response)

    @staticmethod
    def _parse_result(response: McpResponse) -> McpDockerResult:
        result = response.result or {}
        return McpDockerResult(
            exit_code=int(result.get("exit_code", 1)),
            stdout=str(result.get("stdout", "")),
            stderr=str(result.get("stderr", "")),
            duration_seconds=float(result.get("duration_seconds", 0.0)),
        )
