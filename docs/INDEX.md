# Chintu AI – System Guide (Windows)

This document is a complete, detailed guide to how Chintu works, how data flows through the system, and what capabilities and skills are currently present.

---

## Quick Navigation
- `docs/STRUCTURE.md` – project structure & what to edit
- `docs/testing_guide.md` – test inputs & expected results

---

## Launch (Windows)
- Double-click `Launch-Chintu.cmd` for a splash screen while the backend + UI start in the background.
- Logs are saved to `%USERPROFILE%\\.chintu\\logs`.
- Optional flags (PowerShell or cmd): `-WithVoice`, `-NoUI`, `-ForceRestart`, `-NoSplash`.

---

## 1) High-Level Overview
Chintu is a Windows-first personal AI assistant that combines:
- **Voice + UI** input
- **Capability registry** (safe, auditable actions)
- **Memory systems** (short + long-term + temporal)
- **A2UI** (secure, declarative UI cards/forms)
- **Orchestration** (multi-step tasks, approvals, watchdogs)
- **Skills** (declarative, portable command integrations)

Key goals:
- **Reliable** (no silent failures)
- **Secure** (capability gating, confirmation, sandboxing)
- **Future-proof** (modular registries, skills, and orchestration)

---

## 2) Runtime Flow (End-to-End)

```
[UI/Voice/Telegram/WhatsApp]
          |
          v
   [Gateway / WebSocket]
          |
          v
    [CommandHandler]
          |
          +--> [Credential Detector] --(A2UI Prompt if needed)
          |
          +--> [Context Manager + Clarifier]
          |
          +--> [Capability Router + Policy Engine]
          |
          +--> [Tool / Capability Execution]
          |
          +--> [Memory + Learning Journal + Training Logger]
          |
          v
     [A2UI / UI / TTS Response]
```

### What happens when you send a request
1) **Input arrives** (UI, voice, Telegram, WhatsApp)
2) **Credential check** (auto-detect API keys or ask in A2UI form)
3) **Clarification** if needed
4) **Capability selection** (intent → capability)
5) **Policy check** (confirmations, risk levels)
6) **Execution** (capability, tool, or skill)
7) **Memory + learning logs**
8) **Response rendered** (text + optional A2UI card + TTS)

---

## 3) Capability System (Core Actions)
Capabilities are **safe, auditable actions** defined in Python and registered via the central loader.

### Registration Flow
```
register_all_capabilities()
  → core + help
  → memory + temporal
  → search + files + browser
  → automation + tasks + goals
  → mcp + tools + security
  → watchdog + orchestrator
  → skills (from SKILL.md)
```

### Capability Categories (Current)
- **Core**: help, status, reasoning, context, clipboard
- **Memory**: remember, recall, forget, preferences
- **Tasks / Goals**: create, list, update, reminders, schedules
- **Automation**: open/close apps, window control
- **Browser**: open/search/browse URLs, read pages
- **Files**: list/read/document parsing
- **Vision**: screen OCR, click, find elements
- **Security**: identity vault, login workflows
- **Tools**: thumbnails, email codes
- **Workflows**: run/resume/list deterministic YAML/JSON workflows with approvals (recipes in `chintu/workflows/recipes`)
- **Learning**: auto-categorized learning journal, weekly export, status command
- **MCP**: tool registry / server calls
- **Orchestrator**: approvals, multi-step project handling
- **Watchdog**: monitor and recover

> Actual registered capabilities are discovered at runtime (see `CapabilityRegistry`).

---

## 4) Skills System (Declarative, Portable)
Skills are **Markdown-defined integrations** loaded from multiple sources with precedence.

### Skill Sources and Precedence
1) `chintu/skills/bundled/` (shipped with app)
2) `~/.chintu/skills_learned/` (active learning)
3) `~/.chintu/skills/` (user custom)
4) `./skills/` (workspace override)

### Current Bundled Skill Packs (Windows)
- **Productivity**: Notion, Obsidian, OneNote, Trello, GitHub CLI
- **Email**: Himalaya CLI, Outlook open
- **Calendar**: gcalcli, Windows Calendar
- **Home / IoT**: Home Assistant
- **Media**: video frames (ffmpeg), native screenshot
- **Basics**: Weather, IP info

### Skill Execution Security
- Skills can be **disabled globally**.
- Shell skills require explicit allow.
- Optional Docker sandbox isolation.
- Runtime prompts for missing credentials.

---

## 5) Memory System
Chintu uses a hybrid memory architecture:

```
Short-term Memory (Conversation)
        +
Long-term Memory (Hybrid store)
        +
Temporal Memory (timeline/graph)
```

### Features
- **Recall facts** (preferences, history)
- **Summaries** for long conversations
- **Lifecycle management** (dedupe, decay)

### Learning Journal
- Events stored in `~/.chintu/learning/events.jsonl`
- Human-readable log in `~/.chintu/brain_md/Learning.md`
- Weekly export to `~/.chintu/training/exports/weekly_learning_YYYYMMDD.jsonl`
- Default training base: `Qwen/Qwen2.5-1.5B-Instruct` (LoRA adapters in `~/.chintu/models/adapters`)
- If an adapter exists, Chintu auto-uses it for local responses
- Command: `learning status`

---

## 6) Orchestration and Approvals
Long tasks use the orchestrator:
- Breaks into steps
- Requests missing inputs
- Shows approvals in A2UI
- Supports retries and monitoring

---

## 7) A2UI: Secure UI Cards and Forms
A2UI is the safe UI channel for:
- **Approvals**
- **Credential prompts**
- **Structured outputs** (tables)

---

## 8) Reliability and Safety
- **Policy engine** controls high-risk actions
- **Confirmation flows** prevent accidental actions
- **Watchdog** detects stuck processes
- **Training logger** captures safe data
- **Error reporter** surfaces issues
- **Response style** emphasizes concise answers, clear clarifying questions, and no hallucinated facts or sources

---

## 9) Hardware Fit (Your PC)
- GTX 1650 (4GB): fits small local models (1.5B–3B)
- CPU i5 12th gen + 32GB RAM: fine for multitask
- SSD: adequate for memory DB + logs

---

## 10) Where to Look in Code
- `chintu/core/command_handler.py` → main brain
- `chintu/core/capability_loader.py` → capability wiring
- `chintu/skills/skill_registry.py` → skill loader
- `chintu/ui/a2ui.py` → UI cards + forms
- `chintu/memory/` → memory stack
- `chintu/learning/` → learning engine, weekly export, adapter training
- `chintu/llm/adapter_client.py` → fine-tuned adapter runtime
- `chintu/orchestrator/` → multi-step workflows

---

## 11) How to Extend
### Add a new skill
1) Create `skills/your_skill.md`
2) Add `Triggers:` and `Command:`
3) Enable skills in `.env`

### Add a new capability
1) Add handler in a `*_capabilities.py`
2) Register with `register_all_capabilities()`

---

## 12) ASCII Flow Diagrams (Architecture)

**Command Flow**
```
User -> Gateway -> CommandHandler -> Capability Router -> Action -> Response
```

**Skills Flow**
```
SKILL.md -> SkillRegistry -> Capability -> Policy -> Execution
```

**Memory Flow**
```
Conversation -> Memory Store -> Retrieval -> Response
```

---

*Chintu AI – System Guide (Windows)*
