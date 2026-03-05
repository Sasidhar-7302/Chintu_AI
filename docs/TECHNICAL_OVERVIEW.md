# Chintu AI Technical Overview

This is the implementation-level technical reference for Chintu.
Use this file when you need to understand how the system behaves in code today.

For product goals and roadmap:
- `docs/PRD/PRODUCT_REQUIREMENTS.md`
- `docs/PLANS/chintu_ultimate_plan.md`

For architecture diagrams:
- `docs/ARCHITECTURE.md`

---

## 1) Runtime Stack

Primary stack:
- backend: Python (`chintu_backend/`)
- UI: Flutter (`chintu_ui/`)
- scripts and diagnostics: `scripts/`
- tests: `tests/`

Main runtime entry points:
- `python -m chintu_backend`
- `scripts/start_chintu.bat`
- `scripts/chintu_cli.py`

---

## 2) Core Control Path

### 2.1 Request handling

Primary file:
- `chintu_backend/core/command_handler.py`

Responsibilities:
- normalize incoming user request
- attach session context
- run safety and policy checks
- route to capability or orchestrator
- return user-safe response

### 2.2 Dispatch and execution

Primary file:
- `chintu_backend/core/action_dispatcher.py`

Responsibilities:
- select matching capability
- execute capability and collect output
- apply verification on required capabilities
- normalize final result shape

### 2.3 Capability registry

Primary files:
- `chintu_backend/core/capabilities.py`
- `chintu_backend/core/capability_loader.py`

Responsibilities:
- declare capability contracts
- maintain trigger metadata
- register built-in and skill-backed capabilities

---

## 3) Run Lifecycle and Evidence

Primary file:
- `chintu_backend/core/run_manager.py`

A request is tracked as a run with explicit state transitions.

Typical statuses:
- `queued`
- `running`
- `waiting_approval`
- `waiting_input`
- `completed`
- `failed`
- `cancelled`
- `timed_out`

Artifacts:
- run events JSONL under `~/.chintu/runs/<run_id>/events.jsonl`
- run receipt under `~/.chintu/runs/<run_id>/receipt.md`

Expected behavior:
- every completed task has evidence or verifiable outputs
- failures include explicit error reason and unblock guidance when possible

---

## 4) Event Bus and Cross-Component Signaling

Primary file:
- `chintu_backend/core/events.py`

The EventBus is the central signaling mechanism across runtime modules.

Common event families:
- system lifecycle
- command processing
- run updates
- scheduler and task events
- notifications and errors
- UI updates

Design intent:
- decouple modules
- keep run state observable
- support UI streaming and diagnostics

---

## 5) Planning, Orchestration, and Long Tasks

Primary folder:
- `chintu_backend/orchestrator/`

Used for:
- multi-step project-style workflows
- plan decomposition and step execution
- retry and fallback orchestration

The orchestrator is expected to cooperate with:
- policy engine
- run manager
- verifier
- memory and history

---

## 6) Policy and Safety Model

Primary areas:
- `chintu_backend/security/`
- policy checks in `core` execution path

Safety model:
- classify action risk
- auto-approve low-risk actions
- require explicit confirmation for sensitive actions
- block policy-forbidden actions

Hard boundaries:
- no payment or checkout automation
- destructive operations require explicit confirmation
- account publish/send/login-sensitive actions are gated

---

## 7) Skills Architecture

Skill runtime locations:
- bundled skills: `chintu_backend/automation/skills/bundled/`
- workspace skills: `skills/`
- user/imported skills: `~/.chintu/skills/`
- learned skills: `~/.chintu/skills_learned/`

Registry area:
- `chintu_backend/automation/skills/skill_registry.py`

Key expectations:
- generalized reusable skills over one-off skills
- skill approval path before activation when required
- skill execution must emit clear success/failure outcome

---

## 8) Memory, Recall, and Learning Data

Primary area:
- `chintu_backend/brain/memory/`

Memory layers:
- short-term session context
- durable memory store
- retrieval index for recall
- task-history dossiers for provenance

Training and history expectations:
- preserve intent, plan, tool calls, outcomes
- keep provenance for recall answers
- allow export for local RAG/fine-tuning workflows

---

## 9) Browser and Vision Subsystems

Browser automation area:
- `chintu_backend/automation/browser/`

Vision area:
- `chintu_backend/vision/`

Operating model:
- browser uses DOM-first automation when possible
- fall back to vision/screen interpretation when needed
- maintain relevance gating and evidence capture

Vision configuration reference:
- `docs/vision.md`

---

## 10) Voice Runtime

Primary area:
- `chintu_backend/audio/`

Expected behavior:
- robust STT capture
- interruptible TTS
- sanitized spoken output (avoid reading raw links/paths unless asked)

---

## 11) Scheduler and Task Manager

Primary files:
- `chintu_backend/core/scheduler.py`
- `chintu_backend/tasks/task_manager.py`

Responsibilities:
- cron-like scheduled jobs
- reminders and deferred tasks
- retries and dead-letter handling for failures
- status emission through EventBus

---

## 12) Model Routing

Primary file:
- `chintu_backend/core/model_router.py`

Router inputs typically include:
- task type
- privacy sensitivity
- latency and reliability requirements
- local hardware availability
- provider health and fallback order

Goal:
- local-first where practical
- cloud fallback for quality/capability gaps
- stable output normalization for downstream execution

---

## 13) Filesystem Layout for Operations

Important locations:
- runtime logs: `logs/`
- canonical validation reports: `tests/reports/`
- ephemeral reports: `generated_reports/`
- user runtime state: `~/.chintu/`

Operational docs:
- `docs/MAINTENANCE.md`
- `docs/runbooks/WEEKLY_MAINTENANCE.md`

---

## 14) Testing Model

Testing docs:
- `docs/TESTING.md`
- `docs/MANUAL_QA_MATRIX.md`

Core test types:
- unit and subsystem tests under `tests/`
- targeted scenario tests for high-risk flows
- benchmark suites for end-to-end behavior

Expectation:
- do not trust only exit codes for benchmark quality
- include response-content validation for critical flows

---

## 15) Change Workflow for New Contributors

When adding or modifying capabilities:
1. identify where capability should live
2. define capability contract and risk class
3. implement with deterministic evidence output
4. add verification checks
5. add targeted tests
6. update docs (`INDEX`, this file, and relevant guide)

When changing safety behavior:
1. update policy logic
2. add regression tests for allow/confirm/block paths
3. verify approval ledger behavior
4. update plan lock report if phase contract changes

---

## 16) Open Risks and Current Engineering Priorities

Known themes to monitor:
- avoid response truncation in long-form outputs
- prevent duplicate memory recall lines
- ensure browser flows do not stop early at login pages
- enforce no false success when steps were not actually completed

Priority strategy:
- verify-first execution
- stronger post-step assertions
- targeted regression tests on observed failures

---

## 17) Related Documents

- `docs/INDEX.md` - top-level docs map
- `docs/ARCHITECTURE.md` - architecture diagrams and control flow
- `docs/STRUCTURE.md` - repository map
- `docs/PRD/PRODUCT_REQUIREMENTS.md` - product requirements
- `docs/PLANS/chintu_ultimate_plan.md` - execution roadmap and phase contracts
- `docs/PLANS/PHASE_LOCKS.md` - lock-state index for implemented phases
- `docs/TESTING.md` - test commands and suites
- `docs/MANUAL_QA_MATRIX.md` - manual validation prompts
- `docs/MAINTENANCE.md` - hygiene and cleanup workflows
