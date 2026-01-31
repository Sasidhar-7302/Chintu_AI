"""Gateway protocol helpers (JSON-RPC 2.0)."""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Optional, Tuple


def new_id() -> str:
    return uuid.uuid4().hex


def parse_message(raw: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Parse incoming JSON; returns (message, error)."""
    try:
        return json.loads(raw), None
    except Exception as exc:
        return None, f"invalid_json: {exc}"


def is_request(message: Dict[str, Any]) -> bool:
    return bool(message.get("method")) and message.get("jsonrpc") == "2.0"


def make_result(req_id: Any, result: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def make_error(req_id: Any, code: int, message: str, data: Any = None) -> Dict[str, Any]:
    payload = {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}
    if data is not None:
        payload["error"]["data"] = data
    return payload
