from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from chintu_backend.core.task_history import TaskHistoryManager


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _cfg(root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        data_dir=root,
        task_history_enabled=True,
        history_event_store_path=root / "history" / "events.jsonl",
        task_dossiers_dir=root / "history" / "dossiers",
        task_history_index_path=root / "history" / "dossier_index.sqlite3",
        training_exports_dir=root / "training" / "exports",
    )


def run_replay() -> dict:
    workspace = Path(".tmp") / "phase5_replay"
    workspace.mkdir(parents=True, exist_ok=True)
    manager = TaskHistoryManager(config=_cfg(workspace))

    runs = [
        {
            "id": "phase5_run_1",
            "session_id": "main",
            "source": "chat",
            "user_text": "Create visa bot feature backlog",
            "status": "completed",
            "created_at": "2026-02-19T05:00:00Z",
            "started_at": "2026-02-19T05:00:01Z",
            "ended_at": "2026-02-19T05:00:06Z",
            "meta": {"result_summary": "Backlog created with milestones."},
            "steps": [
                {
                    "id": "s1",
                    "title": "Draft feature list",
                    "capability": "app_builder_plan",
                    "status": "completed",
                    "message": "Feature list drafted with priorities.",
                    "meta": {"verification": {"ok": True}},
                    "evidence": [],
                }
            ],
        },
        {
            "id": "phase5_run_2",
            "session_id": "main",
            "source": "chat",
            "user_text": "Compare best phone deals under 500",
            "status": "failed",
            "created_at": "2026-02-19T06:00:00Z",
            "started_at": "2026-02-19T06:00:01Z",
            "ended_at": "2026-02-19T06:00:04Z",
            "error": "Network timeout from source websites.",
            "meta": {"result_summary": "Could not finish comparison due to timeout."},
            "steps": [
                {
                    "id": "s1",
                    "title": "Fetch offers",
                    "capability": "skill::price-compare",
                    "status": "failed",
                    "message": "Timeout while fetching pages.",
                    "meta": {"failure_type": "transient_network_error"},
                    "evidence": [],
                }
            ],
        },
    ]

    for run in runs:
        manager.ingest_run_record(run, trigger="replay")

    answer = manager.answer_history_question("visa bot backlog", limit=2)
    export = manager.export_training_bundle(limit=20)

    dossier_dir = workspace / "history" / "dossiers"
    dossiers = [p for p in dossier_dir.glob("*.json") if p.is_file()]
    pass_conditions = {
        "dossiers_created": len(dossiers) >= len(runs),
        "history_answer_has_provenance": "Provenance:" in str(answer.get("message") or ""),
        "history_match_found": len(answer.get("matches") or []) >= 1,
        "training_chat_exported": int(export.get("chat_count") or 0) >= 1,
        "training_rag_exported": int(export.get("rag_count") or 0) >= 1,
    }
    success = all(pass_conditions.values())

    report = {
        "phase": "phase5",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "success": success,
        "checks": pass_conditions,
        "metrics": {
            "dossier_count": len(dossiers),
            "history_match_count": len(answer.get("matches") or []),
            "chat_count": int(export.get("chat_count") or 0),
            "rag_count": int(export.get("rag_count") or 0),
        },
        "artifacts": {
            "workspace": str(workspace),
            "history_events": str(workspace / "history" / "events.jsonl"),
            "dossiers_dir": str(dossier_dir),
            "chat_export": str(export.get("chat_path") or ""),
            "rag_export": str(export.get("rag_path") or ""),
            "manifest": str(export.get("manifest_path") or ""),
        },
        "history_answer_preview": str(answer.get("message") or "")[:1000],
    }
    return report


def main() -> int:
    report = run_replay()
    reports_dir = Path("generated_reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    output = reports_dir / f"phase5_memory_replay_{_timestamp()}.json"
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote replay report: {output}")
    if report.get("success"):
        print("Phase 5 replay: PASS")
        return 0
    print("Phase 5 replay: FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
