"""Chintu MCP Server - Complete Model Context Protocol implementation.

Exposes all Chintu capabilities as MCP tools, resources, and prompts.
Supports both stdio and HTTP transports.

Usage:
    # Start stdio server (for Claude Desktop, Cursor, etc.)
    python -m chintu_backend.mcp.server
    
    # Start HTTP server
    python -m chintu_backend.mcp.server --http --port 8080

Configuration for Claude Desktop (claude_desktop_config.json):
{
    "mcpServers": {
        "chintu": {
            "command": "python",
            "args": ["-m", "chintu_backend.mcp.server"],
            "cwd": "C:/Users/yepur/Desktop/My_Projects/Chintu_AI"
        }
    }
}
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to path
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    TextContent,
    Tool,
    Resource,
    Prompt,
    PromptMessage,
    GetPromptResult,
    PromptArgument,
)

logger = logging.getLogger(__name__)

# Create the MCP server
mcp = Server("chintu")


# =============================================================================
# TOOLS - Executable actions
# =============================================================================

@mcp.list_tools()
async def list_tools() -> List[Tool]:
    """Return all available tools."""
    return [
        # Browser Tools
        Tool(
            name="browser_open",
            description="Open a URL in the browser and return page info",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to open"},
                    "headless": {"type": "boolean", "default": True},
                },
                "required": ["url"],
            },
        ),
        Tool(
            name="browser_search",
            description="Search Google and return results",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="browser_screenshot",
            description="Take a screenshot of the current page",
            inputSchema={
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Optional filename"},
                },
            },
        ),
        
        # System Automation Tools
        Tool(
            name="screen_click",
            description="Click at screen coordinates",
            inputSchema={
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "X coordinate"},
                    "y": {"type": "integer", "description": "Y coordinate"},
                    "button": {"type": "string", "enum": ["left", "right"], "default": "left"},
                },
                "required": ["x", "y"],
            },
        ),
        Tool(
            name="screen_type",
            description="Type text at current cursor position",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to type"},
                },
                "required": ["text"],
            },
        ),
        Tool(
            name="ui_find_click",
            description="Find and click a Windows UI element by name or description",
            inputSchema={
                "type": "object",
                "properties": {
                    "element": {"type": "string", "description": "Element name or description"},
                },
                "required": ["element"],
            },
        ),
        Tool(
            name="vision_click",
            description="Use AI vision to find and click an element by visual description",
            inputSchema={
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "Visual description of what to click"},
                },
                "required": ["description"],
            },
        ),
        Tool(
            name="vision_describe",
            description="Describe what's currently on screen using AI vision",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        
        # RPA Tools
        Tool(
            name="rpa_start_recording",
            description="Start recording mouse and keyboard actions",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="rpa_stop_recording",
            description="Stop recording and save with a name",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Recording name"},
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="rpa_play",
            description="Play back a recorded automation",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Recording name to play"},
                    "speed": {"type": "number", "default": 1.0},
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="rpa_list",
            description="List all saved RPA recordings",
            inputSchema={"type": "object", "properties": {}},
        ),
        
        # Memory Tools
        Tool(
            name="memory_learn",
            description="Learn a new fact and store in mind palace",
            inputSchema={
                "type": "object",
                "properties": {
                    "fact": {"type": "string", "description": "The fact to remember"},
                    "category": {"type": "string", "enum": ["people", "preferences", "projects"]},
                },
                "required": ["fact"],
            },
        ),
        Tool(
            name="memory_recall",
            description="Recall facts matching a query",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                },
                "required": ["query"],
            },
        ),
        
        # Sandbox Tools
        Tool(
            name="sandbox_run",
            description="Run a command in Docker sandbox",
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Command to run"},
                    "timeout": {"type": "integer", "default": 30},
                },
                "required": ["command"],
            },
        ),
        Tool(
            name="sandbox_python",
            description="Run Python code in sandbox",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python code to execute"},
                },
                "required": ["code"],
            },
        ),
        
        # File Tools
        Tool(
            name="file_read",
            description="Read contents of a file",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "max_lines": {"type": "integer", "default": 500},
                },
                "required": ["path"],
            },
        ),
        Tool(
            name="file_write",
            description="Write content to a file",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                "required": ["path", "content"],
            },
        ),
        Tool(
            name="file_list",
            description="List files in a directory",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path"},
                    "pattern": {"type": "string", "default": "*"},
                },
                "required": ["path"],
            },
        ),
        
        # App Control
        Tool(
            name="app_launch",
            description="Launch an application",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "App name or path"},
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="window_focus",
            description="Focus a window by title",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Window title (partial match)"},
                },
                "required": ["title"],
            },
        ),
        Tool(
            name="window_close",
            description="Close a window by title",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Window title"},
                },
                "required": ["title"],
            },
        ),
        
        # Skill Tools
        Tool(
            name="skill_detect",
            description="Detect the topic/skill needed for a query",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "User query"},
                },
                "required": ["query"],
            },
        ),
        
        # Factory Tool
        Tool(
            name="factory_build",
            description="Build a new capability using the Capability Factory",
            inputSchema={
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "What capability to build"},
                },
                "required": ["task"],
            },
        ),
        
        # Monitor Tools
        Tool(
            name="monitor_list",
            description="List all connected monitors",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="monitor_screenshot",
            description="Screenshot a specific monitor",
            inputSchema={
                "type": "object",
                "properties": {
                    "monitor_id": {"type": "integer", "description": "Monitor ID (0-based)"},
                },
                "required": ["monitor_id"],
            },
        ),
    ]


@mcp.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    """Execute a tool and return results."""
    try:
        result = await _execute_tool(name, arguments)
        return [TextContent(type="text", text=str(result))]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {e}")]


async def _execute_tool(name: str, args: Dict[str, Any]) -> str:
    """Execute tool by name."""
    
    # Browser tools
    if name == "browser_open":
        from chintu_backend.automation.browser.browser_controller import get_browser_controller
        bc = get_browser_controller(headless=args.get("headless", True))
        info = bc.open_url(args["url"])
        return f"Opened: {info.title}\nURL: {info.url}\nPreview: {info.text_preview[:200]}"
    
    if name == "browser_search":
        from chintu_backend.automation.browser.browser_controller import get_browser_controller
        bc = get_browser_controller()
        info = bc.search_google(args["query"])
        return f"Searched for: {args['query']}\n{info.text_preview[:500]}"
    
    if name == "browser_screenshot":
        from chintu_backend.automation.browser.browser_controller import get_browser_controller
        bc = get_browser_controller()
        path = bc.take_screenshot(args.get("filename"))
        return f"Screenshot saved: {path}"
    
    # Screen tools
    if name == "screen_click":
        from chintu_backend.automation.screen_control import get_screen_controller
        sc = get_screen_controller()
        success = sc.click_at(args["x"], args["y"], button=args.get("button", "left"))
        return f"Clicked at ({args['x']}, {args['y']}): {'Success' if success else 'Failed'}"
    
    if name == "screen_type":
        from chintu_backend.automation.screen_control import get_screen_controller
        sc = get_screen_controller()
        success = sc.type_text(args["text"])
        return f"Typed text: {'Success' if success else 'Failed'}"
    
    if name == "ui_find_click":
        from chintu_backend.automation.accessibility_tree import get_accessibility_tree
        at = get_accessibility_tree()
        elem = at.find_by_description(args["element"])
        if elem:
            success = at.click_element(elem)
            return f"Found and clicked '{elem.name}': {'Success' if success else 'Failed'}"
        return f"Element not found: {args['element']}"
    
    if name == "vision_click":
        from chintu_backend.automation.vision_automation import get_vision_automation
        va = get_vision_automation()
        success = await va.click_element(args["description"])
        return f"Vision click on '{args['description']}': {'Success' if success else 'Failed'}"
    
    if name == "vision_describe":
        from chintu_backend.automation.vision_automation import get_vision_automation
        va = get_vision_automation()
        description = await va.describe_screen()
        return description
    
    # RPA tools
    if name == "rpa_start_recording":
        from chintu_backend.automation.rpa_recorder import get_rpa_manager
        rpa = get_rpa_manager()
        success = rpa.start_recording()
        return "Recording started. Press ESC to stop." if success else "Failed to start recording"
    
    if name == "rpa_stop_recording":
        from chintu_backend.automation.rpa_recorder import get_rpa_manager
        rpa = get_rpa_manager()
        path = rpa.stop_recording(args["name"])
        return f"Recording saved: {path}" if path else "No recording in progress"
    
    if name == "rpa_play":
        from chintu_backend.automation.rpa_recorder import get_rpa_manager
        rpa = get_rpa_manager()
        success = rpa.play_recording(args["name"], speed=args.get("speed", 1.0))
        return f"Playback {'completed' if success else 'failed'}"
    
    if name == "rpa_list":
        from chintu_backend.automation.rpa_recorder import get_rpa_manager
        rpa = get_rpa_manager()
        recordings = rpa.list_recordings()
        if not recordings:
            return "No recordings found"
        lines = ["Saved recordings:"]
        for r in recordings:
            lines.append(f"- {r['name']} ({r['action_count']} actions, {r['duration']:.1f}s)")
        return "\n".join(lines)
    
    # Memory tools
    if name == "memory_learn":
        from chintu_backend.brain.memory.mind_palace import get_mind_palace
        mp = get_mind_palace()
        result = mp.learn(args["fact"], category=args.get("category"))
        if result["success"]:
            return f"Learned fact in {result['category']}/{result['file']}"
        return f"Failed to learn: {result.get('error')}"
    
    if name == "memory_recall":
        from chintu_backend.brain.memory.mind_palace import get_mind_palace
        mp = get_mind_palace()
        results = mp.recall(args["query"])
        if not results:
            return "No matching facts found"
        lines = ["Matching facts:"]
        for r in results:
            lines.append(f"- {r['fact']} [{r['category']}]")
        return "\n".join(lines)
    
    # Sandbox tools
    if name == "sandbox_run":
        from chintu_backend.sandbox.docker_sandbox import DockerSandbox
        sandbox = DockerSandbox()
        ok, output = sandbox.run(args["command"], timeout=args.get("timeout", 30))
        return output if ok else f"Error: {output}"
    
    if name == "sandbox_python":
        from chintu_backend.sandbox.docker_sandbox import DockerSandbox
        sandbox = DockerSandbox()
        ok, output = sandbox.run(f"python -c \"{args['code']}\"")
        return output if ok else f"Error: {output}"
    
    # File tools
    if name == "file_read":
        path = Path(args["path"])
        if not path.exists():
            return f"File not found: {path}"
        content = path.read_text(encoding="utf-8", errors="replace")
        lines = content.split("\n")
        max_lines = args.get("max_lines", 500)
        if len(lines) > max_lines:
            content = "\n".join(lines[:max_lines]) + f"\n... ({len(lines) - max_lines} more lines)"
        return content
    
    if name == "file_write":
        path = Path(args["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args["content"], encoding="utf-8")
        return f"Written {len(args['content'])} bytes to {path}"
    
    if name == "file_list":
        path = Path(args["path"])
        if not path.exists():
            return f"Directory not found: {path}"
        pattern = args.get("pattern", "*")
        files = list(path.glob(pattern))[:50]
        lines = [f"Files in {path}:"]
        for f in files:
            size = f.stat().st_size if f.is_file() else "dir"
            lines.append(f"- {f.name} ({size})")
        return "\n".join(lines)
    
    # App control
    if name == "app_launch":
        from chintu_backend.automation.app_launcher import AppLauncher
        launcher = AppLauncher()
        success = launcher.launch(args["name"])
        return f"Launched {args['name']}: {'Success' if success else 'Failed'}"
    
    if name == "window_focus":
        from chintu_backend.automation.window_services import find_and_focus_window
        success = find_and_focus_window(args["title"])
        return f"Focused window '{args['title']}': {'Success' if success else 'Not found'}"
    
    if name == "window_close":
        from chintu_backend.automation.native_control import get_native_controller
        nc = get_native_controller()
        success = nc.close_window_by_title(args["title"])
        return f"Closed window '{args['title']}': {'Success' if success else 'Failed'}"
    
    # Skill tools
    if name == "skill_detect":
        from chintu_backend.core.skill_loader import get_skill_loader
        sl = get_skill_loader()
        topic = sl.detect_topic(args["query"])
        return f"Detected topic: {topic or 'general'}"
    
    # Factory tools
    if name == "factory_build":
        from chintu_backend.meta.factory import get_capability_factory
        factory = get_capability_factory()
        result = await factory.build(args["task"])
        if result["success"]:
            return f"Built capability '{result['name']}' at {result['file']}"
        return f"Failed to build: {result.get('error')}"
    
    # Monitor tools
    if name == "monitor_list":
        from chintu_backend.automation.multi_monitor import get_multi_monitor_controller
        mm = get_multi_monitor_controller()
        lines = ["Connected monitors:"]
        for m in mm.monitors:
            lines.append(f"- {m.id}: {m.name} ({m.width}x{m.height})")
        return "\n".join(lines)
    
    if name == "monitor_screenshot":
        from chintu_backend.automation.multi_monitor import get_multi_monitor_controller
        mm = get_multi_monitor_controller()
        from chintu_backend.core.config import get_config
        config = get_config()
        path = config.data_dir / "screenshots" / f"monitor_{args['monitor_id']}_{datetime.now():%Y%m%d_%H%M%S}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        mm.screenshot_monitor(args["monitor_id"], str(path))
        return f"Screenshot saved: {path}"
    
    return f"Unknown tool: {name}"


# =============================================================================
# RESOURCES - Data endpoints
# =============================================================================

@mcp.list_resources()
async def list_resources() -> List[Resource]:
    """Return available resources."""
    return [
        Resource(
            uri="chintu://config",
            name="Chintu Configuration",
            description="Current configuration settings",
            mimeType="application/json",
        ),
        Resource(
            uri="chintu://capabilities",
            name="Registered Capabilities",
            description="All registered capabilities",
            mimeType="application/json",
        ),
        Resource(
            uri="chintu://skills",
            name="Available Skills",
            description="Loaded skill modules",
            mimeType="application/json",
        ),
        Resource(
            uri="chintu://memory/summary",
            name="Mind Palace Summary",
            description="Summary of stored memories",
            mimeType="text/plain",
        ),
        Resource(
            uri="chintu://monitors",
            name="Monitor Configuration",
            description="Connected display information",
            mimeType="application/json",
        ),
        Resource(
            uri="chintu://rpa/recordings",
            name="RPA Recordings",
            description="Saved automation recordings",
            mimeType="application/json",
        ),
    ]


@mcp.read_resource()
async def read_resource(uri: str) -> str:
    """Read a resource by URI."""
    
    if uri == "chintu://config":
        from chintu_backend.core.config import get_config
        config = get_config()
        return json.dumps({
            "data_dir": str(config.data_dir),
            "models_dir": str(config.models_dir),
            "whisper_model": config.whisper_model,
            "wake_word_sensitivity": config.wake_word_sensitivity,
        }, indent=2)
    
    if uri == "chintu://capabilities":
        from chintu_backend.core.capabilities import get_registry
        registry = get_registry()
        caps = []
        for cap in registry._capabilities.values():
            caps.append({
                "name": cap.name,
                "description": cap.description,
                "triggers": cap.triggers,
            })
        return json.dumps(caps, indent=2)
    
    if uri == "chintu://skills":
        from chintu_backend.core.skill_loader import get_skill_loader
        sl = get_skill_loader()
        return json.dumps(sl.list_skills(), indent=2)
    
    if uri == "chintu://memory/summary":
        from chintu_backend.brain.memory.mind_palace import get_mind_palace
        mp = get_mind_palace()
        return mp.get_summary()
    
    if uri == "chintu://monitors":
        from chintu_backend.automation.multi_monitor import get_multi_monitor_controller
        mm = get_multi_monitor_controller()
        monitors = []
        for m in mm.monitors:
            monitors.append({
                "id": m.id,
                "name": m.name,
                "width": m.width,
                "height": m.height,
                "x": m.x,
                "y": m.y,
                "is_primary": m.is_primary,
            })
        return json.dumps(monitors, indent=2)
    
    if uri == "chintu://rpa/recordings":
        from chintu_backend.automation.rpa_recorder import get_rpa_manager
        rpa = get_rpa_manager()
        return json.dumps(rpa.list_recordings(), indent=2)
    
    return f"Unknown resource: {uri}"


# =============================================================================
# PROMPTS - Reusable prompt templates
# =============================================================================

@mcp.list_prompts()
async def list_prompts() -> List[Prompt]:
    """Return available prompts."""
    return [
        Prompt(
            name="automate_task",
            description="Create an automation script for a task",
            arguments=[
                PromptArgument(name="task", description="Task to automate", required=True),
            ],
        ),
        Prompt(
            name="debug_code",
            description="Debug Python code with sandbox execution",
            arguments=[
                PromptArgument(name="code", description="Code to debug", required=True),
                PromptArgument(name="error", description="Error message", required=False),
            ],
        ),
        Prompt(
            name="learn_preference",
            description="Learn a user preference",
            arguments=[
                PromptArgument(name="preference", description="Preference to learn", required=True),
            ],
        ),
    ]


@mcp.get_prompt()
async def get_prompt(name: str, arguments: Dict[str, str]) -> GetPromptResult:
    """Generate a prompt from template."""
    
    if name == "automate_task":
        return GetPromptResult(
            messages=[
                PromptMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text=f"""I need to automate this task: {arguments['task']}

