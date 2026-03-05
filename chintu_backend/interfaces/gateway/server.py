"""Gateway server (FastAPI + WebSocket JSON-RPC)."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

from ...core.state import get_state_manager
from ...core.events import get_event_bus, EventType, Event
from .protocol import parse_message, is_request, make_result, make_error
from .bus import GatewayEventBus
from ...core.config import get_config
from ...channels.policy import ChannelPolicyManager
from .tool_registry import GatewayToolRegistry
from .control_plane import build_control_plane_snapshot
from .mini_app_html import render_control_plane_mini_app_html

logger = logging.getLogger(__name__)


class GatewayServer:
    """JSON-RPC 2.0 gateway for external clients."""

    def __init__(
        self,
        command_handler,
        host: str = "127.0.0.1",
        port: int = 18789,
        auth_token: Optional[str] = None,
    ):
        self.command_handler = command_handler
        self.host = host
        self.port = port
        self._config = get_config()
        self.auth_token = auth_token or self._config.gateway_auth_token

        self.app = FastAPI(title="Chintu Gateway", version="0.1")
        self._clients: Dict[int, WebSocket] = {}
        self._server: Optional[uvicorn.Server] = None
        self._server_task: Optional[asyncio.Task] = None
        self._bus = GatewayEventBus()
        self._state = get_state_manager()
        self._event_bus = get_event_bus()
        self._sessions: Dict[int, Dict[str, Any]] = {}
        self._gateway_version = getattr(self._config, "gateway_version", "1.0.0")
        self._audit_events = deque(maxlen=int(getattr(self._config, "gateway_audit_history_limit", 300)))
        self._channel_policy = ChannelPolicyManager()
        self._tools = GatewayToolRegistry(self.command_handler)
        self._ops_rate_buckets: Dict[str, deque] = {}

        self._whatsapp_gateway = None
        self._slack_gateway = None
        self._discord_gateway = None
        self._relay_gateway = None
        self._register_routes()
        self._attach_event_forwarders()

    @staticmethod
    def _is_local_addr(addr: str) -> bool:
        if not addr:
            return False
        if addr in {"127.0.0.1", "localhost", "::1"}:
            return True
        try:
            return ipaddress.ip_address(addr).is_loopback
        except Exception:
            return False

    def _is_remote_ip_allowed(self, addr: str) -> bool:
        if self._is_local_addr(addr):
            return True
        allowlist = [str(item).strip() for item in (getattr(self._config, "gateway_remote_ip_allowlist", []) or []) if str(item).strip()]
        if not allowlist:
            return True
        try:
            ip = ipaddress.ip_address(addr)
        except Exception:
            return False
        for item in allowlist:
            try:
                if "/" in item:
                    if ip in ipaddress.ip_network(item, strict=False):
                        return True
                elif ip == ipaddress.ip_address(item):
                    return True
            except Exception:
                continue
        return False

    def _http_authorized(self, request: Request) -> bool:
        token = request.headers.get("x-gateway-token") or request.query_params.get("token")
        if self.auth_token and token != self.auth_token:
            return False
        client_host = getattr(request.client, "host", "") if request.client else ""
        if not self._is_remote_ip_allowed(client_host):
            return False
        return True

    def _record_audit(
        self,
        session: Optional[Dict[str, Any]],
        method: str,
        status: str,
        detail: Optional[str] = None,
    ) -> None:
        entry = {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "method": method,
            "status": status,
            "detail": detail or "",
            "session_id": (session or {}).get("session_id"),
            "channel": (session or {}).get("channel"),
            "user_id": (session or {}).get("user_id"),
            "remote_addr": (session or {}).get("remote_addr"),
            "is_untrusted": bool((session or {}).get("is_untrusted")),
        }
        self._audit_events.append(entry)

    def _session_owner_allowed(self, session: Optional[Dict[str, Any]]) -> bool:
        """Owner-only gate for remote control-plane operations."""
        s = session or {}
        if bool(s.get("is_local")):
            return True
        channel = str(s.get("channel") or "").strip().lower()
        user_id = s.get("user_id")
        if not channel or user_id is None:
            return False
        if not self._channel_policy.is_allowed(channel, user_id):
            return False
        if channel == "telegram":
            allowed = int(getattr(self._config, "telegram_allowed_user_id", 0) or 0)
            if allowed and str(allowed) != str(user_id):
                return False
        return True

    def _check_ops_rate_limit(self, session: Optional[Dict[str, Any]], *, bucket: str, limit: int, window_s: int) -> bool:
        """Simple per-session sliding-window limiter for ops endpoints."""
        s = session or {}
        key = f"{bucket}:{s.get('session_id') or 'http'}"
        now = time.time()
        dq = self._ops_rate_buckets.get(key)
        if dq is None:
            dq = deque()
            self._ops_rate_buckets[key] = dq
        while dq and (now - float(dq[0])) > float(window_s):
            dq.popleft()
        if len(dq) >= max(1, int(limit)):
            return False
        dq.append(now)
        return True

    def _ops_signing_secret(self) -> str:
        secret = str(getattr(self._config, "telegram_approval_signing_secret", "") or "").strip()
        if secret:
            return secret
        token = str(getattr(self._config, "gateway_auth_token", "") or "").strip()
        if token:
            return token
        return str(self.auth_token or "").strip()

    def _sign_json_payload(self, payload: Dict[str, Any]) -> str:
        secret = self._ops_signing_secret()
        if not secret:
            return ""
        canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=True)
        return hmac.new(secret.encode("utf-8", errors="ignore"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()

    def _verify_json_payload_signature(self, payload: Dict[str, Any], signature: str) -> bool:
        provided = str(signature or "").strip().lower()
        if not provided:
            return False
        expected = self._sign_json_payload(payload)
        if not expected:
            return False
        try:
            return hmac.compare_digest(provided, expected)
        except Exception:
            return False

    def _sign_owner_gate_signature(self, user_id: str, exp_ts: int) -> str:
        secret = self._ops_signing_secret()
        if not secret:
            return ""
        message = f"uid:{user_id}|exp:{int(exp_ts)}"
        return hmac.new(secret.encode("utf-8", errors="ignore"), message.encode("utf-8"), hashlib.sha256).hexdigest()[:16]

    def _verify_owner_gate_signature(self, user_id: str, exp_ts: int, signature: str) -> bool:
        try:
            if int(exp_ts) < int(time.time()):
                return False
        except Exception:
            return False
        provided = str(signature or "").strip().lower()
        expected = self._sign_owner_gate_signature(str(user_id), int(exp_ts))
        if not provided or not expected:
            return False
        try:
            return hmac.compare_digest(provided, expected)
        except Exception:
            return False

    def _http_owner_allowed(self, request: Request, *, user_id_hint: Optional[str] = None) -> bool:
        """
        Owner-only gate for remote HTTP ops endpoints.

        Localhost requests are trusted. Remote requests must carry a valid
        signed owner payload (`uid`, `exp`, `sig`) matching configured owner.
        """
        client_host = getattr(request.client, "host", "") if request.client else ""
        if self._is_local_addr(client_host):
            return True

        allowed_owner = int(getattr(self._config, "telegram_allowed_user_id", 0) or 0)
        uid = str(
            user_id_hint
            or request.query_params.get("uid")
            or request.headers.get("x-telegram-user-id")
            or ""
        ).strip()
        exp_raw = str(
            request.query_params.get("exp")
            or request.headers.get("x-ops-owner-exp")
            or ""
        ).strip()
        sig = str(
            request.query_params.get("sig")
            or request.headers.get("x-ops-owner-signature")
            or ""
        ).strip()

        if not uid or not exp_raw or not sig:
            return False
        if allowed_owner and uid != str(allowed_owner):
            return False
        try:
            exp_ts = int(exp_raw)
        except Exception:
            return False
        return self._verify_owner_gate_signature(uid, exp_ts, sig)

    def _attach_signed_approval_payloads(
        self,
        control_plane: Dict[str, Any],
        *,
        ttl_s: int = 600,
    ) -> Dict[str, Any]:
        approvals = control_plane.get("approvals_ledger")
        if not isinstance(approvals, dict):
            return control_plane
        pending = approvals.get("pending")
        if not isinstance(pending, list):
            return control_plane

        issued_at = int(time.time())
        expires_at = issued_at + max(60, int(ttl_s))
        for item in pending:
            if not isinstance(item, dict):
                continue
            payload = {
                "kind": str(item.get("kind") or "").strip().lower(),
                "id": str(item.get("id") or "").strip(),
                "step_id": str(item.get("step_id") or "").strip(),
                "capability": str(item.get("capability") or "").strip(),
                "run_id": str(item.get("run_id") or "").strip(),
                "issued_at": issued_at,
                "expires_at": expires_at,
            }
            item["approval_payload"] = payload
            item["approval_signature"] = self._sign_json_payload(payload)
        return control_plane

    def _build_control_plane_snapshot(
        self,
        *,
        session: Optional[Dict[str, Any]] = None,
        limit_runs: int = 30,
        limit_approvals: int = 30,
    ) -> Dict[str, Any]:
        run_summary: Dict[str, Any] = {}
        runs_root = self._config.data_dir / "runs"
        try:
            from chintu_backend.core.run_manager import get_run_manager

            run_summary = get_run_manager().snapshot(limit=max(10, int(limit_runs)))
        except Exception:
            run_summary = {"runs": [], "lanes": {}}
        control_plane = build_control_plane_snapshot(
            command_handler=self.command_handler,
            run_summary=run_summary,
            session=session or {},
            channel_policy=self._channel_policy,
            runs_root=runs_root,
            limit_runs=limit_runs,
            limit_approvals=limit_approvals,
        )
        ttl = int(getattr(self._config, "gateway_approval_payload_ttl_seconds", 600) or 600)
        return self._attach_signed_approval_payloads(control_plane, ttl_s=ttl)

    def _resolve_approval_request(self, *, params: Dict[str, Any], session: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        kind = str(params.get("kind") or "action").strip().lower()
        decision = str(params.get("decision") or "").strip().lower()
        if decision not in {"allow_once", "whitelist", "deny"}:
            return {"ok": False, "error": "decision must be allow_once|whitelist|deny"}

        sess = session or {}
        require_signed = bool(getattr(self._config, "telegram_require_signed_approvals", True))
        if require_signed and not bool(sess.get("is_local")):
            payload = params.get("approval_payload")
            signature = str(params.get("approval_signature") or "").strip()
            if not isinstance(payload, dict):
                return {"ok": False, "error": "approval_payload is required for remote approvals"}
            if not self._verify_json_payload_signature(payload, signature):
                return {"ok": False, "error": "approval payload signature check failed"}
            try:
                exp_ts = int(payload.get("expires_at") or 0)
            except Exception:
                exp_ts = 0
            if exp_ts <= int(time.time()):
                return {"ok": False, "error": "approval payload expired"}
            payload_kind = str(payload.get("kind") or "").strip().lower()
            if payload_kind and payload_kind != kind:
                return {"ok": False, "error": "approval payload kind mismatch"}

        if kind == "orchestrator_step":
            step_id = str(params.get("step_id") or "").strip()
            if not step_id:
                return {"ok": False, "error": "step_id is required for orchestrator_step approvals"}
            if require_signed and not bool(sess.get("is_local")):
                payload = params.get("approval_payload") if isinstance(params.get("approval_payload"), dict) else {}
                payload_step = str(payload.get("step_id") or "").strip()
                if payload_step and payload_step != step_id:
                    return {"ok": False, "error": "approval payload step mismatch"}
            try:
                from chintu_backend.orchestrator import get_orchestrator_manager

                updated = get_orchestrator_manager().approve_step(step_id, approve=(decision != "deny"))
                if not updated:
                    return {"ok": False, "error": "step not found or no update"}
                return {
                    "ok": True,
                    "kind": kind,
                    "decision": decision,
                    "step_id": step_id,
                    "status": getattr(updated.status, "value", str(getattr(updated, "status", ""))),
                }
            except Exception as exc:
                return {"ok": False, "error": str(exc)}

        if kind != "action":
            return {"ok": False, "error": f"unsupported approval kind: {kind}"}

        dispatcher = getattr(self.command_handler, "action_dispatcher", None)
        if not dispatcher:
            return {"ok": False, "error": "action dispatcher unavailable"}
        pending = dispatcher.get_pending_confirmation() or {}
        if not bool(pending.get("pending")):
            return {"ok": False, "error": "no pending action approval"}

        pending_capability = str(pending.get("capability") or "").strip()
        if require_signed and not bool(sess.get("is_local")):
            payload = params.get("approval_payload") if isinstance(params.get("approval_payload"), dict) else {}
            payload_capability = str(payload.get("capability") or "").strip()
            if payload_capability and payload_capability != pending_capability:
                return {"ok": False, "error": "approval payload capability mismatch"}

        if decision == "deny":
            cancelled = bool(dispatcher.cancel_pending())
            try:
                from chintu_backend.core.run_manager import get_run_manager

                run_mgr = get_run_manager()
                rid = str(run_mgr.pending_confirmation_run_id() or "").strip()
                if rid:
                    run_mgr.mark_cancelled(rid, reason="Denied via gateway.ops.resolve_approval")
                    run_mgr.release_run_turn(rid)
            except Exception:
                pass
            return {"ok": bool(cancelled), "kind": kind, "decision": decision, "capability": pending_capability}

        if decision == "whitelist":
            channel = str((session or {}).get("channel") or "").strip().lower()
            user_id = (session or {}).get("user_id")
            if channel and user_id is not None and pending_capability:
                try:
                    existing = self._channel_policy.get_tool_policy(channel, user_id) or {}
                    allow = [str(x) for x in (existing.get("allow") or [])]
                    deny = [str(x) for x in (existing.get("deny") or [])]
                    if pending_capability not in allow:
                        allow.append(pending_capability)
                    self._channel_policy.set_tool_policy(channel, allow=allow, deny=deny, user_id=user_id)
                except Exception:
                    pass

        confirm_context: Dict[str, Any] = {}
        try:
            from chintu_backend.core.run_manager import get_run_manager

            rid = str(get_run_manager().pending_confirmation_run_id() or "").strip()
            if rid:
                confirm_context["_run_id"] = rid
        except Exception:
            pass
        result = dispatcher.confirm_pending(context=confirm_context)
        if not result:
            return {"ok": False, "error": "failed to confirm pending action"}
        return {
            "ok": True,
            "kind": kind,
            "decision": decision,
            "capability": pending_capability,
            "result_success": bool(getattr(result, "success", False)),
            "result_message": str(getattr(result, "message", "") or "")[:400],
        }

    def _resolve_run_control_request(self, *, params: Dict[str, Any], session: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        action = str(params.get("action") or "").strip().lower()
        run_id = str(params.get("run_id") or "").strip()
        if action not in {"receipt", "cancel"}:
            return {"ok": False, "error": "action must be receipt|cancel"}
        if not run_id:
            return {"ok": False, "error": "run_id is required"}

        try:
            from chintu_backend.core.run_manager import get_run_manager

            mgr = get_run_manager()
            summary = mgr.snapshot(limit=500)
            runs = summary.get("runs") if isinstance(summary, dict) else []
            if not isinstance(runs, list):
                runs = []
            row = next((r for r in runs if isinstance(r, dict) and str(r.get("id") or "") == run_id), None)
            if not row:
                return {"ok": False, "error": "run not found", "run_id": run_id}

            if action == "cancel":
                cancelled = bool(mgr.cancel_run(run_id, reason="Cancelled via gateway run control"))
                return {"ok": cancelled, "action": action, "run_id": run_id, "status": "cancelled" if cancelled else "not_cancelled"}

            receipt_path = str(row.get("receipt_path") or "").strip()
            if not receipt_path:
                return {"ok": False, "error": "receipt not available", "run_id": run_id}
            path = Path(receipt_path)
            if not path.exists():
                return {"ok": False, "error": "receipt file missing", "run_id": run_id, "receipt_path": receipt_path}
            max_chars = int(getattr(self._config, "gateway_run_receipt_max_chars", 50000) or 50000)
            text = path.read_text(encoding="utf-8", errors="ignore")[: max(2000, min(max_chars, 500000))]
            return {
                "ok": True,
                "action": action,
                "run_id": run_id,
                "run": row,
                "receipt_path": receipt_path,
                "receipt_text": text,
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc), "run_id": run_id, "action": action}

    def _build_ops_snapshot(self) -> Dict[str, Any]:
        pending = {}
        try:
            dispatcher = getattr(self.command_handler, "action_dispatcher", None)
            if dispatcher:
                pending = dispatcher.get_pending_confirmation() or {}
        except Exception:
            pending = {}

        run_summary: Dict[str, Any] = {}
        try:
            from chintu_backend.core.run_manager import get_run_manager

            run_summary = get_run_manager().snapshot(limit=20)
        except Exception:
            run_summary = {"runs": []}

        failures: Dict[str, int] = {}
        for event in self._audit_events:
            if event.get("status") not in {"error", "blocked"}:
                continue
            reason = str(event.get("detail") or "unknown")
            failures[reason] = failures.get(reason, 0) + 1

        return {
            "gateway_version": self._gateway_version,
            "active_sessions": len(self._sessions),
            "active_clients": len(self._clients),
            "pending_approvals": pending,
            "recent_actions": list(self._audit_events)[-50:],
            "top_failure_reasons": sorted(
                [{"reason": reason, "count": count} for reason, count in failures.items()],
                key=lambda item: item["count"],
                reverse=True,
            )[:10],
            "run_summary": run_summary,
        }

    def _load_channel_gateway(self, key: str):
        if key == "whatsapp":
            if not self._whatsapp_gateway:
                from chintu_backend.channels.whatsapp import WhatsAppGateway

                self._whatsapp_gateway = WhatsAppGateway(self.command_handler)
            return self._whatsapp_gateway
        if key == "slack":
            if not self._slack_gateway:
                from chintu_backend.channels.slack import SlackGateway

                self._slack_gateway = SlackGateway(self.command_handler)
            return self._slack_gateway
        if key == "discord":
            if not self._discord_gateway:
                from chintu_backend.channels.discord import DiscordGateway

                self._discord_gateway = DiscordGateway(self.command_handler)
            return self._discord_gateway
        if key == "relay":
            if not self._relay_gateway:
                from chintu_backend.channels.relay import RelayGateway

                self._relay_gateway = RelayGateway(self.command_handler)
            return self._relay_gateway
        return None

    def _register_routes(self) -> None:
        @self.app.post("/webhook/whatsapp")
        async def whatsapp_webhook(request: Request) -> JSONResponse:
            try:
                gateway = self._load_channel_gateway("whatsapp")
            except Exception:
                return JSONResponse({"status": "disabled"}, status_code=503)
            if not gateway or not gateway.is_enabled():
                return JSONResponse({"status": "disabled"}, status_code=503)
            status, _ = await gateway.handle_webhook(request)
            return JSONResponse({"status": "ok" if status == 200 else "denied"}, status_code=status)

        @self.app.post("/webhook/slack")
        async def slack_webhook(request: Request) -> JSONResponse:
            try:
                gateway = self._load_channel_gateway("slack")
            except Exception:
                return JSONResponse({"status": "disabled"}, status_code=503)
            if not gateway or not gateway.is_enabled():
                return JSONResponse({"status": "disabled"}, status_code=503)
            status, payload = await gateway.handle_webhook(request)
            return JSONResponse(payload, status_code=status)

        @self.app.post("/webhook/discord")
        async def discord_webhook(request: Request) -> JSONResponse:
            try:
                gateway = self._load_channel_gateway("discord")
            except Exception:
                return JSONResponse({"status": "disabled"}, status_code=503)
            if not gateway or not gateway.is_enabled():
                return JSONResponse({"status": "disabled"}, status_code=503)
            status, payload = await gateway.handle_webhook(request)
            return JSONResponse(payload, status_code=status)

        @self.app.post("/webhook/relay")
        async def relay_webhook(request: Request) -> JSONResponse:
            try:
                gateway = self._load_channel_gateway("relay")
            except Exception:
                return JSONResponse({"status": "disabled"}, status_code=503)
            if not gateway or not gateway.is_enabled():
                return JSONResponse({"status": "disabled"}, status_code=503)
            status, payload = await gateway.handle_webhook(request)
            return JSONResponse(payload, status_code=status)

        @self.app.get("/ops/snapshot")
        async def ops_snapshot(request: Request) -> JSONResponse:
            if not self._http_authorized(request):
                return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)
            return JSONResponse({"ok": True, "snapshot": self._build_ops_snapshot()})

        @self.app.get("/ops/sessions")
        async def ops_sessions(request: Request) -> JSONResponse:
            if not self._http_authorized(request):
                return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)
            return JSONResponse({"ok": True, "sessions": list(self._sessions.values())})

        @self.app.get("/ops/control-plane")
        async def ops_control_plane(request: Request) -> JSONResponse:
            if not self._http_authorized(request):
                return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)
            if not self._http_owner_allowed(request):
                return JSONResponse({"ok": False, "error": "owner_access_required"}, status_code=403)
            client_host = getattr(request.client, "host", "") if request.client else ""
            rate_session = {"session_id": f"http:{client_host or 'unknown'}"}
            if not self._check_ops_rate_limit(
                rate_session,
                bucket="ops.control_plane.http",
                limit=int(getattr(self._config, "gateway_ops_rate_limit_per_minute", 60) or 60),
                    window_s=60,
            ):
                return JSONResponse({"ok": False, "error": "rate_limited"}, status_code=429)
            uid = str(
                request.query_params.get("uid")
                or request.headers.get("x-telegram-user-id")
                or ""
            ).strip()
            session = {
                "session_id": rate_session["session_id"],
                "is_local": self._is_local_addr(client_host),
                "channel": "telegram" if uid else "gateway",
                "user_id": uid or None,
            }
            limit_runs = 30
            limit_approvals = 30
            try:
                limit_runs = max(10, min(int(request.query_params.get("limit_runs", "30")), 200))
            except Exception:
                limit_runs = 30
            try:
                limit_approvals = max(10, min(int(request.query_params.get("limit_approvals", "30")), 200))
            except Exception:
                limit_approvals = 30
            payload = self._build_control_plane_snapshot(
                session=session,
                limit_runs=limit_runs,
                limit_approvals=limit_approvals,
            )
            return JSONResponse({"ok": True, "control_plane": payload})

        @self.app.post("/ops/resolve-approval")
        async def ops_resolve_approval(request: Request) -> JSONResponse:
            if not self._http_authorized(request):
                return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)
            try:
                body = await request.json()
            except Exception:
                body = {}
            params = body if isinstance(body, dict) else {}
            uid_hint = str(params.get("user_id") or "").strip() or None
            if not self._http_owner_allowed(request, user_id_hint=uid_hint):
                return JSONResponse({"ok": False, "error": "owner_access_required"}, status_code=403)
            client_host = getattr(request.client, "host", "") if request.client else ""
            rate_session = {"session_id": f"http:{client_host or 'unknown'}"}
            if not self._check_ops_rate_limit(
                rate_session,
                bucket="ops.resolve_approval.http",
                limit=int(getattr(self._config, "gateway_ops_approval_rate_limit_per_minute", 30) or 30),
                window_s=60,
            ):
                return JSONResponse({"ok": False, "error": "rate_limited"}, status_code=429)
            uid = str(
                uid_hint
                or request.query_params.get("uid")
                or request.headers.get("x-telegram-user-id")
                or ""
            ).strip()
            session = {
                "session_id": rate_session["session_id"],
                "is_local": self._is_local_addr(client_host),
                "channel": "telegram" if uid else "gateway",
                "user_id": uid or None,
            }
            payload = self._resolve_approval_request(params=params, session=session)
            if bool(payload.get("ok")):
                return JSONResponse({"ok": True, "result": payload})
            return JSONResponse({"ok": False, "error": payload.get("error") or "approval_resolution_failed", "detail": payload}, status_code=400)

        @self.app.get("/ops/mini-app")
        async def ops_mini_app(request: Request) -> HTMLResponse | JSONResponse:
            if not self._http_authorized(request):
                return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)
            if not self._http_owner_allowed(request):
                return JSONResponse({"ok": False, "error": "owner_access_required"}, status_code=403)
            return HTMLResponse(render_control_plane_mini_app_html())

        @self.app.get("/ops/run/{run_id}/receipt")
        async def ops_run_receipt(run_id: str, request: Request) -> JSONResponse:
            if not self._http_authorized(request):
                return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)
            if not self._http_owner_allowed(request):
                return JSONResponse({"ok": False, "error": "owner_access_required"}, status_code=403)
            client_host = getattr(request.client, "host", "") if request.client else ""
            rate_session = {"session_id": f"http:{client_host or 'unknown'}"}
            if not self._check_ops_rate_limit(
                rate_session,
                bucket="ops.run_receipt.http",
                limit=int(getattr(self._config, "gateway_ops_rate_limit_per_minute", 60) or 60),
                window_s=60,
            ):
                return JSONResponse({"ok": False, "error": "rate_limited"}, status_code=429)
            uid = str(
                request.query_params.get("uid")
                or request.headers.get("x-telegram-user-id")
                or ""
            ).strip()
            session = {
                "session_id": rate_session["session_id"],
                "is_local": self._is_local_addr(client_host),
                "channel": "telegram" if uid else "gateway",
                "user_id": uid or None,
            }
            payload = self._resolve_run_control_request(
                params={"action": "receipt", "run_id": run_id},
                session=session,
            )
            if bool(payload.get("ok")):
                return JSONResponse({"ok": True, "result": payload})
            return JSONResponse({"ok": False, "error": payload.get("error") or "run_receipt_failed", "detail": payload}, status_code=404)

        @self.app.post("/ops/run/{run_id}/cancel")
        async def ops_cancel_run(run_id: str, request: Request) -> JSONResponse:
            if not self._http_authorized(request):
                return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)
            try:
                body = await request.json()
            except Exception:
                body = {}
            params = body if isinstance(body, dict) else {}
            uid_hint = str(params.get("user_id") or "").strip() or None
            if not self._http_owner_allowed(request, user_id_hint=uid_hint):
                return JSONResponse({"ok": False, "error": "owner_access_required"}, status_code=403)
            client_host = getattr(request.client, "host", "") if request.client else ""
            rate_session = {"session_id": f"http:{client_host or 'unknown'}"}
            if not self._check_ops_rate_limit(
                rate_session,
                bucket="ops.cancel_run.http",
                limit=int(getattr(self._config, "gateway_ops_approval_rate_limit_per_minute", 30) or 30),
                window_s=60,
            ):
                return JSONResponse({"ok": False, "error": "rate_limited"}, status_code=429)
            uid = str(
                uid_hint
                or request.query_params.get("uid")
                or request.headers.get("x-telegram-user-id")
                or ""
            ).strip()
            session = {
                "session_id": rate_session["session_id"],
                "is_local": self._is_local_addr(client_host),
                "channel": "telegram" if uid else "gateway",
                "user_id": uid or None,
            }
            payload = self._resolve_run_control_request(
                params={"action": "cancel", "run_id": run_id},
                session=session,
            )
            if bool(payload.get("ok")):
                return JSONResponse({"ok": True, "result": payload})
            return JSONResponse({"ok": False, "error": payload.get("error") or "run_cancel_failed", "detail": payload}, status_code=400)

        @self.app.websocket("/ws")
        async def websocket_endpoint(ws: WebSocket) -> None:
            token = ws.query_params.get("token") or ws.headers.get("x-gateway-token")
            client_host = getattr(ws.client, "host", "") if ws.client else ""
            is_local = self._is_local_addr(client_host)
            if self.auth_token and token != self.auth_token:
                await ws.close(code=4403)
                return
            if not is_local and not self.auth_token:
                await ws.close(code=4403)
                return
            if not self._is_remote_ip_allowed(client_host):
                await ws.close(code=4403)
                return
            await ws.accept()
            client_id = id(ws)
            self._clients[client_id] = ws
            self._sessions[client_id] = {
                "session_id": str(client_id),
                "ws_client_id": client_id,
                "agent_key": "primary",
                "agent_role": None,
                "channel": "gateway",
                "user_id": None,
                "client_version": None,
                "client_role": None,
                "client_id": None,
                "remote_addr": client_host,
                "is_local": is_local,
                "is_untrusted": not is_local,
            }
            await self._send(
                ws,
                {
                    "type": "session.started",
                    "session_id": str(client_id),
                    "gateway_version": self._gateway_version,
                },
            )
            self._record_audit(self._sessions.get(client_id), "session.started", "ok")
            try:
                while True:
                    raw = await ws.receive_text()
                    await self._handle_message(ws, raw)
            except WebSocketDisconnect:
                pass
            finally:
                self._record_audit(self._sessions.get(client_id), "session.closed", "ok")
                self._clients.pop(client_id, None)
                self._sessions.pop(client_id, None)

    def _attach_event_forwarders(self) -> None:
        async def forward_event(event: Event) -> None:
            payload = {
                "type": "event",
                "event": event.type.value,
                "data": event.data,
                "source": event.source,
            }
            await self.broadcast(payload)

        for evt in (
            EventType.TRANSCRIPT_READY,
            EventType.COMMAND_EXECUTED,
            EventType.COMMAND_FAILED,
            EventType.ERROR,
            EventType.STATE_CHANGED,
            EventType.CANVAS_UPDATE,
            EventType.RUN_UPDATE,
            EventType.RUN_SNAPSHOT,
        ):
            self._event_bus.subscribe(evt, lambda e, evt=evt: asyncio.create_task(forward_event(e)), is_async=False)

    async def _handle_message(self, ws: WebSocket, raw: str) -> None:
        message, err = parse_message(raw)
        if err or not message:
            await self._send(ws, make_error(None, -32700, "Parse error", err))
            return

        if not is_request(message):
            await self._send(ws, make_error(message.get("id"), -32600, "Invalid Request"))
            return

        req_id = message.get("id")
        method = message.get("method")
        params = message.get("params") or {}
        session = self._sessions.get(id(ws), {})

        try:
            if method == "gateway.hello":
                client_version = None
                if isinstance(params, dict):
                    client_version = params.get("client_version")
                    session["client_version"] = client_version
                    session["client_role"] = params.get("role")
                    session["client_id"] = params.get("client_id")
                    self._sessions[id(ws)] = session
                if client_version and isinstance(client_version, str):
                    try:
                        g_major = self._gateway_version.split(".")[0]
                        c_major = client_version.split(".")[0]
                        if g_major != c_major:
                            await self._send(ws, make_error(req_id, -32001, "Gateway version mismatch"))
                            return
                    except Exception:
                        pass
                meta = {
                    "gateway_version": self._gateway_version,
                    "session_id": session.get("session_id"),
                    "is_untrusted": bool(session.get("is_untrusted")),
                }
                await self._send(ws, make_result(req_id, meta))
                self._record_audit(session, method, "ok")
                return

            if method == "health.ping":
                await self._send(ws, make_result(req_id, {"ok": True}))
                self._record_audit(session, method, "ok")
                return

            if method == "state.get":
                await self._send(ws, make_result(req_id, self._state.state.to_dict()))
                self._record_audit(session, method, "ok")
                return

            if method == "session.create":
                await self._send(ws, make_result(req_id, {"session_id": str(id(ws))}))
                self._record_audit(session, method, "ok")
                return

            if method == "session.update":
                if isinstance(params, dict):
                    session.update(
                        {
                            "agent_key": params.get("agent_key", session.get("agent_key", "primary")),
                            "agent_role": params.get("agent_role", session.get("agent_role")),
                            "channel": params.get("channel", session.get("channel", "gateway")),
                            "user_id": params.get("user_id", session.get("user_id")),
                            "session_id": params.get("session_id", session.get("session_id")),
                        }
                    )
                    if str(session.get("channel") or "").lower() in {
                        str(item).lower() for item in (getattr(self._config, "gateway_untrusted_channels", []) or [])
                    }:
                        session["is_untrusted"] = True
                    self._sessions[id(ws)] = session
                await self._send(ws, make_result(req_id, {"ok": True, "session": session}))
                self._record_audit(session, method, "ok")
                return

            if method == "gateway.ops.snapshot":
                await self._send(ws, make_result(req_id, self._build_ops_snapshot()))
                self._record_audit(session, method, "ok")
                return

            if method == "gateway.ops.sessions":
                await self._send(ws, make_result(req_id, {"sessions": list(self._sessions.values())}))
                self._record_audit(session, method, "ok")
                return

            if method == "gateway.ops.audit":
                limit = 50
                if isinstance(params, dict):
                    try:
                        limit = max(1, min(int(params.get("limit", 50)), 500))
                    except Exception:
                        limit = 50
                await self._send(ws, make_result(req_id, {"events": list(self._audit_events)[-limit:]}))
                self._record_audit(session, method, "ok")
                return

            if method == "gateway.ops.control_plane":
                if not self._session_owner_allowed(session):
                    await self._send(ws, make_error(req_id, -32003, "Owner access required"))
                    self._record_audit(session, method, "blocked", "owner_access_required")
                    return
                if not self._check_ops_rate_limit(
                    session,
                    bucket="ops.control_plane.ws",
                    limit=int(getattr(self._config, "gateway_ops_rate_limit_per_minute", 60) or 60),
                    window_s=60,
                ):
                    await self._send(ws, make_error(req_id, -32029, "Rate limit exceeded"))
                    self._record_audit(session, method, "blocked", "rate_limited")
                    return
                limit_runs = 30
                limit_approvals = 30
                if isinstance(params, dict):
                    try:
                        limit_runs = max(5, min(int(params.get("limit_runs", 30)), 100))
                    except Exception:
                        limit_runs = 30
                    try:
                        limit_approvals = max(5, min(int(params.get("limit_approvals", 30)), 100))
                    except Exception:
                        limit_approvals = 30
                payload = self._build_control_plane_snapshot(
                    session=session,
                    limit_runs=limit_runs,
                    limit_approvals=limit_approvals,
                )
                await self._send(ws, make_result(req_id, payload))
                self._record_audit(session, method, "ok")
                return

            if method == "gateway.ops.resolve_approval":
                if not self._session_owner_allowed(session):
                    await self._send(ws, make_error(req_id, -32003, "Owner access required"))
                    self._record_audit(session, method, "blocked", "owner_access_required")
                    return
                if not self._check_ops_rate_limit(
                    session,
                    bucket="ops.resolve_approval.ws",
                    limit=int(getattr(self._config, "gateway_ops_approval_rate_limit_per_minute", 30) or 30),
                    window_s=60,
                ):
                    await self._send(ws, make_error(req_id, -32029, "Rate limit exceeded"))
                    self._record_audit(session, method, "blocked", "rate_limited")
                    return
                payload = self._resolve_approval_request(
                    params=params if isinstance(params, dict) else {},
                    session=session,
                )
                if bool(payload.get("ok")):
                    await self._send(ws, make_result(req_id, payload))
                    self._record_audit(session, method, "ok")
                else:
                    await self._send(ws, make_error(req_id, -32004, "Approval resolution failed", payload))
                    self._record_audit(session, method, "blocked", str(payload.get("error") or "approval_resolution_failed"))
                return

            if method == "gateway.ops.run_receipt":
                if not self._session_owner_allowed(session):
                    await self._send(ws, make_error(req_id, -32003, "Owner access required"))
                    self._record_audit(session, method, "blocked", "owner_access_required")
                    return
                if not self._check_ops_rate_limit(
                    session,
                    bucket="ops.run_receipt.ws",
                    limit=int(getattr(self._config, "gateway_ops_rate_limit_per_minute", 60) or 60),
                    window_s=60,
                ):
                    await self._send(ws, make_error(req_id, -32029, "Rate limit exceeded"))
                    self._record_audit(session, method, "blocked", "rate_limited")
                    return
                payload = self._resolve_run_control_request(
                    params={
                        "action": "receipt",
                        "run_id": str((params or {}).get("run_id") or ""),
                    },
                    session=session,
                )
                if bool(payload.get("ok")):
                    await self._send(ws, make_result(req_id, payload))
                    self._record_audit(session, method, "ok")
                else:
                    await self._send(ws, make_error(req_id, -32005, "Run receipt fetch failed", payload))
                    self._record_audit(session, method, "blocked", str(payload.get("error") or "run_receipt_failed"))
                return

            if method == "gateway.ops.cancel_run":
                if not self._session_owner_allowed(session):
                    await self._send(ws, make_error(req_id, -32003, "Owner access required"))
                    self._record_audit(session, method, "blocked", "owner_access_required")
                    return
                if not self._check_ops_rate_limit(
                    session,
                    bucket="ops.cancel_run.ws",
                    limit=int(getattr(self._config, "gateway_ops_approval_rate_limit_per_minute", 30) or 30),
                    window_s=60,
                ):
                    await self._send(ws, make_error(req_id, -32029, "Rate limit exceeded"))
                    self._record_audit(session, method, "blocked", "rate_limited")
                    return
                payload = self._resolve_run_control_request(
                    params={
                        "action": "cancel",
                        "run_id": str((params or {}).get("run_id") or ""),
                    },
                    session=session,
                )
                if bool(payload.get("ok")):
                    await self._send(ws, make_result(req_id, payload))
                    self._record_audit(session, method, "ok")
                else:
                    await self._send(ws, make_error(req_id, -32006, "Run cancellation failed", payload))
                    self._record_audit(session, method, "blocked", str(payload.get("error") or "run_cancel_failed"))
                return

            if method == "assistant.handle":
                text = params.get("text", "")
                source = params.get("source", "gateway")
                context = params.get("context") if isinstance(params.get("context"), dict) else None
                # Build agent-scoped context if provided
                if context is None:
                    context = {}
                if isinstance(context, dict):
                    agent_key = params.get("agent_key") or context.get("agent_key") or session.get("agent_key") or "primary"
                    agent_role = params.get("agent_role") or context.get("agent_role") or session.get("agent_role")
                    channel = params.get("channel") or context.get("channel") or session.get("channel")
                    user_id = params.get("user_id") or context.get("user_id") or session.get("user_id")
                    session_id = params.get("session_id") or context.get("session_id") or session.get("session_id")
                    context["_untrusted"] = bool(session.get("is_untrusted"))
                    context["remote_untrusted"] = bool(session.get("is_untrusted"))
                    context["_channel"] = channel or session.get("channel")
                    # Channel allowlist gate (pairing/allowlist)
                    if channel and user_id and getattr(get_config(), "channel_pairing_enabled", False):
                        if not self._channel_policy.is_allowed(channel, user_id):
                            code = self._channel_policy.request_pairing_code(channel, user_id)
                            await self._send(
                                ws,
                                make_error(
                                    req_id,
                                    -32002,
                                    "Channel pairing required",
                                    {"pairing_code": code, "channel": channel},
                                ),
                            )
                            self._record_audit(session, method, "blocked", "channel_pairing_required")
                            return
                    try:
                        from chintu_backend.agents.agent_directory import get_agent_directory

                        directory = get_agent_directory()
                        runtime = directory.get_or_create(agent_key, role=agent_role)
                        context.update(
                            directory.build_context(
                                runtime,
                                agent_key,
                                channel=channel,
                                user_id=user_id,
                            )
                        )
                        if session_id:
                            context["session_id"] = session_id
                        elif channel and user_id:
                            context["session_id"] = f"{channel}:{user_id}"
                    except Exception as exc:
                        logger.warning("Gateway agent context build failed: %s", exc)
                response = await asyncio.to_thread(self.command_handler.handle, text, source, context)
                await self._send(ws, make_result(req_id, {"response": response}))
                self._record_audit(session, method, "ok")
                return

            if method == "tools.list":
                await self._send(ws, make_result(req_id, {"tools": self._tools.list_tools()}))
                self._record_audit(session, method, "ok")
                return

            if method.startswith("tools."):
                params = params if isinstance(params, dict) else {}
                result = self._tools.call(method, params, context=session)
                await self._send(ws, make_result(req_id, result))
                status = "ok" if result.get("ok") else "blocked"
                detail = str(result.get("error") or result.get("message") or "")
                self._record_audit(session, method, status, detail=detail)
                return

            if method == "event.emit":
                event_type = params.get("type", "custom")
                payload = params.get("data", {})
                await self._bus.publish_safe(event_type, payload)
                await self._send(ws, make_result(req_id, {"ok": True}))
                self._record_audit(session, method, "ok")
                return

            await self._send(ws, make_error(req_id, -32601, f"Method not found: {method}"))
            self._record_audit(session, method, "error", "method_not_found")
        except Exception as exc:
            await self._send(ws, make_error(req_id, -32000, "Server error", str(exc)))
            self._record_audit(session, method or "unknown", "error", str(exc))

    async def _send(self, ws: WebSocket, payload: Dict[str, Any]) -> None:
        await ws.send_json(payload)

    async def broadcast(self: "GatewayServer", payload: Dict[str, Any]) -> None:
        for ws in list(self._clients.values()):
            try:
                await ws.send_json(payload)
            except Exception:
                continue

    async def start(self: "GatewayServer") -> None:
        config = uvicorn.Config(self.app, host=self.host, port=self.port, log_level="info")
        self._server = uvicorn.Server(config)
        self._server_task = asyncio.create_task(asyncio.to_thread(self._server.run))
        logger.info("Gateway server starting on %s:%s", self.host, self.port)

    async def stop(self: "GatewayServer") -> None:
        if self._server:
            self._server.should_exit = True
        if self._server_task:
            await asyncio.sleep(0)
        logger.info("Gateway server stopped")
