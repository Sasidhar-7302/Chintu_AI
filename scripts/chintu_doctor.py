"""Chintu doctor - quick reliability/security audit."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, List, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = REPO_ROOT / "logs" / "latest.log"


def _ok(msg: str) -> str:
    return f"[OK] {msg}"


def _warn(msg: str) -> str:
    return f"[WARN] {msg}"


def _fail(msg: str) -> str:
    return f"[FAIL] {msg}"


def check_python_runtime() -> Tuple[bool, str]:
    exe = Path(sys.executable).resolve()
    in_venv = "venv" in str(exe).lower()
    if in_venv:
        return True, _ok(f"Using venv interpreter: {exe}")
    return False, _warn(f"Not running from project venv: {exe}")


def check_chromadb() -> Tuple[bool, str]:
    if importlib.util.find_spec("chromadb") is None:
        return False, _fail("chromadb is not importable in this interpreter.")
    return True, _ok("chromadb import check passed.")


def check_ollama_vision() -> Tuple[bool, str]:
    try:
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))
        from chintu_backend.core.validators import PrereqStatus, PrerequisiteChecker

        res = PrerequisiteChecker().check_ollama_vision()
        if res.status == PrereqStatus.OK:
            return True, _ok(res.message)
        fix = f" Fix: {res.fix_instructions}" if res.fix_instructions else ""
        return False, _warn(f"{res.message}.{fix}".strip())
    except Exception as exc:
        return False, _warn(f"Could not verify Ollama vision readiness: {exc}")


def check_docker_sandbox() -> Tuple[bool, str]:
    try:
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))
        from chintu_backend.sandbox.docker_sandbox import DockerSandbox

        healthy, message = DockerSandbox.health_check()
        if healthy:
            return True, _ok(message or "Docker sandbox healthy.")
        return False, _warn(message or "Docker sandbox unavailable on this machine session.")
    except Exception as exc:
        return False, _warn(f"Could not verify Docker sandbox health: {exc}")


def check_model_fit_alignment() -> Tuple[bool, str]:
    """Recommend best-fit local model settings and flag mismatches."""
    try:
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))
        from chintu_backend.core.model_fit import collect_model_fit_snapshot

        snapshot = collect_model_fit_snapshot(max_show_models=3)
        fit = snapshot.get("fit", {}) if isinstance(snapshot, dict) else {}
        recommended = fit.get("recommended", {}) if isinstance(fit, dict) else {}
        mismatches = list(fit.get("mismatches", []) or []) if isinstance(fit, dict) else []
        if mismatches:
            message = "; ".join(str(item) for item in mismatches[:3])
            return (
                False,
                _warn(
                    "Model-fit mismatch: "
                    + message
                    + f". Recommended base={recommended.get('ollama_model', '')},"
                    + f" strong={recommended.get('ollama_model_strong', '')},"
                    + f" vision={recommended.get('vision_ollama_model', '')},"
                    + f" llm_num_gpu={recommended.get('llm_num_gpu', '')}."
                ),
            )
        return True, _ok("Model-fit recommendations align with current configured model settings.")
    except Exception as exc:
        return False, _warn(f"Could not compute model-fit recommendations: {exc}")


def check_mcp_runtime() -> Tuple[bool, str]:
    try:
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))
        from chintu_backend.interfaces.mcp.registry import get_mcp_registry

        registry = get_mcp_registry()
        if not registry.is_enabled:
            return True, _ok("MCP is disabled by config.")
        ok, msg = registry.start()
        if not ok:
            return False, _warn(msg)
        tools = registry.list_tools(refresh=False)
        if tools:
            return True, _ok(f"MCP runtime active with {len(tools)} discovered tool(s).")
        return False, _warn("MCP started but no tools were discovered.")
    except Exception as exc:
        return False, _warn(f"Could not verify MCP runtime: {exc}")


def _extract_mcp_tool_text(payload: Any) -> str:
    """Best-effort extraction of text from an MCP tools/call result."""
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload.strip()
    if isinstance(payload, dict):
        content = payload.get("content")
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("text"):
                    parts.append(str(item["text"]))
            return "\n".join(parts).strip()
    return ""


def check_mcp_tool_coverage() -> Tuple[bool, str]:
    """Ensure core MCP tools exist for browser + files + vision automation."""
    try:
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))
        from chintu_backend.interfaces.mcp.registry import get_mcp_registry

        registry = get_mcp_registry()
        if not registry.is_enabled:
            return True, _ok("MCP tool coverage skipped (MCP disabled).")

        ok, msg = registry.start()
        if not ok:
            return False, _warn(msg)

        tools = registry.list_tools(refresh=True)
        discovered = {t.name for t in tools if getattr(t, "name", None)}
        required = {
            # Browser automation
            "browser_open",
            "browser_search",
            "browser_screenshot",
            # Screen + vision automation
            "screen_click",
            "screen_type",
            "vision_describe",
            "vision_click",
            # Files
            "file_read",
            "file_write",
            "file_list",
            "repo_index",
            "repo_search",
            # Sandbox
            "sandbox_run",
            "sandbox_python",
            # Memory
            "memory_learn",
            "memory_recall",
        }
        missing = sorted(required - discovered)
        if missing:
            return False, _warn("MCP missing required tool(s): " + ", ".join(missing))
        return True, _ok("MCP includes required core tools for browser/files/vision workflows.")
    except Exception as exc:
        return False, _warn(f"Could not verify MCP tool coverage: {exc}")


def check_mcp_tool_smoke() -> Tuple[bool, str]:
    """Run a harmless MCP tool call to verify end-to-end execution works."""
    try:
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))
        from chintu_backend.interfaces.mcp.registry import get_mcp_registry

        registry = get_mcp_registry()
        if not registry.is_enabled:
            return True, _ok("MCP tool smoke test skipped (MCP disabled).")

        ok, msg = registry.start()
        if not ok:
            return False, _warn(msg)

        ok, _, result = registry.call_tool("file_list", {"path": str(REPO_ROOT), "pattern": "*"})
        if not ok:
            return False, _warn("MCP tool call failed: file_list")
        text = _extract_mcp_tool_text(result)
        if "Files in" not in text:
            return False, _warn("MCP tool call returned unexpected payload for file_list.")
        return True, _ok("MCP tool call smoke test passed (file_list).")
    except Exception as exc:
        return False, _warn(f"Could not run MCP tool smoke test: {exc}")


def check_skill_policy_contracts() -> Tuple[bool, str]:
    try:
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))
        from chintu_backend.automation.skills.skill_registry import SkillRegistry
        from chintu_backend.core.capabilities import CapabilityRegistry
        from chintu_backend.core.config import get_config
        from chintu_backend.policy import get_policy_engine

        cfg = get_config()
        skill_registry = SkillRegistry()
        sources = [
            (Path(cfg.skills_bundled_dir), "bundled"),
            (Path(cfg.skills_user_dir), "user"),
            (Path(cfg.skills_dir), "workspace"),
            (Path(cfg.skills_learned_dir), "learned"),
        ]
        skill_registry.load_sources(sources)
        skill_registry.register_capabilities(CapabilityRegistry())

        engine = get_policy_engine()
        missing: List[str] = []
        custom = getattr(engine, "_custom_contracts", {})
        for name in ("skill::daily-briefing", "skill::hardware-health", "skill::price-compare"):
            contract = custom.get(name)
            if not contract:
                missing.append(name)
                continue
            if contract.requires_confirmation:
                missing.append(name)
        if missing:
            return False, _warn(
                "Some skill contracts still require confirmation by default: "
                + ", ".join(missing)
            )
        return True, _ok("Skill contracts are registered with non-blocking defaults.")
    except Exception as exc:
        return False, _warn(f"Could not verify skill policy contracts: {exc}")


def check_phase8_security_controls() -> Tuple[bool, str]:
    try:
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))
        from chintu_backend.core.config import get_config
        from chintu_backend.policy.action_approvals import get_action_approval_ledger
        from chintu_backend.policy.capability_contracts import CapabilityContract, RiskLevel
        from chintu_backend.policy.unified_resolver import ResolverDecision, UnifiedPolicyResolver

        cfg = get_config()
        resolver = UnifiedPolicyResolver(cfg)
        contract = CapabilityContract(
            risk_level=RiskLevel.MEDIUM,
            requires_internet=True,
            requires_confirmation=False,
            side_effects=["browser_action"],
        )
        outcome = resolver.resolve(
            capability_name="browser_act_ref",
            contract=contract,
            context={"_request_text": "click publish", "_runtime_profile": "safe_mode"},
        )
        if outcome.decision != ResolverDecision.confirm:
            return False, _warn("Unified policy resolver did not enforce safe-mode confirmation on publish submit.")

        ledger = get_action_approval_ledger()
        ledger_path = getattr(ledger, "path", None)
        if not ledger_path:
            return False, _warn("Action approval ledger path is not configured.")
        return True, _ok("Phase 8 unified policy resolver and approval ledger checks passed.")
    except Exception as exc:
        return False, _warn(f"Could not verify Phase 8 security controls: {exc}")


def check_recent_logs() -> Tuple[bool, List[str]]:
    issues: List[str] = []
    if not LOG_PATH.exists():
        return True, [_warn("No logs/latest.log found yet.")]

    try:
        lines = LOG_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()[-2000:]
    except Exception as exc:
        return False, [_warn(f"Could not read logs: {exc}")]

    joined = "\n".join(lines)
    if "No predefined contract found for capability: skill::" in joined:
        issues.append(_warn("Log still shows missing policy contracts for some skills."))
    if "ChromaDB unavailable" in joined:
        issues.append(_warn("Log reports ChromaDB unavailable in recent startup."))
    if "LLM fallback reason: All models failed" in joined:
        issues.append(_warn("Some skills still fell back due to model router failures."))
    if "No local Ollama vision model installed" in joined or "No Ollama vision model installed" in joined:
        issues.append(_warn("Vision backend reports no local Ollama vision model installed."))
    if "Docker sandbox unavailable on this machine session" in joined:
        issues.append(_warn("Recent runs report Docker sandbox unavailable."))
    if "MCP tool call failed" in joined:
        issues.append(_warn("Recent logs contain MCP tool call failures."))

    if not issues:
        issues.append(_ok("No critical recurring warnings detected in recent logs."))
        return True, issues
    return False, issues


def main() -> int:
    print("=== Chintu Doctor ===")
    print("")

    checks = [
        check_python_runtime,
        check_chromadb,
        check_model_fit_alignment,
        check_ollama_vision,
        check_docker_sandbox,
        check_mcp_runtime,
        check_mcp_tool_coverage,
        check_mcp_tool_smoke,
        check_skill_policy_contracts,
        check_phase8_security_controls,
    ]

    hard_fail = False
    for check in checks:
        ok, message = check()
        print(message)
        hard_fail = hard_fail or (not ok and message.startswith("[FAIL]"))

    log_ok, log_messages = check_recent_logs()
    for msg in log_messages:
        print(msg)

    summary = {
        "hard_fail": hard_fail,
        "log_warnings": [m for m in log_messages if m.startswith("[WARN]")],
    }
    print("")
    print("Summary:")
    print(json.dumps(summary, indent=2, ensure_ascii=True))

    if hard_fail:
        return 2
    if not log_ok:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
