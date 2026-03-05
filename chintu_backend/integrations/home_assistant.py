"""Home Assistant integration helpers (service calls).

CLI usage (via skill packs):
    python -m chintu_backend.integrations.home_assistant "service=light.turn_on entity_id=light.kitchen data={\"brightness\":150}"

Environment:
    - HASS_URL
    - HASS_TOKEN
"""

from __future__ import annotations

import json
import os
import shlex
import sys
from typing import Any, Dict, Optional

import requests


def _expand_argv(argv: list[str]) -> list[str]:
    """Allow skill runners to pass a whole query as one quoted arg."""
    if len(argv) == 1 and any(ch.isspace() for ch in argv[0]):
        try:
            return shlex.split(argv[0], posix=False)
        except Exception:
            return argv[0].split()
    return argv


def _parse_kv(args: list[str]) -> Dict[str, str]:
    data: Dict[str, str] = {}
    for token in args:
        if "=" in token:
            key, value = token.split("=", 1)
            data[key.strip().lower()] = value.strip()
    return data


def call_service(
    *,
    service: str,
    entity_id: str,
    data: Optional[Dict[str, Any]] = None,
    hass_url: Optional[str] = None,
    hass_token: Optional[str] = None,
    timeout_s: float = 12.0,
) -> None:
    hass_url = hass_url or os.getenv("HASS_URL")
    hass_token = hass_token or os.getenv("HASS_TOKEN")
    if not hass_url or not hass_token:
        raise RuntimeError("Missing HASS_URL or HASS_TOKEN.")

    if "." not in service:
        raise ValueError("service must be domain.service (e.g., light.turn_on).")

    domain, action = service.split(".", 1)
    payload: Dict[str, Any] = {"entity_id": entity_id}
    if data:
        payload.update(data)

    url = hass_url.rstrip("/") + f"/api/services/{domain}/{action}"
    headers = {"Authorization": f"Bearer {hass_token}", "Content-Type": "application/json"}
    resp = requests.post(url, headers=headers, json=payload, timeout=timeout_s)
    if resp.status_code >= 400:
        raise RuntimeError(f"Home Assistant error {resp.status_code}: {resp.text}")


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        print(
            "Usage: python -m chintu_backend.integrations.home_assistant "
            'service=domain.service entity_id=<id> [data=<json>]'
        )
        return 0

    argv = _expand_argv(argv)
    kv = _parse_kv(argv)

    service = kv.get("service") or kv.get("svc")
    entity_id = kv.get("entity_id") or kv.get("entity")
    raw_data = kv.get("data", "")
    if not service or not entity_id:
        print("Provide service=domain.service and entity_id=<id>.")
        return 0

    payload: Dict[str, Any] = {}
    if raw_data:
        try:
            payload.update(json.loads(raw_data))
        except json.JSONDecodeError:
            payload["data"] = raw_data

    try:
        call_service(service=service, entity_id=entity_id, data=payload or None)
        print("Home Assistant service call sent.")
        return 0
    except Exception as exc:
        print(f"Home Assistant call failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

