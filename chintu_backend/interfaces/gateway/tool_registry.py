"""Typed tool registry for Gateway RPC (Phase 1.5)."""

from __future__ import annotations

import json
import logging
import re
import urllib.request
from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Any, Callable, Dict, Optional, List

from pydantic import BaseModel, Field, ValidationError

from chintu_backend.search.web_search import get_search_engine
from chintu_backend.automation.parallel_executor import get_parallel_executor
from chintu_backend.brain.memory.conversation_memory import get_conversation_memory
from chintu_backend.core.capabilities import ActionResult
from chintu_backend.core.config import get_config
from chintu_backend.policy.exec_approvals import get_exec_approval_ledger
from chintu_backend.swarm.agent_policy import AgentPolicyStore
from chintu_backend.channels.policy import ChannelPolicyManager

logger = logging.getLogger(__name__)


class ExecRunSchema(BaseModel):
    command: str = Field(..., description="Command to run.")
    cwd: Optional[str] = Field(None, description="Working directory (must be allowed).")
    timeout_seconds: Optional[int] = Field(60, description="Timeout in seconds.")
    confirmed: Optional[bool] = Field(False, description="Whether approval is already granted.")


class ProcessListSchema(BaseModel):
    status: Optional[str] = Field(None, description="Filter by status.")


class ProcessGetSchema(BaseModel):
    task_id: str = Field(..., description="Task id.")


class ProcessCancelSchema(BaseModel):
    task_id: str = Field(..., description="Task id to cancel.")


class SessionsListSchema(BaseModel):
    limit: Optional[int] = Field(20, description="Max sessions.")


class SessionsHistorySchema(BaseModel):
    session_id: str = Field(..., description="Session id.")
    limit: Optional[int] = Field(20, description="Max turns.")


class SessionsSendSchema(BaseModel):
    session_id: str = Field(..., description="Session id.")
    text: str = Field(..., description="Message to send.")


class SessionsSpawnSchema(BaseModel):
    session_id: Optional[str] = Field(None, description="Optional session id.")
    text: str = Field(..., description="Message to send.")


class SessionStatusSchema(BaseModel):
    session_id: Optional[str] = Field(None, description="Optional session id.")


class MemorySearchSchema(BaseModel):
    query: str = Field(..., description="Search query.")
    limit: Optional[int] = Field(5, description="Max results.")


class MemoryGetSchema(BaseModel):
    query: str = Field(..., description="Retrieval query.")
    n_results: Optional[int] = Field(4, description="Number of results.")


class WebSearchSchema(BaseModel):
    query: str = Field(..., description="Search query.")
    max_results: Optional[int] = Field(5, description="Max results.")
    region: Optional[str] = Field("us-en", description="Search region.")


class WebFetchSchema(BaseModel):
    url: str = Field(..., description="URL to fetch.")
    max_chars: Optional[int] = Field(4000, description="Max chars to return.")
    timeout_seconds: Optional[int] = Field(12, description="Timeout in seconds.")


class ConfirmSchema(BaseModel):
    approve: bool = Field(..., description="Approve or deny pending action.")


class CanvasGetSchema(BaseModel):
    board_id: Optional[str] = Field(None, description="Optional board id.")


class CanvasActionSchema(BaseModel):
    action: Dict[str, Any] = Field(..., description="Canvas action payload.")


class ChannelPairSchema(BaseModel):
    channel: str = Field(..., description="Channel name.")
    code: str = Field(..., description="Pairing code.")


class ChannelPolicySchema(BaseModel):
    channel: str = Field(..., description="Channel name.")
    allow: Optional[List[str]] = Field(None, description="Tool allowlist.")
    deny: Optional[List[str]] = Field(None, description="Tool denylist.")
    user_id: Optional[str] = Field(None, description="Optional user id.")


class ChannelAgentSchema(BaseModel):
    channel: str = Field(..., description="Channel name.")
    user_id: str = Field(..., description="User id.")
    agent_key: str = Field(..., description="Agent key.")
    role: Optional[str] = Field(None, description="Agent role.")


