"""Capabilities for inspecting Chintu's learning system."""

from __future__ import annotations

import re
from typing import Dict, Any

from chintu_backend.core.capabilities import Capability, CapabilityType, ActionResult
from chintu_backend.brain.learning.learning_engine import get_learning_engine
from chintu_backend.brain.learning.dataset_generator import generate_dataset_v2
from chintu_backend.brain.learning.safe_self_improvement import get_safe_self_improvement_manager
from chintu_backend.brain.learning.weekly_trainer import (
    approve_pending_adapter_activation,
    get_biweekly_learning_status,
    get_pending_adapter_activation,
    run_biweekly_learning,
)


def handle_learning_status(text: str, context: Dict[str, Any]) -> ActionResult:
    engine = get_learning_engine()
    stats = engine.store.get_stats()
    state = engine.store.load_state()
    schedule = get_biweekly_learning_status()
    config = engine.config
    total = stats.get("total", 0)
    by_category = stats.get("by_category", {})

    if total == 0:
        return ActionResult.ok(
            "I haven't stored any learning events yet.",
            {"stats": stats},
            "learning_status",
        )

    lines = [f"Learning events: {total}"]
    base_model = getattr(config, "learning_base_model_id", "")
    if base_model:
        lines.append(f"Training base model: {base_model}")
    if state.get("last_training_message"):
        lines.append(f"Last training: {state.get('last_training_message')}")
    if schedule.get("last_run"):
        lines.append(f"Last bi-weekly run: {schedule.get('last_run')}")
    if schedule.get("next_run_estimate"):
        lines.append(f"Next run estimate: {schedule.get('next_run_estimate')}")
    for category, count in sorted(by_category.items()):
        lines.append(f"- {category}: {count}")
    return ActionResult.ok("\n".join(lines), {"stats": stats}, "learning_status")


def handle_gcc_context(text: str, context: Dict[str, Any]) -> ActionResult:
    """Return GCC (Git-style context controller) overview for the current workspace."""
    try:
        from chintu_backend.brain.learning.gcc_context_controller import get_gcc_controller

        gcc = get_gcc_controller()
    except Exception as exc:
        return ActionResult.fail(f"GCC is unavailable: {exc}", "gcc_context")

    raw = (text or "").strip()
    lowered = raw.lower()

    branch = None
    m_branch = re.search(r"\\bbranch\\b\\s+([a-zA-Z0-9_.-]+)", lowered)
    if m_branch:
        branch = m_branch.group(1).strip()

    log_lines = 30
    m_lines = re.search(r"\\b(log\\s*lines|log-lines)\\b\\s*(\\d{1,3})", lowered)
    if m_lines:
        try:
            log_lines = int(m_lines.group(2))
        except Exception:
            log_lines = 30
    if "no log" in lowered or "no logs" in lowered:
        log_lines = 0

    try:
        data = gcc.context(branch=branch, log_lines=max(0, min(120, int(log_lines))))
    except Exception as exc:
        return ActionResult.fail(f"Failed to read GCC context: {exc}", "gcc_context")

    current = data.get("current_branch") or ""
    active = data.get("branch") or ""
    branches = data.get("branches") or []
    main_excerpt = (data.get("main_excerpt") or "").strip()
    latest_commits = data.get("latest_commits") or []
    log_tail = (data.get("log_tail") or "").strip()

    lines = ["GCC Context"]
    lines.append(f"- Root: {data.get('root','')}")
    if current:
        lines.append(f"- Current branch: {current}")
    if active and active != current:
        lines.append(f"- Viewing branch: {active}")
    if branches:
        lines.append(f"- Branches: {', '.join([str(b) for b in branches][:10])}{' ...' if len(branches) > 10 else ''}")
    if main_excerpt:
        lines.append("")
        lines.append("Roadmap (tail):")
        lines.append(main_excerpt[:1200])
    if latest_commits:
        lines.append("")
        lines.append("Latest commits (tail):")
        for entry in latest_commits[-6:]:
            lines.append(str(entry)[:260])
    if log_tail:
        lines.append("")
        lines.append(f"Recent OTA log (last {log_lines} lines):")
        lines.append(log_tail[:1200])

    return ActionResult.ok("\n".join(lines).strip(), data, "gcc_context")



