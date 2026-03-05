"""Quick standalone test for NVIDIA Kimi API.

This file is intentionally import-safe (no side effects) so pytest won't fail during collection.
Run it directly:
  venv\\Scripts\\python.exe scripts\\quick_nvidia_test.py
"""

from __future__ import annotations

import os

import requests


def main() -> int:
    api_key = os.environ.get("NVIDIA_API_KEY", "").strip()
    model = "moonshotai/kimi-k2-instruct"

    print("Testing NVIDIA API with Kimi K2...")
    print(f"Model: {model}")
    if not api_key:
        raise SystemExit("Missing NVIDIA_API_KEY in environment. Set it or store it in the Identity Vault.")

    try:
        response = requests.post(
            "https://integrate.api.nvidia.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Say hello in one word only."}],
                "max_tokens": 20,
                "temperature": 0.1,
            },
            timeout=30,
        )

        print(f"Status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            print(f"Response: {content}")
            print("[SUCCESS] NVIDIA API key is working!")
            return 0

        print(f"Error: {response.text[:500]}")
        print("[FAILED] API returned error")
        return 2

    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc}")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
