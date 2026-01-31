"""Capabilities that expose MCP tools to the assistant."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from chintu_backend.core.capabilities import (
    ActionResult,
    Capability,
    CapabilityRegistry,
    CapabilityType,
    get_registry,
)
from chintu_backend.interfaces.mcp.registry import get_mcp_registry

logger = logging.getLogger(__name__)


def _extract_tool_and_args(text: str) -> Tuple[str, str]:
    lowered = (text or "").strip()
    if not lowered:
        return "", ""

    markers = ["mcp call", "mcp tool", "call mcp"]
    start = 0
    for marker in markers:
        idx = lowered.lower().find(marker)
        if idx != -1:
            start = idx + len(marker)
            break

    remainder = lowered[start:].strip()
    if not remainder:
        return "", ""

    if "{" in remainder:
        tool_part, args_part = remainder.split("{", 1)
        return tool_part.strip(), "{" + args_part

    parts = remainder.split(maxsplit=1)
    tool_name = parts[0].strip()
    args_part = parts[1].strip() if len(parts) > 1 else ""
    return tool_name, args_part


def handle_mcp_list_tools(_text: str, _context: Dict[str, Any]) -> ActionResult:
    registry = get_mcp_registry()
    ok, msg = registry.start()
    if not ok:
        return ActionResult.fail(msg, "mcp_list_tools")

    tools = registry.list_tools(refresh=True)
    if not tools:
        return ActionResult.fail(
            "No MCP tools found. Configure CHINTU_MCP_SERVERS or enable MCP docker.",
            "mcp_list_tools",
        )

    lines = []
    for tool in tools[:20]:
        label = f"{tool.server}:{tool.name}"
        if tool.description:
            lines.append(f"- {label} - {tool.description}")
        else:
            lines.append(f"- {label}")
    if len(tools) > 20:
        lines.append(f"...and {len(tools) - 20} more")

    return ActionResult.ok(
        "Available MCP tools:\n" + "\n".join(lines),
        data={"count": len(tools)},
        capability="mcp_list_tools",
    )


def handle_mcp_call_tool(text: str, _context: Dict[str, Any]) -> ActionResult:
    registry = get_mcp_registry()
    ok, msg = registry.start()
    if not ok:
        return ActionResult.fail(msg, "mcp_call_tool")

    tool_name, raw_args = _extract_tool_and_args(text)
    if not tool_name:
        return ActionResult.fail(
            "Usage: 'mcp call <tool_name> {\"arg\":\"value\"}'",
            "mcp_call_tool",
        )

    args = registry.parse_arguments(raw_args)
    success, message, result = registry.call_tool(tool_name, arguments=args)
    if not success:
        return ActionResult.fail(message, "mcp_call_tool")

    rendered = _render_result(result)
    return ActionResult.ok(
        f"{message}\n{rendered}",
        data={"tool": tool_name, "result": result},
        capability="mcp_call_tool",
    )


def _render_result(result: Any) -> str:
    if result is None:
        return "(no result)"
    if isinstance(result, dict):
        # Many MCP servers return content blocks; keep it readable.
        content = result.get("content")
        if isinstance(content, list) and content:
            block = content[0]
            if isinstance(block, dict) and "text" in block:
                return str(block.get("text"))
        return str(result)
    return str(result)


def register_mcp_capabilities(registry: Optional[CapabilityRegistry] = None) -> None:
    registry = registry or get_registry()

    registry.register(
        Capability(
            name="mcp_list_tools",
            triggers=[
                "mcp tools",
                "list mcp tools",
                "list mcp",
                "mcp list",
            ],
            handler=handle_mcp_list_tools,
            description="List available MCP tools from configured servers",
            capability_type=CapabilityType.AI_AGENT,
            examples=["mcp tools", "list mcp tools"],
        )
    )

    registry.register(
        Capability(
            name="mcp_call_tool",
            triggers=[
                "mcp call",
                "mcp tool",
                "call mcp",
            ],
            handler=handle_mcp_call_tool,
            description="Call a specific MCP tool with JSON or key=value arguments",
            capability_type=CapabilityType.AI_AGENT,
            examples=[
                "mcp call docker:docker_run {\"command\":\"python -V\"}",
                "mcp call docker_run command=python -V",
            ],
        )
    )

    logger.info("Registered MCP capabilities")
