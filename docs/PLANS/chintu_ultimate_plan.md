# Chintu Ultimate Plan (Production-Grade Autonomy)

Plan status: v2 finalized for execution (2026-03-03)

## What Changed In v2

- Integrated the local-first autonomous cofounder architecture synthesis into the execution contracts.
- Integrated audit-priority improvements for maintainability, reliability, testing, UI completion, and operations.
- Added planned phases for multi-persona specialist mode, Telegram Mini App control plane, and full autonomy integration gates.
- Locked infrastructure scope to single-machine, single-tenant, single-process baseline with internal queues; Redis/RabbitMQ and microservices remain deferred/optional.
- Deferred extreme 70B disk-streaming local inference to an experimental appendix.
- Tracked the audit handoff in `docs/PLANS/Chintu AI - Comprehensive Audit Rep.md`.

## Status As Of 2026-03-03 17:52:06Z

- `gates all` passes end-to-end, including phases 17/18/19/27/28/29 plus deployment preflight and release readiness.
- `gates ci` and `gates ci --skip-flutter-tests` both pass with receipt generation in `generated_reports`.
- Python suite currently passes (`155 passed`) and Flutter UI suite passes (`flutter test --concurrency=1`).
- Remaining roadmap items stay in planned phase order; no locked phase behavior was redefined.

## Mission

Build Chintu as a local-first autonomous system that can handle almost any practical task end-to-end with:
- strong planning,
- reliable execution,
- automatic skill reuse/generalization,
- safe dependency/bootstrap management,
- long-term memory and training data capture,
- human-quality voice interaction (STT + smart TTS).

## Non-Negotiable Requirements

1. **Finish tasks, not partial attempts**
   - Every task runs under a plan with verification and retries.
   - "Success" is allowed only with evidence.

2. **Generalize skills by default**
   - New skills must be reusable families, not one-off copies (no "ssd skill", then "monitor skill", etc.).
   - Similar requests should map to the same generalized skill.

3. **Bootstrap dependencies automatically**
   - If a task requires missing packages/tools, Chintu plans and installs them in the correct environment (venv/container), then re-runs verification.

4. **Preserve conversation + execution history**
   - Store task intent, plans, tool calls, outputs, artifacts, and outcomes for recall, auditing, and future training.

5. **Voice quality must be production-grade**
   - STT must be robust under noise/interruptions.
   - TTS must speak only human-relevant content by default (skip links/citations/paths unless user asks).

6. **Smart model selection (local + cloud)**
   - Route work to the best model/provider for the task (intent, complexity, cost, latency, reliability, privacy).
   - Prefer local models when possible; use cloud models when it materially improves outcomes.
   - Track provider/model performance over time and adapt routing.

7. **Stay current on AI + tech**
   - Daily ingestion of AI/tech news + model/tool releases into memory.
   - Maintain a local "model/tool catalog" so Chintu can recommend and choose up-to-date options.

8. **WAT-style workflows (Workflows + Agent + Tools)**
   - Repeatable work is captured as editable Markdown workflows (SOPs) plus strict output schemas.
   - The agent uses those workflows to plan/execute, and improves them over time via gated edits (diff + tests + approval).
   - Side effects happen only through deterministic tools (scripts/capabilities), not free-form LLM text.

9. **Sandbox + supply-chain safety by default**
   - Treat all external content and third-party code (skills, plugins, repos) as untrusted by default.
   - Prefer isolated execution (uv ephemeral envs, Docker/WSL2, optional remote sandboxes) for untrusted code.
   - New skill sources must be pinned (repo + commit), reviewed/scanned, and approved before use.

## Safety Boundaries (Hard Rules)

- **No payments allowed**: never click "buy", "checkout", "pay", "subscribe", "upgrade plan", or enter payment details.
- **No destructive actions without explicit confirmation**: deletes, resets, formatting, uninstalling, registry edits, or bulk file moves require confirmation + receipts.
- **Protected paths**: do not read/modify outside allowed roots (workspace + explicitly permitted directories).
- **Account actions require confirmation**: sign-ups/account creation, posting/uploading/publishing, logging in, changing account settings, or sending messages must be gated.
- **Credentials are never handled as raw passwords**:
  - Chintu should not ask for, store, or repeat passwords in chat/logs.
  - Prefer OAuth tokens stored in the Identity Vault (encrypted at rest) with least-privilege scopes and revocation.
  - For browser logins, Chintu can navigate to the login page and wait; the user enters credentials manually.
- **Calls/messages require explicit intent + gating**:
  - Calls/messages to anyone except the configured owner/master require explicit confirmation.
  - Calls to the configured owner/master can be allowed without confirmation (configurable), and must still be logged with receipts.
- **Third-party code and plugins are untrusted by default**:
  - Installing/enabling skills/plugins from the internet requires explicit confirmation and a provenance receipt (source + pinned commit/tag).
  - Untrusted code should run in sandboxed workspaces (container/uv env/remote sandbox) with minimal file access and no secrets mounted.

## External Baseline (Reference Areas)

Reference areas from external autonomy frameworks (kept as optional reference material):
- `docs/concepts/architecture.md`
- `docs/tools/exec-approvals.md`
- `docs/tools/loop-detection.md`
- `src/agents/tool-policy.ts`
- `src/agents/tool-loop-detection.ts`
- `src/commands/doctor-security.ts`

Adoption notes: consolidated into this plan and `docs/PLANS/PHASE_LOCKS.md`.

## Other Reference Systems (Patterns To Steal, Not Copy)

These are the "design patterns" we want to incorporate so Chintu ends up *more reliable*, *more secure*, and *more usable* than any single framework:

- **NanoClaw**: small, hackable core; "skills are tiny programs"; container-first isolation by default.
- **ZeroClaw**: security-first autonomy levels + explicit tool allowlists/deny-lists; predictable execution boundaries.
- **TrustClaw**: OAuth-first integrations and strong auditability/governance posture (tokens over passwords).
- **Nanobot (MCP-native agents)**: standard tool protocol + UI-capable tools; composability across ecosystems.
- **Moltworker**: gateway/control-plane thinking and remote access patterns (cloud edge + local node) without exposing the PC directly.

Chintu's target outcome comes from combining: **(1) control plane + observability**, **(2) sandbox-by-default execution**, **(3) evidence-based completion**, **(4) safe self-improvement**, and **(5) professional cofounder workflows**.

## Current Implemented Foundation (Completed)

1. **Skill policy contracts + low-friction confirmations**
   - Auto-contract registration for loaded skills.
   - Low-risk skills do not ask unnecessary confirmations.