def handle_deep_learn(text: str, context: Dict[str, Any]) -> ActionResult:
    """Perform deep autonomous research on a topic."""
    try:
        from chintu_backend.brain.agents.deep_researcher import get_deep_researcher
    except ImportError:
        return ActionResult.fail("Deep Research Agent not available.", "deep_learn")
    
    # Extract topic from triggers like "learn about X", "research X"
    # Basic cleaning
    topic = text
    triggers = ["learn about", "deep research", "research", "study", "learn"]
    for t in triggers:
        if text.lower().startswith(t + " "):
            topic = text[len(t):].strip()
            break
            
    if len(topic) < 2:
        return ActionResult.fail("Please specify a topic to learn about.", "deep_learn")
        
    try:
        researcher = get_deep_researcher()
        
        # Run in background to avoid blocking
        import threading
        def _bg_research():
            try:
                # We can inject a notification mechanism here later
                researcher.learn_topic(topic)
            except Exception as e:
                pass 

        threading.Thread(target=_bg_research, daemon=True).start()
        
        return ActionResult.ok(
            f"I've started researching '{topic}'. I'll write a structured book about it in the Knowledge Store. This may take a few minutes.",
            {}, 
            "deep_learn"
        )
    except Exception as e:
        return ActionResult.fail(f"Failed to start research: {e}", "deep_learn")


def handle_generate_dataset(text: str, context: Dict[str, Any]) -> ActionResult:
    """Generate a fine-tuning dataset from memory."""
    try:
        msg = generate_dataset_v2(limit=1000)
        return ActionResult.ok(msg, {}, "generate_training_data")
    except Exception as e:
        return ActionResult.fail(f"Dataset generation failed: {e}", "generate_training_data")


def handle_learning_schedule_status(text: str, context: Dict[str, Any]) -> ActionResult:
    try:
        status = get_biweekly_learning_status()
        pending = status.get("pending_adapter_activation") if isinstance(status, dict) else {}
        lines = [
            f"Bi-weekly learning enabled: {status.get('enabled')}",
            f"Interval: every {status.get('interval_days')} days",
            f"Schedule window: weekday={status.get('target_day')} hour={status.get('target_hour')} (UTC)",
            f"Last run: {status.get('last_run') or 'never'}",
            f"Next run estimate: {status.get('next_run_estimate') or 'pending'}",
            f"Last training message: {status.get('last_training_message') or 'none'}",
            f"Last export style/facts/memory: "
            f"{status.get('last_export_style_count', 0)}/"
            f"{status.get('last_export_facts_count', 0)}/"
            f"{status.get('last_export_memory_count', 0)}",
        ]
        if isinstance(pending, dict) and pending.get("pending"):
            lines.append(f"Pending adapter activation: yes ({pending.get('adapter_path') or 'unknown adapter'})")
            gate = pending.get("phase29_gate") if isinstance(pending, dict) else {}
            if isinstance(gate, dict) and gate:
                lines.append(
                    f"Phase29 gate: required={bool(gate.get('required'))} "
                    f"ok={bool(gate.get('ok'))} "
                    f"({gate.get('message') or 'no message'})"
                )
        else:
            lines.append("Pending adapter activation: no")
        return ActionResult.ok("\n".join(lines), status, "learning_schedule_status")
    except Exception as e:
        return ActionResult.fail(f"Could not load learning schedule status: {e}", "learning_schedule_status")


def handle_run_biweekly_learning(text: str, context: Dict[str, Any]) -> ActionResult:
    force = "force" in (text or "").lower()
    try:
        status = run_biweekly_learning(force=force)
        payload = {
            "ok": status.ok,
            "export_path": status.export_path,
            "manifest_path": status.manifest_path,
            "style_count": status.style_count,
            "facts_count": status.facts_count,
            "memory_count": status.memory_count,
            "trained": status.trained,
            "activation_pending": status.activation_pending,
            "pending_activation_path": status.pending_activation_path,
        }
        if status.ok:
            return ActionResult.ok(status.message, payload, "run_biweekly_learning")
        return ActionResult(
            success=False,
            message=status.message,
            data=payload,
            capability_name="run_biweekly_learning",
        )
    except Exception as e:
        return ActionResult.fail(f"Bi-weekly learning run failed: {e}", "run_biweekly_learning")


