"""Lightweight CLI onboarding and doctor checks for Chintu."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Dict, Tuple

from chintu_backend.core.config import get_config


def _env_path() -> Path:
    return Path.cwd() / ".env"


def _read_env(path: Path) -> Dict[str, str]:
    data: Dict[str, str] = {}
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        data[key.strip()] = value.strip().strip('"')
    return data


def _write_env(path: Path, updates: Dict[str, str]) -> None:
    existing_lines = []
    if path.exists():
        existing_lines = path.read_text(encoding="utf-8").splitlines()

    seen = set()
    new_lines = []
    for line in existing_lines:
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            new_lines.append(line)
            continue
        key, _value = raw.split("=", 1)
        key = key.strip()
        if key in updates:
            value = updates[key]
            if any(c.isspace() for c in value):
                value = f"\"{value}\""
            new_lines.append(f"{key}={value}")
            seen.add(key)
        else:
            new_lines.append(line)

    for key, value in updates.items():
        if key in seen:
            continue
        if any(c.isspace() for c in value):
            value = f"\"{value}\""
        new_lines.append(f"{key}={value}")

    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def _prompt(text: str, default: str | None = None) -> str:
    if default:
        value = input(f"{text} [{default}]: ").strip()
        return value or default
    return input(f"{text}: ").strip()


def _prompt_yes_no(text: str, default: bool = True) -> bool:
    suffix = "Y/n" if default else "y/N"
    value = input(f"{text} ({suffix}): ").strip().lower()
    if not value:
        return default
    return value in {"y", "yes"}


def _store_secret(service: str, username: str, secret: str) -> Tuple[bool, str]:
    try:
        from chintu_backend.security import get_identity_vault

        vault = get_identity_vault()
        if vault.available:
            return vault.store_secret(service=service, username=username, secret=secret, note="onboarded")
        return False, vault.unavailable_reason or "identity vault unavailable"
    except Exception as exc:
        return False, str(exc)


def run_onboard() -> int:
    config = get_config()
    env_path = _env_path()
    updates: Dict[str, str] = {}

    print("Chintu onboarding (lightweight). Press Enter to accept defaults.\n")

    user_name = _prompt("Your name", config.user_name)
    assistant_name = _prompt("Assistant name", config.assistant_name)

    updates["CHINTU_USER_NAME"] = user_name
    updates["CHINTU_ASSISTANT_NAME"] = assistant_name

    enable_whatsapp = _prompt_yes_no("Enable WhatsApp gateway?", default=False)
    enable_telegram = _prompt_yes_no("Enable Telegram gateway?", default=False)

    updates["CHINTU_WHATSAPP_ENABLED"] = str(enable_whatsapp).lower()
    updates["CHINTU_TELEGRAM_ENABLED"] = str(enable_telegram).lower()

    # API keys
    if _prompt_yes_no("Configure Groq API key now?", default=False):
        groq_key = _prompt("Groq API Key")
        if groq_key:
            ok, msg = _store_secret("groq", "api_key", groq_key)
            if ok:
                print("Stored Groq key in Identity Vault.")
            else:
                print(f"Vault unavailable ({msg}), saving to .env instead.")
                updates["GROQ_API_KEY"] = groq_key

    if _prompt_yes_no("Configure Gemini API key now?", default=False):
        gemini_key = _prompt("Google AI Key")
        if gemini_key:
            ok, msg = _store_secret("gemini", "api_key", gemini_key)
            if ok:
                print("Stored Gemini key in Identity Vault.")
            else:
                print(f"Vault unavailable ({msg}), saving to .env instead.")
                updates["GOOGLE_AI_KEY"] = gemini_key

    if _prompt_yes_no("Configure DeepSeek API key now?", default=False):
        deepseek_key = _prompt("DeepSeek API Key")
        if deepseek_key:
            ok, msg = _store_secret("deepseek", "api_key", deepseek_key)
            if ok:
                print("Stored DeepSeek key in Identity Vault.")
            else:
                print(f"Vault unavailable ({msg}), saving to .env instead.")
                updates["DEEPSEEK_API_KEY"] = deepseek_key

    _write_env(env_path, updates)
    print(f"\nSaved configuration to {env_path}")
    return 0


def _status_line(name: str, ok: bool, detail: str = "") -> str:
    status = "OK" if ok else "WARN"
    suffix = f" - {detail}" if detail else ""
    return f"[{status}] {name}{suffix}"


def run_doctor() -> int:
    config = get_config()
    checks = []

    # Config + data dir
    checks.append(("Config loaded", True, ""))
    checks.append(("Data dir", config.data_dir.exists(), str(config.data_dir)))

    # Memory DB
    memory_ok = True
    detail = ""
    try:
        import sqlite3

        conn = sqlite3.connect(config.memory_sqlite_path)
        conn.execute("SELECT 1")
        conn.close()
    except Exception as exc:
        memory_ok = False
        detail = str(exc)
    checks.append(("Memory DB", memory_ok, detail))

    # Library
    checks.append(("Chintus_Library", config.library_root_dir.exists(), str(config.library_root_dir)))

    # Identity vault
    try:
        from chintu_backend.security import get_identity_vault

        vault = get_identity_vault()
        checks.append(("Identity Vault", vault.available, vault.unavailable_reason or ""))
    except Exception as exc:
        checks.append(("Identity Vault", False, str(exc)))

    # Ollama host (best-effort)
    ollama_ok = True
    ollama_detail = ""
    try:
        import urllib.request

        url = config.ollama_host.rstrip("/") + "/api/tags"
        with urllib.request.urlopen(url, timeout=2) as resp:
            if resp.status != 200:
                ollama_ok = False
                ollama_detail = f"HTTP {resp.status}"
    except Exception as exc:
        ollama_ok = False
        ollama_detail = str(exc)
    checks.append(("Ollama", ollama_ok, ollama_detail))

    # Training log
    checks.append(("Training log", config.training_log_path.parent.exists(), str(config.training_log_path)))

    # A2UI
    try:
        from chintu_backend.interfaces.ui import get_a2ui_service

        get_a2ui_service()
        checks.append(("A2UI", True, ""))
    except Exception as exc:
        checks.append(("A2UI", False, str(exc)))

    # Channel allowlist
    checks.append(("Channel allowlist", config.channel_allowlist_path.exists(), str(config.channel_allowlist_path)))
    # Agent registry
    checks.append(("Agent registry", config.agent_registry_path.exists(), str(config.agent_registry_path)))

    failures = 0
    for name, ok, detail in checks:
        print(_status_line(name, ok, detail))
        if not ok:
            failures += 1

    print(f"\nDoctor summary: {len(checks) - failures}/{len(checks)} checks OK")
    return 0 if failures == 0 else 1


def run_agents_list() -> int:
    from chintu_backend.agents.agent_directory import get_agent_directory

    directory = get_agent_directory()
    profiles = directory.list_profiles()
    if not profiles:
        print("No agents registered yet.")
        return 0
    for key, profile in profiles.items():
        print(
            f"- {key}: role={profile.role} id={profile.agent_id} "
            f"workspace={profile.workspace_dir}"
        )
    return 0


def run_agents_create(agent_key: str, role: str | None = None, workspace: str | None = None) -> int:
    from chintu_backend.agents.agent_directory import get_agent_directory

    directory = get_agent_directory()
    runtime = directory.get_or_create(
        agent_key,
        role=role,
        workspace_dir=Path(workspace) if workspace else None,
    )
    print(f"Created agent {agent_key} (role={runtime.role}) at {runtime.workspace_dir}")
    return 0


def run_agents_assign(channel: str, user_id: str, agent_key: str, role: str | None = None) -> int:
    from chintu_backend.channels.policy import ChannelPolicyManager
    from chintu_backend.agents.agent_directory import get_agent_directory

    policy = ChannelPolicyManager()
    policy.set_agent_profile(channel, user_id, agent_key, role or agent_key)
    directory = get_agent_directory()
    runtime = directory.get_or_create(agent_key, role=role or agent_key)
    print(
        f"Assigned {channel}:{user_id} -> {agent_key} "
        f"(role={runtime.role}, workspace={runtime.workspace_dir})"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Chintu CLI")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("onboard", help="Run lightweight onboarding wizard")
    sub.add_parser("doctor", help="Run health checks")
    agents = sub.add_parser("agents", help="Manage agent profiles and routing")
    agents_sub = agents.add_subparsers(dest="agents_cmd")
    agents_sub.add_parser("list", help="List registered agents")
    create_cmd = agents_sub.add_parser("create", help="Create an agent")
    create_cmd.add_argument("--key", required=True, help="Agent key (unique)")
    create_cmd.add_argument("--role", default=None, help="Agent role/policy")
    create_cmd.add_argument("--workspace", default=None, help="Workspace path")
    assign_cmd = agents_sub.add_parser("assign", help="Assign channel user to agent")
    assign_cmd.add_argument("--channel", required=True, help="Channel name (telegram/slack/discord/etc)")
    assign_cmd.add_argument("--user", required=True, help="User identifier for that channel")
    assign_cmd.add_argument("--agent", required=True, help="Agent key to assign")
    assign_cmd.add_argument("--role", default=None, help="Optional role override")

    args = parser.parse_args()

    if args.command == "onboard":
        return run_onboard()
    if args.command == "doctor":
        return run_doctor()
    if args.command == "agents":
        if args.agents_cmd == "list":
            return run_agents_list()
        if args.agents_cmd == "create":
            return run_agents_create(args.key, role=args.role, workspace=args.workspace)
        if args.agents_cmd == "assign":
            return run_agents_assign(args.channel, args.user, args.agent, role=args.role)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
