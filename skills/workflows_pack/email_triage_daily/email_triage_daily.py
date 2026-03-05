from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from chintu_backend.core.config import get_config
from chintu_backend.core.scheduler import get_scheduler


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def ensure_daily_schedule() -> Dict[str, Any]:
    scheduler = get_scheduler()
    workflow_text = "run email triage daily"
    for task in scheduler.list_tasks():
        if str(getattr(task, "workflow", "")).strip().lower() == workflow_text:
            return {"scheduled": True, "created": False, "task_id": str(getattr(task, "id", ""))}
    task = scheduler.schedule(
        name="Daily email triage drafts",
        workflow=workflow_text,
        schedule_type="daily",
        schedule_time="08:30",
    )
    return {"scheduled": True, "created": True, "task_id": str(task.id)}


def _build_draft(sender: str, subject: str, snippet: str) -> str:
    return "\n".join(
        [
            f"Subject: Re: {subject or 'Your message'}",
            "",
            "Hi,",
            "",
            "Thanks for your message. I reviewed your note and here is a draft response:",
            "",
            f"- Context captured: {snippet[:180]}",
            "- Proposed next step: confirm required details and expected timeline.",
            "",
            "Best,",
            "Chintu (draft)",
        ]
    )


def write_daily_triage_report() -> Dict[str, Any]:
    cfg = get_config()
    out_dir = Path(getattr(cfg, "workflows_dir", cfg.data_dir / "workflows")) / "email_triage"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{datetime.now().strftime('%Y-%m-%d')}.md"

    matches: List[Any] = []
    status_note = ""
    try:
        from chintu_backend.automation.tools.email_reader import EmailReader

        reader = EmailReader()
        configured, reason = reader.configured
        if configured:
            matches, status_note = reader.fetch_recent_codes(lookback_minutes=24 * 60, max_messages=12)
        else:
            status_note = reason
    except Exception as exc:
        status_note = f"Email triage source unavailable: {exc}"
        matches = []

    lines = [
        "# Daily Email Triage Drafts",
        "",
        f"- Generated UTC: {_utc_now()}",
        f"- Status: {status_note or 'ok'}",
        "",
    ]
    draft_count = 0
    if matches:
        for idx, item in enumerate(matches[:10], start=1):
            sender = str(getattr(item, "sender", "") or "")
            subject = str(getattr(item, "subject", "") or "")
            snippet = str(getattr(item, "snippet", "") or "")
            lines.extend(
                [
                    f"## Draft {idx}",
                    "",
                    f"- Sender: {sender}",
                    f"- Subject: {subject}",
                    "",
                    "```text",
                    _build_draft(sender, subject, snippet),
                    "```",
                    "",
                ]
            )
            draft_count += 1
    else:
        lines.extend(
            [
                "## Draft 1",
                "",
                "```text",
                _build_draft("unknown", "Follow-up", "No new emails were available in this run."),
                "```",
                "",
            ]
        )
        draft_count = 1

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return {"report_path": str(out_path), "draft_count": draft_count, "status": status_note}


def run(request_text: str) -> Dict[str, Any]:
    low = str(request_text or "").lower()
    wants_schedule = any(token in low for token in ["set up", "setup", "schedule", "daily"])
    run_now = "schedule only" not in low

    result: Dict[str, Any] = {
        "workflow": "email_triage_daily",
        "requested_schedule": bool(wants_schedule),
        "requested_run_now": bool(run_now),
        "timestamp_utc": _utc_now(),
    }
    if wants_schedule:
        result["schedule"] = ensure_daily_schedule()
    if run_now:
        result.update(write_daily_triage_report())
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily email triage draft workflow.")
    parser.add_argument("--request", default="")
    args = parser.parse_args()
    print(json.dumps(run(args.request), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
