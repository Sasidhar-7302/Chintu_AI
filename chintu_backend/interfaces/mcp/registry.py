"""MCP registry for discovering and calling Model Context Protocol tools."""

from __future__ import annotations

import json
import logging
import shlex
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from chintu_backend.core.config import get_config
from chintu_backend.core.state import get_state_manager

from .stdio_client import StdioMcpClient

logger = logging.getLogger(__name__)


@dataclass
class McpTool:
    """A single MCP tool exposed by a server."""

    server: str
    name: str
    description: str = ""
    input_schema: Optional[Dict[str, Any]] = None


@dataclass
class McpServerSpec:
    """Specification for an MCP server process."""

    name: str
    command: str
    args: List[str]
    enabled: bool = True


class McpServerClient:
    """Wrapper around a stdio MCP server with simple tool caching."""

    def __init__(self, spec: McpServerSpec, cache_ttl_seconds: float):
        self.spec = spec
        self.cache_ttl_seconds = cache_ttl_seconds
        self.client = StdioMcpClient(command=spec.command, args=spec.args)
        self._tools_cache: List[McpTool] = []
        self._last_tools_refresh: float = 0.0
        self._started = False

    def start(self) -> None:
        if not self.spec.enabled or self._started:
            return
        self.client.start()
        self._started = True

    def stop(self) -> None:
        if not self._started:
            return
        self.client.stop()
        self._started = False

    def list_tools(self, refresh: bool = False) -> List[McpTool]:
        now = time.monotonic()
        cache_valid = (now - self._last_tools_refresh) <= self.cache_ttl_seconds
        if self._tools_cache and cache_valid and not refresh:
            return list(self._tools_cache)

        response = self.client.call("tools/list", timeout=20.0)
        result = response.result or {}
        tools_payload = result.get("tools") if isinstance(result, dict) else None
        tools_payload = tools_payload or []

        tools: List[McpTool] = []
        for tool in tools_payload:
            if not isinstance(tool, dict):
                continue
            tools.append(
                McpTool(
                    server=self.spec.name,
                    name=str(tool.get("name", "")),
                    description=str(tool.get("description") or ""),
                    input_schema=tool.get("inputSchema") or tool.get("input_schema"),
                )
            )

        self._tools_cache = tools
        self._last_tools_refresh = now
        return list(tools)

    def call_tool(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        payload = {"name": tool_name, "arguments": arguments or {}}
        response = self.client.call("tools/call", params=payload, timeout=60.0)
        return response.result


class McpRegistry:
    """Registry that manages MCP server processes and tool calls."""

    def __init__(self):
        self.config = get_config()
        self.state_manager = get_state_manager()
        self._clients: Dict[str, McpServerClient] = {}
        self._started = False
        self._init_clients()

    def _init_clients(self) -> None:
        specs = list(self._iter_specs())
        for spec in specs:
            if spec.name in self._clients:
                continue
            self._clients[spec.name] = McpServerClient(
                spec=spec,
                cache_ttl_seconds=self.config.mcp_tool_cache_ttl_seconds,
            )

    def _iter_specs(self) -> Iterable[McpServerSpec]:
        # Docker MCP server is treated as a first-class MCP provider.
        if self.config.mcp_docker_enabled:
            yield McpServerSpec(
                name="docker",
                command=self.config.mcp_docker_command,
                args=list(self.config.mcp_docker_args),
                enabled=True,
            )

        for idx, command_str in enumerate(self.config.mcp_servers):
            command_str = (command_str or "").strip()
            if not command_str:
                continue
            parts = shlex.split(command_str)
            if not parts:
                continue
            name = parts[0]
            # Make the name stable and readable.
            base_name = name.split("/")[-1].split("\\")[-1]
            spec_name = f"{base_name}_{idx + 1}"
            yield McpServerSpec(name=spec_name, command=parts[0], args=parts[1:], enabled=True)

    @property
    def is_enabled(self) -> bool:
        if self.config.mcp_enabled:
            return True
        return self.config.mcp_docker_enabled or bool(self.config.mcp_servers)

    def start(self) -> Tuple[bool, str]:
        if not self.is_enabled:
            self.state_manager.update_feature("mcp", enabled=False, status="inactive")
            return False, "MCP is disabled in config"
        if self._started:
            return True, "MCP already started"

        self._init_clients()
        started_any = False
        errors: List[str] = []
        for name, client in self._clients.items():
            try:
                client.start()
                started_any = True
                logger.info("Started MCP server: %s", name)
            except Exception as exc:  # noqa: BLE001 - defensive
                err = f"{name}: {exc}"
                errors.append(err)
                logger.warning("Failed to start MCP server %s: %s", name, exc)

        self._started = started_any
        if started_any:
            self.state_manager.update_feature("mcp", enabled=True, status="active")
            if errors:
                return True, f"MCP started with warnings: {', '.join(errors[:2])}"
            return True, f"MCP started with {len(self._clients)} server(s)"

        self.state_manager.update_feature(
            "mcp",
            enabled=False,
            status="inactive",
            error="; ".join(errors[:2]) if errors else "No MCP servers configured",
        )
        return False, "No MCP servers could be started"

    def stop(self) -> None:
        for client in self._clients.values():
            try:
                client.stop()
            except Exception:
                continue
        self._started = False
        self.state_manager.update_feature("mcp", status="inactive")

    def list_tools(self, refresh: bool = False) -> List[McpTool]:
        if not self._started:
            self.start()
        tools: List[McpTool] = []
        for name, client in self._clients.items():
            try:
                tools.extend(client.list_tools(refresh=refresh))
            except Exception as exc:  # noqa: BLE001
                logger.debug("MCP tools/list failed for %s: %s", name, exc)
        if tools:
            self.state_manager.update_feature("mcp", enabled=True, status="active")
        return tools

    def _resolve_tool(
        self, tool_name: str, server_name: Optional[str] = None
    ) -> Tuple[Optional[McpServerClient], Optional[str]]:
        if server_name:
            client = self._clients.get(server_name)
            if client:
                return client, tool_name
            return None, None

        if ":" in tool_name:
            server_part, name_part = tool_name.split(":", 1)
            client = self._clients.get(server_part)
            if client:
                return client, name_part
            return None, None

        # Search across servers by name.
        for client in self._clients.values():
            for tool in client.list_tools():
                if tool.name == tool_name:
                    return client, tool_name
        return None, None

    def call_tool(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
        server_name: Optional[str] = None,
    ) -> Tuple[bool, str, Any]:
        if not tool_name:
            return False, "Tool name is required", None
        if not self._started:
            self.start()

        client, resolved_name = self._resolve_tool(tool_name, server_name=server_name)
        if not client or not resolved_name:
            return False, f"MCP tool not found: {tool_name}", None

        try:
            result = client.call_tool(resolved_name, arguments=arguments)
            self.state_manager.update_feature("mcp", status="active")
            return True, f"MCP tool executed via {client.spec.name}", result
        except Exception as exc:  # noqa: BLE001
            logger.warning("MCP tool call failed (%s): %s", tool_name, exc)
            self.state_manager.update_feature("mcp", status="testing", error=str(exc))
            return False, f"MCP tool call failed: {exc}", None

    @staticmethod
    def parse_arguments(raw: str) -> Dict[str, Any]:
        raw = (raw or "").strip()
        if not raw:
            return {}
        if raw.startswith("{"):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass

        args: Dict[str, Any] = {}
        for token in raw.split():
            if "=" not in token:
                continue
            key, value = token.split("=", 1)
            args[key.strip()] = value.strip()
        return args


_registry: Optional[McpRegistry] = None


def get_mcp_registry() -> McpRegistry:
    """Get or create the global MCP registry."""
    global _registry
    if _registry is None:
        _registry = McpRegistry()
    return _registry