2. **Loop guard + safer dispatch**
   - Per-session repeated-call detection (warning + critical block).
   - Dispatcher loop-aware execution path.

3. **Model-router reliability fixes**
   - Safer kwargs handling for model client compatibility.
   - Better fallback behavior when model calls fail.

4. **Skill runtime hardening**
   - Skill shell Python commands forced to current venv interpreter.

5. **Daily briefing quality**
   - Fresh multi-source ingest, recency filters, category balancing, read-more flow.

6. **Generic price-compare family skill**
   - `skill::price-compare` now handles broad product categories, not SSD-only.

7. **Global proposal-time skill generalization policy**
   - Auto-generalization and duplicate blocking for narrow skill drafts.

8. **Doctor checks + regression validation**
   - Runtime health checks and end-to-end task validation scripts.

9. **Curated skills bootstrap flow**
   - Added a staged skills catalog and installer (`chintu skills catalog`, `chintu skills bootstrap`) so initial "good-to-have" skills are installed as a controlled pack and later/community entries stay manual-review by default.

10. **Third-party skill discovery/import flow**
   - Added GitHub scout/import commands (`chintu skills scout-github`, `chintu skills import-github`) with provenance tagging and Phase 25 supply-chain enforcement before activation.
   - Added GitHub ranking + thresholded auto-import (`chintu skills rank-github`, `chintu skills auto-import-github`) so Chintu can prioritize importable skill repos and avoid low-signal candidates.

9. **Vision extraction hardening (local-first)**
   - Local-first vision backend default (`qwen3-vl:8b`) with model fallback chain.
   - Robust response normalization (JSON extraction + plain-text fallback parsing).
   - Human-style screen summaries (key elements, actions, readable text, running apps).

10. **TTS runtime resilience hardening**
    - Shutdown-safe Edge-TTS handling (no noisy runtime-shutdown failures).
    - Controlled local fallback behavior and reduced fallback error spam.

11. **Browser reliability hardening**
    - Structured DOM pruning + bounded wait primitives to reduce context bloat and SPA freeze/stall failures.
    - YouTube channel setup moved to checkpointed state-machine navigation (`switch account -> all channels -> create channel -> form -> submit`).
    - Tier-3 vision fallback now prefers high-precision model ordering with explicit main-GPU routing.

## Target Architecture

1. **Planner (local brain first)**
   - Creates a typed plan graph (steps, preconditions, dependencies, success criteria).

2. **Executor**
   - Runs one step at a time with policy checks and workspace boundaries.

3. **Verifier**
   - Confirms artifacts/outputs and enforces "no evidence, no success."

4. **Model Orchestrator**
   - Chooses provider/model per step using constraints (privacy, budget, time) and measured performance.
   - Supports pinned preferences, provider fallbacks, and "safe-mode" routing.
   - Provider switching (cloud APIs + cloud Ollama + local) with budget/quota awareness:
     - Cloud APIs (when keys/quotas allow): NVIDIA NIM (Kimi), Groq, Gemini, DeepSeek, Anthropic, etc.
     - Cloud Ollama (when configured): remote Ollama endpoints/models (e.g., DeepSeek, MiniMax M2) as a cost-effective fallback when cloud APIs are rate-limited.
     - Local Ollama: on-device models on RTX 3060 / GTX 1650.
     - CPU: safe fallback when GPUs/providers are unavailable or over budget.
   - Configurable routing ladder:
     - privacy-first: `local -> cloud -> cpu` when `routing_prefer_privacy=true`.
     - free/cost-first: `cloud -> cloud_ollama -> local -> cpu` when `routing_prefer_free=true`.
   - Always record provider/model choice + rationale into the run dossier (so routing decisions are auditable and can be tuned safely).

5. **Skill System**
   - Reusable skill families, auto-proposal, approval workflow, duplicate prevention.

6. **Dependency Manager**
   - Detects missing requirements and installs in controlled environments.

7. **Memory + Training Pipeline**
   - Durable logs, retrieval-ready memory, and export pipeline for model tuning.

8. **Knowledge Updater (Local RAG)**
   - Ingests AI/tech news + model/tool releases on a schedule.
   - Embeds daily items into a local vector store (Chroma or LanceDB) to avoid context-window bloat.
   - Planner queries this store on-demand; daily digests are summaries with "read more" expansion on request.
   - Prefer a small embedding model on GTX 1650 (fallback to CPU) to keep RTX 3060 free for the main brain.

9. **Voice Layer**
   - STT robustness + smart TTS rendering policy.

10. **Gateway / Control Plane**
   - Sessions, channels, device-nodes, and a single audit/event stream for everything Chintu does.
   - Enables "cofounder" usage: always-on, multi-channel, safe remote access, strong governance.
   - Tool protocol: MCP-first (or MCP-compatible wrappers) so new tools plug in without custom glue.

11. **Browser Autopilot**
   - DOM-first automation (Playwright) + screen-fallback (vision) with a strict relevance policy.
   - Anti prompt-injection scanning on web content + hard gates for login/submit/publish.
   - Use GTX 1650 as the default "sanitizer" GPU: scan/summarize raw web text before it reaches the executive brain on RTX 3060.
   - Enforce a strict execution contract per step: `snapshot -> act -> verify` with evidence artifacts.
   - Use token-pruned A11y snapshots (drop hidden/non-interactive noise) before sending context to planners/models.
   - Use SPA-safe waits: bounded `wait_for_load_state` plus selector/ref visibility checks (no unbounded waiting).
   - For Tier-3 visual grounding fallback (coordinate-level clicks/types), route by default to RTX 3060 high-precision vision models.
   - Handle hostile auth/account flows with explicit state machines instead of free-form page guessing.

12. **Dashboard Studio (Ops + Domain Dashboards)**
   - Generates dashboards (Streamlit/FastAPI+UI) from data sources and from Chintu's own run telemetry.
   - Provides a "single pane of glass" for: reliability, costs, GPU/latency, tasks, content pipelines, and finance (read-only).

13. **Identity + OAuth Vault**
   - OAuth tokens, scopes, and revocation tooling; encrypted at rest; never exfiltrated to cloud LLMs.
   - Owner/master profile:
     - name, email, phone, timezone, and safe contact rules (who can be called/messaged without confirmation).
   - Assistant identity support:
     - optional dedicated browser profile(s) for the assistant's own accounts (email, social, etc.),
     - passwords are never stored in plain text; login is user-entered in the browser when required.
   - Secret hygiene:
     - secrets are never written to logs, reports, or chat transcripts,
     - vault supports rotation/revocation receipts and least-privilege defaults.

