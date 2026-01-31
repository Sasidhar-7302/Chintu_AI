"""Home Assistant skill CLI (basic service call)."""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict

import requests


def _parse_kv(args: list[str]) -> Dict[str, str]:
    data: Dict[str, str] = {}
    for token in args:
        if '=' in token:
            key, value = token.split('=', 1)
            data[key.strip().lower()] = value.strip()
    return data


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python -m chintu_backend.skills.tools.hass service=domain.service entity_id=<id> [data=<json>]")
        return 0
    hass_url = os.getenv("HASS_URL")
    hass_token = os.getenv("HASS_TOKEN")
    if not hass_url or not hass_token:
        print("Missing HASS_URL or HASS_TOKEN. Set them in .env to enable Home Assistant calls.")
        return 0
    kv = _parse_kv(sys.argv[1:])
    service = kv.get('service') or kv.get('svc')
    entity_id = kv.get('entity_id') or kv.get('entity')
    raw_data = kv.get('data', '')
    if not service or not entity_id:
        print("Provide service=domain.service and entity_id=<id>.")
        return 0
    if '.' not in service:
        print("Service must be in form domain.service (e.g., light.turn_on).")
        return 0
    domain, action = service.split('.', 1)
    payload: Dict[str, Any] = {"entity_id": entity_id}
    if raw_data:
        try:
            payload.update(json.loads(raw_data))
        except json.JSONDecodeError:
            payload["data"] = raw_data
    url = hass_url.rstrip('/') + f"/api/services/{domain}/{action}"
    headers = {"Authorization": f"Bearer {hass_token}", "Content-Type": "application/json"}
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=12)
        if resp.status_code >= 400:
            raise RuntimeError(f"Home Assistant error {resp.status_code}: {resp.text}")
        print("Home Assistant service call sent.")
        return 0
    except Exception as exc:
        print(f"Home Assistant call failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