def handle_pending_adapter_activation_status(text: str, context: Dict[str, Any]) -> ActionResult:
    try:
        pending = get_pending_adapter_activation()
        if pending.get("pending"):
            msg = (
                "A trained adapter is pending activation approval.\n"
                f"Adapter: {pending.get('adapter_path') or 'unknown'}\n"
                f"Created: {pending.get('created_at') or 'unknown'}"
            )
            return ActionResult.ok(msg, pending, "pending_adapter_activation_status")
        return ActionResult.ok("No pending adapter activation.", pending, "pending_adapter_activation_status")
    except Exception as e:
        return ActionResult.fail(f"Could not read pending adapter activation status: {e}", "pending_adapter_activation_status")


def handle_approve_adapter_activation(text: str, context: Dict[str, Any]) -> ActionResult:
    expected: str = ""
    lower = str(text or "").lower()
    marker = "adapter="
    if marker in lower:
        idx = lower.index(marker) + len(marker)
        expected = str(text[idx:]).strip()
    actor = str((context or {}).get("user_id") or "operator")
    ok, message, payload = approve_pending_adapter_activation(
        actor=actor,
        expected_adapter_path=expected or None,
    )
    if ok:
        return ActionResult.ok(message, payload, "approve_adapter_activation")
    return ActionResult.fail(message, "approve_adapter_activation")


def handle_phase15_gap_plan(text: str, context: Dict[str, Any]) -> ActionResult:
    query = str(text or "").strip()
    for prefix in ("phase15 gap plan", "create unblock plan", "unblock plan for", "plan missing capability for"):
        if query.lower().startswith(prefix):
            query = query[len(prefix) :].strip()
            break
    if not query:
        return ActionResult.fail("Tell me which failed task needs an unblock plan.", "phase15_gap_plan")
    manager = get_safe_self_improvement_manager()
    plan = manager.create_unblock_plan(
        task_text=query,
        failure_message="Missing capability while handling user request.",
        capability_name="",
        context=context,
    )
    if not plan:
        return ActionResult.fail("Phase 15 manager is disabled.", "phase15_gap_plan")
    return ActionResult.ok(
        str(plan.get("message") or "Created unblock plan."),
        {
            "plan_path": plan.get("plan_path"),
            "outcome_label": "blocked_with_unblock_plan",
            "phase15_unblock_plan": plan,
        },
        "phase15_gap_plan",
    )


def handle_phase15_routing_tune(text: str, context: Dict[str, Any]) -> ActionResult:
    low = str(text or "").lower()
    apply = "apply" in low or "enable" in low
    manager = get_safe_self_improvement_manager()
    report = manager.tune_routing_from_telemetry(hours=72, apply=apply)
    if not report:
        return ActionResult.fail("Could not generate routing tuning report.", "phase15_routing_tune")
    gate = report.get("gate") if isinstance(report.get("gate"), dict) else {}
    message_lines = [
        "Phase 15 routing tuning report generated.",
        f"Gate passed: {bool(gate.get('passed'))}",
        f"Baseline: {', '.join(report.get('baseline_priority') or []) or 'n/a'}",
        f"Recommended: {', '.join(report.get('recommended_priority') or []) or 'n/a'}",
    ]
    if report.get("report_path"):
        message_lines.append(f"Report: {report.get('report_path')}")
    if apply:
        message_lines.append(
            "Applied routing change." if report.get("applied") else "Routing change not applied (gate failed or no improvement)."
        )
    return ActionResult.ok("\n".join(message_lines), report, "phase15_routing_tune")