14. **Inbox Intake + Knowledge Curation**
   - Ingests user-shared content from channels (Telegram) and local drop locations (links, images, videos, documents).
   - Extracts signal locally first (OCR/transcription), summarizes, classifies, and stores into local RAG with provenance.
   - Produces: "What I learned" + "What I'll do next" (store only, draft tasks, or propose a new workflow/tool) with approvals for any sensitive action.

15. **Workspace + Sandbox Runtime**
   - A workspace abstraction to run tasks in:
     - local Windows host (for OS/UI control, gated),
     - Docker/WSL2 sandboxes (default for untrusted code),
     - optional remote sandbox providers for high-risk code execution without touching the PC.
   - Enforces minimal mounts, secret isolation, and idempotent retries (no double side effects).

## Execution Roadmap (Accurate And Followable)

Status as of 2026-03-03:
- Phases 1-16 and 20-26 are implemented and locked (see `docs/PLANS/PHASE_LOCKS.md`).
- Active work should focus on reliability hardening, benchmark drift monitoring, and incremental quality improvements within locked contracts.
- Quality gate chain currently passes end-to-end via `chintu gates all` with generated receipts for Phases 17, 18, 19, 27, 28, and 29.
- Flutter UI widget tests are passing on current baseline (`flutter test` in `chintu_ui`).
- CI chain gate is available and passing in local runs (`chintu gates ci --skip-flutter-tests`).
- Ops runbooks now include incident response and disaster recovery playbooks in `docs/runbooks/`.
- Release-readiness gate is available (`chintu gates release`) with static packaging policy checks and optional package smoke validation.
- Deployment preflight gate is available (`chintu gates preflight`) with optional doctor/docker active checks.

### Priority Crosswalk (Strategic Priorities -> Phase Contracts)

| Strategic priority | Maps to locked phases | Maps to planned phases | Exit gate / evidence |
| --- | --- | --- | --- |
| 1. Cloud escalation cascade | 2.5, 7, 11, 23 | 29 (hardening + integration tests) | escalation reason codes, structured artifacts, verified completion receipts |
| 2. Operationalize training loop | 5, 15, 22 | 29 (eval hardening only) | dataset/export receipts, eval metrics, approval-gated activation |
| 3. Autonomous skill creation | 3, 15, 25, 26 | 19 (workflow-pack productization) | proposal/approval records, sandboxed execution evidence |
| 4. Multi-persona specialist mode | none | 27 | persona routing evidence in run dossier, no policy drift |
| 5. Telegram interface enhancement | 12, 21 | 28 | remote approval receipts, signed approval payload trace |
| 6. Modularization | none | 17 (expanded) | no-behavior-drift regression results, file-size guardrail reports |
| 7. Progressive local training | 22 | 29 (regression gates + drift monitoring) | gated adapter evals and promotion receipts |
| 8. UI vNext | none | 18 | operator can control runs/approvals/evidence without logs |
| 9. Cofounder workflow packs | none | 19 | end-to-end replayable pack benchmarks with evidence |
| 10. Full autonomy integration testing | none | 29 | complex run contract passes (local -> escalation -> verify -> train artifact) |

### Completed (Locked)

These phases are already implemented and tracked in a single lock index: `docs/PLANS/PHASE_LOCKS.md`.

Contract rule:
- Do not change locked behavior without updating `docs/PLANS/PHASE_LOCKS.md` and adding/adjusting tests.

---

### Forward Roadmap (Planned, Post-Lock)

This is the phase-by-phase plan from here onward. Completed/locked phases are referenced above; their detailed designs live in the lock reports to avoid duplication and drift.

Each new phase must produce:
- a lock report under `docs/PLANS/phaseXX_lock_report.md`,
- targeted tests for the new behavior,
- and a short operator runbook describing how to use/debug it.

Recommended execution order (dependency-first):
- Phase 18 (UI vNext) and Phase 17 (maintainability) can run in parallel
- Phase 19 (cofounder workflow packs)
- Phase 27 (persona adapters + playbooks)
- Phase 28 (Telegram Mini App control plane)
- Phase 29 (full integration/perf/chaos gates as final readiness gate)

Infrastructure boundary for this roadmap window:
- Keep single-machine, single-tenant, single-process baseline with internal queues.
- Treat Redis/RabbitMQ and microservices decomposition as deferred/optional extensions, not mandatory prerequisites for Phases 17-29.

---

### Phase 16 - Human Output Layer + Multi-turn Context
**Goal:** Chintu responds like a professionally built assistant (great text and great speech) and does not lose context between turns.

Status: **LOCKED** (tracked in `docs/PLANS/PHASE_LOCKS.md`)

Why:
- Chat output should be complete, but TTS should sound human (no reading URLs, file paths, underscores, or markdown noise unless asked).
- Multi-turn flows must reliably resolve follow-ups like "read more about #1".

Current progress (implemented):
- TTS sanitization now defaults to human-first spoken output:
  - suppresses link/path/code-table meta hints by default,
  - returns a human fallback when output is only technical artifacts.
- Empty post-sanitization responses now recover via conversation fallback (prevents generic dead-end replies for creative prompts).
- Morning briefing context continuity hardened:
  - briefing items persist to `~/.chintu/daily_briefing_cache.json`,
  - `read more about #N` works across session/process gaps.
- Deterministic headline routing guard in dispatcher for explicit Hacker News "top N headlines" prompts.
- Context budget manager implemented in command flow:
  - centralized LLM context build helper with configurable char budget,
  - truncation preserving section order,
  - integrated into cloud fallback and question streaming paths.
- Clarifier gate added for underspecified follow-ups when no context is available.
- Numbered follow-up continuity added for search/research threads:
  - captured/persisted list context in `~/.chintu/followup_context.json`,
  - follow-up expansion supports prompts like "go deeper on point 2" and "details on result #3".

Deliverables:
- Dual-view rendering contract:
  - `text_view`: full response (links/paths/code allowed).
  - `speech_view`: humanized response (remove/replace URLs, file paths, markdown fences/dividers, excessive punctuation, and underscore/snake_case artifacts by default).
- "Last list" memory per session:
  - persist the most recent numbered lists (daily briefing headlines, search results, comparisons) in a small session cache.
  - follow-ups supported: `read more #N`, `open #N`, `compare #N vs #M`, `save #N to file`.
