"""Control-plane snapshot builder for remote operator dashboards."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_str(value: Any, limit: int = 300) -> str:
    text = str(value or "").strip()
    if len(text) > max(0, int(limit)):
        return text[: max(0, int(limit) - 3)] + "..."
    return text


def _parse_ts(value: Any) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None


def _bucket_start(ts: datetime, bucket_minutes: int) -> datetime:
    b = max(1, int(bucket_minutes))
    minute = (int(ts.minute) // b) * b
    return ts.replace(minute=minute, second=0, microsecond=0)


def _tail_jsonl(path: Path, max_lines: int = 200) -> List[Dict[str, Any]]:
    try:
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()[-max(1, int(max_lines)) :]
    except Exception:
        return []
    rows: List[Dict[str, Any]] = []
    for raw in lines:
        raw = (raw or "").strip()
        if not raw:
            continue
        try:
            item = json.loads(raw)
        except Exception:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _extract_run_artifacts(run_id: str, runs_root: Path, receipt_path: str = "", max_items: int = 30) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    seen: set[str] = set()
    run_dir = runs_root / str(run_id)

    def _add(kind: str, value: str, label: str = "") -> None:
        raw = _safe_str(value, 600)
        if not raw or raw in seen:
            return
        seen.add(raw)
        out.append({"kind": _safe_str(kind, 40), "value": raw, "label": _safe_str(label, 120)})

    if receipt_path:
        _add("receipt", receipt_path, "receipt.md")

    events_path = run_dir / "events.jsonl"
    if events_path.exists():
        _add("events", str(events_path), "events.jsonl")

    for row in _tail_jsonl(events_path, max_lines=220):
        step = row.get("step") if isinstance(row.get("step"), dict) else {}
        evidence = step.get("evidence") if isinstance(step.get("evidence"), list) else []
        for ev in evidence:
            if not isinstance(ev, dict):
                continue
            kind = str(ev.get("kind") or "artifact").strip().lower()
            value = str(ev.get("value") or "").strip()
            summary = str(ev.get("summary") or "").strip()
            if not value:
                continue
            if kind in {"path", "receipt", "report", "file"}:
                _add("file", value, summary or Path(value).name)
            elif kind in {"url", "link"}:
                _add("url", value, summary or "link")
            elif kind in {"screenshot", "image"}:
                _add("image", value, summary or Path(value).name)
            else:
                if value.startswith(("http://", "https://")):
                    _add("url", value, summary or "link")
                elif "/" in value or "\\" in value:
                    _add("file", value, summary or Path(value).name)
        event = row.get("event") if isinstance(row.get("event"), dict) else {}
        artifacts = event.get("artifacts") if isinstance(event.get("artifacts"), list) else []
        for item in artifacts:
            val = str(item or "").strip()
            if val:
                _add("artifact", val, Path(val).name if ("/" in val or "\\" in val) else "artifact")

    return out[: max(1, int(max_items))]


def build_run_board(
    *,
    run_summary: Dict[str, Any],
    runs_root: Path,
    limit_runs: int = 30,
) -> Dict[str, Any]:
    runs = run_summary.get("runs") if isinstance(run_summary.get("runs"), list) else []
    lanes = run_summary.get("lanes") if isinstance(run_summary.get("lanes"), dict) else {}
    pending_approval_run_id = str(run_summary.get("pending_confirmation_run_id") or "").strip()
    pending_input_run_id = str(run_summary.get("pending_input_run_id") or "").strip()

    status_counts = Counter()
    cards: List[Dict[str, Any]] = []
    for row in runs[: max(1, int(limit_runs))]:
        if not isinstance(row, dict):
            continue
        status = _safe_str(row.get("status") or "unknown", 40)
        status_counts[status] += 1
        run_id = _safe_str(row.get("id") or "", 120)
        receipt_path = _safe_str(row.get("receipt_path") or "", 600)
        cards.append(
            {
                "run_id": run_id,
                "session_id": _safe_str(row.get("session_id") or "", 80),
                "source": _safe_str(row.get("source") or "", 40),
                "status": status,
                "outcome_label": _safe_str(row.get("outcome_label") or "", 80),
                "created_at": _safe_str(row.get("created_at") or "", 80),
                "started_at": _safe_str(row.get("started_at") or "", 80),
                "ended_at": _safe_str(row.get("ended_at") or "", 80),
                "result_summary": _safe_str(row.get("result_summary") or "", 220),
                "is_waiting_approval": bool(run_id and run_id == pending_approval_run_id),
                "is_waiting_input": bool(run_id and run_id == pending_input_run_id),
                "artifact_links": _extract_run_artifacts(run_id, runs_root, receipt_path=receipt_path, max_items=24),
            }
        )

    return {
        "counts": {
            "queued": int(status_counts.get("queued", 0)),
            "running": int(status_counts.get("running", 0)),
            "waiting_approval": int(status_counts.get("waiting_approval", 0)),
            "waiting_input": int(status_counts.get("waiting_input", 0)),
            "completed": int(status_counts.get("completed", 0)),
            "failed": int(status_counts.get("failed", 0)),
            "cancelled": int(status_counts.get("cancelled", 0)),
            "timed_out": int(status_counts.get("timed_out", 0)),
            "total": int(len(cards)),
        },
        "lanes": lanes,
        "pending_confirmation_run_id": pending_approval_run_id,
        "pending_input_run_id": pending_input_run_id,
        "runs": cards,
    }


def _get_dispatcher_pending(command_handler) -> Dict[str, Any]:
    try:
        dispatcher = getattr(command_handler, "action_dispatcher", None)
        if dispatcher:
            pending = dispatcher.get_pending_confirmation() or {}
            if isinstance(pending, dict):
                return pending
    except Exception:
        pass
    return {}


def _get_orchestrator_pending() -> List[Dict[str, Any]]:
    try:
        from chintu_backend.orchestrator import get_orchestrator_manager

        manager = get_orchestrator_manager()
        overview = manager.get_overview(limit=50)
        items = overview.get("pending_approvals") if isinstance(overview, dict) else []
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    except Exception:
        pass
    return []


def _build_approval_items(
    *,
    command_handler,
    run_summary: Dict[str, Any],
    session: Optional[Dict[str, Any]],
    channel_policy,
    limit: int = 30,
) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    pending = _get_dispatcher_pending(command_handler)
    if bool(pending.get("pending")):
        items.append(
            {
                "id": "dispatcher_pending",
                "kind": "action",
                "capability": _safe_str(pending.get("capability") or "", 120),
                "message": _safe_str(pending.get("message") or "", 400),
                "confirmation_type": _safe_str(pending.get("confirmation_type") or "", 80),
                "run_id": _safe_str(run_summary.get("pending_confirmation_run_id") or "", 120),
                "decision_options": ["allow_once", "whitelist", "deny"],
            }
        )

    for approval in _get_orchestrator_pending():
        step_id = _safe_str(approval.get("step_id") or approval.get("id") or "", 120)
        items.append(
            {
                "id": step_id or f"orchestrator_{len(items)+1}",
                "kind": "orchestrator_step",
                "step_id": step_id,
                "project_id": _safe_str(approval.get("project_id") or "", 120),
                "reason": _safe_str(approval.get("reason") or "", 320),
                "created_at": _safe_str(approval.get("created_at") or "", 80),
                "decision_options": ["allow_once", "deny"],
            }
        )

    recent_action_approvals: List[Dict[str, Any]] = []
    recent_exec_approvals: List[Dict[str, Any]] = []
    try:
        from chintu_backend.policy.action_approvals import get_action_approval_ledger

        recent_action_approvals = list(get_action_approval_ledger().recent(limit=min(limit, 40)))
    except Exception:
        recent_action_approvals = []
    try:
        from chintu_backend.policy.exec_approvals import get_exec_approval_ledger

        ledger = get_exec_approval_ledger()
        # best-effort introspection; no public recent() API.
        rows = []
        try:
            ledger._load()  # noqa: SLF001
            now = datetime.now(timezone.utc).timestamp()
            for item in list(getattr(ledger, "_cache", {}).values()):  # noqa: SLF001
                expires_at = float(getattr(item, "expires_at", 0.0) or 0.0)
                if expires_at <= now:
                    continue
                rows.append({"command_hash": str(getattr(item, "command_hash", "") or ""), "expires_at": expires_at})
        except Exception:
            rows = []
        rows.sort(key=lambda r: float(r.get("expires_at", 0.0)), reverse=True)
        recent_exec_approvals = rows[: min(limit, 40)]
    except Exception:
        recent_exec_approvals = []

    channel_tool_policy: Dict[str, Any] = {}
    session_channel = str((session or {}).get("channel") or "").strip().lower()
    session_user = (session or {}).get("user_id")
    if session_channel and session_user is not None and channel_policy is not None:
        try:
            channel_tool_policy = channel_policy.get_tool_policy(session_channel, session_user) or {}
        except Exception:
            channel_tool_policy = {}

    return {
        "pending": items[: max(1, int(limit))],
        "pending_count": len(items),
        "recent_action_approvals": recent_action_approvals,
        "recent_exec_approvals": recent_exec_approvals,
        "channel_tool_policy": channel_tool_policy,
    }


def _build_telemetry(command_handler) -> Dict[str, Any]:
    resource = {}
    gpu_inventory: Dict[str, Any] = {}
    provider_health = {}
    routing_summary = {}
    try:
        from chintu_backend.core.resource_manager import get_resource_manager

        status = get_resource_manager().get_status()
        resource = {
            "cpu_percent": float(getattr(status, "cpu_percent", 0.0) or 0.0),
            "ram_percent": float(getattr(status, "ram_percent", 0.0) or 0.0),
            "ram_available_mb": int(getattr(status, "ram_available_mb", 0) or 0),
            "gpu_pressure": bool(getattr(status, "gpu_pressure", False)),
            "recommendation": _safe_str(getattr(status, "recommendation", "") or "", 240),
            "vram": (
                getattr(status, "vram").to_dict()
                if hasattr(getattr(status, "vram", None), "to_dict")
                else {}
            ),
        }
    except Exception:
        resource = {}
    try:
        from chintu_backend.core.gpu_resource_manager import get_gpu_resource_manager

        gpu_inventory = get_gpu_resource_manager().capture_snapshot()
    except Exception:
        gpu_inventory = {}

    router = getattr(command_handler, "router", None)
    if router:
        try:
            provider_health = router.get_provider_health()
        except Exception:
            provider_health = {}
        try:
            routing_summary = router.get_arbiter_telemetry_summary(hours=24, limit=1200)
        except Exception:
            routing_summary = {}
    provider_trends = _build_provider_trends(
        router=router,
        provider_health=provider_health,
        hours=6,
        bucket_minutes=30,
        limit=2400,
    )

    return {
        "resource": resource,
        "gpu_inventory": gpu_inventory,
        "provider_health": provider_health,
        "routing_telemetry": routing_summary,
        "provider_trends": provider_trends,
    }


def _build_provider_trends(
    *,
    router,
    provider_health: Dict[str, Any],
    hours: int = 6,
    bucket_minutes: int = 30,
    limit: int = 2400,
) -> Dict[str, Any]:
    if not router:
        return {
            "window_hours": int(hours),
            "bucket_minutes": int(bucket_minutes),
            "providers": {},
        }
    store = getattr(router, "arbiter_telemetry", None)
    if not store or not hasattr(store, "read_recent"):
        return {
            "window_hours": int(hours),
            "bucket_minutes": int(bucket_minutes),
            "providers": {},
        }

    try:
        records = list(store.read_recent(limit=max(100, int(limit))) or [])
    except Exception:
        records = []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, int(hours)))
    stats: Dict[str, Dict[datetime, Dict[str, Any]]] = defaultdict(
        lambda: defaultdict(
            lambda: {
                "attempts": 0,
                "success": 0,
                "failed": 0,
                "latency_total_ms": 0.0,
                "latency_count": 0,
            }
        )
    )
    providers_seen: set[str] = set()

    for row in records:
        if not isinstance(row, dict):
            continue
        if str(row.get("event") or "").strip().lower() != "provider_attempt":
            continue
        ts = _parse_ts(row.get("ts"))
        if not ts or ts < cutoff:
            continue
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        provider = str(payload.get("provider") or "unknown").strip().lower()
        if not provider:
            provider = "unknown"
        providers_seen.add(provider)
        bucket = _bucket_start(ts, bucket_minutes=max(1, int(bucket_minutes)))
        node = stats[provider][bucket]
        node["attempts"] += 1
        success = bool(payload.get("success"))
        if success:
            node["success"] += 1
        else:
            node["failed"] += 1
        try:
            latency_ms = float(payload.get("latency_ms", 0.0) or 0.0)
        except Exception:
            latency_ms = 0.0
        if latency_ms > 0:
            node["latency_total_ms"] += latency_ms
            node["latency_count"] += 1

    if isinstance(provider_health, dict):
        providers_seen.update(str(k).strip().lower() for k in provider_health.keys() if str(k).strip())

    provider_rows: Dict[str, Dict[str, Any]] = {}
    for provider in sorted(providers_seen):
        buckets = stats.get(provider, {})
        bucket_keys = sorted(buckets.keys())
        points: List[Dict[str, Any]] = []
        success_rate_series: List[float] = []
        attempts_series: List[int] = []
        latency_series: List[float] = []
        total_attempts = 0
        total_success = 0
        total_failed = 0
        for key in bucket_keys:
            node = buckets.get(key, {})
            attempts = int(node.get("attempts", 0) or 0)
            success = int(node.get("success", 0) or 0)
            failed = int(node.get("failed", 0) or 0)
            total_attempts += attempts
            total_success += success
            total_failed += failed
            success_rate = (float(success) / float(attempts)) if attempts > 0 else 0.0
            avg_latency_ms = 0.0
            lat_count = int(node.get("latency_count", 0) or 0)
            if lat_count > 0:
                avg_latency_ms = float(node.get("latency_total_ms", 0.0) or 0.0) / float(lat_count)
            success_rate_series.append(round(success_rate, 3))
            attempts_series.append(attempts)
            latency_series.append(round(avg_latency_ms, 2))
            points.append(
                {
                    "bucket_start": key.isoformat().replace("+00:00", "Z"),
                    "attempts": attempts,
                    "success": success,
                    "failed": failed,
                    "success_rate": round(success_rate, 3),
                    "avg_latency_ms": round(avg_latency_ms, 2),
                }
            )
        health = provider_health.get(provider, {}) if isinstance(provider_health, dict) else {}
        latest_available = bool(health.get("available")) if isinstance(health, dict) else False
        latest_reason = str(health.get("reason") or "").strip() if isinstance(health, dict) else ""
        provider_rows[provider] = {
            "points": points,
            "success_rate_series": success_rate_series,
            "attempt_series": attempts_series,
            "latency_series": latency_series,
            "totals": {
                "attempts": total_attempts,
                "success": total_success,
                "failed": total_failed,
                "success_rate": round((float(total_success) / float(total_attempts)), 3) if total_attempts > 0 else 0.0,
            },
            "latest_available": latest_available,
            "latest_reason": latest_reason,
        }

    return {
        "window_hours": int(hours),
        "bucket_minutes": int(bucket_minutes),
        "providers": provider_rows,
    }


def build_control_plane_snapshot(
    *,
    command_handler: Any,
    run_summary: Dict[str, Any],
    session: Optional[Dict[str, Any]],
    channel_policy: Any,
    runs_root: Path,
    limit_runs: int = 30,
    limit_approvals: int = 30,
) -> Dict[str, Any]:
    run_board = build_run_board(run_summary=run_summary, runs_root=runs_root, limit_runs=limit_runs)
    approvals = _build_approval_items(
        command_handler=command_handler,
        run_summary=run_summary,
        session=session,
        channel_policy=channel_policy,
        limit=limit_approvals,
    )
    telemetry = _build_telemetry(command_handler)

    artifact_recent: List[Dict[str, Any]] = []
    for run in run_board.get("runs", [])[:15]:
        if not isinstance(run, dict):
            continue
        run_id = _safe_str(run.get("run_id") or "", 120)
        for item in run.get("artifact_links", []) or []:
            if not isinstance(item, dict):
                continue
            artifact_recent.append(
                {
                    "run_id": run_id,
                    "kind": _safe_str(item.get("kind") or "", 40),
                    "value": _safe_str(item.get("value") or "", 600),
                    "label": _safe_str(item.get("label") or "", 120),
                }
            )
            if len(artifact_recent) >= 120:
                break
        if len(artifact_recent) >= 120:
            break

    return {
        "generated_at_utc": _utc_now(),
        "run_board": run_board,
        "approvals_ledger": approvals,
        "telemetry": telemetry,
        "artifact_viewer": {"recent": artifact_recent},
    }
