"""Dashboard Studio (Phase 13): build exportable dashboards from local data sources."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from chintu_backend.core.config import get_config


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_slug(value: str) -> str:
    raw = "".join(ch.lower() if ch.isalnum() else "-" for ch in str(value or "").strip())
    while "--" in raw:
        raw = raw.replace("--", "-")
    return raw.strip("-") or "dashboard"


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


@dataclass
class DashboardBuildResult:
    kind: str
    project_dir: str
    app_path: str
    spec_path: str
    data_path: str
    readme_path: str
    test_path: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "kind": self.kind,
            "project_dir": self.project_dir,
            "app_path": self.app_path,
            "spec_path": self.spec_path,
            "data_path": self.data_path,
            "readme_path": self.readme_path,
            "test_path": self.test_path,
        }


class DashboardStudio:
    """Generate dashboard projects with code, data, tests, and run instructions."""

    VALID_KINDS = {"reliability", "content", "finance"}

    def __init__(self, output_root: Optional[Path] = None, data_root: Optional[Path] = None):
        cfg = get_config()
        self.config = cfg
        self.output_root = Path(output_root or (cfg.data_dir / "dashboard_studio"))
        self.data_root = Path(data_root or cfg.data_dir)
        self.output_root.mkdir(parents=True, exist_ok=True)

    def discover_sources(self) -> Dict[str, Any]:
        social_root = self.data_root / "content_studio" / "social_campaigns"
        social_manifests = list(social_root.glob("*/campaign_manifest.json")) if social_root.exists() else []
        arbiter_path = Path(getattr(self.config, "arbiter_telemetry_path", self.data_root / "telemetry" / "arbiter_routing.jsonl"))
        return {
            "runs_snapshot": "chintu_backend.core.run_manager.get_run_manager().snapshot()",
            "arbiter_telemetry": str(arbiter_path),
            "social_campaign_manifests": [str(path) for path in social_manifests[-10:]],
            "finance_csv_hint": "Provide CSV with columns like symbol/ticker and value/market_value/amount.",
        }

    def build_dashboard(
        self,
        kind: str,
        *,
        name: Optional[str] = None,
        finance_csv_path: Optional[Path] = None,
    ) -> DashboardBuildResult:
        normalized = str(kind or "").strip().lower()
        if normalized not in self.VALID_KINDS:
            raise ValueError(f"Unsupported dashboard kind: {kind}")

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        title = str(name or f"{normalized.title()} Dashboard").strip()
        project_dir = self.output_root / f"{ts}_{_safe_slug(normalized)}"
        data_dir = project_dir / "data"
        tests_dir = project_dir / "tests"
        data_dir.mkdir(parents=True, exist_ok=True)
        tests_dir.mkdir(parents=True, exist_ok=True)

        payload = self._collect_data(normalized, finance_csv_path=finance_csv_path)
        spec = self._build_spec(normalized, title=title, payload=payload)

        data_path = data_dir / "input.json"
        spec_path = project_dir / "dashboard_spec.json"
        app_path = project_dir / "app.py"
        readme_path = project_dir / "README.md"
        test_path = tests_dir / "test_dashboard.py"

        data_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
        spec_path.write_text(json.dumps(spec, indent=2, ensure_ascii=True), encoding="utf-8")
        app_path.write_text(self._build_app_py(title=title, kind=normalized), encoding="utf-8")
        readme_path.write_text(self._build_readme(title=title, kind=normalized), encoding="utf-8")
        test_path.write_text(self._build_test_py(kind=normalized), encoding="utf-8")

        return DashboardBuildResult(
            kind=normalized,
            project_dir=str(project_dir),
            app_path=str(app_path),
            spec_path=str(spec_path),
            data_path=str(data_path),
            readme_path=str(readme_path),
            test_path=str(test_path),
        )

    def _collect_data(self, kind: str, finance_csv_path: Optional[Path]) -> Dict[str, Any]:
        if kind == "reliability":
            return self._collect_reliability_data()
        if kind == "content":
            return self._collect_content_data()
        if kind == "finance":
            return self._collect_finance_data(finance_csv_path)
        raise ValueError(f"Unsupported dashboard kind: {kind}")

    def _collect_reliability_data(self) -> Dict[str, Any]:
        runs_payload: Dict[str, Any] = {"runs": []}
        try:
            from chintu_backend.core.run_manager import get_run_manager

            runs_payload = get_run_manager().snapshot(limit=250)
        except Exception:
            runs_payload = {"runs": []}

        runs = list(runs_payload.get("runs") or [])
        status_counts: Dict[str, int] = {}
        durations: List[float] = []
        total_steps = 0
        total_completed = 0
        for row in runs:
            status = str(row.get("status") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
            total_steps += int(row.get("steps_total") or 0)
            total_completed += int(row.get("steps_completed") or 0)
            start_ts = _parse_iso(str(row.get("started_at") or row.get("created_at") or ""))
            end_ts = _parse_iso(str(row.get("ended_at") or ""))
            if start_ts and end_ts and end_ts >= start_ts:
                durations.append((end_ts - start_ts).total_seconds())

        avg_duration_s = round(sum(durations) / len(durations), 2) if durations else 0.0
        pass_rate = 0.0
        terminal = sum(status_counts.get(k, 0) for k in ("completed", "failed", "cancelled", "timed_out"))
        if terminal:
            pass_rate = round(status_counts.get("completed", 0) / float(terminal), 4)

        arbiter_summary: Dict[str, Any] = {}
        try:
            from chintu_backend.core.arbiter_telemetry import get_arbiter_telemetry

            arbiter_summary = get_arbiter_telemetry().summarize(hours=24, limit=1500)
        except Exception:
            arbiter_summary = {}

        return {
            "generated_at_utc": _utc_now_iso(),
            "kind": "reliability",
            "metrics": {
                "total_runs": len(runs),
                "completed_runs": status_counts.get("completed", 0),
                "pass_rate": pass_rate,
                "avg_duration_s": avg_duration_s,
                "step_completion_rate": round((total_completed / float(total_steps)), 4) if total_steps else 0.0,
            },
            "status_counts": status_counts,
            "runs": runs[:120],
            "arbiter_summary": arbiter_summary,
        }

    def _collect_content_data(self) -> Dict[str, Any]:
        social_root = self.data_root / "content_studio" / "social_campaigns"
        campaigns: List[Dict[str, Any]] = []
        if social_root.exists():
            for manifest_path in sorted(social_root.glob("*/campaign_manifest.json"), reverse=True):
                try:
                    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                files = payload.get("files", {}) if isinstance(payload, dict) else {}
                file_health = {
                    key: Path(str(path)).exists()
                    for key, path in (files.items() if isinstance(files, dict) else [])
                }
                campaigns.append(
                    {
                        "manifest": str(manifest_path),
                        "topic": str(payload.get("topic") or ""),
                        "platforms": list(payload.get("platforms") or []),
                        "created_at_utc": str(payload.get("created_at_utc") or ""),
                        "duration_seconds": int(payload.get("duration_seconds") or 0),
                        "files_ok": file_health,
                        "files_ok_ratio": round(
                            (sum(1 for ok in file_health.values() if ok) / float(len(file_health))) if file_health else 0.0,
                            3,
                        ),
                    }
                )

        return {
            "generated_at_utc": _utc_now_iso(),
            "kind": "content",
            "metrics": {
                "campaigns_total": len(campaigns),
                "campaigns_last_7": self._count_recent(campaigns, days=7),
                "avg_file_health_ratio": round(
                    (sum(float(c.get("files_ok_ratio") or 0.0) for c in campaigns) / float(len(campaigns))) if campaigns else 0.0,
                    3,
                ),
            },
            "campaigns": campaigns[:120],
        }

    def _collect_finance_data(self, finance_csv_path: Optional[Path]) -> Dict[str, Any]:
        if not finance_csv_path:
            raise ValueError("finance_csv_path is required for finance dashboard")
        csv_path = Path(finance_csv_path)
        if not csv_path.exists():
            raise FileNotFoundError(f"Finance CSV not found: {csv_path}")

        rows: List[Dict[str, Any]] = []
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if not isinstance(row, dict):
                    continue
                symbol = str(
                    row.get("symbol")
                    or row.get("ticker")
                    or row.get("asset")
                    or row.get("name")
                    or ""
                ).strip()
                if not symbol:
                    continue
                value = self._coerce_value(
                    row.get("market_value")
                    or row.get("value")
                    or row.get("amount")
                    or row.get("current_value")
                )
                pnl = self._coerce_value(
                    row.get("pnl")
                    or row.get("profit_loss")
                    or row.get("gain_loss")
                    or row.get("unrealized_pnl")
                )
                rows.append({"symbol": symbol.upper(), "value": value, "pnl": pnl})

        total_value = sum(float(row.get("value") or 0.0) for row in rows)
        allocations = []
        for row in rows:
            value = float(row.get("value") or 0.0)
            allocations.append(
                {
                    "symbol": row["symbol"],
                    "value": round(value, 2),
                    "pnl": round(float(row.get("pnl") or 0.0), 2),
                    "allocation_pct": round((value / total_value) * 100.0, 3) if total_value else 0.0,
                }
            )
        allocations.sort(key=lambda item: item["value"], reverse=True)

        return {
            "generated_at_utc": _utc_now_iso(),
            "kind": "finance",
            "source_csv": str(csv_path),
            "metrics": {
                "positions": len(allocations),
                "total_value": round(total_value, 2),
                "total_pnl": round(sum(float(item.get("pnl") or 0.0) for item in allocations), 2),
                "largest_position_pct": float(allocations[0]["allocation_pct"]) if allocations else 0.0,
            },
            "allocations": allocations,
        }

    @staticmethod
    def _coerce_value(value: Any) -> float:
        try:
            text = str(value or "").strip().replace(",", "")
            if text.startswith("$"):
                text = text[1:]
            if not text:
                return 0.0
            return float(text)
        except Exception:
            return 0.0

    @staticmethod
    def _count_recent(items: List[Dict[str, Any]], days: int = 7) -> int:
        cutoff = datetime.now(timezone.utc).timestamp() - float(days * 86400)
        count = 0
        for row in items:
            ts = _parse_iso(str(row.get("created_at_utc") or ""))
            if ts and ts.timestamp() >= cutoff:
                count += 1
        return count

    def _build_spec(self, kind: str, title: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        questions_map = {
            "reliability": [
                "What is current pass rate and average run duration?",
                "Which statuses are dominating failures?",
                "Are routing/provider outcomes stable?",
            ],
            "content": [
                "How many campaigns are being produced consistently?",
                "Are campaign artifacts complete and ready for staging?",
                "Which platforms are most active?",
            ],
            "finance": [
                "What is current portfolio allocation?",
                "Where is concentration risk highest?",
                "How is PnL distributed across positions?",
            ],
        }
        return {
            "title": title,
            "kind": kind,
            "generated_at_utc": _utc_now_iso(),
            "workflow": [
                "what_data_do_we_have",
                "what_questions_do_we_want_answered",
                "build_dashboard",
                "verify_charts",
                "run_command",
            ],
            "questions": questions_map.get(kind, []),
            "sources": self.discover_sources(),
            "metrics_keys": sorted(list((payload.get("metrics") or {}).keys())),
        }

    def _build_app_py(self, *, title: str, kind: str) -> str:
        return (
            "from __future__ import annotations\n\n"
            "import json\n"
            "from pathlib import Path\n\n"
            "import streamlit as st\n\n"
            "BASE_DIR = Path(__file__).resolve().parent\n"
            "DATA_PATH = BASE_DIR / 'data' / 'input.json'\n\n"
            "payload = json.loads(DATA_PATH.read_text(encoding='utf-8')) if DATA_PATH.exists() else {}\n"
            f"st.set_page_config(page_title={title!r}, layout='wide')\n"
            f"st.title({title!r})\n"
            "st.caption(f\"Dashboard kind: " + kind + " | Generated: {payload.get('generated_at_utc', '')}\")\n\n"
            "metrics = payload.get('metrics') or {}\n"
            "if metrics:\n"
            "    cols = st.columns(max(1, min(4, len(metrics))))\n"
            "    for idx, (key, value) in enumerate(metrics.items()):\n"
            "        cols[idx % len(cols)].metric(label=key.replace('_', ' ').title(), value=value)\n\n"
            "if payload.get('runs'):\n"
            "    st.subheader('Runs')\n"
            "    st.dataframe(payload.get('runs'))\n"
            "if payload.get('status_counts'):\n"
            "    st.subheader('Status Counts')\n"
            "    st.bar_chart(payload.get('status_counts'))\n"
            "if payload.get('campaigns'):\n"
            "    st.subheader('Campaigns')\n"
            "    st.dataframe(payload.get('campaigns'))\n"
            "if payload.get('allocations'):\n"
            "    st.subheader('Allocations')\n"
            "    st.dataframe(payload.get('allocations'))\n"
            "if payload.get('arbiter_summary'):\n"
            "    st.subheader('Arbiter Summary')\n"
            "    st.json(payload.get('arbiter_summary'))\n"
        )

    @staticmethod
    def _build_readme(*, title: str, kind: str) -> str:
        return (
            f"# {title}\n\n"
            f"Kind: `{kind}`\n\n"
            "## What this includes\n"
            "- `app.py`: Streamlit dashboard app\n"
            "- `data/input.json`: normalized dashboard data payload\n"
            "- `dashboard_spec.json`: workflow + questions + data sources\n"
            "- `tests/test_dashboard.py`: smoke tests for dashboard artifacts\n\n"
            "## Run\n"
            "```bash\n"
            "python -m pip install streamlit\n"
            "streamlit run app.py\n"
            "```\n\n"
            "## Test\n"
            "```bash\n"
            "python -m pytest tests/test_dashboard.py -q\n"
            "```\n"
        )

    @staticmethod
    def _build_test_py(*, kind: str) -> str:
        return (
            "from __future__ import annotations\n\n"
            "import json\n"
            "from pathlib import Path\n\n\n"
            "def test_dashboard_artifacts_exist():\n"
            "    root = Path(__file__).resolve().parents[1]\n"
            "    assert (root / 'app.py').exists()\n"
            "    assert (root / 'dashboard_spec.json').exists()\n"
            "    assert (root / 'data' / 'input.json').exists()\n\n"
            "def test_dashboard_payload_has_kind_and_metrics():\n"
            "    root = Path(__file__).resolve().parents[1]\n"
            "    payload = json.loads((root / 'data' / 'input.json').read_text(encoding='utf-8'))\n"
            f"    assert payload.get('kind') == {kind!r}\n"
            "    assert isinstance(payload.get('metrics') or {}, dict)\n"
        )


_studio: Optional[DashboardStudio] = None


def get_dashboard_studio() -> DashboardStudio:
    global _studio
    if _studio is None:
        _studio = DashboardStudio()
    return _studio