- Context budget manager (prevent "context rot"):
  - keep large artifacts (search results, long transcripts, scraped pages) out of the live prompt; store them as structured artifacts and retrieve on demand.
  - aggressively prune/summarize older turns; enforce a token budget per model and a VRAM-aware cap for local models.
  - maintain a small, structured session state (e.g., last list IDs + minimal metadata) so follow-ups work without bloating context.
- Constraint verifier:
  - enforce "top N" and "exact count" requirements with retries (e.g., "top 3 headlines" returns exactly 3).
- Local-LLM playbooks where safe:
  - structured schemas for: summarization, list generation, "read more" expansion, and unblock plans.
  - deterministic verifiers gate completion ("no evidence, no success").

Exit Gate:
- "Daily briefing" then "read more about #1" works in the same session without re-asking.
- TTS never reads URLs/paths by default (validated by unit tests and a short manual checklist).
- "Top N headlines" returns exactly N in targeted tests.

---

### Phase 17 - Codebase Maintainability (Modularization + Guardrails)
**Goal:** Keep the codebase clean, reviewable, and safe to extend without creating new monoliths.

Why:
- Oversized modules increase regression risk and slow down development/reviews.

Deliverables (incremental, tested, no behavior drift):
- 17.1 Command path split (target: `chintu_backend/core/command_handler.py`)
  - Extract into:
    - `chintu_backend/core/response_formatting.py` (display/sanitization/tts digest)
    - `chintu_backend/core/confirmation_flow.py` (pending confirmation logic)
    - `chintu_backend/core/intent_bridge.py` (intent classification helpers)
  - Exit: existing command-handler tests pass; approval behavior unchanged on spot checks.
- 17.2 Routing split (target: `chintu_backend/core/model_router.py`)
  - Extract into:
    - `chintu_backend/core/routing/policy.py`
    - `chintu_backend/core/routing/provider_adapters.py`
    - `chintu_backend/core/routing/verification.py`
  - Exit: fallback behavior unchanged or improved; no provider regressions.
- 17.3 Capability split (targets: `chintu_backend/automation/automation_capabilities.py`, `chintu_backend/core/capability_handlers.py`)
  - Extract by domain:
    - windows control
    - browser/navigation
    - file operations
    - social/content actions
    - reminders/tasks
  - Exit: capability registry loads all handlers; doctor checks show no missing capability.
- 17.4 Continuous guardrails
  - CI warning report for files > 1200 lines.
  - Policy for new modules (< 800 lines) unless explicitly justified.
  - Track top-10 largest files in monthly governance report.
  - Locked-phase regression suite:
    - maintain a fast "locks check" test pack that covers Phases 1-15 contracts.
    - run it automatically after each modularization extraction so any lock regression fails fast.
- 17.5 Config split (target: `chintu_backend/core/config.py`)
  - Extract loader/env parsing, defaults, validation, and feature flags into bounded modules.
  - Guardrail: configuration schema remains a single source of truth.
- 17.6 Type system + error taxonomy
  - Introduce strict typing gates with incremental adoption.
  - Establish a compact exception hierarchy and normalize cross-module error handling patterns.
- 17.7 Provider reliability hardening (roadmap contract)
  - Define circuit-breaker semantics per provider adapter (open, half-open, closed).
  - Keep existing retry budgets/backoff, and add breaker transitions as explicit testable behavior.

Implementation update (2026-03-03):
- Baseline circuit-breaker behavior is implemented for cloud providers in sync and streaming paths.
- New module: `chintu_backend/core/provider_circuit_breaker.py`.
- Router integration: `chintu_backend/core/model_router.py`.
- Config controls added in `chintu_backend/core/config.py`:
  - `provider_circuit_breaker_enabled`
  - `provider_circuit_failure_threshold`
  - `provider_circuit_recovery_seconds`
  - `provider_circuit_half_open_successes`
- Tests added:
  - `tests/core/test_provider_circuit_breaker.py`
  - `tests/core/test_model_router_circuit_breaker.py`
- Maintainability guard automation added:
  - `scripts/phase17_maintainability_gate.py` emits JSON/Markdown reports for file-size thresholds, typed-target checks, and exception taxonomy availability.
  - `chintu_backend/core/exceptions.py` introduces a normalized exception hierarchy for incremental adoption.
- Config initialization split started:
  - path/default runtime initialization extracted to `chintu_backend/core/config_runtime.py`.
  - `Config.__init__` and fast-default flow now delegate to helper functions to reduce `config.py` monolith size without behavior drift.
- Tests added:
  - `tests/core/test_phase17_maintainability_gate.py`
  - `tests/core/test_config_runtime_split.py`
- Follow-up hardening:
  - fixed typed-target violations in gateway ops handlers, control-plane builder, workflow runner, and weekly trainer scheduler.
  - files: `chintu_backend/interfaces/gateway/server.py`, `chintu_backend/interfaces/gateway/control_plane.py`, `chintu_backend/workflows/workflow_runner.py`, `chintu_backend/brain/learning/weekly_trainer.py`
  - gate evidence: `generated_reports/phase17_maintainability_gate_*.md` now returns pass when run from current baseline.

Exit Gate:
- No behavior regressions on targeted suites after each extraction.
- New guardrails prevent new mega-files from emerging.

---

### Phase 18 - UI vNext (Minimal Black/White + Teal Accents)
**Goal:** A clean, modern operator UI that makes autonomy understandable and controllable.

Deliverables:
- Design system:
  - black/white base, minimal teal accents, consistent typography and spacing.
  - accessibility: contrast, keyboard navigation, readable density.
- Core screens:
  - Chat (text + speech preview), Runs (plan/steps/evidence), Approvals (pending/ledger),
  - Memory (search/forget/export), Models (router + health),
  - Identity (owner/master profile, OAuth connections, vault health),
  - Settings (policies, integrations, contact/call rules).
- UX contracts:
  - all sensitive actions route through an approvals panel with reason + receipts.
  - evidence artifacts are one-click viewable (screenshots, web extracts, files created).
  - approvals are surfaced as structured cards (A2UI-style) so the operator sees the exact action, risk reason, and evidence before approving/denying.

Implementation update (2026-03-03, partial):
- Dashboard tabs expanded to include explicit `Models` and `Identity` panels:
  - file: `chintu_ui/lib/widgets/dashboard_panel.dart`
  - `Models` surfaces runtime model metadata + provider key posture.
  - `Identity` surfaces gateway/session context + integration linkage posture.
- Testability hardening:
  - `WebSocketService` now supports `autoConnect: false` for deterministic widget tests.
  - file: `chintu_ui/lib/services/websocket_service.dart`
