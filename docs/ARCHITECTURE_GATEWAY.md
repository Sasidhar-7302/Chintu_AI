# Gateway Architecture Spec (Phase 0)

## Goals
- Single control plane for all nodes, channels, and tools.
- Strong isolation by agent: workspace, sessions, tool policy, sandbox.
- Typed tool RPC for safe, auditable execution.
- Forward-compatible protocol versioning.

## Control Plane
- Protocol: WebSocket JSON-RPC 2.0
- Default bind: `ws://127.0.0.1:18789`
- Auth: token-based (header `x-gateway-token` or query `token`)
- Versioned handshake:
  - client -> `connect`
  - gateway -> `welcome` (version + nonce)
  - client -> `auth` (token)
  - gateway -> `ready` (session scope + capabilities)

## Session Model
Session key format:
- `agent:<agent_id>:<channel>:<peer_id>`

Rules:
- Per-agent sessions are isolated.
- Non-main sessions may be sandboxed by default.
- Session metadata carries: agent_id, channel, peer_id, tool policy, sandbox mode.

## Agent Isolation
Per-agent root:
- `~/.chintu/agents/<agent_id>/`
  - `workspace/`
  - `skills/`
  - `memory/`
  - `logs/`
  - `state/`

## Tool RPC
Tool calls are JSON-RPC methods:
- `tools.exec`, `tools.process`, `tools.memory.search`, `tools.sessions.list`, etc.

Each tool:
- typed schema
- policy-aware
- audit logging
- idempotent where possible

## Channel Routing
Channels connect to gateway and send inbound events:
- WhatsApp, Telegram, Slack, Discord, Relay, etc.
- Channel-specific policy allows/denies tools.
- Pairing/allowlist required by default for external channels.

## Daemon / Service
Gateway runs as:
- Windows background process (service optional)
- Linux systemd service
- Optional macOS launchd

## Versioning
Protocol version: `1.0.0` initial
- Gateway must accept previous minor versions
- Strict validation on major version mismatch

## Security
- Token-based auth required outside localhost.
- Tool allowlist per agent and per channel.
- Exec approvals ledger with TTL.
- Sandbox default for non-main sessions.
