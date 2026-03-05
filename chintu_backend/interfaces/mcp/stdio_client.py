"""Stdio-based MCP client for local servers."""

from __future__ import annotations

import json
import logging
import queue
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class McpResponse:
    payload: Dict[str, Any]

    @property
    def result(self) -> Any:
        return self.payload.get("result")


class StdioMcpClient:
    def __init__(
        self,
        command: str,
        args: Optional[list[str]] = None,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
    ):
        self.command = command
        self.args = args or []
        self.env = env
        self.cwd = cwd
        self._process: Optional[subprocess.Popen[str]] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._queue: queue.Queue[Dict[str, Any]] = queue.Queue()
        self._next_id = 1
        self._initialized = False

    def start(self) -> None:
        if self._process:
            return
        self._process = subprocess.Popen(
            [self.command, *self.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=self.env,
            cwd=self.cwd,
        )
        self._reader_thread = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader_thread.start()
        self._stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self._stderr_thread.start()
        logger.info("Started MCP server: %s %s", self.command, " ".join(self.args))
        try:
            self._initialize_session()
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        if not self._process:
            return
        try:
            self._process.terminate()
            self._process.wait(timeout=5)
        except Exception:
            pass
        self._process = None
        self._initialized = False

    def call(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 30.0) -> McpResponse:
        if not self._process or not self._process.stdin:
            raise RuntimeError("MCP client is not started")
        request_id = self._next_id
        self._next_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        }
        line = json.dumps(payload, ensure_ascii=True)
        self._process.stdin.write(line + "\n")
        self._process.stdin.flush()
        response = self._wait_for_response(request_id, timeout)
        return McpResponse(response)

    def _notify(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        if not self._process or not self._process.stdin:
            return
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        }
        line = json.dumps(payload, ensure_ascii=True)
        self._process.stdin.write(line + "\n")
        self._process.stdin.flush()

    def _initialize_session(self) -> None:
        """Perform MCP initialize handshake before tool calls."""
        versions = ("2024-11-05", "2024-10-07", "2024-09-30")
        last_error: Optional[Exception] = None
        for protocol_version in versions:
            try:
                response = self.call(
                    "initialize",
                    params={
                        "protocolVersion": protocol_version,
                        "clientInfo": {"name": "chintu-mcp-client", "version": "1.0"},
                        "capabilities": {},
                    },
                    timeout=12.0,
                )
                if response.result is None:
                    raise RuntimeError("initialize returned no result")
                self._notify("notifications/initialized", {})
                self._initialized = True
                return
            except Exception as exc:
                last_error = exc
                continue
        raise RuntimeError(f"MCP initialize handshake failed: {last_error}")

    def _read_stdout(self) -> None:
        assert self._process and self._process.stdout
        for line in self._process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
                if isinstance(payload, dict):
                    self._queue.put(payload)
            except json.JSONDecodeError:
                logger.debug("Invalid MCP response: %s", line)

    def _read_stderr(self) -> None:
        assert self._process and self._process.stderr
        for line in self._process.stderr:
            line = line.strip()
            if line:
                logger.debug("MCP stderr: %s", line)

    def _wait_for_response(self, request_id: int, timeout: float) -> Dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            remaining = max(0.0, deadline - time.monotonic())
            if remaining == 0.0:
                raise TimeoutError(f"MCP response timeout for id {request_id}")
            try:
                payload = self._queue.get(timeout=remaining)
            except queue.Empty as exc:
                raise TimeoutError(f"MCP response timeout for id {request_id}") from exc
            if payload.get("id") == request_id:
                return payload
            if payload.get("method") == "log":
                logger.debug("MCP log: %s", payload.get("params"))
            # Ignore unrelated messages and continue waiting.