- Flutter widget tests updated:
  - `chintu_ui/test/widget_test.dart` now verifies splash flow plus `Models`/`Identity` tabs.
  - narrow viewport rendering check added for dashboard panel (mobile-safe layout sanity).
  - `flutter test` passes on current baseline.
- Phase gate added:
  - `scripts/phase18_ui_vnext_gate.py`
  - validates dashboard tab contracts + websocket test-mode support + flutter widget test pass.
- Tests added:
  - `tests/core/test_phase18_ui_vnext_gate.py`

Exit Gate:
- Operator can: run a task, see plan + evidence, approve/deny safely, and review what happened without reading logs.

---

### Phase 19 - Cofounder Workflow Packs (Professional, Repeatable)
**Goal:** Turn "agentic capability" into repeatable, professional workflows for real daily work.

Deliverables:
- Workflow packs (playbook-driven, schema-validated, verifiable):
  - Build-an-app: idea -> PRD -> architecture -> scaffold -> tests -> milestones -> demo.
  - Research + decision: multi-source research -> pros/cons -> recommendation -> follow-up plan.
  - Content studio: script -> captions -> thumbnails -> staging -> publish gate.
  - Finance (read-only): import -> insights -> draft plan -> manual checklist.
- WAT structure (Workflows + Agent + Tools):
  - Workflows: Markdown SOPs (discovery questions, step guidance, acceptance criteria) stored as versioned artifacts (e.g., `workflows/`).
  - Agent: reads workflows, asks clarifying questions, plans and executes, and proposes workflow improvements from feedback.
  - Tools: small deterministic scripts/capabilities (e.g., `tools/`) written/tested by the agent; side effects never happen via free-form LLM text.
  - Workflow/tool changes are gated: show diff + run targeted tests + require approval to enable.
- Caching and reuse:
  - research results and intermediate data are saved locally (JSON/Markdown) and reused to avoid re-researching and to reduce API spend.
- Each pack ships:
  - a playbook (LLM instructions + schemas),
  - a deterministic verifier (evidence + constraints),
  - and replayable benchmark scenarios.

Implementation update (2026-03-03, partial):
- Deterministic workflow pack executors added:
  - `scripts/workflow_packs/build_app_pack.py`
  - `scripts/workflow_packs/research_decision_pack.py`
  - `scripts/workflow_packs/finance_readonly_pack.py`
  - `scripts/workflow_packs/content_studio_pack.py`
- Workflow recipes added:
  - `chintu_backend/workflows/recipes/build_app_pack.yaml`
  - `chintu_backend/workflows/recipes/research_decision_pack.yaml`
  - `chintu_backend/workflows/recipes/finance_readonly_pack.yaml`
  - `chintu_backend/workflows/recipes/content_studio_pack.yaml`
- Replayable benchmark runner added:
  - `scripts/phase19_workflow_pack_benchmark.py`
- Workflow shell command argument preservation fixed:
  - `chintu_backend/workflows/workflow_runner.py`
- Tests added:
  - `tests/core/test_phase19_workflow_pack_benchmark.py`
  - `tests/core/test_workflow_runner_shell_args.py`

Exit Gate:
- At least 3 packs run end-to-end with evidence and no policy violations on weekly benchmarks.

---

### Phase 27 - Multi-Persona Specialist Mode (Adapters + Playbooks)
**Goal:** Enable fast persona switching through adapter + playbook selection without fragmenting shared memory.

Deliverables:
- Persona registry:
  - define persona name, adapter path/version, playbook set, and routing tags.
- Intent-to-persona routing:
  - apply lightweight classification/heuristics to select a persona deterministically.
- Safe fallback:
  - if adapter is missing/unhealthy, route to default persona while preserving task execution safety.
- Auditability:
  - record persona choice and rationale in the run dossier for each routed step.

Implementation update (2026-03-03, partial):
- Persona registry + lightweight intent routing are implemented.
- New module: `chintu_backend/core/persona_registry.py` with:
  - default personas (`default`, `coding`, `finance`, `medical`)
  - routing tags, playbook overlays, adapter-path awareness
  - safe fallback to default persona when a requested persona adapter is missing/disabled
- Model-router integration:
  - persona selection now runs per request and is attached to routing constraints + execution trace
  - persona playbook overlay is appended to the system prompt for routed LLM calls
  - files: `chintu_backend/core/model_router.py`
- Run dossier evidence:
  - persona routing selections are now recorded to run metadata and rendered in receipts under `## Personas`
  - files: `chintu_backend/core/run_manager.py`, `chintu_backend/core/command_handler.py`
- Config controls:
  - `persona_mode_enabled`
  - `persona_default_name`
  - `persona_registry_path`
  - file: `chintu_backend/core/config.py`
- Tests added:
  - `tests/core/test_persona_registry.py`
  - `tests/core/test_model_router_persona_trace.py`
  - `tests/core/test_run_manager_persona_receipt.py`
- Phase gate added:
  - `scripts/phase27_persona_specialist_gate.py`
  - validates mixed prompt routing (coding/finance/medical/default), deterministic routing, and fallback safety behavior.
- Tests added:
  - `tests/core/test_phase27_persona_specialist_gate.py`

Exit Gate:
- Finance, Medical, and Coding personas switch correctly on a mixed prompt suite with no routing loops and no policy drift.

---

### Phase 28 - Telegram Mini App Control Plane
**Goal:** Deliver real remote operations control (runs, approvals, telemetry) without expanding unsafe action surface.

Deliverables:
- Mini app UI:
  - run board, approvals panel, telemetry panel, and artifact viewer.
- Secure approval transport:
  - signed approval payloads plus owner allowlist enforcement for control actions.
- Backward compatibility:
  - Telegram inline keyboard remains a fallback approvals transport.

Implementation update (2026-03-03, partial; backend control-plane contract implemented):
- Signed orchestrator approval payload support is implemented in the Telegram gateway callback path.
- Approval callback verification now enforces signature checks when `telegram_require_signed_approvals=true`.
- Legacy unsigned `orch:approve/reject` callbacks are still supported only when signed payloads are explicitly disabled.
- New config controls in `chintu_backend/core/config.py`:
  - `telegram_approval_signing_secret`
  - `telegram_require_signed_approvals`
  - `gateway_ops_rate_limit_per_minute`
  - `gateway_ops_approval_rate_limit_per_minute`
- Runtime updates in `chintu_backend/channels/telegram.py`:
  - signed callback generation for approval notifications
  - signed callback parsing + verification (HMAC)
  - explicit rejection messaging for invalid/unsigned payloads when required