class BrowserOpenSchema(BaseModel):
    url: str = Field(..., description="URL to open in browser.")
    profile: Optional[str] = Field(None, description="Optional browser profile name.")


class BrowserSearchSchema(BaseModel):
    query: str = Field(..., description="Search query.")
    profile: Optional[str] = Field(None, description="Optional browser profile name.")


class BrowserReadSchema(BaseModel):
    max_chars: Optional[int] = Field(2000, description="Max chars to return.")
    profile: Optional[str] = Field(None, description="Optional browser profile name.")


class BrowserClickSchema(BaseModel):
    text: str = Field(..., description="Link or button text to click.")
    profile: Optional[str] = Field(None, description="Optional browser profile name.")


class BrowserScreenshotSchema(BaseModel):
    profile: Optional[str] = Field(None, description="Optional browser profile name.")


class BrowserCloseSchema(BaseModel):
    profile: Optional[str] = Field(None, description="Optional browser profile name.")


class BrowserSnapshotSchema(BaseModel):
    max_chars: Optional[int] = Field(2000, description="Max chars to return.")
    profile: Optional[str] = Field(None, description="Optional browser profile name.")


class BrowserActSchema(BaseModel):
    ref: str = Field(..., description="Element ref from structured snapshot.")
    action: str = Field("click", description="Action: click|fill|type|press|select|check|uncheck|hover|focus|scroll")
    value: Optional[str] = Field(None, description="Value for fill/type/press/select.")
    screenshot_after: Optional[bool] = Field(True, description="Capture screenshot after the action.")
    profile: Optional[str] = Field(None, description="Optional browser profile name.")


class McpListSchema(BaseModel):
    refresh: Optional[bool] = Field(False, description="Force refresh of MCP tool metadata.")


class McpCallSchema(BaseModel):
    tool_name: str = Field(..., description="MCP tool name. Supports server:tool syntax.")
    arguments: Optional[Dict[str, Any]] = Field(None, description="Tool arguments JSON object.")
    server_name: Optional[str] = Field(None, description="Optional explicit MCP server name.")


@dataclass
class ToolSpec:
    name: str
    group: str
    schema: type[BaseModel]
    handler: Callable[[BaseModel, Dict[str, Any]], Dict[str, Any]]


