"""
Action Dispatcher.
Decouples execution logic from CommandHandler.
Responsible for finding and running clean capabilities via the Registry.
"""

import logging
from typing import Optional, Dict, Any, Tuple
from pathlib import Path
from pydantic import ValidationError
from .capabilities import CapabilityRegistry, ActionResult
from .config import get_config
from .llm_tool_router import LLMToolRouter
from .tool_loop_guard import get_tool_loop_guard
from .execution_contracts import FailureTaxonomy, classify_failure_type
from .dependency_bootstrap import DependencyRecoveryResult, InstallPlan, get_dependency_bootstrap_agent
from .self_healing import FailureAwareRetryPlanner, PlanWatchdog, ToolFallbackGraph
from .gpu_resource_manager import get_gpu_resource_manager
try:
    from ..brain.memory.hybrid_memory import get_hybrid_memory
except ImportError:
    get_hybrid_memory = lambda: None

logger = logging.getLogger(__name__)

class ActionDispatcher:
    """
    Dispatches parsed commands to the appropriate Capability.
    Fully autonomous LLM-driven dispatching (Phase 1).
    """

    def __init__(self, registry: CapabilityRegistry, llm_client=None, memory_manager=None, swarm=None):
        self.registry = registry
        self.config = get_config()
        # If a caller didn't pass an LLM, we keep it disabled. Do not implicitly
        # spin up Ollama here, because tests and deterministic callers expect
        # dispatch() to remain capability-driven.
        self.llm = llm_client 
        self.memory_manager = memory_manager
        self.swarm = swarm
        self.max_step_retries = int(getattr(self.config, "orchestrator_max_step_attempts", 2))
        # Verification-driven retries are separate from "handler failed" retries.
        self.max_verification_attempts = int(getattr(self.config, "verification_max_attempts", 2))
        self.fast_path_threshold = float(getattr(self.config, "dispatcher_fast_path_threshold", 0.35))
        self.direct_capability_threshold = float(
            getattr(self.config, "dispatcher_direct_capability_threshold", 0.45)
        )
        self.direct_capabilities = set(
            getattr(self.config, "dispatcher_direct_capabilities", None) or []
        ) or {
            "set_reminder",
            "timer",
            "cancel_reminder",
            "add_task",
            "list_tasks",
            "complete_task",
            "list_calendar",
            "add_calendar_event",
            "list_files",
            "system_info",
            "volume_control",
            "screenshot",
            "list_windows",
            "status",
            "sandbox_data_task",
            "autonomy_workflow",
        }
        self.verification_retry_capabilities = set(
            getattr(self.config, "verification_retry_capabilities", None) or []
        ) or {
            # Idempotent-ish, user-visible tasks where retry is low risk.
            "take_screenshot",
            "open_app",
        }
        self.loop_guard = get_tool_loop_guard(self.config)
        self.tool_router = LLMToolRouter(self.registry, self.llm, self.config)
        self._pending_confirmation: Optional[ActionResult] = None
        self.dependency_bootstrap = get_dependency_bootstrap_agent(config=self.config)
        self.fallback_graph = ToolFallbackGraph()
        self.retry_planner = FailureAwareRetryPlanner(self.fallback_graph)
        self.plan_watchdog = PlanWatchdog(
            repeat_threshold=int(getattr(self.config, "phase7_watchdog_repeat_threshold", 3)),
            window_seconds=float(getattr(self.config, "phase7_watchdog_window_seconds", 180.0)),
        )
        self.gpu_resource_manager = None
        if bool(getattr(self.config, "gpu_resource_manager_enabled", True)):
            try:
                self.gpu_resource_manager = get_gpu_resource_manager(config=self.config)
            except Exception as exc:
                logger.warning("GPU resource manager unavailable: %s", exc)

    def dispatch(self, text: str, context: Dict[str, Any] = None) -> ActionResult:
        """
        Finds the best capability for the text and executes it.
        Uses LLMToolRouter as the primary decision maker.
        Supports compound command decomposition.
        """
        context = context or {}
        forced_name = str(context.get("_forced_capability") or "").strip()
        if forced_name:
            forced_cap = self.registry.get(forced_name)
            if forced_cap is not None:
                logger.info("Forced capability route -> %s", forced_name)
                return self._execute_with_loop_guard(forced_cap, text, context)

        # If a single deterministic capability is an extremely strong match, run it
        # directly and skip decomposition. This prevents the LLM from "helpfully"
        # rewriting obvious commands into multi-step plans that can misroute.
        try:
            cap, score = self.registry.match_with_score(text)
        except Exception:
            cap, score = None, 0.0
        text_lower = (text or "").lower()
        if self._is_sandbox_data_task_request(text):
            logger.info("Deterministic sandbox-data route -> sandbox_data_task")
            forced = self.registry.get("sandbox_data_task")
            if forced is not None:
                return self._execute_with_loop_guard(forced, text, context)
            return self._dispatch_single(text, context)
        if self._is_autonomy_workflow_request(text):
            logger.info("Deterministic autonomy route -> autonomy_workflow")
            forced = self.registry.get("autonomy_workflow")
            if forced is not None:
                return self._execute_with_loop_guard(forced, text, context)
            return self._dispatch_single(text, context)
        is_compound = (" and " in text_lower) or (" then " in text_lower)
        if is_compound:
            if (
                "hacker news" in text_lower
                and "headline" in text_lower
                and any(token in text_lower for token in ("top ", "find ", "search "))
            ):
                logger.info("Compound bypass: routing Hacker News headline request directly to live_search.")
                return self._dispatch_single(text, context)
            skill_cap, skill_score = self._best_skill_match(text)
            skill_compound_threshold = float(
                getattr(self.config, "llm_tool_routing_match_threshold", 0.18)
            )
            if skill_cap is not None and float(skill_score) >= skill_compound_threshold:
                logger.info(
                    "Compound command routed directly to skill: %s (score=%s)",
                    getattr(skill_cap, "name", ""),
                    round(float(skill_score), 3),
                )
                return self._execute_with_loop_guard(skill_cap, text, context)
            # Strong direct capability matches should bypass decomposition as well.
            if cap is not None and float(score or 0.0) >= self.direct_capability_threshold:
                logger.info(
                    "Compound command routed directly to capability: %s (score=%s)",
                    getattr(cap, "name", ""),
                    round(float(score or 0.0), 3),
                )
                return self._dispatch_single(text, context)
            compound_bypass_caps = {
                "code_interpreter",
                "buying_guide",
                "social_content_pipeline",
                "social_publish_post",
                "live_search",
                "sandbox_data_task",
                "autonomy_workflow",
            }
            if (
                cap is not None
                and str(getattr(cap, "name", "") or "") in compound_bypass_caps
                and float(score or 0.0) >= skill_compound_threshold
            ):
                logger.info(
                    "Compound bypass routed directly to capability: %s (score=%s)",
                    getattr(cap, "name", ""),
                    round(float(score or 0.0), 3),
                )
                return self._dispatch_single(text, context)
        is_skill_cap = bool(cap is not None and str(getattr(cap, "name", "")).startswith("skill::"))
        if cap is not None and (not is_compound or is_skill_cap):
            score_val = float(score or 0.0)
            is_direct_cap = str(getattr(cap, "name", "") or "") in self.direct_capabilities
            if score_val >= self.fast_path_threshold or (
                is_direct_cap and score_val >= self.direct_capability_threshold
            ) or (
                is_skill_cap and score_val >= self.direct_capability_threshold
            ):
                return self._dispatch_single(text, context)
        
        # 0. Decomposition (Split compound commands)
        steps = self.tool_router.decompose(text)
        # Decomposition is only useful when it produces multiple actionable sub-steps.
        # For single-step outputs, preserve the user's original text (LLM rewrites can lose detail).
        if not steps or len(steps) <= 1:
            # Single task flow
            return self._dispatch_single(text, context)
            
        # Multi-task flow
        results = []
        for idx, step in enumerate(steps, start=1):
            logger.info(f"Executing decomposed step {idx}/{len(steps)}: {step.text} (Thought: {step.thought})")
            attempts = 0
            res = None
            while attempts < max(1, self.max_step_retries):
                attempts += 1
                res = self._dispatch_single(step.text, context)
                # If no deterministic route exists for this sub-step, answer directly with LLM
                # so compound commands can still complete end-to-end.
                if res and res.success and res.message == "__LLM_ROUTE__":
                    llm_msg = self._answer_with_llm(step.text)
                    res = ActionResult.ok(llm_msg, capability="conversation")
                    break
                if res and res.success:
                    break
                if attempts >= max(1, self.max_step_retries):
                    break
            if not res:
                res = ActionResult.fail(f"Step {idx} failed with no result.", capability="compound_command")
            results.append(res)
            
        # Combine results
        # If all successful, return combined message
        # If any failed, report failures
        all_success = all(r.success for r in results)
        combined_msg = " | ".join(r.message for r in results)
        return ActionResult(
            success=all_success,
            message=combined_msg,
            capability_name="compound_command",
            data={"results": [r.to_dict() for r in results]}
        )

    def _is_sandbox_data_task_request(self, text: str) -> bool:
        """Detect CSV cleaning/chart tasks that must run in sandbox as a single workflow."""
        low = str(text or "").lower()
        if not low:
            return False
        # Explicit alias form, e.g. "analyze sales_2025.csv in sandbox".
        if (
            ("analyze " in low or "analyse " in low)
            and ".csv" in low
            and "sandbox" in low
        ):
            return True
        has_data_ref = any(token in low for token in ("csv", "dataset", ".csv"))
        has_cleaning = any(token in low for token in ("clean", "null", "missing values", "impute"))
        has_chart = any(token in low for token in ("trend chart", "matplotlib", "plot", "chart"))
        has_sandbox = any(
            token in low
            for token in ("sandbox", "do not run on my main os", "don't run on my main os")
        )
        return has_data_ref and has_cleaning and has_chart and has_sandbox

    def _is_autonomy_workflow_request(self, text: str) -> bool:
        low = str(text or "").lower()
        if not low:
            return False
        patterns = [
            ("pdf", "recent research", "downloads"),
            ("linkedin", "latest cv", "clipboard"),
            ("open-source", "github", "visa"),
            ("fastapi", "sop library", "vs code"),
            ("heavy data scraping", "rtx 3060", "2 am"),
            ("i5-12600k", "temperature exceeds", "gaming"),
            ("youtube shorts bot", "jira ticket"),
            ("statement of purpose", "data science phd", "courses"),
            ("f1 opt", "draft a reply"),
            ("record my screen", "analyze the video"),
        ]
        for group in patterns:
            if all(token in low for token in group):
                return True
        return False

    def _best_skill_match(self, text: str) -> tuple[Optional[Any], float]:
        best = None
        best_score = 0.0
        capabilities = getattr(self.registry, "_capabilities", {}) or {}
        for name, cap in capabilities.items():
            if not str(name).startswith("skill::"):
                continue
            try:
                score = float(cap.get_match_score(text))
            except Exception:
                continue
            if score > best_score:
                best = cap
                best_score = score
        return best, best_score

    def _answer_with_llm(self, text: str) -> str:
        if self.llm:
            try:
                if hasattr(self.llm, "answer_question"):
                    return str(self.llm.answer_question(text))
                if hasattr(self.llm, "generate"):
                    return str(self.llm.generate(text))
            except Exception as e:
                logger.warning(f"LLM fallback failed: {e}")
        return "I couldn't complete that step automatically."

    def _dispatch_single(self, text: str, context: Dict[str, Any] = None) -> ActionResult:
        """Dispatches a single (non-compound) command."""
        context = context or {}
        # Remove transient routing/validation state from prior turns or steps.
        # Reusing the same context dict across commands should not leak schema params.
        transient_keys = [
            "_planned_params",
            "_extracted_params",
            "_validated_params",
            "_llm_routed",
            "_llm_route_confidence",
            "_rag_context",
        ]
        if context.get("_keep_extracted_params"):
            transient_keys = [k for k in transient_keys if k != "_extracted_params"]
        for transient_key in transient_keys:
            context.pop(transient_key, None)

        run_id = context.get("_run_id") if isinstance(context, dict) else None
        run_mgr = None
        step_id = ""
        gpu_before_snapshot: Dict[str, Any] = {}
        if run_id:
            try:
                from chintu_backend.core.run_manager import get_run_manager

                run_mgr = get_run_manager()
                if run_mgr.is_cancel_requested(str(run_id)):
                    return ActionResult.fail("Cancelled.", capability="cancelled")
                step_id = run_mgr.start_step(str(run_id), title=text, meta={"kind": "dispatch"})
            except Exception:
                run_mgr = None
                step_id = ""
        if self.gpu_resource_manager and bool(getattr(self.config, "gpu_step_telemetry_enabled", True)):
            try:
                gpu_before_snapshot = self.gpu_resource_manager.capture_snapshot()
            except Exception:
                gpu_before_snapshot = {}

        def _evidence_from_result(result: ActionResult) -> list:
            evidence = []
            try:
                from chintu_backend.core.run_manager import EvidenceRef

                data = result.data if isinstance(result.data, dict) else {}
                if isinstance(data, dict):
                    seen = set()
                    for key in (
                        "path",
                        "artifact_path",
                        "file_path",
                        "report_path",
                        "screenshot",
                        "filepath",
                    ):
                        path = data.get(key)
                        if path:
                            p = str(path)
                            if p and p not in seen:
                                seen.add(p)
                                evidence.append(EvidenceRef(kind="path", value=p, summary="artifact"))
                    url = data.get("url")
                    if url:
                        evidence.append(EvidenceRef(kind="url", value=str(url), summary="url"))
                    coords = data.get("coords")
                    if coords:
                        evidence.append(EvidenceRef(kind="coords", value=str(coords), summary="coords"))
                    app = data.get("app")
                    if app:
                        evidence.append(EvidenceRef(kind="app", value=str(app), summary="app"))
            except Exception:
                return []
            return evidence

        def _build_side_effect_log(result: Optional[ActionResult], capability_name: str) -> list:
            if not result or not bool(getattr(result, "success", False)):
                return []
            data = result.data if isinstance(result.data, dict) else {}
            if not isinstance(data, dict):
                return []

            entries = []
            seen = set()
            cap_label = str(capability_name or getattr(result, "capability_name", "") or "action").strip() or "action"

            for key in ("path", "artifact_path", "file_path", "report_path", "screenshot", "filepath"):
                raw = data.get(key)
                if not raw:
                    continue
                where = str(raw).strip()
                if not where:
                    continue
                proof = "reported_path"
                try:
                    proof = "path_exists" if Path(where).exists() else "reported_path"
                except Exception:
                    proof = "reported_path"
                row = {
                    "what_changed": f"{cap_label} updated artifact",
                    "where": where,
                    "proof": proof,
                }
                token = (row["what_changed"], row["where"], row["proof"])
                if token in seen:
                    continue
                seen.add(token)
                entries.append(row)

            url = data.get("url") or data.get("new_url")
            if url:
                row = {
                    "what_changed": f"{cap_label} changed navigation target",
                    "where": str(url),
                    "proof": "reported_url",
                }
                token = (row["what_changed"], row["where"], row["proof"])
                if token not in seen:
                    seen.add(token)
                    entries.append(row)

            coords = data.get("coords")
            if coords:
                row = {
                    "what_changed": f"{cap_label} acted on screen coordinates",
                    "where": str(coords),
                    "proof": "reported_coords",
                }
                token = (row["what_changed"], row["where"], row["proof"])
                if token not in seen:
                    seen.add(token)
                    entries.append(row)

            app = data.get("app")
            if app:
                row = {
                    "what_changed": f"{cap_label} interacted with application",
                    "where": str(app),
                    "proof": "reported_app",
                }
                token = (row["what_changed"], row["where"], row["proof"])
                if token not in seen:
                    seen.add(token)
                    entries.append(row)

            if entries:
                if not isinstance(result.data, dict):
                    result.data = {}
                result.data["evidence_log"] = entries
            return entries

        result: Optional[ActionResult] = None
        executed_capability = None

        # Deterministic browser/news guard: prevent decomposition/routing drift for
        # explicit Hacker News headline requests ("top N ... from Hacker News").
        text_lower = str(text or "").lower()
        if (
            "hacker news" in text_lower
            and "headline" in text_lower
            and any(token in text_lower for token in ("top ", "find ", "search "))
        ):
            for cap_name in ("live_search", "news_search"):
                candidate = self.registry.get(cap_name)
                if candidate:
                    logger.info("Deterministic HN route -> %s", cap_name)
                    executed_capability = candidate
                    result = self._execute_with_loop_guard(candidate, text, context)
                    break
        
        # 1. Fast Keyword Match (Deterministic Fast-Path)
        # This keeps obvious commands like "screenshot" or "mute" fast (10ms vs 1s LLM)
        capability, score = self.registry.match_with_score(text)
        if result is None:
            score_val = float(score or 0.0)
            is_direct_cap = str(getattr(capability, "name", "") or "") in self.direct_capabilities
            if score_val >= self.fast_path_threshold or (
                is_direct_cap and score_val >= self.direct_capability_threshold
            ):
                logger.info(f"Fast-path match: {capability.name} (Score: {score})")
                executed_capability = capability
                result = self._execute_with_loop_guard(capability, text, context)
        if result is None:
            # 2. RAG Context Retrieval (Context Injection)
            rag_context = ""
            if self.memory_manager:
                try:
                    from ..brain.memory.retrieval_router import get_retrieval_router
                    retriever = get_retrieval_router()
                    results = retriever.retrieve(text, max_results=3)
                    rag_context = retriever.format_for_llm(results)
                    context["_rag_context"] = rag_context
                    if rag_context:
                        logger.info(f"Injected RAG context for routing: {len(results)} items")
                except Exception as e:
                    logger.warning(f"RAG retrieval failed in dispatcher: {e}")

            # 3. Swarm Routing (v5.1 Multi-Agent Processing)
            if self.swarm and self.swarm.is_available and self.swarm.should_use_swarm(text):
                logger.info("Routing to Swarm for complex task processing.")
                swarm_res = self.swarm.process(text, context=rag_context)
                if swarm_res.success:
                    result = ActionResult.ok(swarm_res.content, capability="swarm_delegation")
                # If swarm fails, fall through to tool router

            # 4. LLM Tool Routing (Brain-mode)
            if result is None and self.llm and getattr(self.config, "llm_tool_routing_enabled", True):
                logger.info(f"Routing '{text}' via LLM Executive Brain...")
                # Note: We should pass rag_context to tool_router.select if we want it to see memory
                route = self.tool_router.select(text, context)
                if route:
                    if route.needs_clarification and route.clarify_question:
                        result = ActionResult.ok(route.clarify_question, capability="conversation")
                    elif route.capability.lower() != "none":
                        candidate = self.registry.get(route.capability)
                        if candidate:
                            context["_planned_params"] = route.parameters or {}
                            context["_llm_routed"] = True
                            context["_llm_route_confidence"] = route.confidence
                            logger.info(f"LLM routed to: {candidate.name} (Conf: {route.confidence})")
                            executed_capability = candidate
                            result = self._execute_with_loop_guard(candidate, text, context)

            # 5. Code Interpreter Fallback (High-Performance Logic)
            if result is None:
                math_logic_keywords = ["calculate", "math", "fibonacci", "sort", "reverse", "date of"]
                if any(k in text.lower() for k in math_logic_keywords):
                    interpreter = self.registry.get("code_interpreter")
                    if interpreter:
                        logger.info("Routing to Code Interpreter for math/logic task.")
                        executed_capability = interpreter
                        result = self._execute_with_loop_guard(interpreter, text, context)

            # 5.5 Deterministic fallback: if we *did* match a capability but LLM routing
            # produced nothing (or the LLM is unavailable), prefer the best local match
            # over the conversation fallback.
            if result is None and capability and score >= float(getattr(self.config, "llm_tool_routing_match_threshold", 0.18)):
                try:
                    logger.info(f"Deterministic fallback match: {capability.name} (Score: {score})")
                    executed_capability = capability
                    result = self._execute_with_loop_guard(capability, text, context)
                except Exception:
                    result = None

            # 6. Final Fallback: Conversation (Cloud/Large LLM)
            if result is None:
                logger.info("No local capability or interpreter fit. Falling back to Conversation flow.")
                result = ActionResult.ok("__LLM_ROUTE__")

        verification = {}
        verification_attempts = []
        evidence_accum = _evidence_from_result(result) if result else []
        cap_for_evidence = str(
            (getattr(executed_capability, "name", "") if executed_capability else "")
            or (getattr(result, "capability_name", "") if result else "")
            or ""
        ).strip()
        side_effect_log_accum = _build_side_effect_log(result, cap_for_evidence)
        execution_contract = None
        contract_eval_obj = None
        contract_eval: Dict[str, Any] = {}
        failure_type = ""
        cap_name = ""
        try:
            cap_name = str(
                (getattr(executed_capability, "name", "") if executed_capability else "")
                or (getattr(result, "capability_name", "") if result else "")
                or ""
            ).strip()
            if cap_name:
                from chintu_backend.core.execution_contracts import get_execution_contract

                execution_contract = get_execution_contract(cap_name)
        except Exception:
            execution_contract = None

        # Verification-driven retries: only for safe capabilities and only when we have checks.
        if (
            executed_capability
            and result
            and bool(getattr(result, "success", False))
            and not bool(getattr(result, "requires_confirmation", False))
        ):
            try:
                from chintu_backend.core.verification import verify_action_result

                contract_max_attempts = int(
                    getattr(getattr(execution_contract, "retry_policy", None), "max_verification_attempts", 0) or 0
                )
                if contract_max_attempts <= 0:
                    contract_max_attempts = int(self.max_verification_attempts)
                max_attempts = max(1, min(int(self.max_verification_attempts), contract_max_attempts))
                for attempt in range(1, max_attempts + 1):
                    verification = verify_action_result(result)
                    verification_attempts.append(
                        {
                            "attempt": attempt,
                            "capability": getattr(executed_capability, "name", "") or getattr(result, "capability_name", ""),
                            "success": bool(getattr(result, "success", False)),
                            "verification": verification,
                        }
                    )

                    checks = verification.get("checks") if isinstance(verification, dict) else None
                    has_checks = bool(isinstance(checks, list) and len(checks) > 0)
                    ok = bool(verification.get("ok")) if isinstance(verification, dict) else False

                    cap_name = str(cap_name or getattr(executed_capability, "name", "") or getattr(result, "capability_name", "")).strip()

                    # If verified (or unverifiable), we're done.
                    if not has_checks:
                        # Avoid recording "verification_ok: False" for purely informational
                        # commands where we have no deterministic checks to run.
                        verification = {}
                        break
                    if ok:
                        break

                    # Only retry a small allowlist to avoid duplicating risky side-effects.
                    contract_allows_retry = bool(
                        getattr(getattr(execution_contract, "retry_policy", None), "retry_on_verification_failure", False)
                    )
                    if cap_name not in self.verification_retry_capabilities and not contract_allows_retry:
                        break

                    if attempt >= max_attempts:
                        break

                    # Honor cancellation between retries.
                    if run_mgr and run_mgr.is_cancel_requested(str(run_id)):
                        result = ActionResult.fail("Cancelled.", capability="cancelled")
                        verification = {}
                        break

                    logger.info(
                        "Verification failed for %s; retrying (%s/%s).",
                        cap_name,
                        attempt,
                        max_attempts,
                    )
                    # Retry the same capability with the same inputs.
                    result = self._execute_with_loop_guard(executed_capability, text, context)
                    evidence_accum.extend(_evidence_from_result(result))
                    if result:
                        retry_cap = str(
                            getattr(executed_capability, "name", "")
                            or getattr(result, "capability_name", "")
                            or cap_name
                        ).strip()
                        for row in _build_side_effect_log(result, retry_cap):
                            if row not in side_effect_log_accum:
                                side_effect_log_accum.append(row)
            except Exception:
                verification = {}
                verification_attempts = []

        # Evaluate Phase-2 execution contract (expected artifacts + verification hooks).
        try:
            if result and bool(getattr(result, "success", False)) and not bool(getattr(result, "requires_confirmation", False)):
                from chintu_backend.core.execution_contracts import evaluate_execution_contract

                if execution_contract is not None:
                    contract_eval_obj = evaluate_execution_contract(execution_contract, verification if isinstance(verification, dict) else {})
                    contract_eval = contract_eval_obj.to_dict()
                    if not contract_eval_obj.ok:
                        detail = contract_eval_obj.detail or "I couldn't verify the requested action."
                        if "path_exists" in str(detail):
                            detail = "I couldn't verify the file/artifact was created. Please try again."
                        result = ActionResult.fail(
                            detail,
                            capability=str(getattr(result, "capability_name", "") or ""),
                        )
        except Exception:
            pass

        dependency_recovery: Dict[str, Any] = {}
        if (
            executed_capability
            and result
            and not bool(getattr(result, "success", False))
            and not bool(getattr(result, "requires_confirmation", False))
        ):
            try:
                result, dependency_recovery = self._maybe_recover_missing_dependency(
                    result=result,
                    capability=executed_capability,
                    text=text,
                    context=context,
                )
            except Exception as exc:
                logger.warning("Dependency recovery attempt failed: %s", exc)
                dependency_recovery = {}

        # Attach normalized failure taxonomy for receipts and retry planners.
        try:
            if result and not bool(getattr(result, "success", False)):
                failure_type = classify_failure_type(str(getattr(result, "message", "") or ""), contract_eval_obj)
        except Exception:
            failure_type = ""

        self_healing: Dict[str, Any] = {}
        if (
            executed_capability
            and result
            and not bool(getattr(result, "success", False))
            and not bool(getattr(result, "requires_confirmation", False))
        ):
            try:
                result, self_healing = self._maybe_self_heal_failure(
                    result=result,
                    capability=executed_capability,
                    text=text,
                    context=context,
                    failure_type=failure_type,
                    execution_contract=execution_contract,
                )
                # Re-classify if recovery still failed with a new message.
                if result and not bool(getattr(result, "success", False)):
                    failure_type = classify_failure_type(str(getattr(result, "message", "") or ""), contract_eval_obj)
                elif result and bool(getattr(result, "success", False)):
                    failure_type = ""
            except Exception as exc:
                logger.warning("Phase-7 self-healing failed: %s", exc)
                self_healing = {}

        if result and bool(getattr(result, "requires_confirmation", False)) and getattr(result, "pending_action", None):
            if not self.registry.has_pending():
                self._pending_confirmation = result

        if result:
            final_cap = str(
                (getattr(executed_capability, "name", "") if executed_capability else "")
                or getattr(result, "capability_name", "")
                or cap_name
            ).strip()
            for row in _build_side_effect_log(result, final_cap):
                if row not in side_effect_log_accum:
                    side_effect_log_accum.append(row)

        if run_mgr and step_id and result:
            try:
                status = "completed" if result.success else "failed"
                if getattr(result, "requires_confirmation", False):
                    status = "waiting_approval"
                elif isinstance(getattr(result, "data", None), dict) and bool(
                    result.data.get("awaiting_user_action")
                    or result.data.get("manual_login_required")
                    or result.data.get("pending_user_input")
                    or result.data.get("waiting_for_user")
                ):
                    status = "waiting_input"
                meta = {}
                if verification:
                    meta["verification"] = verification
                if verification_attempts:
                    meta["verification_attempts"] = verification_attempts
                if execution_contract is not None:
                    try:
                        from chintu_backend.core.execution_contracts import contract_to_dict

                        meta["execution_contract"] = contract_to_dict(execution_contract)
                    except Exception:
                        pass
                if contract_eval:
                    meta["contract_evaluation"] = contract_eval
                if failure_type:
                    meta["failure_type"] = failure_type
                if dependency_recovery:
                    meta["dependency_recovery"] = dependency_recovery
                if self_healing:
                    meta["self_healing"] = self_healing
                if side_effect_log_accum:
                    meta["side_effect_log"] = side_effect_log_accum
                if self.gpu_resource_manager and bool(getattr(self.config, "gpu_step_telemetry_enabled", True)):
                    try:
                        gpu_after_snapshot = self.gpu_resource_manager.capture_snapshot()
                        gpu_cap_name = str(
                            getattr(result, "capability_name", "")
                            or getattr(executed_capability, "name", "")
                            or ""
                        ).strip()
                        meta["gpu_resource"] = self.gpu_resource_manager.build_step_meta(
                            gpu_cap_name,
                            gpu_before_snapshot,
                            gpu_after_snapshot,
                        )
                    except Exception:
                        pass
                run_mgr.end_step(
                    str(run_id),
                    step_id,
                    status=status,
                    message=result.message,
                    capability=result.capability_name,
                    evidence=evidence_accum,
                    meta=meta or None,
                )
                if getattr(result, "requires_confirmation", False):
                    run_mgr.mark_waiting_approval(str(run_id), prompt=result.message, capability=result.capability_name)
            except Exception:
                pass

        return result

    def _maybe_recover_missing_dependency(
        self,
        *,
        result: ActionResult,
        capability,
        text: str,
        context: Dict[str, Any],
    ) -> Tuple[ActionResult, Dict[str, Any]]:
        if not bool(getattr(self.config, "dependency_bootstrap_enabled", True)):
            return result, {}
        if context.get("_dependency_recovery_attempted"):
            return result, {}

        max_attempts = int(getattr(self.config, "dependency_bootstrap_max_attempts", 1))
        attempts = int(context.get("_dependency_recovery_attempts", 0) or 0)
        if attempts >= max(1, max_attempts):
            return result, {}

        failure_type = classify_failure_type(str(getattr(result, "message", "") or ""))
        if failure_type != FailureTaxonomy.missing_dependency.value:
            return result, {}

        cap_name = str(getattr(capability, "name", "") or getattr(result, "capability_name", "") or "").strip()
        validated = context.get("_validated_params")
        extracted = context.get("_extracted_params")
        cwd_value = ""
        if isinstance(validated, dict):
            cwd_value = str(validated.get("cwd") or "")
        else:
            cwd_value = str(getattr(validated, "cwd", "") or "")
        if not cwd_value:
            if isinstance(extracted, dict):
                cwd_value = str(extracted.get("cwd") or "")
            else:
                cwd_value = str(getattr(extracted, "cwd", "") or "")
        planning_context = {
            "capability_name": cap_name,
            "cwd": cwd_value or str(context.get("cwd") or ""),
        }

        plan = self.dependency_bootstrap.plan_from_failure(
            str(getattr(result, "message", "") or ""),
            context=planning_context,
        )
        if not plan:
            return result, {}

        base_meta = {
            "enabled": True,
            "dependency_name": plan.dependency_name,
            "dependency_kind": plan.dependency_kind,
            "plan_requires_confirmation": bool(plan.requires_confirmation),
            "plan_command_preview": plan.command_preview(),
        }

        if plan.requires_confirmation and not context.get("_confirmed_dependency_install"):
            def pending_install() -> ActionResult:
                install_context = dict(context or {})
                install_context["_confirmed_dependency_install"] = True
                install_context["_dependency_recovery_attempted"] = True
                install_context["_dependency_recovery_attempts"] = attempts + 1
                return self._execute_dependency_recovery(
                    plan=plan,
                    capability=capability,
                    text=text,
                    context=install_context,
                )

            confirmation_msg = (
                f"Dependency fix needed for '{plan.dependency_name}'. "
                f"{plan.confirmation_reason or 'Install requires confirmation.'}\n\n"
                f"I can run:\n`{plan.command_preview()}`"
            )
            confirm_result = ActionResult.confirm(confirmation_msg, pending_install, cap_name)
            return confirm_result, {
                **base_meta,
                "status": "waiting_approval",
            }

        install_context = dict(context or {})
        install_context["_dependency_recovery_attempted"] = True
        install_context["_dependency_recovery_attempts"] = attempts + 1
        recovered = self._execute_dependency_recovery(
            plan=plan,
            capability=capability,
            text=text,
            context=install_context,
        )

        recovery_payload: Dict[str, Any] = dict(base_meta)
        data = recovered.data if isinstance(recovered.data, dict) else {}
        dep_data = data.get("dependency_recovery") if isinstance(data, dict) else {}
        if isinstance(dep_data, dict):
            recovery_payload.update(dep_data)
        recovery_payload["status"] = "success" if recovered.success else "failed"
        return recovered, recovery_payload

    def _execute_dependency_recovery(
        self,
        *,
        plan: InstallPlan,
        capability,
        text: str,
        context: Dict[str, Any],
    ) -> ActionResult:
        recovery_result: DependencyRecoveryResult = self.dependency_bootstrap.execute_plan(
            plan,
            context=context,
        )
        cap_name = str(getattr(capability, "name", "") or "")
        recovery_data = {
            "dependency_recovery": {
                "success": bool(recovery_result.success),
                "message": recovery_result.message,
                "receipt_path": recovery_result.receipt_path,
                "installed": list(recovery_result.installed),
                "rollback_hints": list(recovery_result.rollback_hints),
            }
        }
        if not recovery_result.success:
            return ActionResult(
                success=False,
                message=f"{recovery_result.message}\nReceipt: {recovery_result.receipt_path}",
                data=recovery_data,
                capability_name=cap_name,
            )

        if not bool(getattr(self.config, "dependency_bootstrap_auto_resume", True)):
            msg = f"{recovery_result.message}\nReceipt: {recovery_result.receipt_path}"
            return ActionResult.ok(msg, data=recovery_data, capability=cap_name)

        resume_context = dict(context or {})
        resume_context["_dependency_recovery_attempted"] = True
        resume_result = self._execute_capability(capability, text, resume_context)
        if not isinstance(resume_result.data, dict):
            resume_result.data = {}
        if isinstance(resume_result.data, dict):
            resume_result.data.update(recovery_data)
        resume_result.message = f"{recovery_result.message}\n\n{resume_result.message}".strip()
        return resume_result

    def _maybe_self_heal_failure(
        self,
        *,
        result: ActionResult,
        capability,
        text: str,
        context: Dict[str, Any],
        failure_type: str,
        execution_contract=None,
    ) -> Tuple[ActionResult, Dict[str, Any]]:
        """Phase 7: failure-aware retries + fallback graph + graceful watchdog stop."""
        if not bool(getattr(self.config, "phase7_self_healing_enabled", True)):
            return result, {}

        cap_name = str(getattr(capability, "name", "") or getattr(result, "capability_name", "") or "").strip()
        if not cap_name:
            return result, {}

        attempts_map = context.get("_phase7_recovery_attempts")
        if not isinstance(attempts_map, dict):
            attempts_map = {}
            context["_phase7_recovery_attempts"] = attempts_map
        attempt = int(attempts_map.get(cap_name, 0) or 0)
        max_attempts = int(getattr(self.config, "phase7_max_recovery_attempts", 2))
        allow_cloud_fallback = bool(getattr(self.config, "phase7_cloud_fallback_enabled", True))
        no_cloud_fallback_caps = {
            "system_info",
            "volume_control",
            "remember_fact",
            "list_calendar",
            "social_publish_post",
            "repo_search",
            "dependency_summary",
        }
        if cap_name in no_cloud_fallback_caps:
            allow_cloud_fallback = False
        if (
            str(failure_type or "").strip().lower() == FailureTaxonomy.verification_failed.value
            and bool(getattr(execution_contract, "enforce", False))
        ):
            # Keep deterministic contract failures local; cloud fallback would bypass hard guarantees.
            allow_cloud_fallback = False

        run_key = str(context.get("_run_id") or context.get("session_id") or "global")
        watchdog = self.plan_watchdog.register_failure(
            run_key=run_key,
            capability_name=cap_name,
            failure_type=failure_type,
            message=str(getattr(result, "message", "") or ""),
        )

        alternatives = [
            alt
            for alt in self.fallback_graph.alternatives(cap_name)
            if alt and alt != cap_name and self.registry.get(alt) is not None
        ]
        plan = self.retry_planner.build_plan(
            capability_name=cap_name,
            failure_type=failure_type,
            attempt=attempt,
            max_attempts=max_attempts,
            allow_cloud_fallback=allow_cloud_fallback,
            local_alternatives=alternatives,
            watchdog_blocked=bool(watchdog.get("blocked")),
        )

        meta: Dict[str, Any] = {
            "enabled": True,
            "capability": cap_name,
            "failure_type": str(failure_type or ""),
            "attempt": attempt + 1,
            "max_attempts": max_attempts,
            "plan_actions": list(plan.actions),
            "alternatives": list(plan.alternatives),
            "watchdog": watchdog,
            "reason": plan.reason,
        }

        if not plan.actions:
            if bool(watchdog.get("blocked")):
                graceful = ActionResult.fail(
                    (
                        "I detected a repeated failure loop and stopped this step to avoid thrashing. "
                        "You can ask me to retry with cloud fallback or adjust the task."
                    ),
                    capability=cap_name,
                )
                return graceful, {**meta, "status": "watchdog_blocked"}
            return result, {**meta, "status": "no_recovery_plan"}

        attempts_map[cap_name] = attempt + 1
        last_result = result
        executed_actions: list[str] = []

        for action in plan.actions:
            if action == "retry_same":
                executed_actions.append("retry_same")
                retry_ctx = dict(context or {})
                retry_ctx["_phase7_recovery_active"] = True
                retried = self._execute_with_loop_guard(capability, text, retry_ctx)
                if retried.requires_confirmation:
                    self._attach_self_healing_data(
                        retried,
                        {
                            **meta,
                            "status": "recovered",
                            "strategy": "retry_same",
                            "executed_actions": executed_actions,
                        },
                    )
                    return retried, {**meta, "status": "recovered", "strategy": "retry_same", "executed_actions": executed_actions}
                if retried.success:
                    validated, retried = self._validate_recovery_result(
                        retried,
                        execution_contract=execution_contract,
                    )
                    if validated:
                        self._attach_self_healing_data(
                            retried,
                            {
                                **meta,
                                "status": "recovered",
                                "strategy": "retry_same",
                                "executed_actions": executed_actions,
                            },
                        )
                        return retried, {
                            **meta,
                            "status": "recovered",
                            "strategy": "retry_same",
                            "executed_actions": executed_actions,
                        }
                last_result = retried
                continue

            if action == "fallback_local":
                for alt_name in plan.alternatives:
                    alt_cap = self.registry.get(alt_name)
                    if alt_cap is None:
                        continue
                    executed_actions.append(f"fallback_local:{alt_name}")
                    alt_ctx = dict(context or {})
                    for key in (
                        "_planned_params",
                        "_extracted_params",
                        "_validated_params",
                        "_llm_routed",
                        "_llm_route_confidence",
                    ):
                        alt_ctx.pop(key, None)
                    alt_ctx["_phase7_recovery_active"] = True
                    alt_result = self._execute_with_loop_guard(alt_cap, text, alt_ctx)
                    if alt_result.requires_confirmation:
                        self._attach_self_healing_data(
                            alt_result,
                            {
                                **meta,
                                "status": "recovered",
                                "strategy": "fallback_local",
                                "selected_alternative": alt_name,
                                "executed_actions": executed_actions,
                            },
                        )
                        return (
                            alt_result,
                            {
                                **meta,
                                "status": "recovered",
                                "strategy": "fallback_local",
                                "selected_alternative": alt_name,
                                "executed_actions": executed_actions,
                            },
                        )
                    if alt_result.success:
                        validated, alt_result = self._validate_recovery_result(
                            alt_result,
                            execution_contract=execution_contract,
                        )
                        if validated:
                            self._attach_self_healing_data(
                                alt_result,
                                {
                                    **meta,
                                    "status": "recovered",
                                    "strategy": "fallback_local",
                                    "selected_alternative": alt_name,
                                    "executed_actions": executed_actions,
                                },
                            )
                            return (
                                alt_result,
                                {
                                    **meta,
                                    "status": "recovered",
                                    "strategy": "fallback_local",
                                    "selected_alternative": alt_name,
                                    "executed_actions": executed_actions,
                                },
                            )
                    last_result = alt_result
                continue

            if action == "fallback_cloud":
                executed_actions.append("fallback_cloud")
                cloud_route = ActionResult.ok(
                    "__LLM_ROUTE__",
                    data={
                        "phase7_self_healing": {
                            **meta,
                            "status": "recovered",
                            "strategy": "fallback_cloud",
                            "executed_actions": executed_actions,
                        }
                    },
                    capability="conversation",
                )
                return cloud_route, {
                    **meta,
                    "status": "recovered",
                    "strategy": "fallback_cloud",
                    "executed_actions": executed_actions,
                }

        self._attach_self_healing_data(
            last_result,
            {
                **meta,
                "status": "failed_after_recovery",
                "executed_actions": executed_actions,
            },
        )
        return last_result, {
            **meta,
            "status": "failed_after_recovery",
            "executed_actions": executed_actions,
        }

    def _validate_recovery_result(self, result: ActionResult, execution_contract=None) -> Tuple[bool, ActionResult]:
        """Re-apply verification/contract checks for Phase-7 recovery outcomes."""
        if not isinstance(result, ActionResult):
            return False, ActionResult.fail("Recovered action returned an invalid result type.")
        if bool(getattr(result, "requires_confirmation", False)):
            return True, result
        if not bool(getattr(result, "success", False)):
            return False, result

        verification: Dict[str, Any] = {}
        try:
            from chintu_backend.core.verification import verify_action_result

            verification = verify_action_result(result)
        except Exception:
            verification = {}

        if execution_contract is not None:
            try:
                from chintu_backend.core.execution_contracts import evaluate_execution_contract

                contract_eval_obj = evaluate_execution_contract(
                    execution_contract,
                    verification if isinstance(verification, dict) else {},
                )
                if not contract_eval_obj.ok:
                    detail = contract_eval_obj.detail or "I couldn't verify the requested action."
                    if "path_exists" in str(detail):
                        detail = "I couldn't verify the file/artifact was created. Please try again."
                    failed = ActionResult.fail(
                        detail,
                        capability=str(getattr(result, "capability_name", "") or ""),
                    )
                    if isinstance(result.data, dict):
                        failed.data = dict(result.data)
                    return False, failed
            except Exception:
                pass

        checks = verification.get("checks") if isinstance(verification, dict) else None
        if isinstance(checks, list) and checks and not bool(verification.get("ok")):
            failed = ActionResult.fail(
                "Recovered execution could not be verified.",
                capability=str(getattr(result, "capability_name", "") or ""),
            )
            if isinstance(result.data, dict):
                failed.data = dict(result.data)
            return False, failed
        return True, result

    @staticmethod
    def _attach_self_healing_data(result: ActionResult, payload: Dict[str, Any]) -> None:
        if not isinstance(result, ActionResult):
            return
        if isinstance(result.data, dict):
            result.data["phase7_self_healing"] = payload
            return
        result.data = {"phase7_self_healing": payload}

    def _loop_session_id(self, context: Dict[str, Any]) -> str:
        try:
            if isinstance(context, dict):
                sid = str(context.get("session_id") or "").strip()
                if sid:
                    return sid
        except Exception:
            pass
        return "global"

    def _execute_with_loop_guard(self, capability, text: str, context: Dict[str, Any]) -> ActionResult:
        """Execute capability with repeated-call loop guardrails."""
        session_id = self._loop_session_id(context)
        capability_name = str(getattr(capability, "name", "") or "")

        signal = self.loop_guard.detect(
            session_id=session_id,
            capability_name=capability_name,
            text=text,
        )
        if signal.blocked:
            logger.warning("Loop guard blocked capability %s: %s", capability_name, signal.message)
            return ActionResult.fail(signal.message, capability=capability_name)

        result = self._execute_capability(capability, text, context)
        completed_ok = bool(result.success and not result.requires_confirmation)
        self.loop_guard.record(
            session_id=session_id,
            capability_name=capability_name,
            text=text,
            success=completed_ok,
            message=result.message,
        )

        if signal.level == "warning" and result.success and not result.requires_confirmation:
            result.message = f"{result.message}\n\n{signal.message}"
        return result

    def _execute_capability(self, capability, text: str, context: Dict[str, Any]) -> ActionResult:
        """Executes the capability with parameters and persistence."""
        # Parameter Extraction & Validation
        if capability.schema:
            planned = context.get("_planned_params") or context.get("_extracted_params")
            if planned and isinstance(planned, dict):
                planned = self._normalize_params_for_schema(planned, capability.schema)
                context["_extracted_params"] = planned
                try:
                    context["_validated_params"] = capability.schema(**planned)
                except ValidationError as e:
                    logger.warning(f"Schema validation failed during dispatch for {capability.name}: {e}")
                    context.pop("_validated_params", None)

        # Execution
        result = self.registry.execute(capability, text, context)
        
        # Logging & Persistence
        try:
            mem = get_hybrid_memory()
            if mem:
                mem.save_interaction(
                    role="assistant",
                    content=f"Executed capability '{capability.name}': {result.message}",
                    meta={
                        "capability": capability.name,
                        "success": result.success,
                        "source": "action_dispatcher",
                        "route_reason": "fast_path" if not context.get("_llm_routed") else "llm_routing"
                    },
                    category="task_execution"
                )
        except Exception as e:
            logger.warning(f"Failed to persist interaction: {e}")

        return result

    def _normalize_params_for_schema(self, params: Dict[str, Any], schema: Any) -> Dict[str, Any]:
        """Normalize parameter keys to match schema."""
        if not isinstance(params, dict) or not schema:
            return params or {}
            
        try:
            schema_json = schema.model_json_schema() if hasattr(schema, "model_json_schema") else schema.schema()
            props = schema_json.get("properties", {}) if isinstance(schema_json, dict) else {}
        except Exception:
            props = {}

        alias_map = {
            "content": ["task", "task_content", "text", "title", "name", "value"],
            "query": ["question", "search", "q", "prompt", "text"],
            "topic": ["query", "subject", "text"],
            "time": ["when", "datetime", "date", "at"],
            "target": ["id", "name", "item"],
        }

        normalized = dict(params)
        for target, aliases in alias_map.items():
            if target in props and target not in normalized:
                for alias in aliases:
                    if alias in normalized and normalized.get(alias):
                        normalized[target] = normalized[alias]
                        break
        return normalized

    def get_pending_confirmation(self) -> Dict[str, Any]:
        """
        Returns any pending actions requiring user confirmation.
        (SafeExecutor usually handles this, but CommandHandler checks here too).
        """
        try:
            if self.registry and self.registry.has_pending():
                return self.registry.pending_snapshot()
        except Exception:
            pass
        pending = self._pending_confirmation
        if pending and pending.pending_action:
            return {
                "pending": True,
                "capability": pending.capability_name or "",
                "message": pending.message or "",
                "confirmation_type": pending.confirmation_type or "",
            }
        return {}

    def confirm_pending(self, context: Optional[Dict[str, Any]] = None):
        """Execute currently pending capability confirmation, if any.

        Note: Pending confirmations are often created by PolicyEngine before the
        underlying handler executes. The confirmed handler call can bypass the
        normal dispatch() step tracking, so we attach a dedicated run step here.
        """
        if not self.registry and not self._pending_confirmation:
            return None

        context = context or {}
        use_registry_pending = False
        try:
            use_registry_pending = bool(self.registry and self.registry.has_pending())
        except Exception:
            use_registry_pending = False
        pending_result = self._pending_confirmation if not use_registry_pending else None
        if pending_result and not pending_result.pending_action:
            pending_result = None

        # Prefer explicit run_id (CommandHandler resumes the run before confirming).
        run_id = ""
        try:
            if isinstance(context, dict):
                run_id = str(context.get("_run_id") or "").strip()
        except Exception:
            run_id = ""
        if not run_id:
            try:
                from chintu_backend.core.run_manager import get_run_manager

                run_id = str(get_run_manager().pending_confirmation_run_id() or "").strip()
            except Exception:
                run_id = ""

        pending = {}
        try:
            pending = self.get_pending_confirmation() or {}
        except Exception:
            pending = {}
        pending_cap = str(pending.get("capability") or "").strip()

        run_mgr = None
        exec_step_id = ""
        if run_id:
            try:
                from chintu_backend.core.run_manager import get_run_manager

                run_mgr = get_run_manager()
                # Mark the previously "waiting_approval" step as resolved so dashboards don't
                # show a finished run with a still-waiting step.
                prev_wait = run_mgr.find_last_step_id(run_id, status="waiting_approval", capability=pending_cap or None)
                if prev_wait:
                    run_mgr.end_step(
                        run_id,
                        prev_wait,
                        status="completed",
                        meta={"approved": True},
                    )
                exec_step_id = run_mgr.start_step(
                    run_id,
                    title=f"Execute after approval: {pending_cap or 'action'}",
                    capability=pending_cap or "",
                    meta={"kind": "confirmation"},
                )
            except Exception:
                run_mgr = None
                exec_step_id = ""

        result = None
        if use_registry_pending and self.registry:
            try:
                result = self.registry.confirm_pending()
            except Exception as e:
                logger.warning(f"Failed to confirm pending action: {e}")
                result = None
        elif pending_result and pending_result.pending_action:
            try:
                result = pending_result.pending_action()
            except Exception as e:
                logger.warning(f"Failed to confirm dispatcher pending action: {e}")
                result = ActionResult.fail(f"Action failed: {e}", capability=pending_cap)
            finally:
                self._pending_confirmation = None

        if run_mgr and run_id and exec_step_id and result:
            try:
                from chintu_backend.core.run_manager import EvidenceRef

                evidence = []
                data = result.data if isinstance(result.data, dict) else {}
                if isinstance(data, dict):
                    seen = set()
                    for key in ("path", "artifact_path", "file_path", "report_path", "screenshot", "filepath"):
                        path = data.get(key)
                        if path:
                            p = str(path)
                            if p and p not in seen:
                                seen.add(p)
                                evidence.append(EvidenceRef(kind="path", value=p, summary="artifact"))
                    url = data.get("url")
                    if url:
                        evidence.append(EvidenceRef(kind="url", value=str(url), summary="url"))

                status = "completed" if bool(getattr(result, "success", False)) else "failed"
                if bool(getattr(result, "requires_confirmation", False)):
                    status = "waiting_approval"

                verification = {}
                if bool(getattr(result, "success", False)) and not bool(getattr(result, "requires_confirmation", False)):
                    try:
                        from chintu_backend.core.verification import verify_action_result

                        verification = verify_action_result(result)
                    except Exception:
                        verification = {}

                meta = {"verification": verification} if verification else None
                run_mgr.end_step(
                    run_id,
                    exec_step_id,
                    status=status,
                    message=getattr(result, "message", "") or "",
                    capability=str(getattr(result, "capability_name", "") or pending_cap or ""),
                    evidence=evidence,
                    meta=meta,
                )
                if bool(getattr(result, "requires_confirmation", False)):
                    run_mgr.mark_waiting_approval(run_id, prompt=getattr(result, "message", "") or "", capability=pending_cap)
                    if not use_registry_pending:
                        self._pending_confirmation = result
            except Exception:
                pass

        return result

    def cancel_pending(self) -> bool:
        """Cancel currently pending capability confirmation, if any."""
        cancelled = False
        if self.registry:
            try:
                had_pending = bool(self.registry.has_pending())
                self.registry.cancel_pending()
                cancelled = cancelled or had_pending
            except Exception as e:
                logger.warning(f"Failed to cancel pending action: {e}")
        if self._pending_confirmation:
            self._pending_confirmation = None
            cancelled = True
        return cancelled
