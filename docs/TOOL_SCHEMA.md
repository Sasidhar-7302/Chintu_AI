# Tool Schema Spec (Phase 0)

## Goals
- Typed, validated tool surface (Pydantic).
- Stable method names for gateway RPC.
- Tool grouping for policy enforcement.

## Tool Naming
Format: `tools.<group>.<action>`
Examples:
- `tools.exec.run`
- `tools.process.list`
- `tools.sessions.send`
- `tools.memory.search`

## Schema Rules
- Every tool has:
  - `name`, `group`, `schema`, `risk_level`, `requires_confirmation`
  - `inputs` and `outputs`
- Validation errors are returned as JSON-RPC error responses.

## Core Tools (Phase 1.5)
Runtime:
- `tools.exec.run` (strict allowlist)
- `tools.process.list`
- `tools.process.read`
- `tools.process.kill` (high risk)

Sessions:
- `tools.sessions.list`
- `tools.sessions.history`
- `tools.sessions.send`
- `tools.sessions.spawn`
- `tools.session.status`

Memory:
- `tools.memory.search`
- `tools.memory.get`
- `tools.memory.write` (confirmed)

Web:
- `tools.web.search`
- `tools.web.fetch`

## Tool Groups
- runtime
- fs
- sessions
- memory
- web
- ui

## Policy Integration
- Per-agent allow/deny
- Per-channel allow/deny
- Exec approvals ledger

## Backward Compatibility
- Existing capability handlers can be wrapped until full tool migration.