class GatewayToolRegistry:
    def __init__(self, command_handler):
        self.command_handler = command_handler
        self._tools: Dict[str, ToolSpec] = {}
        self._policy_store = AgentPolicyStore()
        self._channel_policy = ChannelPolicyManager()
        self._register_core()

    def list_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": spec.name,
                "group": spec.group,
                "schema": spec.schema.model_json_schema(),
            }
            for spec in self._tools.values()
        ]

    def call(self, name: str, params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        spec = self._tools.get(name)
        if not spec:
            return {"ok": False, "error": f"Unknown tool: {name}"}
        if not self._policy_allows(spec, context or {}):
            return {"ok": False, "error": "Tool blocked by agent policy"}
        try:
            validated = spec.schema(**(params or {}))
        except ValidationError as exc:
            return {"ok": False, "error": "Validation error", "details": json.loads(exc.json())}
        try:
            return spec.handler(validated, params or {})
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _policy_allows(self, spec: ToolSpec, context: Dict[str, Any]) -> bool:
        if self._blocked_by_untrusted_profile(spec, context):
            return False
        role = (context.get("agent_role") or context.get("_agent_role") or "default").lower()
        profile = self._policy_store.get_profile(role)
        allow = [a.lower() for a in profile.tool_allowlist]
        deny = [d.lower() for d in profile.tool_denylist]
        channel = (context.get("channel") or context.get("_channel") or "").lower()
        user_id = context.get("user_id") or context.get("_user_id")
        channel_policy = None
        if channel:
            channel_policy = self._channel_policy.get_tool_policy(channel, user_id=user_id)
        channel_allow = [a.lower() for a in (channel_policy.get("allow", []) if channel_policy else [])]
        channel_deny = [d.lower() for d in (channel_policy.get("deny", []) if channel_policy else [])]

        def _match(pattern: str, name: str, group: str) -> bool:
            if pattern.startswith("group:"):
                return fnmatch(f"group:{group}", pattern)
            return fnmatch(name, pattern)

        tool_name = spec.name.lower()
        group_name = spec.group.lower()
        for pattern in channel_deny:
            if _match(pattern, tool_name, group_name):
                return False
        for pattern in deny:
            if _match(pattern, tool_name, group_name):
                return False
        if channel_allow:
            return any(_match(pattern, tool_name, group_name) for pattern in channel_allow)
        if allow:
            return any(_match(pattern, tool_name, group_name) for pattern in allow)
        return True

    def _blocked_by_untrusted_profile(self, spec: ToolSpec, context: Dict[str, Any]) -> bool:
        config = get_config()
        explicit_trust = bool(context.get("trusted") or context.get("_trusted"))
        if explicit_trust:
            return False
        channel = str(context.get("channel") or context.get("_channel") or "").lower()
        remote_untrusted = bool(context.get("is_untrusted") or context.get("_untrusted") or context.get("remote_untrusted"))
        channel_untrusted = channel in {str(c).lower() for c in (config.gateway_untrusted_channels or [])}
        if not (remote_untrusted or channel_untrusted):
            return False

        blocked_groups = {str(g).lower() for g in (config.gateway_untrusted_group_denylist or [])}
        return spec.group.lower() in blocked_groups

    # ------------------------------------------------------------------
    # Core tool handlers
    # ------------------------------------------------------------------
    def _register_core(self) -> None:
        self._register("tools.exec.run", "runtime", ExecRunSchema, self._exec_run)
        self._register("tools.process.list", "runtime", ProcessListSchema, self._process_list)
        self._register("tools.process.get", "runtime", ProcessGetSchema, self._process_get)
        self._register("tools.process.cancel", "runtime", ProcessCancelSchema, self._process_cancel)
        self._register("tools.sessions.list", "sessions", SessionsListSchema, self._sessions_list)
        self._register("tools.sessions.history", "sessions", SessionsHistorySchema, self._sessions_history)
        self._register("tools.sessions.send", "sessions", SessionsSendSchema, self._sessions_send)
        self._register("tools.sessions.spawn", "sessions", SessionsSpawnSchema, self._sessions_spawn)
        self._register("tools.session.status", "sessions", SessionStatusSchema, self._session_status)
        self._register("tools.memory.search", "memory", MemorySearchSchema, self._memory_search)
        self._register("tools.memory.get", "memory", MemoryGetSchema, self._memory_get)
        self._register("tools.web.search", "web", WebSearchSchema, self._web_search)
        self._register("tools.web.fetch", "web", WebFetchSchema, self._web_fetch)
        self._register("tools.confirm", "runtime", ConfirmSchema, self._confirm)
        self._register("tools.canvas.get", "canvas", CanvasGetSchema, self._canvas_get)
        self._register("tools.canvas.action", "canvas", CanvasActionSchema, self._canvas_action)
        self._register("tools.channel.pair", "channels", ChannelPairSchema, self._channel_pair)
        self._register("tools.channel.policy.set", "channels", ChannelPolicySchema, self._channel_policy_set)
        self._register("tools.channel.agent.set", "channels", ChannelAgentSchema, self._channel_agent_set)
        self._register("tools.browser.open", "browser", BrowserOpenSchema, self._browser_open)
        self._register("tools.browser.search", "browser", BrowserSearchSchema, self._browser_search)
        self._register("tools.browser.read", "browser", BrowserReadSchema, self._browser_read)
        self._register("tools.browser.click", "browser", BrowserClickSchema, self._browser_click)
        self._register("tools.browser.screenshot", "browser", BrowserScreenshotSchema, self._browser_screenshot)
        self._register("tools.browser.close", "browser", BrowserCloseSchema, self._browser_close)
        self._register("tools.browser.snapshot", "browser", BrowserSnapshotSchema, self._browser_snapshot)
        self._register("tools.browser.act", "browser", BrowserActSchema, self._browser_act)
        self._register("tools.mcp.list", "mcp", McpListSchema, self._mcp_list)
        self._register("tools.mcp.call", "mcp", McpCallSchema, self._mcp_call)

    def _register(self, name: str, group: str, schema: type[BaseModel], handler: Callable[[BaseModel, Dict[str, Any]], Dict[str, Any]]) -> None:
        self._tools[name] = ToolSpec(name=name, group=group, schema=schema, handler=handler)

    def _exec_run(self, params: ExecRunSchema, _raw: Dict[str, Any]) -> Dict[str, Any]:
        registry = self.command_handler.capability_registry
        cap = registry.get("terminal_exec")
        if not cap:
            return {"ok": False, "error": "terminal_exec capability not available"}
        config = get_config()
        ledger = get_exec_approval_ledger() if config.exec_approval_enabled else None
        approved = ledger.is_approved(params.command, params.cwd) if ledger else False
        context = {
            "_terminal_exec_payload": {
                "command": params.command,
                "cwd": params.cwd,
                "timeout": params.timeout_seconds,
            }
        }
        if params.confirmed or approved:
            context["_confirmed"] = True
        if params.confirmed and ledger:
            ledger.record_approval(params.command, params.cwd, config.exec_approval_ttl_minutes)
        result: ActionResult = registry.execute(cap, params.command, context)
        if result.requires_confirmation:
            return {"ok": False, "requires_confirmation": True, "message": result.message}
        return {"ok": result.success, "message": result.message, "data": result.data}

    def _process_list(self, params: ProcessListSchema, _raw: Dict[str, Any]) -> Dict[str, Any]:
        executor = get_parallel_executor()
        tasks = executor.list_tasks()
        if params.status:
            tasks = [t for t in tasks if t.status.value == params.status]
        payload = [
            {
                "id": t.id,
                "name": t.name,
                "status": t.status.value,
                "duration": t.duration,
            }
            for t in tasks
        ]
        return {"ok": True, "tasks": payload}

    def _process_get(self, params: ProcessGetSchema, _raw: Dict[str, Any]) -> Dict[str, Any]:
        task = get_parallel_executor().get_task(params.task_id)
        if not task:
            return {"ok": False, "error": "Task not found"}
        return {
            "ok": True,
            "task": {
                "id": task.id,
                "name": task.name,
                "status": task.status.value,
                "result": task.result,
                "error": task.error,
                "duration": task.duration,
            },
        }

    def _process_cancel(self, params: ProcessCancelSchema, _raw: Dict[str, Any]) -> Dict[str, Any]:
        ok = get_parallel_executor().cancel(params.task_id)
        return {"ok": ok}

    def _sessions_list(self, params: SessionsListSchema, _raw: Dict[str, Any]) -> Dict[str, Any]:
        try:
            from chintu_backend.core.session_manager import get_session_manager

            mgr = get_session_manager()
            sessions = mgr.list_sessions(active_only=True)
            if params.limit:
                sessions = sessions[: params.limit]
            payload = [
                {
                    "session_id": s.id,
                    "started": s.created_at.isoformat(),
                    "updated_at": s.updated_at.isoformat(),
                    "type": s.type.value,
                    "visibility": s.visibility.value,
                }
                for s in sessions
            ]
            return {"ok": True, "sessions": payload}
        except Exception:
            memory = get_conversation_memory()
            sessions = list(memory._history)
            current = memory._current_session
            if current:
                sessions.append(
                    {
                        "session_id": current.session_id,
                        "started": current.started,
                        "turns": [],
                    }
                )
            sessions = sessions[-(params.limit or 20):]
            return {"ok": True, "sessions": [{"session_id": s.get("session_id"), "started": s.get("started")} for s in sessions]}

    def _sessions_history(self, params: SessionsHistorySchema, _raw: Dict[str, Any]) -> Dict[str, Any]:
        try:
            from chintu_backend.core.session_manager import get_session_manager

            mgr = get_session_manager()
            turns = mgr.get_history(params.session_id, limit=params.limit or 20)
            if turns:
                return {"ok": True, "turns": turns}
        except Exception:
            pass

        memory = get_conversation_memory()
        if memory._current_session and memory._current_session.session_id == params.session_id:
            turns = memory._current_session.turns[-(params.limit or 20):]
            return {"ok": True, "turns": [t.__dict__ for t in turns]}
        for s in memory._history:
            if s.get("session_id") == params.session_id:
                turns = s.get("turns", [])[-(params.limit or 20):]
                return {"ok": True, "turns": turns}
        return {"ok": False, "error": "Session not found"}

    def _sessions_send(self, params: SessionsSendSchema, _raw: Dict[str, Any]) -> Dict[str, Any]:
        response = self.command_handler.handle(params.text, source="session", context={"session_id": params.session_id})
        return {"ok": True, "response": response}

    def _sessions_spawn(self, params: SessionsSpawnSchema, _raw: Dict[str, Any]) -> Dict[str, Any]:
        session_id = params.session_id or f"spawn:{params.text[:12]}"
        response = self.command_handler.handle(params.text, source="session", context={"session_id": session_id})
        return {"ok": True, "session_id": session_id, "response": response}

    def _session_status(self, params: SessionStatusSchema, _raw: Dict[str, Any]) -> Dict[str, Any]:
        try:
            from chintu_backend.core.session_manager import get_session_manager

            mgr = get_session_manager()
            session_id = params.session_id
            if session_id:
                s = mgr.get_session(session_id)
                if s:
                    return {
                        "ok": True,
                        "session": {
                            "session_id": s.id,
                            "started": s.created_at.isoformat(),
                            "updated_at": s.updated_at.isoformat(),
                            "type": s.type.value,
                            "visibility": s.visibility.value,
                        },
                    }
        except Exception:
            pass

        memory = get_conversation_memory()
        session_id = params.session_id or (memory._current_session.session_id if memory._current_session else None)
        if not session_id:
            return {"ok": False, "error": "No session"}
        if memory._current_session and memory._current_session.session_id == session_id:
            s = memory._current_session
            return {"ok": True, "session": {"session_id": s.session_id, "started": s.started, "turns": len(s.turns)}}
        for s in memory._history:
            if s.get("session_id") == session_id:
                return {"ok": True, "session": {"session_id": s.get("session_id"), "started": s.get("started"), "turns": len(s.get("turns", []))}}
        return {"ok": False, "error": "Session not found"}

    def _memory_search(self, params: MemorySearchSchema, _raw: Dict[str, Any]) -> Dict[str, Any]:
        mem = getattr(self.command_handler, "memory_manager", None)
        if not mem:
            return {"ok": False, "error": "Memory manager unavailable"}
        results = mem.search(params.query, limit=params.limit or 5)
        return {"ok": True, "results": results}

    def _memory_get(self, params: MemoryGetSchema, _raw: Dict[str, Any]) -> Dict[str, Any]:
        mem = getattr(self.command_handler, "memory_manager", None)
        if not mem:
            return {"ok": False, "error": "Memory manager unavailable"}
        context = mem.retrieve_context(params.query, n_results=params.n_results or 4)
        return {"ok": True, "context": context}

    def _web_search(self, params: WebSearchSchema, _raw: Dict[str, Any]) -> Dict[str, Any]:
        engine = get_search_engine()
        if not engine.is_available:
            return {"ok": False, "error": "Web search not available (install ddgs)"}
        results = engine.search(params.query, max_results=params.max_results or 5, region=params.region or "us-en")
        return {"ok": True, "results": [r.__dict__ for r in results]}

    def _web_fetch(self, params: WebFetchSchema, _raw: Dict[str, Any]) -> Dict[str, Any]:
        try:
            req = urllib.request.Request(params.url, headers={"User-Agent": "Chintu/1.0"})
            with urllib.request.urlopen(req, timeout=params.timeout_seconds or 12) as resp:
                raw = resp.read().decode("utf-8", errors="ignore")
            text = re.sub(r"<[^>]+>", " ", raw)
            text = re.sub(r"\s+", " ", text).strip()
            return {"ok": True, "content": text[: (params.max_chars or 4000)]}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _confirm(self, params: ConfirmSchema, _raw: Dict[str, Any]) -> Dict[str, Any]:
        if params.approve:
            result = self.command_handler.action_dispatcher.confirm_pending()
            if result:
                return {"ok": True, "result": result.message, "success": result.success}
            return {"ok": False, "error": "No pending confirmation"}
        self.command_handler.action_dispatcher.cancel_pending()
        return {"ok": True, "result": "Cancelled"}

    def _canvas_get(self, params: CanvasGetSchema, _raw: Dict[str, Any]) -> Dict[str, Any]:
        from chintu_backend.canvas import get_canvas_manager

        manager = get_canvas_manager()
        if params.board_id:
            board = manager.store.get_board(params.board_id)
            return {"ok": True, "board": board.to_dict() if board else None}
        return {"ok": True, "canvas": manager.store.to_dict()}

    def _canvas_action(self, params: CanvasActionSchema, _raw: Dict[str, Any]) -> Dict[str, Any]:
        from chintu_backend.canvas import get_canvas_manager

        manager = get_canvas_manager()
        ok = manager.apply_action(params.action)
        return {"ok": ok}

    def _channel_pair(self, params: ChannelPairSchema, _raw: Dict[str, Any]) -> Dict[str, Any]:
        policy = ChannelPolicyManager()
        user_id = policy.approve_code(params.channel, params.code)
        if not user_id:
            return {"ok": False, "error": "Invalid or expired code"}
        return {"ok": True, "user_id": user_id}

    def _channel_policy_set(self, params: ChannelPolicySchema, _raw: Dict[str, Any]) -> Dict[str, Any]:
        policy = ChannelPolicyManager()
        policy.set_tool_policy(params.channel, allow=params.allow, deny=params.deny, user_id=params.user_id)
        return {"ok": True}

    def _channel_agent_set(self, params: ChannelAgentSchema, _raw: Dict[str, Any]) -> Dict[str, Any]:
        policy = ChannelPolicyManager()
        policy.set_agent_profile(params.channel, params.user_id, params.agent_key, params.role)
        return {"ok": True}

    def _browser_open(self, params: BrowserOpenSchema, _raw: Dict[str, Any]) -> Dict[str, Any]:
        from chintu_backend.automation.browser.browser_controller import get_browser_controller

        controller = get_browser_controller(headless=False, profile_name=params.profile)
        try:
            page_info = controller.open_url(params.url)
            return {
                "ok": True,
                "message": f"Opened {page_info.title}",
                "data": {"url": page_info.url, "title": page_info.title},
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _browser_search(self, params: BrowserSearchSchema, _raw: Dict[str, Any]) -> Dict[str, Any]:
        from chintu_backend.automation.browser.browser_controller import get_browser_controller

        controller = get_browser_controller(headless=False, profile_name=params.profile)
        try:
            page_info = controller.search_google(params.query)
            return {
                "ok": True,
                "message": f"Searched for {params.query}",
                "data": {"url": page_info.url, "title": page_info.title, "preview": page_info.text_preview},
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _browser_read(self, params: BrowserReadSchema, _raw: Dict[str, Any]) -> Dict[str, Any]:
        from chintu_backend.automation.browser.browser_controller import get_browser_controller

        controller = get_browser_controller(headless=False, profile_name=params.profile)
        if not controller.is_open:
            return {"ok": False, "error": "No browser page is open"}
        content = controller.get_page_content(max_length=params.max_chars or 2000)
        return {"ok": True, "content": content}

    def _browser_click(self, params: BrowserClickSchema, _raw: Dict[str, Any]) -> Dict[str, Any]:
        from chintu_backend.automation.browser.browser_controller import get_browser_controller

        controller = get_browser_controller(headless=False, profile_name=params.profile)
        if not controller.is_open:
            return {"ok": False, "error": "No browser page is open"}
        ok = controller.click_link(params.text)
        if ok:
            page_info = controller.get_page_info()
            return {"ok": True, "message": f"Clicked {params.text}", "data": {"url": page_info.url if page_info else ""}}
        return {"ok": False, "error": "Click failed"}

    def _browser_screenshot(self, _params: BrowserScreenshotSchema, _raw: Dict[str, Any]) -> Dict[str, Any]:
        from chintu_backend.automation.browser.browser_controller import get_browser_controller

        controller = get_browser_controller(headless=False, profile_name=_params.profile)
        if not controller.is_open:
            return {"ok": False, "error": "No browser page is open"}
        path = controller.take_screenshot()
        return {"ok": True, "path": path}

    def _browser_close(self, _params: BrowserCloseSchema, _raw: Dict[str, Any]) -> Dict[str, Any]:
        from chintu_backend.automation.browser.browser_controller import get_browser_controller

        controller = get_browser_controller(headless=False, profile_name=_params.profile)
        controller.close()
        return {"ok": True}

    def _browser_snapshot(self, params: BrowserSnapshotSchema, _raw: Dict[str, Any]) -> Dict[str, Any]:
        from chintu_backend.automation.browser.browser_controller import get_browser_controller

        controller = get_browser_controller(headless=False, profile_name=params.profile)
        if not controller.is_open:
            return {"ok": False, "error": "No browser page is open"}
        try:
            page_info = controller.get_page_info()
            content = controller.get_page_content(max_length=params.max_chars or 2000)
            screenshot = controller.take_screenshot()
            refs = []
            summary = ""
            try:
                listing = controller.list_interactive_elements(max_elements=60)
                refs = listing.get("elements") or []
                summary = listing.get("summary") or ""
            except Exception:
                refs = []
                summary = ""
            return {
                "ok": True,
                "snapshot": {
                    "title": page_info.title,
                    "url": page_info.url,
                    "content": content,
                    "screenshot": str(screenshot),
                    "refs": refs,
                    "refs_summary": summary[:2000],
                },
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _browser_act(self, params: BrowserActSchema, _raw: Dict[str, Any]) -> Dict[str, Any]:
        from chintu_backend.automation.browser.browser_controller import get_browser_controller

        controller = get_browser_controller(headless=False, profile_name=params.profile)
        if not controller.is_open:
            return {"ok": False, "error": "No browser page is open"}

        acted = controller.act_by_ref(
            params.ref,
            action=params.action,
            value=params.value,
            screenshot_after=bool(params.screenshot_after),
        )
        if not acted.get("success"):
            return {"ok": False, "error": acted.get("error") or "Browser action failed"}

        return {"ok": True, "data": acted, "path": acted.get("screenshot")}

    def _mcp_list(self, params: McpListSchema, _raw: Dict[str, Any]) -> Dict[str, Any]:
        from chintu_backend.interfaces.mcp.registry import get_mcp_registry

        registry = get_mcp_registry()
        ok, message = registry.start()
        if not ok and "already started" not in str(message).lower():
            return {"ok": False, "error": message}

        tools = registry.list_tools(refresh=bool(params.refresh))
        payload = [
            {
                "server": t.server,
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in tools
        ]
        return {"ok": True, "tools": payload}

    def _mcp_call(self, params: McpCallSchema, _raw: Dict[str, Any]) -> Dict[str, Any]:
        from chintu_backend.interfaces.mcp.registry import get_mcp_registry

        registry = get_mcp_registry()
        ok, message = registry.start()
        if not ok and "already started" not in str(message).lower():
            return {"ok": False, "error": message}

        success, msg, result = registry.call_tool(
            params.tool_name,
            arguments=params.arguments or {},
            server_name=params.server_name,
        )
        return {
            "ok": bool(success),
            "message": msg,
            "result": result,
        }