- Gateway control-plane snapshot contract implemented:
  - new snapshot builder: `chintu_backend/interfaces/gateway/control_plane.py`
  - sections: `run_board`, `approvals_ledger`, `telemetry`, `artifact_viewer`
  - evidence links are extracted from run receipts + `events.jsonl` into dashboard-ready artifacts
- Gateway ops APIs implemented for remote operator flows:
  - HTTP: `GET /ops/control-plane`
  - HTTP: `POST /ops/resolve-approval`
  - HTTP: `GET /ops/run/{run_id}/receipt`
  - HTTP: `POST /ops/run/{run_id}/cancel`
  - HTTP: `GET /ops/mini-app` (embedded control surface for Telegram Web App usage)
  - WS RPC: `gateway.ops.control_plane`, `gateway.ops.resolve_approval`, `gateway.ops.run_receipt`, `gateway.ops.cancel_run`
  - owner-only access gate for remote sessions + configurable per-minute rate limits
  - approval decisions supported: `allow_once`, `whitelist`, `deny` for action and orchestrator-step approvals
- Signed owner gating + signed approval payload contract:
  - remote HTTP control-plane access now requires signed owner tuple (`uid`, `exp`, `sig`) and owner allowlist match
  - pending approval cards now include signed `approval_payload` + `approval_signature`
  - remote approval resolution enforces signed payload verification and expiry checks when signed approvals are required
- Runtime updates in `chintu_backend/interfaces/gateway/server.py`:
  - owner/session policy checks for control-plane actions
  - control-plane payload assembly and approval-resolution handler
  - audit entries for blocked/approved resolution paths
- Telegram operator entrypoint:
  - `/dashboard` command now returns a Telegram Mini App button when enabled
  - URL builder appends signed owner gating params + gateway token pass-through for ops endpoints
  - config: `telegram_mini_app_enabled`, `telegram_mini_app_url`, `telegram_mini_app_token_ttl_seconds`
- Mini App control surface upgrade:
  - replaced temporary inline HTML with modular renderer `chintu_backend/interfaces/gateway/mini_app_html.py`
  - dashboard now includes responsive KPI tiles, approvals ledger actions, run board, telemetry panel, artifact viewer, and auto-refresh toggle
  - layout is mobile-safe for Telegram in-app webview and desktop browser fallback
  - run-board and artifact-viewer now support client-side filtering + pagination controls
  - control-plane fetch now supports `limit_runs` and `limit_approvals` query controls for larger operator views
  - telemetry panel now renders provider trend rows from bucketed arbiter `provider_attempt` history (sparkline + totals)
- Additional gateway config:
  - `gateway_approval_payload_ttl_seconds`
- Tests added:
  - `tests/core/test_telegram_approval_signing.py`
  - `tests/core/test_gateway_control_plane.py`
  - `tests/core/test_gateway_server_approvals.py`
  - `tests/core/test_gateway_server_signed_ops.py`
  - `tests/core/test_gateway_mini_app_html.py`
- Additional run-control tests:
  - `tests/core/test_gateway_server_approvals.py` now covers run receipt fetch and cancel flows.
- Phase gate added:
  - `scripts/phase28_telegram_control_plane_gate.py`
  - validates control-plane sections, signed approval payloads, remote approval resolution, run receipt access, and run cancel actions.
- Tests added:
  - `tests/core/test_phase28_telegram_control_plane_gate.py`

Exit Gate:
- Remote approve/deny workflows complete end-to-end with receipts and zero silent execution paths.

---

### Phase 29 - Full Autonomy Integration + E2E/Perf/Chaos Gates
**Goal:** Validate the complete autonomy loop under realistic failure and load conditions.

Deliverables:
- End-to-end scenario runner:
  - assert evidence artifacts and run-state transitions, not just response text.
- Performance benchmarks:
  - capture latency, timeout behavior, and VRAM-pressure handling.
- Chaos/failure simulations:
  - provider outage, browser DOM drift, local OOM, and partial tool-failure scenarios.
- Promotion quality gates:
  - block routing-weight changes and adapter activation unless all defined gates pass.

Implementation update (2026-03-03, partial):
- Escalation dossier plumbing is now in place for conversation-routing cloud escalations:
  - `ModelRouter` captures per-request execution trace (`provider_attempts`, `routing_outcomes`).
  - `CommandHandler` classifies escalation reason codes and persists structured escalation artifacts to run storage.
  - `RunManager` now records escalation entries and includes them in durable receipts under `## Escalations`.
- Reason-code mapping currently covers:
  - `verifier_fail_budget_exhausted`
  - `tool_schema_validation_loop`
  - `repeated_syntax_error_generation`
  - `context_overflow_risk`
  - `local_model_timeout_or_oom`
- Files updated:
  - `chintu_backend/core/model_router.py`
  - `chintu_backend/core/command_handler.py`
  - `chintu_backend/core/run_manager.py`
- Tests added:
  - `tests/core/test_run_manager_escalation_receipt.py`
  - `tests/core/test_command_handler_escalation_reason.py`
- Full Phase 29 gate runner implemented:
  - `scripts/phase29_autonomy_integration_gate.py`
  - executes workflow-pack benchmark, chaos probes, performance timings, and complex-run contract assertions.
- Operator CLI integration added for quality gates:
  - `chintu gates phase17`
  - `chintu gates phase18`
  - `chintu gates phase19`
  - `chintu gates phase27`
  - `chintu gates phase28`
  - `chintu gates phase29`
  - `chintu gates preflight`
  - `chintu gates release`
  - `chintu gates ci`
  - `chintu gates all`
- Gate chain validation:
  - local end-to-end gate command `chintu gates all` now returns success on current baseline and emits linked evidence receipts for all integrated gate phases.
- CI gate runner:
  - `scripts/ci_quality_gate.py` runs `pytest` core suite + flutter widget tests + phase gate chain (`gates all --skip-flutter-tests`) + deployment preflight + release-readiness gate, and emits CI receipt artifacts.
  - test: `tests/core/test_ci_quality_gate.py`
- CI automation:
  - GitHub workflow added at `.github/workflows/quality-gates.yml` to run Python tests, Flutter tests, phase gates, deployment preflight, and release-readiness gates on push/PR.
- Drift-monitor hardening:
  - Phase 29 gate now evaluates benchmark drift against recent Phase 19 receipts and fails when degradation exceeds threshold.
  - file: `scripts/phase29_autonomy_integration_gate.py`
- Complex-run contract coverage now includes:
  - local attempt failure reason capture (`local_model_timeout_or_oom`),
  - escalation artifact verification,
  - training dataset artifact generation,
  - adapter candidate output with explicit pending-approval status (not auto-activated),
  - evaluation receipt generation.
