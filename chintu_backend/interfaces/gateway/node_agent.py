"""Gateway-connected local node agent with receipt streaming."""

from __future__ import annotations

import json
import shlex
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from chintu_backend.core.safe_exec import get_safe_executor

from .client import GatewayClient


@dataclass
class NodeReceipt:
    ts_utc: str
    action: str
    ok: bool
    details: Dict[str, Any]


class GatewayNodeAgent:
    """Local node worker that executes approved local actions and reports receipts."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 18789,
        token: Optional[str] = None,
        channel: str = "node",
        role: str = "sandbox",
        receipts_path: Optional[Path] = None,
    ):
        self.client = GatewayClient(host=host, port=port, token=token)
        self.channel = channel
        self.role = role
        self.receipts_path = receipts_path or (Path.home() / ".chintu" / "gateway_node_receipts.jsonl")
        self._connected = False

    async def connect(self) -> None:
        if self._connected:
            return
        await self.client.connect()
        await self.client.update_session(channel=self.channel, agent_role=self.role, agent_key="node")
        self._connected = True

    async def close(self) -> None:
        await self.client.close()
        self._connected = False

    async def run_task(self, text: str, source: str = "node", context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        await self.connect()
        payload_context = dict(context or {})
        payload_context.setdefault("_channel", self.channel)
        payload_context.setdefault("_untrusted", True)
        result = await self.client.send_request(
            "assistant.handle",
            {
                "text": text,
                "source": source,
                "context": payload_context,
            },
        )
        receipt = NodeReceipt(
            ts_utc=datetime.now(timezone.utc).isoformat(),
            action="assistant.handle",
            ok=True,
            details={"text": text[:120], "response_preview": str(result)[:240]},
        )
        await self._emit_receipt(receipt)
        return result if isinstance(result, dict) else {"response": str(result)}

    async def call_tool(self, tool_method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        await self.connect()
        result = await self.client.send_request(tool_method, params or {})
        ok = bool((result or {}).get("ok", True)) if isinstance(result, dict) else True
        receipt = NodeReceipt(
            ts_utc=datetime.now(timezone.utc).isoformat(),
            action=tool_method,
            ok=ok,
            details={"params": params or {}, "result_preview": str(result)[:240]},
        )
        await self._emit_receipt(receipt)
        return result if isinstance(result, dict) else {"result": result}

    async def execute_local_command(
        self,
        command: str,
        cwd: Optional[str] = None,
        timeout_seconds: int = 60,
        approved: bool = False,
    ) -> Dict[str, Any]:
        """Execute command locally only when explicitly approved by caller."""
        if not approved:
            receipt = NodeReceipt(
                ts_utc=datetime.now(timezone.utc).isoformat(),
                action="local.exec",
                ok=False,
                details={"error": "approval_required", "command": command},
            )
            await self._emit_receipt(receipt)
            return {"ok": False, "error": "approval_required"}

        executor = get_safe_executor()
        args = shlex.split(command)
        result = executor.run(args=args, cwd=cwd, timeout=timeout_seconds)
        payload = {
            "ok": bool(result.success),
            "stdout": result.stdout,
            "stderr": result.stderr,
            "error": result.error,
            "returncode": result.returncode,
        }
        receipt = NodeReceipt(
            ts_utc=datetime.now(timezone.utc).isoformat(),
            action="local.exec",
            ok=bool(result.success),
            details={"command": command, "cwd": cwd, "returncode": result.returncode},
        )
        await self._emit_receipt(receipt)
        return payload

    async def _emit_receipt(self, receipt: NodeReceipt) -> None:
        self._write_receipt(receipt)
        try:
            await self.client.send_request("event.emit", {"type": "node.receipt", "data": asdict(receipt)})
        except Exception:
            # Receipt is still persisted locally; event streaming is best effort.
            return

    def _write_receipt(self, receipt: NodeReceipt) -> None:
        self.receipts_path.parent.mkdir(parents=True, exist_ok=True)
        with self.receipts_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(receipt), ensure_ascii=True) + "\n")

