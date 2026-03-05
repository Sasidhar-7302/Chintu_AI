# Chintu AI Architecture

This document is the engineering architecture reference for Chintu.
It explains how requests are processed, how safety is enforced, and how results are verified.

## 1) System Context

```mermaid
flowchart LR
    U[User] --> UI[Desktop UI or Voice]
    U --> TG[Telegram or other channel]
    UI --> CH[Command Handler]
    TG --> CH
    CH --> PG[Prompt Guard and Clarifier]
    PG --> PE[Policy Engine]
    PE --> AD[Action Dispatcher]
    AD --> CAP[Capabilities and Skills]
    AD --> ORCH[Orchestrator]
    CAP --> RM[Run Manager]
    ORCH --> RM
    RM --> MEM[Memory and History]
    RM --> EVT[Event Bus]
    EVT --> UI
    RM --> TTS[TTS Output Layer]
    TTS --> U
```

## 2) Request Lifecycle

```mermaid
sequenceDiagram
    participant User
    participant Handler as CommandHandler
    participant Policy as PolicyEngine
    participant Dispatch as ActionDispatcher
    participant Run as RunManager
    participant Tool as Capability/Skill
    participant Verifier
    participant Memory

    User->>Handler: Natural language request
    Handler->>Run: create_run(session_id, text)
    Handler->>Policy: evaluate(request, context)
    Policy-->>Handler: allow / confirm / deny
    Handler->>Dispatch: dispatch(capability, args)
    Dispatch->>Run: start_step(...)
    Dispatch->>Tool: execute
    Tool-->>Dispatch: raw result + evidence
    Dispatch->>Verifier: verify_result_if_needed
    Verifier-->>Dispatch: pass / fail + notes
    Dispatch->>Run: end_step(...)
    Run->>Memory: persist events + dossier
    Handler-->>User: human response + optional follow-up
```

## 3) Planner-Executor-Verifier Loop

For multi-step work, Chintu runs a plan loop rather than one-shot execution.

```mermaid
flowchart TD
    A[Task Intent] --> B[Planner builds typed plan]
    B --> C{Step ready?}
    C -->|No| R[Request clarification or wait]
    C -->|Yes| D[Executor runs step]
    D --> E[Collect evidence]
    E --> F{Verifier passes?}
    F -->|Yes| G[Mark step complete]
    F -->|No| H[Retry or alternate strategy]
    H --> I{Retry budget left?}
    I -->|Yes| D
    I -->|No| J[Blocked with unblock plan]
    G --> K{More steps?}
    K -->|Yes| C
    K -->|No| L[Completed with evidence]
```

## 4) Safety and Approval Control

```mermaid
flowchart TD
    REQ[Incoming action] --> CLASSIFY[Risk classifier]
    CLASSIFY --> LOW[Low risk]
    CLASSIFY --> MED[Medium risk]
    CLASSIFY --> HIGH[High risk]

    LOW --> AUTO[Auto approve]
    MED --> CONFIRM[Explicit user confirmation]
    HIGH --> BLOCK[Blocked by policy]

    CONFIRM --> USER{User approved?}
    USER -->|Yes| EXEC[Execute + receipt]
    USER -->|No| CANCEL[Cancel + log reason]
```

Hard policies:
- No payment or checkout actions.
- Destructive file/system actions require explicit confirmation.
- Account publish/send actions require explicit confirmation.
- Protected paths cannot be modified without policy permit.

## 5) Model Orchestration

```mermaid
flowchart LR
    Q[Task step] --> M[Model Router]
    M --> L[Local model path]
    M --> C[Cloud model path]
    C --> V[Optional local verification]
    L --> O[Normalized output]
    V --> O
    O --> E[Executor]
```

Routing signals:
- task type (chat, code, vision, planning, extraction)
- privacy sensitivity
- latency budget
- model health and timeout history
- local hardware pressure (GPU utilization, VRAM headroom)

## 6) Browser Autopilot Pipeline

```mermaid
flowchart TD
    I[Web intent] --> P[Browser planner]
    P --> R[Relevance gate]
    R -->|Pass| D[DOM-first Playwright action]
    R -->|Fail| S[Skip source]
    D --> X{DOM failed?}
    X -->|Yes| V[Vision fallback]
    X -->|No| E[Extract evidence]
    V --> E
    E --> T[Sanitize content]
    T --> U[Summarize for user]
```

Design targets:
- avoid irrelevant site opens
- preserve source provenance for outputs
- ask for confirmation on login/publish flows

## 7) Memory and Training Data Flow

```mermaid
flowchart LR
    U[User turns] --> SH[Session history]
    EX[Execution events] --> SH
    SH --> DS[Task dossier builder]
    DS --> IDX[Retrieval index]
    DS --> EXP[Training export jobs]
    IDX --> RET[Cross-session recall]
```

Stored artifacts:
- prompt/response turns
- plan and step logs
- tool calls and outputs
- evidence links and receipts
- final outcome labels

## 8) Key Runtime Components

| Layer | Primary files | Responsibility |
| --- | --- | --- |
| Entry | `chintu_backend/core/command_handler.py` | Request orchestration |
| Dispatch | `chintu_backend/core/action_dispatcher.py` | Capability selection and execution |
| Capability registry | `chintu_backend/core/capabilities.py` | Capability metadata and matching |
| Run state | `chintu_backend/core/run_manager.py` | Run lifecycle and receipts |
| Policy | `chintu_backend/security/` and policy modules in `core` | Risk checks and approvals |
| Memory | `chintu_backend/brain/memory/` | Persistence and retrieval |
| Skills | `chintu_backend/automation/skills/` + `skills/` | Reusable skill execution |
| Browser | `chintu_backend/automation/browser/` | Web actions and extraction |
| Voice | `chintu_backend/audio/` | STT/TTS runtime |

## 9) Persistence and Observability

- Run receipts: `~/.chintu/runs/<run_id>/receipt.md`
- Run events: `~/.chintu/runs/<run_id>/events.jsonl`
- App logs: `logs/`
- Validation reports: `tests/reports/` (canonical), `generated_reports/` (ephemeral)

## 10) Failure Semantics

Every task must end in one of these states:
- `completed` with evidence
- `blocked` with unblock plan
- `failed` with explicit error and receipt

No silent success is allowed.

## 11) Extension Strategy

When adding new functionality:
1. define or reuse capability contract
2. add policy classification
3. add verification criteria
4. emit evidence and receipts
5. add targeted tests
6. document in `docs/TECHNICAL_OVERVIEW.md` and `docs/INDEX.md`