- Deterministic chaos probes added for:
  - provider outage/circuit-breaker opening,
  - browser DOM drift fallback trigger,
  - local OOM reason classification,
  - partial tool failure with bounded retry outcome.
- Tests added:
  - `tests/core/test_phase29_autonomy_integration_gate.py`

Exit Gate:
- One complex run demonstrates: local attempt -> escalation -> verified completion -> training dataset artifact -> adapter produced (not activated) -> evaluation receipt.

---

### Phase 20 - OAuth/Integrations Onboarding (TrustClaw-Inspired)
**Goal:** Make integrations easy to connect and easy to revoke without storing passwords.

Status: **LOCKED** (tracked in `docs/PLANS/PHASE_LOCKS.md`)

Deliverables:
- Integration setup wizard UI + CLI helper:
  - guides OAuth flows (Calendar, YouTube, etc.) and stores tokens in the identity vault.
- Scope minimization:
  - least-privilege scopes by default; per-integration scope receipts.
- Revocation and health checks:
  - test tokens, refresh flow, and provide one-click revoke instructions.

Exit Gate:
- A new user can connect Google Calendar end-to-end with clear prompts and can revoke safely.

---

### Phase 21 - Telegram Inbox + Content Intelligence (Instagram Reels/Posts)
**Goal:** Anything you share to Chintu (especially via Telegram) becomes searchable knowledge plus actionable next steps.

Status: **LOCKED** (tracked in `docs/PLANS/PHASE_LOCKS.md`)

Deliverables:
- Telegram inbox intake:
  - accept links, text, images, videos, and forwarded messages.
  - persist an immutable reference to the source (message ID + timestamp) in the history store.
- Intake queue + backpressure (avoid audio bottlenecks):
  - long-running extraction (especially video STT) runs asynchronously in a queue with progress updates.
  - cap concurrent transcriptions and apply GPU/CPU scheduling so forwarding 5 videos doesn't freeze the assistant.
  - support cancel/resume and "summarize first, transcribe later" prioritization.
- Local-first extraction pipeline:
  - links: browser autopilot fetch + evidence capture + safe page text extraction.
  - images: OCR + visual summary + key entities.
  - videos/reels: transcript (local STT), key timestamps/chapters, and a concise summary.
- Structured triage + "opinion":
  - classify: topic/category, novelty, usefulness-to-you, and confidence.
  - produce: "What I learned" + "Why it matters" + "What I'll do next".
  - default actions are safe: store in RAG, draft tasks, draft a workflow/tool proposal; any posting/publishing/logins require approval.
- Knowledge storage:
  - embed extracted items into local RAG with provenance, deduping, and tags (e.g., "automation", "content", "finance", "AI models").
  - make items retrievable by keyword and by "show me what I saved from Telegram this week".

Exit Gate:
- Forward 10 mixed items (links/images/videos) and Chintu reliably:
  - extracts signal,
  - stores it with provenance,
  - and proposes reasonable next actions without unsafe side effects.

---

### Phase 22 - Curiosity Engine + Scheduled Learning + Bi-weekly Fine-tune (Gated)
**Goal:** Stay up-to-date and improve over time without becoming unsafe or unpredictable.

Status: **LOCKED** (tracked in `docs/PLANS/PHASE_LOCKS.md`)

Deliverables:
- Curiosity sources (configurable):
  - model/tool releases (GitHub releases, vendor blogs), AI/tech/security news feeds, and your own saved inbox items.
- Scheduler (cron jobs with resource-awareness):
  - daily: ingest + embed + dedupe + summarize into RAG.
  - weekly: dataset hygiene (PII redaction, label cleanup, eval set refresh).
  - bi-weekly: propose a fine-tune candidate (LoRA/QLoRA) and run an evaluation.
- Fine-tuning pipeline (safe by design):
  - trains adapters (never overwrites base models), produces a rollback-ready artifact, and writes a receipt (data used, steps, metrics).
  - uses GPU/CPU scheduling rules (off-hours, VRAM budgets) to avoid disrupting the desktop.
- Evaluation + promotion gates:
  - run targeted eval suites plus a small "real scenario" set.
  - require explicit approval to activate new adapters or change routing weights.
- Provider/routing refresh:
  - update provider health/latency stats and refresh the routing ladder (cloud APIs -> cloud Ollama -> local) based on availability, privacy, and cost preferences.
- Local model catalog refresh (on-hardware):
  - track new local models/quantizations, run a short eval on your hardware (RTX 3060/GTX 1650/CPU), and update the "known-good" model set used by the router.

Exit Gate:
- After one full two-week cycle:
  - daily knowledge updates are consistent and searchable,
  - a fine-tune candidate is produced with clear metrics,
  - and no new model/routing change is activated without approval.

Implementation update (2026-03-03, partial):
- Adapter activation approval contract is enforced in runtime:
  - bi-weekly training produces a pending adapter activation receipt by default.
  - adapter activation requires explicit approval before writing `active_adapter.json`.
- Optional promotion hardening added:
  - when enabled, adapter activation also requires a recent passing Phase 29 integration gate receipt.
  - stale/missing/failed Phase 29 reports block activation with an explicit reason.
- Files updated:
  - `chintu_backend/brain/learning/weekly_trainer.py`
  - `chintu_backend/brain/learning/learning_capabilities.py`
  - `chintu_backend/core/config.py`
  - `chintu_backend/cli.py`
  - `chintu_backend/core/config_runtime.py`
- New controls:
  - `learning_activation_requires_approval`
  - `learning_auto_activate_adapter`
  - `learning_pending_activation_path`
  - `learning_activation_require_phase29_gate`
  - `learning_phase29_reports_dir`
  - `learning_phase29_gate_max_age_hours`
- CLI operations:
  - `chintu learning pending-activation`
  - `chintu learning approve-activation`
- Tests added:
  - `tests/core/test_weekly_trainer_activation_gate.py`
  - `tests/core/test_config_runtime_split.py`

---

### Phase 23 - Research Browser Profiles + LLM-in-Browser Assist (ChatGPT/Claude/Gemini)
**Goal:** Use ChatGPT/Claude/Gemini as research surfaces safely, in a dedicated browser profile with full auditability.

Status: **LOCKED** (tracked in `docs/PLANS/PHASE_LOCKS.md`)

Deliverables:
- Dedicated browser profiles:
  - separate Playwright profiles for "research" and "logged-in accounts" to avoid mixing sessions and to reduce accidental actions.