Please break this down into steps and use the available Chintu MCP tools to implement it.
Available tools include: screen_click, ui_find_click, vision_click, app_launch, file operations.

For each step, explain what you're doing and then execute the appropriate tool."""
                    ),
                )
            ],
        )
    
    if name == "debug_code":
        error_context = f"\nError: {arguments.get('error', 'Unknown')}" if arguments.get('error') else ""
        return GetPromptResult(
            messages=[
                PromptMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text=f"""Debug this Python code:

```python
{arguments['code']}
```
{error_context}

Use the sandbox_python tool to test fixes. Explain what was wrong and how you fixed it."""
                    ),
                )
            ],
        )
    
    if name == "learn_preference":
        return GetPromptResult(
            messages=[
                PromptMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text=f"Learn this preference: {arguments['preference']}\n\nUse the memory_learn tool to store this in my mind palace."
                    ),
                )
            ],
        )
    
    return GetPromptResult(messages=[])


# =============================================================================
# SERVER ENTRY POINT
# =============================================================================

async def run_stdio():
    """Run the MCP server over stdio."""
    async with stdio_server() as (read_stream, write_stream):
        await mcp.run(read_stream, write_stream, mcp.create_initialization_options())


async def run_http(host: str = "127.0.0.1", port: int = 8080):
    """Run the MCP server over HTTP (Streamable HTTP transport)."""
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Route
    import uvicorn
    
    sse = SseServerTransport("/messages")
    
    async def handle_sse(request):
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            await mcp.run(streams[0], streams[1], mcp.create_initialization_options())
    
    async def handle_messages(request):
        await sse.handle_post_message(request.scope, request.receive, request._send)
    
    app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Route("/messages", endpoint=handle_messages, methods=["POST"]),
        ],
    )
    
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Chintu MCP Server")
    parser.add_argument("--http", action="store_true", help="Use HTTP transport instead of stdio")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP host")
    parser.add_argument("--port", type=int, default=8080, help="HTTP port")
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO)
    
    if args.http:
        logger.info("Starting Chintu MCP Server on http://%s:%d", args.host, args.port)
        asyncio.run(run_http(args.host, args.port))
    else:
        logger.info("Starting Chintu MCP Server (stdio)")
        asyncio.run(run_stdio())


if __name__ == "__main__":
    main()
