"""Phase 8.5 safe social/content automation replay gate."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from chintu_backend.automation import social_content_capabilities as social


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def run_replay(out_dir: Path) -> dict:
    workspace = out_dir / "phase85_social_tmp"
    workspace.mkdir(parents=True, exist_ok=True)
    cfg = SimpleNamespace(data_dir=workspace)

    old_cfg_fn = social.get_config
    social.get_config = lambda: cfg
    try:
        pipeline = social.handle_social_content_pipeline(
            "Create social campaign about local llm productivity for youtube and instagram",
            context={},
        )
        campaign_dir = str((pipeline.data or {}).get("campaign_dir") or "")
        stage = social.handle_social_stage_upload(
            "stage upload for youtube",
            context={"_extracted_params": {"platform": "youtube", "asset_dir": campaign_dir}},
        )
        publish_pending = social.handle_social_publish_post(
            "publish short on youtube",
            context={"_extracted_params": {"platform": "youtube", "asset_dir": campaign_dir}},
        )
        publish_done = publish_pending.pending_action() if publish_pending.requires_confirmation else None
        payment_block = social.handle_social_publish_post("publish and checkout premium plan", context={})

        artifacts_ok = all(
            Path(str((pipeline.data or {}).get(key) or "")).exists()
            for key in ("script", "captions", "hashtags", "thumbnail_prompt", "schedule_checklist", "manifest")
        )
        checks = {
            "pipeline_success": bool(pipeline.success),
            "pipeline_artifacts_complete": bool(artifacts_ok),
            "draft_staging_success": bool(stage.success),
            "staging_no_publish_submit": bool((stage.data or {}).get("publish_submitted") is False),
            "publish_requires_confirmation": bool(publish_pending.requires_confirmation),
            "publish_confirm_path_success": bool(publish_done and publish_done.success),
            "publish_confirm_no_payment_submit": bool((publish_done.data or {}).get("publish_submitted") is False if publish_done else False),
            "payment_ui_blocked": bool(payment_block.success is False),
        }
        success = all(checks.values())
        return {
            "phase": "phase8.5",
            "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "success": success,
            "checks": checks,
            "pipeline": pipeline.to_dict() if hasattr(pipeline, "to_dict") else {},
            "stage": stage.to_dict() if hasattr(stage, "to_dict") else {},
            "publish_pending": publish_pending.to_dict() if hasattr(publish_pending, "to_dict") else {},
            "publish_done": publish_done.to_dict() if publish_done and hasattr(publish_done, "to_dict") else {},
            "payment_block": payment_block.to_dict() if hasattr(payment_block, "to_dict") else {},
        }
    finally:
        social.get_config = old_cfg_fn


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Phase 8.5 social/content replay checks.")
    parser.add_argument("--out-dir", default="generated_reports")
    args = parser.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    report = run_replay(out_dir)
    report_path = out_dir / f"phase85_social_replay_{_now()}.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    print(f"Wrote: {report_path}")
    print(json.dumps({"success": report["success"], "checks": report["checks"]}, indent=2))
    return 0 if bool(report.get("success")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