- LLM site assistants (gated):
  - open ChatGPT/Claude/Gemini, draft a prompt, and show exactly what will be sent.
  - sending a message/uploading a file requires explicit approval (account action gate).
  - capture responses (text + screenshots) into the run dossier for later audit/reuse.
- Trust posture:
  - treat LLM-site outputs as untrusted until verified; optionally cross-check with web evidence when the output includes factual claims.
- Credential handling:
  - Chintu can navigate to login pages and wait; user completes authentication manually.
  - never handles passwords; never extracts session cookies/tokens.

Exit Gate:
- "Research X using ChatGPT in the browser" works end-to-end:
  - correct site opened in the dedicated profile,
  - prompt drafted and approved,
  - response captured into a dossier,
  - no accidental message sends or irrelevant tabs.

---

### Phase 24 - Communications (Calls/Reservations) With Owner-First Rules
**Goal:** Let Chintu help with calls and reservations safely: it can call the owner freely (configurable), but calling anyone else requires explicit confirmation.

Status: **LOCKED** (tracked in `docs/PLANS/PHASE_LOCKS.md`)

Deliverables:
- Owner/master contact setup:
  - owner phone number stored in the Identity system (non-public, never logged in plaintext).
  - policy rule: `call_owner` allowed without confirmation (configurable).
- Third-party call gating:
  - any call/message to non-owner requires explicit confirmation with a call script preview (who/why/what to say).
  - after-call receipt: timestamp, target, outcome, and a short summary.
- Reservation workflow (safe by design):
  - gather requirements (date/time/party size/constraints) + draft the call script.
  - hard-stop if payment/deposit is required (policy block); provide manual steps instead.
- Pluggable comms adapters:
  - browser-based Google Voice automation in a dedicated, assistant-owned browser profile (user logs in manually; Chintu never stores passwords).
  - optional future adapters (e.g., SIP/Twilio/mobile-bridge) behind the same policy gates.
- Auditability:
  - store call intents, approvals, and outcomes in the task history/dossier system.

Exit Gate:
- Chintu can (1) call the configured owner without confirmation and (2) complete a third-party reservation call only after explicit confirmation, with clean receipts and zero policy violations.

---

### Phase 25 - Skill/Plugin Trust + Supply Chain Security (Sandbox-First)
**Goal:** Prevent the #1 real-world failure mode of autonomous assistants: running untrusted code/content that steals secrets or performs unwanted actions.

Status: **LOCKED** (tracked in `docs/PLANS/PHASE_LOCKS.md`)

Deliverables:
- Trusted source policy:
  - allowlist skill/plugin sources (repo + owner), pin to commits/tags, and store provenance receipts.
  - default deny for unknown sources; require explicit approval to add a new source.
- Static scanning before enable:
  - secrets scan (prevent hardcoded keys), suspicious network/credential exfil patterns, and dependency risk checks.
  - disallow auto-running `postinstall` scripts for third-party packages unless approved.
- Sandbox-first execution:
  - third-party tools run in Docker/WSL2 or ephemeral `uv` envs by default.
  - minimal filesystem mounts (only what the task needs), and no secrets mounted unless explicitly required and approved.
- Runtime guardrails:
  - outbound network allowlists for sandboxes (optional), and deterministic timeouts/limits.
  - capture a "dependency receipt" (what ran/installed, where, and why).
- Operator UX:
  - UI shows: source trust level, what will be executed, what access it needs, and the receipt after it runs.

Exit Gate:
- Install/enable a new third-party skill only after approval; the system records provenance and scans it.
- Run 20 sandboxed tool executions with zero secret leakage and zero unintended host modifications.

---

### Phase 26 - Workspace Abstraction (OpenHands-Inspired) + Safer Autonomy
**Goal:** Make Chintu feel like it has "full access" while keeping autonomy safe: OS control stays on the Windows node, but code-heavy work runs in a controlled workspace.

Status: **LOCKED** (tracked in `docs/PLANS/PHASE_LOCKS.md`)

Deliverables:
- Workspace API:
  - unified interface for file ops, shell, browser, and artifacts across local and sandboxed environments.
- Default placement policy:
  - local host: UI automation, launching apps, reading the screen (policy-gated).
  - sandbox: code execution, dependency installs, web scraping/processing (default).
  - remote sandbox (optional): highly untrusted code or when you want isolation from the PC.
- Checkpointing + resumability:
  - long workflows checkpoint state (plan + evidence + artifacts), and resume after failures/restarts.
- Bounded autonomy levels:
  - safe-mode vs high-trust mode profiles (ZeroClaw-like), tied to channel trust and explicit user choice.

Exit Gate:
- A "build an app" workflow completes with sandboxed code execution and host-level UI steps, with clean receipts and no policy violations.

## Appendix A - Extreme Local Inference (Experimental)

This appendix documents an experimental option for layer-wise 70B inference using disk-streaming techniques.

Scope posture:
- Experimental only; not required for roadmap completion.
- Not part of current phase exit gates.

Risks:
- IO-bound latency can dominate and reduce practical throughput.
- Windows runtime complexity increases operational risk.
- ROI is uncertain versus existing cloud escalation and browser fallback paths.

## Definition of Success (For This Project)

Chintu is considered better when all are true:
1. Handles broad task categories with reusable skill families (no narrow skill sprawl).
2. Completes end-to-end tasks with verifiable evidence and robust retries.
3. Auto-resolves missing dependencies in controlled environments.
4. Routes work across local + cloud models/providers intelligently and adapts based on measured outcomes.
5. Maintains high-quality long-term memory and training-ready history (including AI/tech/model catalog updates).
6. Delivers human-grade STT/TTS behavior, especially smart TTS suppression of links/citations by default.
7. Meets or exceeds benchmark pass-rate targets over sustained runs.
8. Operates with a secure control plane + dashboards so you can trust autonomy at scale.
9. Uses a safe browser autopilot that captures evidence and never opens irrelevant pages by default.
10. Never "gives up": every run ends Completed-with-evidence or Blocked-with-unblock-plan.
11. Enforces sandbox-by-default and trusted-source policies so third-party code/plugins cannot silently exfiltrate secrets or modify the host.

## Operational Notes

- Local LLM remains primary planner/executor/validator path; cloud LLMs are fallback/augmentation.
- Every phase must include tests, docs, and measurable exit criteria before moving forward.
- Any new capability must include: policy contract, verification criteria, and artifact logging.
- Phase lock status is maintained in `docs/PLANS/PHASE_LOCKS.md`.
- Detailed audit reference: `docs/PLANS/Chintu AI - Comprehensive Audit Rep.md`.

