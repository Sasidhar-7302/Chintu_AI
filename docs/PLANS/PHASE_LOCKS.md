# Phase Locks Index

Last updated: 2026-02-24

This file is the single source of truth for locked-phase status.
Detailed historical lock reports were consolidated to keep `docs/PLANS` clean and maintainable.

## Locked Phases

| Phase | Name | Status |
| --- | --- | --- |
| 1 | Foundation | Locked |
| 2 | Deterministic Task Contracts | Locked |
| 2.5 | Model Orchestration + Up-to-Date Model Catalog | Locked |
| 3 | Universal Skill Lifecycle (Generalize First) | Locked |
| 4 | Dependency/Environment Bootstrap Agent | Locked |
| 4.5 | Idea-to-Project Builder Workflow | Locked |
| 5 | Memory, History, and Training Data Pipeline | Locked |
| 6 | Voice System (STT + Smart TTS) | Locked |
| 7 | Reliability and Self-Healing | Locked |
| 8 | Security and Control | Locked |
| 8.5 | Social/Content Automation (Safe Publishing) | Locked |
| 9 | Continuous Benchmarking and Governance | Locked |
| 10 | Dual-GPU Resource Manager | Locked |
| 10.5 | Dependency Isolation Hardening (uv + Docker-First) | Locked |
| 11 | Browser Autopilot + Web Evidence | Locked |
| 12 | Gateway/Control Plane + Remote Node | Locked |
| 13 | Dashboards (Product, Ops, Finance, Content) | Locked |
| 13.5 | Knowledge Updater as Local RAG | Locked |
| 14 | Finance + Portfolio Manager (Read-Only) | Locked |
| 15 | Safe Self-Improvement | Locked |
| 16 | Human Output Layer + Multi-turn Context | Locked |
| 20 | OAuth/Integrations Onboarding | Locked |
| 21 | Telegram Inbox + Content Intelligence | Locked |
| 22 | Curiosity Engine + Scheduled Learning | Locked |
| 23 | Research Browser Profiles + LLM-in-Browser Assist | Locked |
| 24 | Communications (Calls/Reservations) With Owner-First Rules | Locked |
| 25 | Skill/Plugin Trust + Supply Chain Security | Locked |
| 26 | Workspace Abstraction + Safer Autonomy | Locked |

## Lock Contract

For any locked phase:
1. do not change behavior silently
2. add/update targeted tests for the phase contract
3. update this index with date and summary when lock state changes
4. update `docs/PLANS/chintu_ultimate_plan.md` if roadmap semantics change

