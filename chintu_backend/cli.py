"""Chintu operator CLI (Phase 4 - Enhanced).

Enhanced with:
- Comprehensive doctor diagnostics (GPU, VRAM, skills, channels, memory)
- Wizard onboarding flow
- Auto-repair suggestions
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Tuple, Dict, Any

from chintu_backend.core.config import get_config
from chintu_backend.automation.skills.skill_registry import SkillRegistry


# =============================================================================
# Formatting Helpers
# =============================================================================

def _print_kv(key: str, value) -> None:
    print(f"{key}: {value}")


def _status_line(name: str, ok: bool, detail: str = "") -> None:
    """Print a status line with OK/FAIL indicator."""
    status = "[OK]" if ok else "[FAIL]"
    detail_str = f" - {detail}" if detail else ""
    print(f"  {status} {name}{detail_str}")


def _warn_line(name: str, detail: str = "") -> None:
    """Print a warning line."""
    detail_str = f" - {detail}" if detail else ""
    print(f"  [WARN] {name}{detail_str}")


def _info_line(name: str, detail: str = "") -> None:
    """Print an info line."""
    detail_str = f" - {detail}" if detail else ""
    print(f"  [INFO] {name}{detail_str}")


def _safe_console_text(value: Any) -> str:
    """Best-effort sanitization for Windows cp1252 terminals."""
    text = str(value or "")
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        return text.encode(encoding, errors="replace").decode(encoding, errors="replace")
    except Exception:
        return text.encode("ascii", errors="replace").decode("ascii", errors="replace")


# =============================================================================
# Health Check Helpers
# =============================================================================

def _check_gateway(port: int = 18789) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.5)
    try:
        return sock.connect_ex(("127.0.0.1", port)) == 0
    finally:
        sock.close()


def _check_gpu() -> Tuple[bool, str, Dict[str, Any]]:
    """Check GPU availability and VRAM."""
    gpu_info: Dict[str, Any] = {"available": False, "name": None, "vram_total": 0, "vram_free": 0}
    
    try:
        import torch
        if torch.cuda.is_available():
            gpu_info["available"] = True
            gpu_info["name"] = torch.cuda.get_device_name(0)
            gpu_info["vram_total"] = torch.cuda.get_device_properties(0).total_memory // (1024**3)
            gpu_info["vram_free"] = (torch.cuda.get_device_properties(0).total_memory - torch.cuda.memory_allocated(0)) // (1024**3)
            return True, f"{gpu_info['name']} ({gpu_info['vram_free']}GB/{gpu_info['vram_total']}GB free)", gpu_info
        else:
            return False, "CUDA not available", gpu_info
    except ImportError:
        return False, "PyTorch not installed", gpu_info
    except Exception as e:
        return False, str(e), gpu_info


def _check_ollama() -> Tuple[bool, str]:
    """Check if Ollama is running and responsive."""
    try:
        import httpx
        response = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
        if response.status_code == 200:
            models = response.json().get("models", [])
            model_names = [m.get("name", "?") for m in models[:3]]
            return True, f"{len(models)} models ({', '.join(model_names)}{'...' if len(models) > 3 else ''})"
        return False, f"HTTP {response.status_code}"
    except Exception as e:
        return False, str(e)


def _check_vision_models() -> Tuple[bool, str]:
    """Check whether at least one local vision model is available in Ollama."""
    try:
        import httpx

        response = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
        if response.status_code != 200:
            return False, f"Ollama tags HTTP {response.status_code}"
        models = [str((m or {}).get("name") or "").lower() for m in response.json().get("models", [])]
        vision_hits = [
            name
            for name in models
            if any(token in name for token in ("llava", "vision", "qwen2.5-vl", "moondream"))
        ]
        if vision_hits:
            preview = ", ".join(vision_hits[:3]) + ("..." if len(vision_hits) > 3 else "")
            return True, preview
        return False, "No local vision model found (install llava:7b or qwen2.5-vl:7b)"
    except Exception as e:
        return False, str(e)


def _check_docker() -> Tuple[bool, str]:
    """Check Docker CLI + daemon availability."""
    try:
        proc = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except FileNotFoundError:
        return False, "docker not found"
    except Exception as e:
        return False, str(e)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        return False, detail[:140] or "docker daemon unavailable"
    version = (proc.stdout or "").strip()
    return True, f"daemon online ({version})" if version else "daemon online"


def _check_skills() -> Tuple[int, int, List[str]]:
    """Check skills health. Returns (loaded_count, error_count, errors)."""
    config = get_config()
    registry = SkillRegistry()
    sources = [
        (config.skills_bundled_dir, "bundled"),
        (config.skills_learned_dir, "learned"),
        (config.skills_user_dir, "user"),
        (config.skills_dir, "workspace"),
    ]
    sources = [(path, label) for path, label in sources if path]
    
    errors = []
    try:
        registry.load_sources(sources)
    except Exception as e:
        errors.append(f"Load error: {e}")
    
    skills = list(registry._skills.values())
    return len(skills), len(errors), errors


def _check_memory() -> Tuple[bool, str]:
    """Check memory system health."""
    config = get_config()
    if not config.memory_enabled:
        return True, "disabled"
    
    try:
        md_dir = config.memory_markdown_dir
        if md_dir and md_dir.exists():
            file_count = len(list(md_dir.glob("*.md")))
            return True, f"markdown sync ({file_count} files)"
        
        # Check SQLite
        db_path = getattr(config, "memory_sqlite_path", None)
        if db_path and Path(db_path).exists():
            return True, "hybrid (SQLite)"
        
        return True, "enabled"
    except Exception as e:
        return False, str(e)


def _check_channels() -> Tuple[bool, str, Dict[str, bool]]:
    """Check channel status (WhatsApp, Telegram)."""
    status: Dict[str, bool] = {"telegram": False, "whatsapp": False}
    
    # Check Telegram
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if telegram_token:
        status["telegram"] = True
    
    # Check WhatsApp (basic check for Baileys session)
    config = get_config()
    whatsapp_session = config.data_dir / "whatsapp_session"
    if whatsapp_session.exists():
        status["whatsapp"] = True
    
    active = [k for k, v in status.items() if v]
    if active:
        return True, f"active: {', '.join(active)}", status
    return False, "no channels configured", status


def _check_env_keys() -> Dict[str, bool]:
    """Check for required API keys in environment."""
    keys = {
        "NVIDIA_API_KEY": bool(os.environ.get("NVIDIA_API_KEY", "")),
        "GROQ_API_KEY": bool(os.environ.get("GROQ_API_KEY", "")),
        "GOOGLE_AI_KEY": bool(os.environ.get("GOOGLE_AI_KEY", "")),
        "DEEPSEEK_API_KEY": bool(os.environ.get("DEEPSEEK_API_KEY", "")),
        "TELEGRAM_BOT_TOKEN": bool(os.environ.get("TELEGRAM_BOT_TOKEN", "")),
    }
    return keys


# =============================================================================
# Doctor Command (Enhanced)
# =============================================================================

def doctor(verbose: bool = False) -> int:
    """Run comprehensive health checks."""
    config = get_config()
    issues: List[str] = []
    
    print("=" * 60)
    print("CHINTU DOCTOR - Comprehensive Health Report")
    print("=" * 60)
    
    # 1. Core Paths
    print("\n[Core Paths]")
    _print_kv("  data_dir", config.data_dir)
    if not config.data_dir.exists():
        issues.append("data_dir missing - run 'chintu wizard' to create")
        _status_line("data_dir exists", False)
    else:
        _status_line("data_dir exists", True)
    
    # 2. Gateway
    print("\n[Gateway]")
    try:
        from chintu_backend.core.gateway_supervisor import get_gateway_supervisor
        supervisor = get_gateway_supervisor()
        health = supervisor.health_check()
        
        status_detail = f"PID: {supervisor._state.pid}" if health.healthy else "Stopped"
        if health.uptime_seconds > 0:
            status_detail += f", Uptime: {int(health.uptime_seconds // 3600)}h {int((health.uptime_seconds % 3600) // 60)}m"
            
        _status_line("Gateway Service", health.healthy, status_detail)
        
        # Disk/Memory from supervisor
        if health.memory_mb > 0:
            _info_line("Gateway Memory", f"{health.memory_mb:.0f} MB")
            
        if not health.healthy:
            issues.append("Gateway service unhealthy or stopped")
            for err in health.errors:
                _warn_line("Health Error", err)
                
    except ImportError:
        # Fallback to simple socket check
        gateway_ok = _check_gateway()
        _status_line("Gateway running (sock)", gateway_ok)
        if not gateway_ok:
            issues.append("Gateway not running - run 'chintu gateway start'")
    
    # 3. GPU/VRAM
    print("\n[GPU/VRAM]")
    gpu_ok, gpu_detail, gpu_info = _check_gpu()
    _status_line("CUDA GPU", gpu_ok, gpu_detail)
    if gpu_ok and gpu_info.get("vram_total", 0) >= 12:
        _info_line("3060+ profile", "12GB VRAM detected, using optimized settings")
    elif gpu_ok and gpu_info.get("vram_total", 0) < 6:
        _warn_line("Low VRAM", "Consider using cloud models primarily")
    
    # 4. Ollama (Local LLM)
    print("\n[Local LLM (Ollama)]")
    ollama_ok, ollama_detail = _check_ollama()
    _status_line("Ollama running", ollama_ok, ollama_detail)
    if not ollama_ok:
        issues.append("Ollama not running - start with 'ollama serve'")

    # 4.5 Vision model readiness
    print("\n[Vision Runtime]")
    vision_ok, vision_detail = _check_vision_models()
    _status_line("Vision model installed", vision_ok, vision_detail)
    if not vision_ok:
        issues.append("No local vision model installed for UI/screenshot tasks")

    # 4.6 Docker sandbox
    print("\n[Docker Sandbox]")
    docker_ok, docker_detail = _check_docker()
    _status_line("Docker daemon", docker_ok, docker_detail)
    if not docker_ok:
        _warn_line("Sandbox fallback", "Chintu will use uv/local fallback when Docker is unavailable")
    
    # 5. API Keys
    print("\n[Cloud LLM Keys]")
    env_keys = _check_env_keys()
    for key, present in env_keys.items():
        if key in ["NVIDIA_API_KEY", "GROQ_API_KEY", "GOOGLE_AI_KEY"]:  # Primary cloud LLMs
            _status_line(key, present, "set" if present else "missing")
    if not any([env_keys["NVIDIA_API_KEY"], env_keys["GROQ_API_KEY"], env_keys["GOOGLE_AI_KEY"]]):
        _warn_line("No cloud LLM keys", "Run 'chintu wizard' to configure")
    
    # 6. Skills
    print("\n[Skills]")
    skill_count, skill_errors, skill_error_list = _check_skills()
    _status_line("Skills loaded", skill_errors == 0, f"{skill_count} skills")
    if skill_errors > 0:
        for err in skill_error_list[:3]:
            _warn_line("Skill error", err)
    if config.skills_enabled and config.skills_dir and not config.skills_dir.exists():
        _warn_line("skills_dir missing", str(config.skills_dir))
    
    # 7. Memory
    print("\n[Memory System]")
    mem_ok, mem_detail = _check_memory()
    _status_line("Memory", mem_ok, mem_detail)

    # 7.5 GCC Context Controller (Git-style long-horizon memory)
    print("\n[GCC Context]")
    if getattr(config, "gcc_enabled", True):
        try:
            from chintu_backend.brain.learning.gcc_context_controller import get_gcc_controller

            gcc = get_gcc_controller()
            info = gcc.initialize(project_goal=getattr(config, "gcc_default_goal", ""))
            branches = info.get("branches") or []
            _status_line("GCC enabled", True, f"{len(branches)} branches")
            _print_kv("  gcc_root", getattr(config, "gcc_root_dir", None) or (Path.cwd() / ".GCC"))
        except Exception as e:
            issues.append("GCC context controller unavailable")
            _status_line("GCC enabled", False, str(e)[:120])
    else:
        _info_line("GCC", "disabled")
    
    # 8. Channels
    print("\n[Channels]")
    channels_ok, channels_detail, channel_status = _check_channels()
    _status_line("Channels", channels_ok, channels_detail)
    if not channel_status["telegram"]:
        _info_line("Telegram", "Set TELEGRAM_BOT_TOKEN to enable")
    if not channel_status["whatsapp"]:
        _info_line("WhatsApp", "Run WhatsApp pairing to enable")
    
    # 9. Exec Approvals
    print("\n[Security]")
    if config.exec_approval_enabled:
        approval_path = config.exec_approval_path or (config.data_dir / "exec_approvals.json")
        _status_line("Exec approval enabled", True, str(approval_path))
    else:
        _info_line("Exec approval", "disabled")

    # 9.5 MCP bus
    print("\n[MCP]")
    _status_line("MCP enabled", bool(config.mcp_enabled), f"servers={len(config.mcp_servers)}")
    if not config.mcp_enabled:
        _warn_line("MCP disabled", "Enable CHINTU_MCP_ENABLED=true for tool-bus interoperability")

    # Summary
    print("\n" + "=" * 60)
    if issues:
        print(f"ISSUES FOUND: {len(issues)}")
        for issue in issues:
            print(f"  - {issue}")
        print("\nRun 'chintu wizard' for guided setup.")
        return 2
    else:
        print("ALL CHECKS PASSED")
        return 0


# =============================================================================
# Wizard Command (Onboarding)
# =============================================================================

def wizard() -> int:
    """Interactive onboarding wizard."""
    print("=" * 60)
    print("CHINTU WIZARD - Guided Setup")
    print("=" * 60)
    
    config = get_config()
    env_path = Path.cwd() / ".env"
    env_vars: Dict[str, str] = {}
    
    # Load existing .env
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key, _, value = line.partition("=")
                env_vars[key.strip()] = value.strip()
    
    # Step 1: Data directory
    print("\n[Step 1/4] Data Directory")
    if not config.data_dir.exists():
        create = input(f"  Create {config.data_dir}? [Y/n]: ").strip().lower()
        if create != "n":
            config.data_dir.mkdir(parents=True, exist_ok=True)
            print(f"  Created: {config.data_dir}")
    else:
        print(f"  Already exists: {config.data_dir}")
    
    # Step 2: Cloud LLM Keys
    print("\n[Step 2/4] Cloud LLM Keys")
    
    if not os.environ.get("NVIDIA_API_KEY"):
        nvidia_key = input("  NVIDIA API Key (Kimi K2) [Enter to skip]: ").strip()
        if nvidia_key:
            env_vars["NVIDIA_API_KEY"] = nvidia_key
            env_vars["NVIDIA_MODEL"] = "moonshotai/kimi-k2-instruct"
            print("  Added NVIDIA_API_KEY")
    else:
        print("  NVIDIA_API_KEY already set")
    
    if not os.environ.get("GROQ_API_KEY"):
        groq_key = input("  Groq API Key [Enter to skip]: ").strip()
        if groq_key:
            env_vars["GROQ_API_KEY"] = groq_key
            print("  Added GROQ_API_KEY")
    else:
        print("  GROQ_API_KEY already set")
    
    if not os.environ.get("GOOGLE_AI_KEY"):
        gemini_key = input("  Gemini API Key [Enter to skip]: ").strip()
        if gemini_key:
            env_vars["GOOGLE_AI_KEY"] = gemini_key
            print("  Added GOOGLE_AI_KEY")
    else:
        print("  GOOGLE_AI_KEY already set")
    
    # Step 3: Channels
    print("\n[Step 3/4] Channels (WhatsApp/Telegram)")
    
    if not os.environ.get("TELEGRAM_BOT_TOKEN"):
        telegram_token = input("  Telegram Bot Token [Enter to skip]: ").strip()
        if telegram_token:
            env_vars["TELEGRAM_BOT_TOKEN"] = telegram_token
            print("  Added TELEGRAM_BOT_TOKEN")
    else:
        print("  TELEGRAM_BOT_TOKEN already set")
    
    print("  WhatsApp: Run 'chintu whatsapp pair' after setup to link device")
    
    # Step 4: Save .env
    print("\n[Step 4/4] Save Configuration")
    if env_vars:
        # Read existing content
        existing_content = ""
        if env_path.exists():
            existing_content = env_path.read_text()
        
        # Append new vars
        new_lines = []
        for key, value in env_vars.items():
            if key not in existing_content:
                new_lines.append(f"{key}={value}")
        
        if new_lines:
            with open(env_path, "a") as f:
                f.write("\n" + "\n".join(new_lines) + "\n")
            print(f"  Updated: {env_path}")
            print(f"  Added {len(new_lines)} new variables")
    else:
        print("  No changes to save")
    
    print("\n" + "=" * 60)
    print("Setup complete! Run 'chintu doctor' to verify.")
    print("Start Chintu with: python -m chintu_backend")
    print("=" * 60)
    
    return 0


# =============================================================================
# Config Command
# =============================================================================

def config_cmd(args: argparse.Namespace) -> int:
    config = get_config()
    if args.subcommand == "get":
        value = getattr(config, args.key, None)
        _print_kv(args.key, value)
        return 0
    if args.subcommand == "paths":
        _print_kv("data_dir", config.data_dir)
        _print_kv("models_dir", config.models_dir)
        _print_kv("memory_markdown_dir", config.memory_markdown_dir)
        _print_kv("skills_dir", config.skills_dir)
        _print_kv("skills_user_dir", config.skills_user_dir)
        _print_kv("skills_bundled_dir", config.skills_bundled_dir)
        _print_kv("skills_learned_dir", config.skills_learned_dir)
        _print_kv("skills_proposals_dir", config.skills_proposals_dir)
        _print_kv("channel_allowlist_path", config.channel_allowlist_path)
        _print_kv("exec_approval_path", config.exec_approval_path)
        return 0
    return 1


# =============================================================================
# Learning Command
# =============================================================================

def learning_cmd(args: argparse.Namespace) -> int:
    from chintu_backend.brain.learning.weekly_trainer import (
        approve_pending_adapter_activation,
        get_biweekly_learning_status,
        get_pending_adapter_activation,
        run_biweekly_learning,
    )
    from chintu_backend.training.biweekly_export import export_biweekly_datasets

    if args.subcommand == "status":
        status = get_biweekly_learning_status()
        _print_kv("enabled", status.get("enabled"))
        _print_kv("interval_days", status.get("interval_days"))
        _print_kv("target_day", status.get("target_day"))
        _print_kv("target_hour_utc", status.get("target_hour"))
        _print_kv("last_run", status.get("last_run") or "never")
        _print_kv("next_run_estimate", status.get("next_run_estimate") or "pending")
        _print_kv("last_training_message", status.get("last_training_message") or "none")
        _print_kv("last_export_path", status.get("last_export_path") or "none")
        _print_kv("last_export_manifest", status.get("last_export_manifest") or "none")
        _print_kv("last_biweekly_approved_ts", status.get("last_biweekly_approved_ts") or "none")
        pending = status.get("pending_adapter_activation") if isinstance(status, dict) else {}
        _print_kv("pending_adapter_activation", bool((pending or {}).get("pending")))
        phase29_gate = (pending or {}).get("phase29_gate") if isinstance(pending, dict) else {}
        if isinstance(phase29_gate, dict) and phase29_gate:
            _print_kv("phase29_gate_required", bool(phase29_gate.get("required")))
            _print_kv("phase29_gate_ok", bool(phase29_gate.get("ok")))
            _print_kv("phase29_gate_message", phase29_gate.get("message") or "")
        if (pending or {}).get("pending"):
            _print_kv("pending_adapter_path", (pending or {}).get("adapter_path") or "")
            _print_kv("pending_adapter_created_at", (pending or {}).get("created_at") or "")
        _print_kv(
            "last_export_counts",
            f"style={status.get('last_export_style_count', 0)} "
            f"facts={status.get('last_export_facts_count', 0)} "
            f"memory={status.get('last_export_memory_count', 0)}",
        )
        return 0

    if args.subcommand == "run":
        status = run_biweekly_learning(force=bool(getattr(args, "force", False)))
        _print_kv("ok", status.ok)
        _print_kv("message", status.message)
        _print_kv("export_path", status.export_path or "")
        _print_kv("manifest_path", status.manifest_path or "")
        _print_kv(
            "counts",
            f"style={status.style_count} facts={status.facts_count} memory={status.memory_count}",
        )
        _print_kv("trained", status.trained)
        _print_kv("activation_pending", status.activation_pending)
        if status.pending_activation_path:
            _print_kv("pending_activation_path", status.pending_activation_path)
        return 0 if status.ok else 2

    if args.subcommand == "export":
        status = get_biweekly_learning_status()
        result = export_biweekly_datasets(
            since_timestamp=None if getattr(args, "full", False) else status.get("last_biweekly_approved_ts") or None,
            include_memory=not bool(getattr(args, "skip_memory", False)),
            memory_limit=int(getattr(args, "memory_limit", 1000)),
        )
        _print_kv("style_path", result.style_path)
        _print_kv("facts_path", result.facts_path)
        _print_kv("memory_path", result.memory_path or "")
        _print_kv(
            "counts",
            f"style={result.style_count} facts={result.facts_count} memory={result.memory_count}",
        )
        _print_kv("manifest_path", result.manifest_path or "")
        return 0

    if args.subcommand == "pending-activation":
        pending = get_pending_adapter_activation()
        _print_kv("pending", bool(pending.get("pending")))
        _print_kv("path", pending.get("path") or "")
        _print_kv("adapter_path", pending.get("adapter_path") or "")
        _print_kv("created_at", pending.get("created_at") or "")
        _print_kv("status", pending.get("status") or "")
        gate = pending.get("phase29_gate") if isinstance(pending, dict) else {}
        if isinstance(gate, dict) and gate:
            _print_kv("phase29_gate_required", bool(gate.get("required")))
            _print_kv("phase29_gate_ok", bool(gate.get("ok")))
            _print_kv("phase29_gate_message", gate.get("message") or "")
        return 0

    if args.subcommand == "approve-activation":
        ok, message, payload = approve_pending_adapter_activation(
            actor="cli",
            expected_adapter_path=getattr(args, "adapter_path", None),
        )
        _print_kv("ok", ok)
        _print_kv("message", message)
        _print_kv("adapter_path", (payload or {}).get("adapter_path") or "")
        _print_kv("approved_at", (payload or {}).get("approved_at") or "")
        return 0 if ok else 2

    if args.subcommand == "gcc":
        return learning_gcc_cmd(args)

    return 1


def learning_gcc_cmd(args: argparse.Namespace) -> int:
    from chintu_backend.brain.learning.gcc_context_controller import get_gcc_controller

    gcc = get_gcc_controller()
    command = getattr(args, "gcc_command", None)

    if command == "init":
        res = gcc.initialize(project_goal=getattr(args, "goal", "") or "")
        _print_kv("root", res.get("root"))
        _print_kv("current_branch", res.get("current_branch"))
        _print_kv("branches", ",".join(res.get("branches", [])))
        return 0

    if command == "status":
        res = gcc.status()
        _print_kv("root", res.get("root"))
        _print_kv("current_branch", res.get("current_branch"))
        _print_kv("branches", ",".join(res.get("branches", [])))
        _print_kv("main_excerpt", (res.get("main_excerpt") or "")[:1000])
        return 0

    if command == "checkout":
        res = gcc.checkout(getattr(args, "name"))
        _print_kv("current_branch", res.get("current_branch"))
        return 0

    if command == "branch":
        res = gcc.create_branch(
            getattr(args, "name"),
            purpose=getattr(args, "purpose", "") or "",
            from_branch=getattr(args, "from_branch", None),
            switch=not bool(getattr(args, "no_switch", False)),
        )
        _print_kv("branch", res.get("branch"))
        _print_kv("from_branch", res.get("from_branch"))
        _print_kv("current_branch", res.get("current_branch"))
        _print_kv("purpose", res.get("purpose"))
        return 0

    if command == "log":
        res = gcc.append_log(
            observation=getattr(args, "observation", "") or "",
            thought=getattr(args, "thought", "") or "",
            action=getattr(args, "action", "") or "",
            result=getattr(args, "result", "") or "",
            branch=getattr(args, "branch", None),
        )
        _print_kv("branch", res.get("branch"))
        _print_kv("pending_events_since_commit", res.get("pending_events_since_commit"))
        return 0

    if command == "commit":
        res = gcc.commit(
            summary=getattr(args, "summary", "") or "",
            branch=getattr(args, "branch", None),
            contribution=getattr(args, "contribution", "") or "",
            update_main=bool(getattr(args, "update_main", False)),
            roadmap_note=getattr(args, "roadmap_note", "") or "",
        )
        _print_kv("branch", res.get("branch"))
        _print_kv("commit_id", res.get("commit_id"))
        _print_kv("commit_count", res.get("commit_count"))
        _print_kv("summary", res.get("summary"))
        return 0

    if command == "merge":
        res = gcc.merge(
            source_branch=getattr(args, "source"),
            into_branch=getattr(args, "into", "main"),
            summary=getattr(args, "summary", "") or "",
        )
        _print_kv("source", res.get("source"))
        _print_kv("into", res.get("into"))
        _print_kv("summary", res.get("summary"))
        return 0

    if command == "context":
        res = gcc.context(
            branch=getattr(args, "branch", None),
            commit_id=getattr(args, "commit", None),
            log_lines=int(getattr(args, "log_lines", 20)),
            metadata_key=getattr(args, "metadata_key", None),
        )
        _print_kv("root", res.get("root"))
        _print_kv("current_branch", res.get("current_branch"))
        _print_kv("branch", res.get("branch"))
        _print_kv("branches", ",".join(res.get("branches", [])))
        if res.get("commit_block"):
            _print_kv("commit_block", res.get("commit_block"))
        else:
            latest = res.get("latest_commits", [])
            _print_kv("latest_commit_count", len(latest))
            if latest:
                _print_kv("latest_commit_head", latest[-1][:400])
        _print_kv("log_tail", res.get("log_tail", ""))
        _print_kv("metadata", json.dumps(res.get("metadata", {}), ensure_ascii=True))
        return 0

    return 1


# =============================================================================
# Gates Command
# =============================================================================

def _gate_script_path(script_name: str) -> Path:
    return Path(__file__).resolve().parents[1] / "scripts" / script_name


def _run_gate_script(script_name: str, extra_args: List[str] | None = None) -> int:
    script_path = _gate_script_path(script_name)
    if not script_path.exists():
        print(f"Missing gate script: {script_path}")
        return 2
    cmd = [sys.executable, str(script_path)]
    if extra_args:
        cmd.extend([str(a) for a in extra_args if str(a).strip()])
    print(f"Running: {' '.join(cmd)}")
    proc = subprocess.run(cmd, check=False)
    return int(proc.returncode)


def gates_cmd(args: argparse.Namespace) -> int:
    sub = getattr(args, "subcommand", "")
    if sub == "phase17":
        extra: List[str] = []
        if getattr(args, "top_n", None):
            extra.extend(["--top-n", str(args.top_n)])
        if getattr(args, "large_file_threshold", None):
            extra.extend(["--large-file-threshold", str(args.large_file_threshold)])
        return _run_gate_script("phase17_maintainability_gate.py", extra)

    if sub == "phase19":
        return _run_gate_script("phase19_workflow_pack_benchmark.py", [])

    if sub == "phase18":
        extra = []
        if bool(getattr(args, "skip_flutter_tests", False)):
            extra.append("--skip-flutter-tests")
        return _run_gate_script("phase18_ui_vnext_gate.py", extra)

    if sub == "ci":
        extra = []
        if bool(getattr(args, "skip_flutter_tests", False)):
            extra.append("--skip-flutter-tests")
        return _run_gate_script("ci_quality_gate.py", extra)

    if sub == "release":
        extra = []
        if bool(getattr(args, "run_package_smoke", False)):
            extra.append("--run-package-smoke")
        return _run_gate_script("release_readiness_gate.py", extra)

    if sub == "preflight":
        extra = []
        if bool(getattr(args, "run_doctor", False)):
            extra.append("--run-doctor")
        if bool(getattr(args, "run_docker_check", False)):
            extra.append("--run-docker-check")
        if bool(getattr(args, "strict_docker", False)):
            extra.append("--strict-docker")
        return _run_gate_script("deployment_preflight_gate.py", extra)

    if sub == "phase27":
        return _run_gate_script("phase27_persona_specialist_gate.py", [])

    if sub == "phase28":
        return _run_gate_script("phase28_telegram_control_plane_gate.py", [])

    if sub == "phase29":
        extra = []
        if bool(getattr(args, "skip_workflow_benchmark", False)):
            extra.append("--skip-workflow-benchmark")
        if bool(getattr(args, "skip_eval_gate", False)):
            extra.append("--skip-eval-gate")
        return _run_gate_script("phase29_autonomy_integration_gate.py", extra)

    if sub == "all":
        rc17 = _run_gate_script(
            "phase17_maintainability_gate.py",
            ["--top-n", str(getattr(args, "top_n", 10) or 10)],
        )
        extra18 = []
        if bool(getattr(args, "skip_flutter_tests", False)):
            extra18.append("--skip-flutter-tests")
        rc18 = _run_gate_script("phase18_ui_vnext_gate.py", extra18)
        rc19 = _run_gate_script("phase19_workflow_pack_benchmark.py", [])
        rc27 = _run_gate_script("phase27_persona_specialist_gate.py", [])
        rc28 = _run_gate_script("phase28_telegram_control_plane_gate.py", [])
        extra29 = []
        if bool(getattr(args, "skip_workflow_benchmark", False)):
            extra29.append("--skip-workflow-benchmark")
        if bool(getattr(args, "skip_eval_gate", False)):
            extra29.append("--skip-eval-gate")
        rc29 = _run_gate_script("phase29_autonomy_integration_gate.py", extra29)
        rc_preflight = _run_gate_script("deployment_preflight_gate.py", [])
        rc_release = _run_gate_script("release_readiness_gate.py", [])
        return 0 if (
            rc17 == 0
            and rc18 == 0
            and rc19 == 0
            and rc27 == 0
            and rc28 == 0
            and rc29 == 0
            and rc_preflight == 0
            and rc_release == 0
        ) else 1

    print("Usage: chintu gates [phase17|phase18|phase19|phase27|phase28|phase29|preflight|release|ci|all]")
    return 1


# =============================================================================
# Skills Command
# =============================================================================

def skills_cmd(args: argparse.Namespace) -> int:
    config = get_config()
    subcommand = str(getattr(args, "subcommand", "") or "").strip().lower()

    if subcommand == "catalog":
        from chintu_backend.automation.skills.catalog import list_catalog_entries

        stage = str(getattr(args, "stage", "all") or "all")
        ids_raw = str(getattr(args, "ids", "") or "").strip()
        selected = [x.strip() for x in ids_raw.split(",") if x.strip()] if ids_raw else None
        rows = list_catalog_entries(stage=stage, selected_ids=selected)
        if getattr(args, "json", False):
            payload = []
            for row in rows:
                payload.append(
                    {
                        "skill_id": row.skill_id,
                        "name": row.name,
                        "stage": row.stage,
                        "summary": row.summary,
                        "install_strategy": row.install_strategy,
                        "source_label": row.source_label,
                        "source_path": row.source_path,
                        "reference_url": row.reference_url,
                        "risk": row.risk,
                        "tags": row.tags,
                    }
                )
            print(json.dumps(payload, indent=2))
            return 0
        if not rows:
            print("No catalog entries matched filters.")
            return 0
        print(f"Catalog entries ({len(rows)}):\n")
        for row in rows:
            source_hint = row.source_path or row.reference_url or "n/a"
            print(f"  {row.skill_id} [{row.stage}] ({row.install_strategy})")
            print(f"    {row.summary}")
            print(f"    source={row.source_label} -> {source_hint}")
        return 0

    if subcommand == "bootstrap":
        from chintu_backend.automation.skills.bootstrap import (
            apply_skill_bootstrap_plan,
            build_skill_bootstrap_plan,
        )

        stage = str(getattr(args, "stage", "initial") or "initial")
        ids_raw = str(getattr(args, "ids", "") or "").strip()
        selected = [x.strip() for x in ids_raw.split(",") if x.strip()] if ids_raw else None
        workspace_dir = Path(str(getattr(args, "workspace_dir", "") or "")).expanduser() if getattr(args, "workspace_dir", None) else config.skills_dir
        if not workspace_dir:
            print("ERROR: workspace skills directory is not configured.")
            return 2
        registry = SkillRegistry()
        sources = [
            (config.skills_bundled_dir, "bundled"),
            (config.skills_learned_dir, "learned"),
            (config.skills_user_dir, "user"),
            (config.skills_dir, "workspace"),
        ]
        sources = [(path, label) for path, label in sources if path]
        registry.load_sources(sources)
        existing_names = {spec.name for spec in registry._skills.values()}

        if bool(getattr(args, "apply", False)):
            receipt_path = None
            if getattr(args, "receipt", None):
                receipt_path = Path(str(args.receipt)).expanduser()
            report = apply_skill_bootstrap_plan(
                workspace_dir=Path(workspace_dir),
                stage=stage,
                selected_ids=selected,
                existing_skill_names=existing_names,
                overwrite=bool(getattr(args, "overwrite", False)),
                receipt_path=receipt_path,
            )
        else:
            report = build_skill_bootstrap_plan(
                workspace_dir=Path(workspace_dir),
                stage=stage,
                selected_ids=selected,
                existing_skill_names=existing_names,
            )
        print(json.dumps(report.to_dict(), indent=2))
        return 0

    if subcommand == "scout-github":
        from chintu_backend.automation.skills.third_party import scout_github_skill_repos

        query = str(getattr(args, "query", "") or "").strip()
        limit = int(getattr(args, "limit", 10) or 10)
        token = str(getattr(args, "token", "") or "").strip()
        rows = scout_github_skill_repos(query=query, limit=limit, token=token)
        if getattr(args, "json", False):
            print(json.dumps([row.to_dict() for row in rows], indent=2))
            return 0
        if not rows:
            print("No candidates found.")
            return 0
        print(f"GitHub candidates ({len(rows)}):\n")
        for row in rows:
            print(_safe_console_text(f"  {row.full_name} [stars={row.stars}]"))
            if row.description:
                print(_safe_console_text(f"    {row.description}"))
            print(_safe_console_text(f"    {row.html_url}"))
        return 0

    if subcommand == "import-github":
        from chintu_backend.automation.skills.third_party import import_skill_from_github

        repo = str(getattr(args, "repo", "") or "").strip()
        path_in_repo = str(getattr(args, "path", "SKILL.md") or "SKILL.md").strip()
        ref = str(getattr(args, "ref", "main") or "main").strip()
        approved = bool(getattr(args, "approve", False))
        target_root = None
        if getattr(args, "target_dir", None):
            target_root = Path(str(args.target_dir)).expanduser()
        result = import_skill_from_github(
            repo=repo,
            path_in_repo=path_in_repo,
            ref=ref,
            approved=approved,
            target_root=target_root,
        )
        print(json.dumps(result.to_dict(), indent=2))
        return 0 if result.ok else 2

    if subcommand == "discover-github-paths":
        from chintu_backend.automation.skills.third_party import discover_skill_paths

        repo = str(getattr(args, "repo", "") or "").strip()
        ref = str(getattr(args, "ref", "main") or "main").strip()
        token = str(getattr(args, "token", "") or "").strip()
        paths = discover_skill_paths(repo=repo, ref=ref, token=token)
        if getattr(args, "json", False):
            print(json.dumps(paths, indent=2))
            return 0
        if not paths:
            print("No SKILL.md-style paths found.")
            return 1
        print(f"Discovered skill paths ({len(paths)}):\n")
        for path in paths:
            print(f"  {path}")
        return 0

    if subcommand == "rank-github":
        from chintu_backend.automation.skills.third_party import rank_github_skill_repos

        query = str(getattr(args, "query", "") or "").strip()
        limit = int(getattr(args, "limit", 20) or 20)
        token = str(getattr(args, "token", "") or "").strip()
        ref = str(getattr(args, "ref", "main") or "main").strip()
        rows = rank_github_skill_repos(query=query, limit=limit, token=token, ref=ref)
        if getattr(args, "json", False):
            print(json.dumps([row.to_dict() for row in rows], indent=2))
            return 0
        if not rows:
            print("No ranked candidates found.")
            return 1
        print(f"Ranked GitHub candidates ({len(rows)}):\n")
        for row in rows:
            label = f"{row.full_name} score={row.score:.2f} importable={str(row.importable).lower()}"
            print(_safe_console_text(f"  {label}"))
            if row.discovered_paths:
                print(_safe_console_text(f"    best_path={row.discovered_paths[0]}"))
            for reason in row.reasons[:4]:
                print(_safe_console_text(f"    - {reason}"))
        return 0

    if subcommand == "auto-import-github":
        from chintu_backend.automation.skills.third_party import auto_import_top_ranked_repos

        query = str(getattr(args, "query", "") or "").strip()
        limit = int(getattr(args, "limit", 20) or 20)
        top = int(getattr(args, "top", 3) or 3)
        threshold = float(getattr(args, "score_threshold", 55.0) or 55.0)
        token = str(getattr(args, "token", "") or "").strip()
        ref = str(getattr(args, "ref", "main") or "main").strip()
        approved = bool(getattr(args, "approve", False))
        target_root = None
        if getattr(args, "target_dir", None):
            target_root = Path(str(args.target_dir)).expanduser()
        report = auto_import_top_ranked_repos(
            query=query,
            limit=limit,
            top=top,
            score_threshold=threshold,
            token=token,
            ref=ref,
            approved=approved,
            target_root=target_root,
        )
        if getattr(args, "json", False):
            print(json.dumps(report.to_dict(), indent=2))
            return 0
        print(
            _safe_console_text(
                f"Auto-import report: selected={len(report.selected)} imported={len(report.imported)} "
                f"threshold={report.threshold:.2f}"
            )
        )
        for item in report.imported:
            status = "ok" if item.ok else "blocked"
            print(_safe_console_text(f"  {item.source_repo} -> {status} ({item.source_path})"))
            if item.issues:
                print(_safe_console_text(f"    issue: {item.issues[0]}"))
        return 0

    registry = SkillRegistry()
    sources = [
        (config.skills_bundled_dir, "bundled"),
        (config.skills_learned_dir, "learned"),
        (config.skills_user_dir, "user"),
        (config.skills_dir, "workspace"),
    ]
    sources = [(path, label) for path, label in sources if path]
    registry.load_sources(sources)
    skills = list(registry._skills.values())

    if subcommand == "list":
        if not skills:
            print("No skills loaded.")
            return 0
        print(f"Loaded {len(skills)} skills:\n")
        for spec in sorted(skills, key=lambda s: s.name):
            print(f"  {spec.name} [{spec.source}]")
            if spec.description:
                print(f"    {spec.description}")
        return 0

    if subcommand == "check":
        # Check skill health (bin dependencies, OS compatibility)
        print("Checking skill dependencies...\n")
        for spec in sorted(skills, key=lambda s: s.name):
            issues = []
            # Check bin requirements
            if hasattr(spec, "requires") and spec.requires:
                for req in spec.requires:
                    if not shutil.which(req):
                        issues.append(f"missing binary: {req}")
            if issues:
                _warn_line(spec.name, ", ".join(issues))
            else:
                _status_line(spec.name, True)
        return 0

    return 1


# =============================================================================
# Gateway Command
# =============================================================================

def gateway_cmd(args: argparse.Namespace) -> int:
    root = Path(__file__).resolve().parents[1]
    scripts_dir = root / "scripts"
    start_script = scripts_dir / "start_gateway.ps1"
    stop_script = scripts_dir / "stop_gateway.ps1"
    
    if args.subcommand == "status":
        running = _check_gateway()
        _print_kv("gateway_running", running)
        _print_kv("gateway_port", 18789)
        return 0
    
    if args.subcommand == "start":
        if _check_gateway():
            print("Gateway already running.")
            return 0
        if not start_script.exists():
            print("ERROR: start_gateway.ps1 not found.")
            return 2
        subprocess.Popen(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(start_script)],
            cwd=str(root),
            creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
        )
        print("Gateway start requested.")
        return 0
    
    if args.subcommand == "stop":
        if not _check_gateway():
            print("Gateway not running.")
            return 0
        if not stop_script.exists():
            print("ERROR: stop_gateway.ps1 not found.")
            return 2
        subprocess.Popen(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(stop_script)],
            cwd=str(root)
        )
        print("Gateway stop requested.")
        return 0

    if args.subcommand == "pair":
        from pathlib import Path
        import secrets

        secret = secrets.token_hex(32)
        path = Path.home() / ".chintu" / "gateway_secret"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secret)
        print("Gateway pairing secret written.")
        _print_kv("secret_path", path)
        return 0

    if args.subcommand == "supervise":
        from chintu_backend.core.gateway_supervisor import get_gateway_supervisor

        supervisor = get_gateway_supervisor()
        supervisor.start_watchdog()
        print("Gateway supervisor watchdog started (press Ctrl+C to stop).")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            return 0
    
    return 1


# =============================================================================
# Service Command (Windows Service Management)
# =============================================================================

def service_cmd(args: argparse.Namespace) -> int:
    """Handle service subcommands."""
    try:
        from chintu_backend.core.gateway_supervisor import get_gateway_supervisor
        supervisor = get_gateway_supervisor()
    except ImportError:
        print("ERROR: Gateway supervisor not available.")
        return 2
    
    if args.subcommand == "install":
        result = supervisor.install_service()
        if result.get("success"):
            print(f"✓ Service installed: {result.get('service_name')}")
            return 0
        print(f"✗ Install failed: {result.get('error')}")
        return 1
    
    if args.subcommand == "uninstall":
        result = supervisor.uninstall_service()
        if result.get("success"):
            print("✓ Service uninstalled")
            return 0
        print(f"✗ Uninstall failed: {result.get('error')}")
        return 1
    
    if args.subcommand == "status":
        status = supervisor.status()
        _print_kv("Status", status.get("status", "unknown"))
        _print_kv("PID", status.get("pid", "N/A"))
        if status.get("uptime"):
            _print_kv("Uptime", status["uptime"])
        return 0
    
    if args.subcommand == "start":
        result = supervisor.start_daemon()
        if result.get("success"):
            print(f"✓ Service started (PID: {result.get('pid')})")
            return 0
        print(f"✗ Start failed: {result.get('error')}")
        return 1
    
    if args.subcommand == "stop":
        result = supervisor.stop_daemon()
        if result.get("success"):
            print("✓ Service stopped")
            return 0
        print(f"✗ Stop failed: {result.get('error')}")
        return 1
    
    if args.subcommand == "restart":
        result = supervisor.restart_daemon()
        if result.get("success"):
            print(f"✓ Service restarted (PID: {result.get('pid')})")
            return 0
        print(f"✗ Restart failed: {result.get('error')}")
        return 1
    
    if args.subcommand == "health":
        report = supervisor.health_check()
        status_icon = "✓" if report.healthy else "✗"
        print(f"{status_icon} Health: {'HEALTHY' if report.healthy else 'UNHEALTHY'}")
        for check, ok in report.checks.items():
            _status_line(f"  {check}", ok)
        return 0 if report.healthy else 1
    
    if args.subcommand == "logs":
        log_file = supervisor.data_dir / "logs" / "gateway.log"
        if not log_file.exists():
            print("No logs found.")
            return 0
        lines = log_file.read_text().splitlines()[-50:]
        for line in lines:
            print(line)
        return 0
    
    print("Usage: chintu service <install|uninstall|status|start|stop|restart|health|logs>")
    return 1


# =============================================================================
# Profile Command (Tool Profiles)
# =============================================================================

def profile_cmd(args: argparse.Namespace) -> int:
    """Handle profile subcommands."""
    try:
        from chintu_backend.tools.tool_profiles import get_profile_manager
        manager = get_profile_manager()
    except ImportError:
        print("ERROR: Profile manager not available.")
        return 2
    
    if args.subcommand == "list":
        profiles = manager.list_profiles()
        print("\nAvailable Profiles:")
        for p in profiles:
            active = " [ACTIVE]" if p['active'] else ""
            print(f"  {p['name']:<12} {p['tool_count']:>5} tools{active}")
        return 0
    
    if args.subcommand == "get":
        profile = manager.get_active_profile()
        print(f"\nActive Profile: {profile.name}")
        print(f"Description: {profile.description}")
        print(f"Tools: {len(profile.tools)}")
        return 0
    
    if args.subcommand == "set":
        result = manager.set_profile(args.name)
        if result.get("success"):
            print(f"✓ Switched to profile: {args.name}")
            return 0
        print(f"✗ Failed: {result.get('error')}")
        return 1
    
    if args.subcommand == "auto":
        context = input("Enter task context: ")
        result = manager.auto_switch_profile(context)
        print(f"Profile: {result.get('profile')}")
        return 0
    
    if args.subcommand == "create":
        tools = getattr(args, "tools", None) or []
        result = manager.create_profile(args.name, f"Custom: {args.name}", tools)
        if result.get("success"):
            print(f"✓ Created profile: {args.name}")
            return 0
        print(f"✗ Failed: {result.get('error')}")
        return 1
    
    print("Usage: chintu profile <list|get|set|auto|create>")
    return 1


def integrations_cmd(args: argparse.Namespace) -> int:
    """OAuth + integration onboarding helpers (Phase 20)."""
    from chintu_backend.integrations.oauth_onboarding import (
        connect_google_calendar,
        get_google_calendar_onboarding_steps,
        google_calendar_health,
        revoke_google_calendar,
    )
    from chintu_backend.integrations.status import get_integrations_snapshot

    sub = getattr(args, "subcommand", None) or "status"
    if sub in {"status", "list"}:
        snapshot = get_integrations_snapshot()
        print(json.dumps(snapshot, indent=2))
        return 0

    if sub == "connect-google-calendar":
        result = connect_google_calendar(
            credentials_path=getattr(args, "credentials", None),
            write_access=bool(getattr(args, "write_access", False)),
            force_reauth=bool(getattr(args, "force_reauth", False)),
        )
        print(result.get("message") or "")
        if result.get("receipt_path"):
            _print_kv("receipt", result.get("receipt_path"))
        return 0 if bool(result.get("ok")) else 1

    if sub == "health":
        health = google_calendar_health()
        print(json.dumps(health, indent=2))
        return 0 if bool(health.get("ok")) else 1

    if sub == "wizard":
        steps = get_google_calendar_onboarding_steps(write_access=bool(getattr(args, "write_access", False)))
        print("Google Calendar OAuth setup:")
        for row in steps:
            print(f"- {row}")
        return 0

    if sub == "revoke-google-calendar":
        result = revoke_google_calendar(remove_credentials=bool(getattr(args, "remove_credentials", False)))
        print(result.get("message") or "")
        if result.get("receipt_path"):
            _print_kv("receipt", result.get("receipt_path"))
        return 0

    print("Usage: chintu integrations <status|wizard|connect-google-calendar|health|revoke-google-calendar>")
    return 1


def workspace_cmd(args: argparse.Namespace) -> int:
    """Workspace abstraction controls (Phase 26)."""
    from chintu_backend.workspace import get_workspace_manager

    manager = get_workspace_manager()
    sub = getattr(args, "subcommand", None) or "status"

    if sub == "status":
        payload = {
            "runtime_profile_default": str(getattr(manager.config, "workspace_default_runtime_profile", "safe_mode")),
            "root_dir": str(manager.root_dir),
            "receipts_dir": str(manager.receipts_dir),
            "checkpoints_dir": str(manager.checkpoints_dir),
            "remote_sandbox_enabled": bool(getattr(manager.config, "workspace_remote_sandbox_enabled", False)),
            "untrusted_channels": list(getattr(manager.config, "workspace_untrusted_channels", []) or []),
        }
        print(json.dumps(payload, indent=2))
        return 0

    if sub == "run":
        command = str(getattr(args, "command_text", "") or "").strip()
        if not command:
            print("ERROR: Provide a command.")
            return 2
        ctx: Dict[str, Any] = {}
        if getattr(args, "channel", None):
            ctx["channel"] = str(args.channel)
        if getattr(args, "channel_trust", None):
            ctx["channel_trust"] = str(args.channel_trust)
        if getattr(args, "runtime_profile", None):
            ctx["_runtime_profile"] = str(args.runtime_profile)
        result = manager.run_shell(
            command,
            action_kind="shell",
            context=ctx,
            cwd=getattr(args, "cwd", None),
            requested_placement=getattr(args, "placement", None),
            allow_network=bool(getattr(args, "allow_network", False)),
            timeout_seconds=int(getattr(args, "timeout", 60)),
        )
        print(result.message)
        if result.stdout.strip():
            print("\n[stdout]")
            print(result.stdout.strip())
        if result.stderr.strip():
            print("\n[stderr]")
            print(result.stderr.strip())
        _print_kv("placement", result.placement.value)
        _print_kv("runtime_profile", result.runtime_profile)
        _print_kv("receipt", str(result.receipt_path))
        return 0 if result.success else 1

    if sub == "checkpoint-save":
        session_id = str(getattr(args, "session_id", "") or "").strip()
        step = str(getattr(args, "step", "") or "").strip()
        if not session_id or not step:
            print("ERROR: session_id and step are required.")
            return 2
        payload: Dict[str, Any] = {}
        if getattr(args, "payload_json", None):
            try:
                parsed = json.loads(str(args.payload_json))
                payload = parsed if isinstance(parsed, dict) else {"value": parsed}
            except Exception as exc:
                print(f"ERROR: Invalid payload_json: {exc}")
                return 2
        path = manager.save_checkpoint(session_id, step, payload)
        _print_kv("checkpoint", str(path))
        return 0

    if sub == "checkpoint-show":
        session_id = str(getattr(args, "session_id", "") or "").strip()
        if not session_id:
            print("ERROR: session_id is required.")
            return 2
        latest = manager.load_latest_checkpoint(session_id)
        if not latest:
            print("No checkpoint found.")
            return 1
        print(json.dumps(latest, indent=2))
        return 0

    print("Usage: chintu workspace <status|run|checkpoint-save|checkpoint-show>")
    return 1


# =============================================================================
# Parser Builder

# =============================================================================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Chintu operator CLI - manage gateway, skills, and configuration"
    )
    sub = parser.add_subparsers(dest="command")

    # Doctor
    doctor_parser = sub.add_parser("doctor", help="Run comprehensive health checks")
    doctor_parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")

    # Wizard
    sub.add_parser("wizard", help="Interactive onboarding wizard")

    # Config
    config_parser = sub.add_parser("config", help="Config inspection tools")
    config_sub = config_parser.add_subparsers(dest="subcommand")
    get_parser = config_sub.add_parser("get", help="Get a config value")
    get_parser.add_argument("key", help="Config key")
    config_sub.add_parser("paths", help="Show important paths")

    # Skills
    skills_parser = sub.add_parser("skills", help="Skills utilities")
    skills_sub = skills_parser.add_subparsers(dest="subcommand")
    skills_sub.add_parser("list", help="List loaded skills")
    skills_sub.add_parser("check", help="Check skill dependencies")
    catalog_parser = skills_sub.add_parser("catalog", help="Show curated skill catalog")
    catalog_parser.add_argument(
        "--stage",
        choices=["initial", "later", "all"],
        default="all",
        help="Catalog stage filter",
    )
    catalog_parser.add_argument(
        "--ids",
        default="",
        help="Optional comma-separated skill ids to filter",
    )
    catalog_parser.add_argument("--json", action="store_true", help="Emit JSON only")

    bootstrap_parser = skills_sub.add_parser("bootstrap", help="Plan or install curated bootstrap skills")
    bootstrap_parser.add_argument(
        "--stage",
        choices=["initial", "later", "all"],
        default="initial",
        help="Bootstrap stage",
    )
    bootstrap_parser.add_argument(
        "--ids",
        default="",
        help="Optional comma-separated skill ids",
    )
    bootstrap_parser.add_argument(
        "--workspace-dir",
        default=None,
        help="Override target workspace skills directory",
    )
    bootstrap_parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply installation instead of dry-run planning",
    )
    bootstrap_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite already installed catalog skills",
    )
    bootstrap_parser.add_argument(
        "--receipt",
        default=None,
        help="Optional JSON receipt output path when --apply is used",
    )
    scout_parser = skills_sub.add_parser("scout-github", help="Search GitHub repositories for skill candidates")
    scout_parser.add_argument(
        "--query",
        default="agent skills",
        help="GitHub repository search query",
    )
    scout_parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Number of repositories to return",
    )
    scout_parser.add_argument(
        "--token",
        default="",
        help="Optional GitHub token for higher rate limits",
    )
    scout_parser.add_argument("--json", action="store_true", help="Emit JSON only")

    import_parser = skills_sub.add_parser("import-github", help="Import a SKILL.md from GitHub into user skills")
    import_parser.add_argument("repo", help="Repo in owner/repo format")
    import_parser.add_argument(
        "--path",
        default="SKILL.md",
        help="Path to SKILL.md in repo",
    )
    import_parser.add_argument(
        "--ref",
        default="main",
        help="Branch, tag, or commit ref",
    )
    import_parser.add_argument(
        "--approve",
        action="store_true",
        help="Mark imported skill as approved in provenance metadata",
    )
    import_parser.add_argument(
        "--target-dir",
        default=None,
        help="Override target root directory (default: skills_user_dir)",
    )
    discover_parser = skills_sub.add_parser(
        "discover-github-paths",
        help="Discover SKILL.md-like paths in a GitHub repository",
    )
    discover_parser.add_argument("repo", help="Repo in owner/repo format")
    discover_parser.add_argument("--ref", default="main", help="Branch, tag, or commit ref")
    discover_parser.add_argument("--token", default="", help="Optional GitHub token")
    discover_parser.add_argument("--json", action="store_true", help="Emit JSON only")

    rank_parser = skills_sub.add_parser("rank-github", help="Rank GitHub skill candidates with safety/importability scores")
    rank_parser.add_argument("--query", default="agent skills", help="GitHub repository search query")
    rank_parser.add_argument("--limit", type=int, default=20, help="Number of repositories to rank")
    rank_parser.add_argument("--token", default="", help="Optional GitHub token")
    rank_parser.add_argument("--ref", default="main", help="Branch, tag, or commit ref for path discovery")
    rank_parser.add_argument("--json", action="store_true", help="Emit JSON only")

    auto_import_parser = skills_sub.add_parser("auto-import-github", help="Auto-import top-ranked importable GitHub skills")
    auto_import_parser.add_argument("--query", default="agent skills", help="GitHub repository search query")
    auto_import_parser.add_argument("--limit", type=int, default=20, help="Number of repositories to evaluate")
    auto_import_parser.add_argument("--top", type=int, default=3, help="Max repositories to auto-import")
    auto_import_parser.add_argument("--score-threshold", type=float, default=55.0, help="Minimum score required")
    auto_import_parser.add_argument("--token", default="", help="Optional GitHub token")
    auto_import_parser.add_argument("--ref", default="main", help="Branch, tag, or commit ref")
    auto_import_parser.add_argument("--approve", action="store_true", help="Set approval flag in imported provenance metadata")
    auto_import_parser.add_argument("--target-dir", default=None, help="Override target root directory (default: skills_user_dir)")
    auto_import_parser.add_argument("--json", action="store_true", help="Emit JSON only")

    # Integrations (Phase 20)
    integ_parser = sub.add_parser("integrations", help="OAuth/integration onboarding and health")
    integ_sub = integ_parser.add_subparsers(dest="subcommand")
    integ_sub.add_parser("status", help="Show integration status")
    integ_sub.add_parser("list", help="Alias for status")
    integ_wizard = integ_sub.add_parser("wizard", help="Show guided OAuth onboarding steps")
    integ_wizard.add_argument("--write-access", action="store_true", help="Show read/write scope setup steps")
    connect_calendar = integ_sub.add_parser("connect-google-calendar", help="Run Google Calendar OAuth onboarding")
    connect_calendar.add_argument("--credentials", default=None, help="Path to downloaded credentials.json")
    connect_calendar.add_argument("--write-access", action="store_true", help="Request write scope in addition to readonly")
    connect_calendar.add_argument("--force-reauth", action="store_true", help="Delete token and force a fresh OAuth login")
    integ_sub.add_parser("health", help="Run integration health checks")
    revoke_calendar = integ_sub.add_parser("revoke-google-calendar", help="Revoke local Google Calendar connection")
    revoke_calendar.add_argument("--remove-credentials", action="store_true", help="Also remove local credentials.json")

    # Learning
    learning_parser = sub.add_parser("learning", help="Learning and bi-weekly training controls")
    learning_sub = learning_parser.add_subparsers(dest="subcommand")
    learning_sub.add_parser("status", help="Show bi-weekly learning status")
    run_parser = learning_sub.add_parser("run", help="Run bi-weekly learning/training now")
    run_parser.add_argument("--force", action="store_true", help="Ignore incremental window and export all approved data")
    export_parser = learning_sub.add_parser("export", help="Export bi-weekly datasets without training")
    export_parser.add_argument("--full", action="store_true", help="Export from all approved history")
    export_parser.add_argument("--skip-memory", action="store_true", help="Do not include memory-derived dataset")
    export_parser.add_argument("--memory-limit", type=int, default=1000, help="Maximum memory-derived samples")
    learning_sub.add_parser("pending-activation", help="Show pending adapter activation approval status")
    activate_parser = learning_sub.add_parser("approve-activation", help="Approve and activate pending trained adapter")
    activate_parser.add_argument("--adapter-path", default=None, help="Optional exact adapter path to approve")
    gcc_parser = learning_sub.add_parser("gcc", help="Git-style context controller for long-horizon memory")
    gcc_sub = gcc_parser.add_subparsers(dest="gcc_command")
    gcc_init = gcc_sub.add_parser("init", help="Initialize .GCC in current workspace")
    gcc_init.add_argument("--goal", default="", help="Optional project goal for main roadmap")
    gcc_sub.add_parser("status", help="Show GCC overview")
    gcc_checkout = gcc_sub.add_parser("checkout", help="Switch current GCC branch")
    gcc_checkout.add_argument("name", help="Branch name")
    gcc_branch = gcc_sub.add_parser("branch", help="Create a GCC branch")
    gcc_branch.add_argument("name", help="New branch name")
    gcc_branch.add_argument("--purpose", default="", help="Branch purpose")
    gcc_branch.add_argument("--from-branch", default=None, help="Source branch")
    gcc_branch.add_argument("--no-switch", action="store_true", help="Do not switch after creation")
    gcc_log = gcc_sub.add_parser("log", help="Append an OTA log entry")
    gcc_log.add_argument("--observation", default="", help="Observation text")
    gcc_log.add_argument("--thought", default="", help="Thought text")
    gcc_log.add_argument("--action", required=True, help="Action text")
    gcc_log.add_argument("--result", default="", help="Result text")
    gcc_log.add_argument("--branch", default=None, help="Target branch")
    gcc_commit = gcc_sub.add_parser("commit", help="Create a context checkpoint commit")
    gcc_commit.add_argument("summary", help="Commit summary")
    gcc_commit.add_argument("--contribution", default="", help="Detailed contribution text")
    gcc_commit.add_argument("--branch", default=None, help="Target branch")
    gcc_commit.add_argument("--update-main", action="store_true", help="Append milestone in main roadmap")
    gcc_commit.add_argument("--roadmap-note", default="", help="Explicit main roadmap note")
    gcc_merge = gcc_sub.add_parser("merge", help="Merge one GCC branch into another")
    gcc_merge.add_argument("source", help="Source branch")
    gcc_merge.add_argument("--into", default="main", help="Target branch")
    gcc_merge.add_argument("--summary", default="", help="Merge summary")
    gcc_context = gcc_sub.add_parser("context", help="Retrieve GCC context")
    gcc_context.add_argument("--branch", default=None, help="Branch to inspect")
    gcc_context.add_argument("--commit", default=None, help="Specific commit id")
    gcc_context.add_argument("--log-lines", type=int, default=20, help="Log lines to include")
    gcc_context.add_argument("--metadata-key", default=None, help="Single metadata key to fetch")

    # Gates / Benchmarks
    gates_parser = sub.add_parser(
        "gates",
        help="Run maintainability, workflow-pack, persona, control-plane, and autonomy quality gates",
    )
    gates_sub = gates_parser.add_subparsers(dest="subcommand")
    gates_p17 = gates_sub.add_parser("phase17", help="Run Phase 17 maintainability gate")
    gates_p17.add_argument("--top-n", type=int, default=10, help="Top largest files to include in report")
    gates_p17.add_argument(
        "--large-file-threshold",
        type=int,
        default=1200,
        help="Line threshold for mega-file guardrail reporting",
    )
    gates_p18 = gates_sub.add_parser("phase18", help="Run Phase 18 UI vNext gate")
    gates_p18.add_argument("--skip-flutter-tests", action="store_true", help="Skip flutter widget tests")
    gates_sub.add_parser("phase19", help="Run Phase 19 workflow-pack benchmark")
    gates_sub.add_parser("phase27", help="Run Phase 27 multi-persona specialist gate")
    gates_sub.add_parser("phase28", help="Run Phase 28 Telegram control-plane gate")
    gates_p29 = gates_sub.add_parser("phase29", help="Run Phase 29 autonomy integration gate")
    gates_p29.add_argument("--skip-workflow-benchmark", action="store_true", help="Skip workflow benchmark step")
    gates_p29.add_argument("--skip-eval-gate", action="store_true", help="Skip eval-gate receipt step")
    gates_preflight = gates_sub.add_parser("preflight", help="Run deployment preflight gate")
    gates_preflight.add_argument("--run-doctor", action="store_true", help="Run chintu_doctor during preflight")
    gates_preflight.add_argument("--run-docker-check", action="store_true", help="Run docker readiness check")
    gates_preflight.add_argument("--strict-docker", action="store_true", help="Fail when docker is unavailable")
    gates_release = gates_sub.add_parser("release", help="Run release-readiness gate")
    gates_release.add_argument("--run-package-smoke", action="store_true", help="Run package script smoke check")
    gates_ci = gates_sub.add_parser("ci", help="Run CI quality gate chain (pytest + flutter + phase gates)")
    gates_ci.add_argument("--skip-flutter-tests", action="store_true", help="Skip flutter widget tests")
    gates_all = gates_sub.add_parser(
        "all",
        help="Run Phase 17, 18, 19, 27, 28, 29 + deployment preflight + release gates in sequence",
    )
    gates_all.add_argument("--top-n", type=int, default=10, help="Phase 17 top largest files count")
    gates_all.add_argument("--skip-flutter-tests", action="store_true", help="Pass-through for Phase 18")
    gates_all.add_argument("--skip-workflow-benchmark", action="store_true", help="Pass-through for Phase 29")
    gates_all.add_argument("--skip-eval-gate", action="store_true", help="Pass-through for Phase 29")

    # Gateway
    gw_parser = sub.add_parser("gateway", help="Gateway control")
    gw_sub = gw_parser.add_subparsers(dest="subcommand")
    gw_sub.add_parser("status", help="Show gateway status")
    gw_sub.add_parser("start", help="Start gateway")
    gw_sub.add_parser("stop", help="Stop gateway")
    gw_sub.add_parser("pair", help="Generate gateway pairing secret")
    gw_sub.add_parser("supervise", help="Run gateway watchdog loop")

    # Service (Windows service management)
    svc_parser = sub.add_parser("service", help="Windows service management")
    svc_sub = svc_parser.add_subparsers(dest="subcommand")
    svc_sub.add_parser("install", help="Install as Windows service")
    svc_sub.add_parser("uninstall", help="Uninstall Windows service")
    svc_sub.add_parser("status", help="Show service status")
    svc_sub.add_parser("start", help="Start service")
    svc_sub.add_parser("stop", help="Stop service")
    svc_sub.add_parser("restart", help="Restart service")
    svc_sub.add_parser("health", help="Run health check")
    svc_sub.add_parser("logs", help="Show recent logs")

    # Profile (tool profiles)
    prof_parser = sub.add_parser("profile", help="Tool profile management")
    prof_sub = prof_parser.add_subparsers(dest="subcommand")
    prof_sub.add_parser("list", help="List available profiles")
    prof_sub.add_parser("get", help="Show current profile")
    set_parser = prof_sub.add_parser("set", help="Set active profile")
    set_parser.add_argument("name", help="Profile name (minimal/coding/research/full)")
    prof_sub.add_parser("auto", help="Auto-detect profile from context")
    create_parser = prof_sub.add_parser("create", help="Create custom profile")
    create_parser.add_argument("name", help="Profile name")
    create_parser.add_argument("--tools", nargs="+", help="Tools to include")

    # Workspace abstraction (Phase 26)
    ws_parser = sub.add_parser("workspace", help="Workspace abstraction controls")
    ws_sub = ws_parser.add_subparsers(dest="subcommand")
    ws_sub.add_parser("status", help="Show workspace runtime defaults")
    ws_run = ws_sub.add_parser("run", help="Run a shell command via workspace manager")
    ws_run.add_argument("command_text", help="Command to execute")
    ws_run.add_argument("--placement", default="auto", help="auto|local_host|sandbox|remote_sandbox")
    ws_run.add_argument("--cwd", default=None, help="Optional working directory")
    ws_run.add_argument("--allow-network", action="store_true", help="Allow network for sandbox execution")
    ws_run.add_argument("--timeout", type=int, default=60, help="Timeout in seconds")
    ws_run.add_argument("--channel", default=None, help="Channel name for trust policy")
    ws_run.add_argument("--channel-trust", default=None, help="trusted|untrusted")
    ws_run.add_argument("--runtime-profile", default=None, help="safe_mode|balanced|high_trust")
    ws_ckpt_save = ws_sub.add_parser("checkpoint-save", help="Save a checkpoint for a session")
    ws_ckpt_save.add_argument("session_id", help="Session identifier")
    ws_ckpt_save.add_argument("step", help="Step identifier")
    ws_ckpt_save.add_argument("--payload-json", default=None, help="Optional JSON payload")
    ws_ckpt_show = ws_sub.add_parser("checkpoint-show", help="Show latest checkpoint for a session")
    ws_ckpt_show.add_argument("session_id", help="Session identifier")

    return parser


# =============================================================================
# Main Entry Point
# =============================================================================

def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    
    if args.command == "doctor":
        return doctor(verbose=getattr(args, "verbose", False))
    if args.command == "wizard":
        return wizard()
    if args.command == "config":
        return config_cmd(args)
    if args.command == "skills":
        return skills_cmd(args)
    if args.command == "integrations":
        return integrations_cmd(args)
    if args.command == "learning":
        return learning_cmd(args)
    if args.command == "gates":
        return gates_cmd(args)
    if args.command == "gateway":
        return gateway_cmd(args)
    if args.command == "service":
        return service_cmd(args)
    if args.command == "profile":
        return profile_cmd(args)
    if args.command == "workspace":
        return workspace_cmd(args)
    
    parser.print_help()
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
