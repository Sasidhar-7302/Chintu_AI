"""Minimal MCP server exposing Docker sandbox tools over stdio."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict

from chintu_backend.sandbox.docker_sandbox import DockerSandbox

logger = logging.getLogger(__name__)


def list_tools() -> Dict[str, Any]:
    return {
        "tools": [
            {
                "name": "docker_run",
                "description": "Run a command inside an ephemeral sandbox container.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "workspace_dir": {"type": "string"},
                        "image": {"type": "string"},
                        "network_mode": {"type": "string"},
                        "env": {"type": "object"},
                    },
                    "required": ["command"],
                },
            },
            {
                "name": "docker_start",
                "description": "Start a long-lived sandbox container session.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "workspace_dir": {"type": "string"},
                        "image": {"type": "string"},
                        "network_mode": {"type": "string"},
                        "env": {"type": "object"},
                    },
                },
            },
            {
                "name": "docker_exec",
                "description": "Execute a command in a running sandbox session.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string"},
                        "command": {"type": "string"},
                    },
                    "required": ["session_id", "command"],
                },
            },
            {
                "name": "docker_stop",
                "description": "Stop a running sandbox session.",
                "input_schema": {
                    "type": "object",
                    "properties": {"session_id": {"type": "string"}},
                    "required": ["session_id"],
                },
            },
        ]
    }


def handle_tool_call(
    name: str,
    arguments: Dict[str, Any],
    sandbox: DockerSandbox,
    sessions: Dict[str, Any],
) -> Dict[str, Any]:
    if name == "docker_run":
        command = arguments.get("command", "")
        workspace_dir = arguments.get("workspace_dir")
        image = arguments.get("image") or sandbox.image
        network_mode = arguments.get("network_mode") or sandbox.network_mode
        env = arguments.get("env")
        sandbox.image = image
        result = sandbox.run(
            command=command,
            workspace_dir=Path(workspace_dir) if workspace_dir else None,
            env=env,
            network_mode=network_mode,
        )
        return _result_to_payload(result)

    if name == "docker_start":
        workspace_dir = arguments.get("workspace_dir")
        image = arguments.get("image") or sandbox.image
        network_mode = arguments.get("network_mode") or sandbox.network_mode
        env = arguments.get("env")
        sandbox.image = image
        session = sandbox.start(
            workspace_dir=Path(workspace_dir) if workspace_dir else None,
            env=env,
            network_mode=network_mode,
        )
        sessions[session.container_name] = session
        return {"session_id": session.container_name}

    if name == "docker_exec":
        session_id = arguments.get("session_id")
        command = arguments.get("command", "")
        session = sessions.get(session_id)
        if not session:
            raise ValueError(f"Unknown session_id: {session_id}")
        result = session.exec(command)
        return _result_to_payload(result)

    if name == "docker_stop":
        session_id = arguments.get("session_id")
        session = sessions.get(session_id)
        if not session:
            raise ValueError(f"Unknown session_id: {session_id}")
        result = session.stop()
        sessions.pop(session_id, None)
        return _result_to_payload(result)

    raise ValueError(f"Unknown tool: {name}")


def _result_to_payload(result) -> Dict[str, Any]:
    return {
        "exit_code": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "duration_seconds": result.duration_seconds,
    }


def _send_response(response: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(response, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    sandbox = DockerSandbox()
    sessions: Dict[str, Any] = {}

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            method = request.get("method")
            request_id = request.get("id")
            params = request.get("params", {})

            if method == "tools/list":
                result = list_tools()
                _send_response({"jsonrpc": "2.0", "id": request_id, "result": result})
                continue

            if method == "tools/call":
                tool_name = params.get("name")
                arguments = params.get("arguments", {})
                result = handle_tool_call(tool_name, arguments, sandbox, sessions)
                _send_response({"jsonrpc": "2.0", "id": request_id, "result": result})
                continue

            _send_response(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"message": f"Unknown method: {method}"},
                }
            )
        except Exception as exc:
            logger.exception("MCP server error")
            _send_response(
                {
                    "jsonrpc": "2.0",
                    "id": request.get("id") if isinstance(request, dict) else None,
                    "error": {"message": str(exc)},
                }
            )


if __name__ == "__main__":
    main()