def register_learning_capabilities(registry) -> None:
    registry.register(
        Capability(
            name="learning_status",
            triggers=[
                "learning status",
                "what did you learn",
                "learning stats",
                "show learning",
            ],
            handler=handle_learning_status,
            requires_confirmation=False,
            description="show learning event statistics",
            capability_type=CapabilityType.SYSTEM,
            examples=["Learning status", "What did you learn?"],
        )
    )
    
    registry.register(
        Capability(
            name="deep_learn",
            triggers=[
                "learn about",
                "research",
                "deep research",
                "study",
                "write a book about"
            ],
            handler=handle_deep_learn,
            requires_confirmation=False, # Safe to run
            description="deeply research a topic and create a knowledge book",
            capability_type=CapabilityType.AI_AGENT,
            examples=["Learn about quantum physics", "Research machine learning"],
        )
    )
    
    registry.register(
        Capability(
            name="generate_training_data",
            triggers=[
                "generate training data",
                "export dataset",
                "create fine-tuning dataset",
                "prepare for training"
            ],
            handler=handle_generate_dataset,
            requires_confirmation=True,
            description="export successful memories to a JSONL training dataset",
            capability_type=CapabilityType.ADMIN,
            examples=["Generate training data"],
        )
    )

    registry.register(
        Capability(
            name="gcc_context",
            triggers=[
                "gcc context",
                "gcc status",
                "show gcc",
                "show gcc context",
                "show my gcc",
            ],
            handler=handle_gcc_context,
            requires_confirmation=False,
            description="show GCC (git-style context controller) memory status",
            capability_type=CapabilityType.SYSTEM,
            examples=["GCC status", "Show GCC context branch main log lines 30"],
        )
    )

    registry.register(
        Capability(
            name="learning_schedule_status",
            triggers=[
                "learning schedule status",
                "training schedule status",
                "when will you train",
                "biweekly status",
            ],
            handler=handle_learning_schedule_status,
            requires_confirmation=False,
            description="show bi-weekly learning schedule and last run details",
            capability_type=CapabilityType.SYSTEM,
            examples=["Learning schedule status"],
        )
    )

    registry.register(
        Capability(
            name="run_biweekly_learning",
            triggers=[
                "run biweekly training",
                "run biweekly learning",
                "run learning cycle",
                "train from memory now",
                "start biweekly training",
            ],
            handler=handle_run_biweekly_learning,
            requires_confirmation=True,
            description="run export and optional adapter training immediately",
            capability_type=CapabilityType.ADMIN,
            examples=["Run biweekly training", "Run biweekly learning force"],
        )
    )
    registry.register(
        Capability(
            name="pending_adapter_activation_status",
            triggers=[
                "pending adapter activation",
                "adapter activation status",
                "is adapter pending approval",
            ],
            handler=handle_pending_adapter_activation_status,
            requires_confirmation=False,
            description="show pending adapter activation approval state",
            capability_type=CapabilityType.SYSTEM,
            examples=["Pending adapter activation", "Adapter activation status"],
        )
    )
    registry.register(
        Capability(
            name="approve_adapter_activation",
            triggers=[
                "approve adapter activation",
                "activate pending adapter",
                "promote pending adapter",
            ],
            handler=handle_approve_adapter_activation,
            requires_confirmation=True,
            description="approve and activate the pending trained adapter",
            capability_type=CapabilityType.ADMIN,
            examples=["Approve adapter activation", "Activate pending adapter"],
        )
    )

    registry.register(
        Capability(
            name="phase15_gap_plan",
            triggers=[
                "phase15 gap plan",
                "create unblock plan",
                "unblock plan for",
                "plan missing capability for",
            ],
            handler=handle_phase15_gap_plan,
            requires_confirmation=False,
            description="create a Phase 15 blocked-with-unblock-plan artifact",
            capability_type=CapabilityType.AI_AGENT,
            examples=["Create unblock plan for automate invoice reconciliation"],
        )
    )

    registry.register(
        Capability(
            name="phase15_routing_tune",
            triggers=[
                "phase15 routing tune",
                "tune routing from telemetry",
                "routing learning report",
                "optimize cloud model routing",
            ],
            handler=handle_phase15_routing_tune,
            requires_confirmation=False,
            description="build or apply A/B-gated routing priority proposals from telemetry",
            capability_type=CapabilityType.SYSTEM,
            examples=["Phase15 routing tune", "Phase15 routing tune apply"],
        )
    )

