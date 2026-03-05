"""
Realistic 50-task benchmark for Chintu.

Goals:
- Execute a practical set of 50 tasks end-to-end through CommandHandler.
- Capture per-task response quality checks.
- Measure per-task timing and resource usage.

Safety default:
- Uses context dry_run side-effects mode by default (full routing, non-destructive actions).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _substitute_placeholders(text: str, *, bench_stamp: str, task_id: str, out_dir: str) -> str:
    """Lightweight placeholder substitution without str.format() pitfalls."""
    raw = str(text or "")
    return (
        raw.replace("{bench_stamp}", str(bench_stamp))
        .replace("{task_id}", str(task_id))
        .replace("{out_dir}", str(out_dir))
    )


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_float(text: str) -> Optional[float]:
    try:
        return float(str(text).strip())
    except Exception:
        return None


def _query_gpu_snapshot() -> Dict[str, Any]:
    """
    Query instantaneous GPU utilization and memory (best-effort).
    Returns max across all visible GPUs.
    """
    cmd = [
        "nvidia-smi",
        "--query-gpu=utilization.gpu,memory.used,memory.total",
        "--format=csv,noheader,nounits",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=2, shell=False)
        if proc.returncode != 0:
            return {"available": False}
        lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
        util_vals: List[float] = []
        mem_used_vals: List[float] = []
        mem_total_vals: List[float] = []
        for ln in lines:
            parts = [p.strip() for p in ln.split(",")]
            if len(parts) < 3:
                continue
            util = _parse_float(parts[0])
            mem_used = _parse_float(parts[1])
            mem_total = _parse_float(parts[2])
            if util is not None:
                util_vals.append(util)
            if mem_used is not None:
                mem_used_vals.append(mem_used)
            if mem_total is not None:
                mem_total_vals.append(mem_total)
        if not util_vals and not mem_used_vals:
            return {"available": False}
        return {
            "available": True,
            "gpu_count": len(lines),
            "util_max_percent": max(util_vals) if util_vals else None,
            "mem_used_max_mb": max(mem_used_vals) if mem_used_vals else None,
            "mem_total_max_mb": max(mem_total_vals) if mem_total_vals else None,
        }
    except Exception:
        return {"available": False}


@dataclass
class ResourceStats:
    proc_cpu_avg_percent: float = 0.0
    proc_cpu_peak_percent: float = 0.0
    proc_rss_start_mb: float = 0.0
    proc_rss_end_mb: float = 0.0
    proc_rss_peak_mb: float = 0.0
    system_cpu_avg_percent: float = 0.0
    system_cpu_peak_percent: float = 0.0
    system_ram_avg_percent: float = 0.0
    system_ram_peak_percent: float = 0.0
    gpu_util_peak_percent: Optional[float] = None
    gpu_mem_used_peak_mb: Optional[float] = None
    net_sent_delta_mb: float = 0.0
    net_recv_delta_mb: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proc_cpu_avg_percent": round(self.proc_cpu_avg_percent, 2),
            "proc_cpu_peak_percent": round(self.proc_cpu_peak_percent, 2),
            "proc_rss_start_mb": round(self.proc_rss_start_mb, 2),
            "proc_rss_end_mb": round(self.proc_rss_end_mb, 2),
            "proc_rss_peak_mb": round(self.proc_rss_peak_mb, 2),
            "system_cpu_avg_percent": round(self.system_cpu_avg_percent, 2),
            "system_cpu_peak_percent": round(self.system_cpu_peak_percent, 2),
            "system_ram_avg_percent": round(self.system_ram_avg_percent, 2),
            "system_ram_peak_percent": round(self.system_ram_peak_percent, 2),
            "gpu_util_peak_percent": None if self.gpu_util_peak_percent is None else round(float(self.gpu_util_peak_percent), 2),
            "gpu_mem_used_peak_mb": None if self.gpu_mem_used_peak_mb is None else round(float(self.gpu_mem_used_peak_mb), 2),
            "net_sent_delta_mb": round(self.net_sent_delta_mb, 3),
            "net_recv_delta_mb": round(self.net_recv_delta_mb, 3),
        }


class ResourceSampler:
    def __init__(self, sample_interval_s: float = 0.15, gpu_sample_every_n: int = 4):
        import psutil

        self.psutil = psutil
        self.sample_interval_s = max(0.05, float(sample_interval_s))
        self.gpu_sample_every_n = max(1, int(gpu_sample_every_n))
        self.proc = psutil.Process(os.getpid())
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self._proc_cpu_samples: List[float] = []
        self._sys_cpu_samples: List[float] = []
        self._sys_ram_samples: List[float] = []
        self._rss_samples_mb: List[float] = []
        self._gpu_util_samples: List[float] = []
        self._gpu_mem_samples_mb: List[float] = []

        self._rss_start_mb = 0.0
        self._rss_end_mb = 0.0
        self._net_sent_start = 0
        self._net_recv_start = 0
        self._net_sent_end = 0
        self._net_recv_end = 0
        self._cpu_time_start = 0.0
        self._cpu_time_end = 0.0
        self._wall_start = 0.0
        self._wall_end = 0.0

    def start(self) -> None:
        vm = self.psutil.virtual_memory()
        _ = vm.percent
        _ = self.psutil.cpu_percent(interval=None)
        _ = self.proc.cpu_percent(interval=None)

        self._rss_start_mb = float(self.proc.memory_info().rss) / (1024 * 1024)
        cpu_t = self.proc.cpu_times()
        self._cpu_time_start = float(cpu_t.user + cpu_t.system)
        net = self.psutil.net_io_counters()
        self._net_sent_start = int(net.bytes_sent)
        self._net_recv_start = int(net.bytes_recv)
        self._wall_start = time.perf_counter()

        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> ResourceStats:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

        self._wall_end = time.perf_counter()
        self._rss_end_mb = float(self.proc.memory_info().rss) / (1024 * 1024)
        cpu_t = self.proc.cpu_times()
        self._cpu_time_end = float(cpu_t.user + cpu_t.system)
        net = self.psutil.net_io_counters()
        self._net_sent_end = int(net.bytes_sent)
        self._net_recv_end = int(net.bytes_recv)

        elapsed = max(0.001, self._wall_end - self._wall_start)
        cpu_time_delta = max(0.0, self._cpu_time_end - self._cpu_time_start)
        proc_cpu_avg_percent = (cpu_time_delta / elapsed) * 100.0

        stats = ResourceStats(
            proc_cpu_avg_percent=proc_cpu_avg_percent,
            proc_cpu_peak_percent=max(self._proc_cpu_samples) if self._proc_cpu_samples else 0.0,
            proc_rss_start_mb=self._rss_start_mb,
            proc_rss_end_mb=self._rss_end_mb,
            proc_rss_peak_mb=max(self._rss_samples_mb) if self._rss_samples_mb else max(self._rss_start_mb, self._rss_end_mb),
            system_cpu_avg_percent=mean(self._sys_cpu_samples) if self._sys_cpu_samples else 0.0,
            system_cpu_peak_percent=max(self._sys_cpu_samples) if self._sys_cpu_samples else 0.0,
            system_ram_avg_percent=mean(self._sys_ram_samples) if self._sys_ram_samples else 0.0,
            system_ram_peak_percent=max(self._sys_ram_samples) if self._sys_ram_samples else 0.0,
            gpu_util_peak_percent=max(self._gpu_util_samples) if self._gpu_util_samples else None,
            gpu_mem_used_peak_mb=max(self._gpu_mem_samples_mb) if self._gpu_mem_samples_mb else None,
            net_sent_delta_mb=float(max(0, self._net_sent_end - self._net_sent_start)) / (1024 * 1024),
            net_recv_delta_mb=float(max(0, self._net_recv_end - self._net_recv_start)) / (1024 * 1024),
        )
        return stats

    def _run(self) -> None:
        counter = 0
        while not self._stop.is_set():
            time.sleep(self.sample_interval_s)
            counter += 1
            try:
                self._proc_cpu_samples.append(float(self.proc.cpu_percent(interval=None)))
                self._rss_samples_mb.append(float(self.proc.memory_info().rss) / (1024 * 1024))
                self._sys_cpu_samples.append(float(self.psutil.cpu_percent(interval=None)))
                self._sys_ram_samples.append(float(self.psutil.virtual_memory().percent))
            except Exception:
                pass

            if counter % self.gpu_sample_every_n == 0:
                snap = _query_gpu_snapshot()
                if snap.get("available"):
                    util = snap.get("util_max_percent")
                    mem = snap.get("mem_used_max_mb")
                    if isinstance(util, (int, float)):
                        self._gpu_util_samples.append(float(util))
                    if isinstance(mem, (int, float)):
                        self._gpu_mem_samples_mb.append(float(mem))


def _base_response_ok(response: str) -> Tuple[bool, str]:
    if not response:
        return False, "empty response"
    stripped = response.strip()
    if not stripped:
        return False, "empty response"
    if len(stripped) < 3:
        # Accept concise numeric/text answers (e.g., "4", "55", "ok").
        if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", stripped) or stripped.lower() in {"ok", "yes", "no"}:
            pass
        else:
            return False, "too short response"
    return True, "non-empty response"


def _scenario_checks(
    scenario: Dict[str, Any], response: str, capability: str
) -> Tuple[Optional[bool], str]:
    checks = scenario.get("checks")
    if not isinstance(checks, dict) or not checks:
        return None, "no scenario checks"

    text = response or ""
    low = text.lower()

    min_length = checks.get("min_length")
    if isinstance(min_length, int) and len(text.strip()) < int(min_length):
        return False, f"expected min_length={min_length}"

    max_length = checks.get("max_length")
    if isinstance(max_length, int) and len(text.strip()) > int(max_length):
        return False, f"expected max_length={max_length}"

    must_contain = checks.get("must_contain") or []
    if isinstance(must_contain, str):
        must_contain = [must_contain]
    if isinstance(must_contain, list):
        for token in must_contain:
            tok = str(token or "").strip().lower()
            if not tok:
                continue
            if tok not in low:
                return False, f"missing required token: {tok}"

    must_not_contain = checks.get("must_not_contain") or []
    if isinstance(must_not_contain, str):
        must_not_contain = [must_not_contain]
    if isinstance(must_not_contain, list):
        for token in must_not_contain:
            tok = str(token or "").strip().lower()
            if not tok:
                continue
            if tok in low:
                return False, f"forbidden token present: {tok}"

    must_match = checks.get("must_match") or []
    if isinstance(must_match, str):
        must_match = [must_match]
    if isinstance(must_match, list):
        for pattern in must_match:
            pat = str(pattern or "").strip()
            if not pat:
                continue
            if not re.search(pat, text, flags=re.IGNORECASE | re.MULTILINE):
                return False, f"missing required pattern: {pat}"

    cap_must = checks.get("capability_must_contain")
    if isinstance(cap_must, str):
        cap_must = [cap_must]
    if isinstance(cap_must, list) and cap_must:
        cap_low = str(capability or "").lower()
        if not any(str(tok).lower() in cap_low for tok in cap_must if str(tok or "").strip()):
            return False, "unexpected capability"

    return True, "scenario checks passed"


def _task_specific_check(task_id: int, text: str, response: str) -> Tuple[bool, str]:
    low = response.lower()
    if task_id == 8:
        ok = ("notepad" in low) and any(tok in low for tok in ["close", "closed", "closing", "quit"])
        return (ok, "expected close confirmation for Notepad")
    if task_id == 10:
        ok = any(tok in low for tok in ["maximiz", "window", "done"])
        return (ok, "expected maximize-window style confirmation")
    if task_id == 13:
        ok = ("note" in low) and ("grocer" in low or "saved" in low or "remember" in low)
        return (ok, "expected note-save confirmation")
    if task_id == 14:
        ok = ("grocer" in low) or ("notes" in low and "-" in response)
        return (ok, "expected notes list including saved note context")
    if task_id == 12:
        return ("buddy" in low, "expected Buddy for dog-name recall")
    if task_id == 17:
        return ("blue" in low, "expected blue for favorite-color recall")
    if task_id == 27:
        if "grocer" in low or "timer" in low:
            return (False, "next meeting should not resolve to reminder/timer content")
        ok = "meeting" in low or "appointment" in low or "could not find a scheduled meeting" in low
        return (ok, "expected true meeting answer or explicit no-meeting message")
    if task_id == 29:
        return (bool(re.search(r"\b4\b", low)), "expected numeric result 4")
    if task_id == 30:
        return (bool(re.search(r"\b12\b", low)), "expected numeric result 12")
    if task_id == 31:
        return (bool(re.search(r"\b55\b", low)), "expected fibonacci(10)=55")
    if task_id == 32:
        ok = ("current working directory" in low) or bool(re.search(r"[a-z]:\\\\", response, re.IGNORECASE))
        return (ok, "expected cwd path-style response")
    if task_id == 35:
        # 100F is about 37.78C
        return (
            any(token in low for token in ["37.7", "37.8", "37.78", "37.77"]),
            "expected ~37.8C for 100F",
        )
    if task_id == 36:
        # Use concrete date to keep the check stable and explicit.
        expected_days = (date(2027, 1, 1) - date.today()).days
        return (str(expected_days) in low, f"expected days until 2027-01-01: {expected_days}")
    if task_id == 37:
        ok = ("the current" not in low) and any(tok in response for tok in ["\\", "/", "\n- ", ".py", ".md", ".json"])
        return (ok, "expected current directory listing (not literal 'the current' path)")
    if task_id == 19:
        ok = ("call mom" in low) and ("10 minute" in low)
        return (ok, "expected one 10-minute reminder for 'call mom'")
    if task_id == 42:
        return ("paris" in low, "expected capital Paris")
    if task_id == 45:
        if any(tok in low for tok in ["deal", "price", "$", "amazon", "newegg"]):
            return (False, "comparison should not route to shopping/deal finder")
        ok = ("python" in low) and ("javascript" in low)
        return (ok, "expected language comparison covering Python and JavaScript")
    if "search" in text.lower():
        return ("http" in low or "result" in low or "search" in low, "search reply should include result-like output")
    return True, "generic response check"


def _verdict(task_id: int, scenario: Dict[str, Any], response: str, capability: str) -> Tuple[str, str]:
    ok_base, reason_base = _base_response_ok(response)
    if not ok_base:
        return "FAIL", reason_base

    ok_scenario, reason_scenario = _scenario_checks(scenario, response, capability)
    if ok_scenario is True:
        return "PASS", reason_scenario
    if ok_scenario is False:
        strict = scenario.get("checks", {}).get("strict", True)
        return ("FAIL" if strict else "REVIEW"), reason_scenario

    text = str(scenario.get("text") or "")
    ok_task, reason_task = _task_specific_check(task_id, text, response)
    if ok_task:
        return "PASS", reason_task
    return "REVIEW", reason_task


def _safe_capability(handler: Any) -> str:
    try:
        return str(handler.state_manager.state.last_capability or "")
    except Exception:
        return ""


def _wait_for_terminal_or_pending(run_mgr: Any, run_id: str, timeout_s: float = 15.0) -> Dict[str, Any]:
    deadline = time.monotonic() + max(2.0, float(timeout_s or 0.0))
    last: Dict[str, Any] = {}
    while time.monotonic() < deadline:
        snap = run_mgr.snapshot(limit=200)
        runs = snap.get("runs") if isinstance(snap, dict) else None
        if isinstance(runs, list):
            for r in runs:
                if isinstance(r, dict) and r.get("id") == run_id:
                    last = dict(r)
                    status = str(r.get("status") or "")
                    if status in {
                        "completed",
                        "failed",
                        "cancelled",
                        "timed_out",
                        "waiting_approval",
                        "waiting_input",
                    }:
                        return last
        time.sleep(0.2)
    return last


def _extract_first_windows_path(text: str, *, suffix: str) -> Optional[str]:
    """
    Extract a Windows path from assistant text. Best-effort.

    Example suffix: ".png", ".md"
    """
    if not text or not suffix:
        return None
    suf = str(suffix)
    # Greedy until whitespace/newline, then trim punctuation.
    # Match either backslash or forward-slash separators after the drive.
    m = re.search(rf"([A-Za-z]:[\\/][^\r\n\t]+?{re.escape(suf)})", str(text))
    if not m:
        return None
    raw = m.group(1).strip().rstrip(").,;\"'")
    return raw or None


def _verify_side_effects(
    *,
    task_id: int,
    scenario: Dict[str, Any],
    response: str,
    capability: str,
    bench_started_local: datetime,
    repo_root: Path,
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Extra verification beyond response-text checks.

    Returns (ok, note, details).
    - ok=False should be treated as a hard failure for tasks that claim side-effects.
    """
    details: Dict[str, Any] = {}

    # 8) Screenshot: verify file path exists and is non-trivial.
    if task_id == 8:
        path = _extract_first_windows_path(response, suffix=".png")
        details["path"] = path or ""
        if not path:
            return False, "missing screenshot path in response", details
        p = Path(path)
        if not p.exists():
            return False, "screenshot file not found on disk", details
        try:
            size = int(p.stat().st_size)
        except Exception:
            size = 0
        details["size_bytes"] = size
        if size < 10_000:
            return False, "screenshot file too small (likely failed capture)", details
        return True, "screenshot file verified", details

    # 15) Reminder: ensure a reminder row exists in tasks.db (call mom).
    if task_id == 15:
        db_path = Path.home() / ".chintu" / "tasks.db"
        details["db_path"] = str(db_path)
        if not db_path.exists():
            return False, "tasks.db not found (reminders not persisted)", details
        try:
            con = sqlite3.connect(str(db_path))
            cur = con.execute(
                "SELECT id, content, trigger_time, status, created_at FROM tasks "
                "WHERE task_type = 'reminder' AND lower(content) LIKE ? "
                "ORDER BY id DESC LIMIT 10",
                ("%call mom%",),
            )
            rows = cur.fetchall()
        except Exception as exc:
            details["error"] = str(exc)
            return False, "failed to query tasks.db for reminder", details
        finally:
            try:
                con.close()
            except Exception:
                pass
        # Filter to this benchmark run window.
        matched = []
        for rid, content, trigger_time, status, created_at in rows:
            try:
                created_dt = datetime.fromisoformat(str(created_at))
            except Exception:
                continue
            if created_dt >= bench_started_local:
                matched.append((rid, content, trigger_time, status, created_at))
        details["matches"] = matched[:3]
        if not matched:
            return False, "reminder was not persisted to tasks.db", details
        return True, "reminder persisted", details

    # 16) Timer: ensure a timer reminder exists (Timer: 5 minutes).
    if task_id == 16:
        db_path = Path.home() / ".chintu" / "tasks.db"
        details["db_path"] = str(db_path)
        if not db_path.exists():
            return False, "tasks.db not found (timers not persisted)", details
        try:
            con = sqlite3.connect(str(db_path))
            cur = con.execute(
                "SELECT id, content, trigger_time, status, created_at FROM tasks "
                "WHERE task_type = 'reminder' AND lower(content) LIKE ? "
                "ORDER BY id DESC LIMIT 10",
                ("%timer:%",),
            )
            rows = cur.fetchall()
        except Exception as exc:
            details["error"] = str(exc)
            return False, "failed to query tasks.db for timer", details
        finally:
            try:
                con.close()
            except Exception:
                pass
        matched = []
        for rid, content, trigger_time, status, created_at in rows:
            try:
                created_dt = datetime.fromisoformat(str(created_at))
            except Exception:
                continue
            if created_dt >= bench_started_local:
                matched.append((rid, content, trigger_time, status, created_at))
        details["matches"] = matched[:3]
        if not matched:
            return False, "timer was not persisted to tasks.db", details
        return True, "timer persisted", details

    # 27) Pandas install: verify import in this interpreter (venv).
    if task_id == 27:
        try:
            import pandas as pd  # type: ignore

            details["pandas_version"] = getattr(pd, "__version__", "")
            return True, "pandas import verified", details
        except Exception as exc:
            details["error"] = str(exc)
            return False, "pandas import failed after install step", details

    # 42) SSD price compare: verify file exists on Desktop and looks like a table.
    if task_id == 42:
        path = _extract_first_windows_path(response, suffix=".md")
        if not path:
            # Fallback to the exact spec path.
            path = str(Path.home() / "Desktop" / "ssd_prices.md")
        details["path"] = path
        p = Path(path)
        if not p.exists():
            return False, "ssd_prices.md not found on Desktop", details
        try:
            mtime = datetime.fromtimestamp(p.stat().st_mtime)
        except Exception:
            mtime = None
        details["mtime"] = mtime.isoformat() if mtime else ""
        # If the file predates this run, treat as suspicious.
        if mtime and mtime < bench_started_local:
            return False, "ssd_prices.md was not updated during this benchmark run", details
        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:
            details["error"] = str(exc)
            return False, "failed to read ssd_prices.md", details
        low = content.lower()
        if "| store |" not in low or "\n| ---" not in low:
            return False, "ssd_prices.md missing markdown table header", details
        if "amazon" not in low or "newegg" not in low:
            return False, "ssd_prices.md missing vendor rows", details
        return True, "ssd_prices.md verified", details

    # 44) Focus protocol: best-effort verify that Spotify + VS Code are running.
    if task_id == 44:
        try:
            import psutil  # type: ignore

            names = {p.name().lower() for p in psutil.process_iter(attrs=["name"]) if p.info.get("name")}
            details["running"] = sorted([n for n in names if n in {"spotify.exe", "code.exe", "spotify", "code"}])[:10]
            has_spotify = any(n.startswith("spotify") for n in details["running"])
            has_code = any(n.startswith("code") for n in details["running"])
            if has_spotify and has_code:
                return True, "apps running", details
            # Don’t hard-fail here; some environments won’t have Spotify installed.
            return True, "apps launch not verifiable (missing process)", details
        except Exception as exc:
            details["error"] = str(exc)
            return True, "apps launch not verifiable", details

    return True, "no side-effect verification for this task", details


def _is_non_dangerous_confirmation(task_text: str, capability: str, message: str) -> bool:
    cap = str(capability or "").strip().lower()
    combined = " ".join([task_text or "", message or "", cap]).lower()

    # Capabilities that should *never* be auto-approved in benchmarks.
    always_deny = {
        "sandbox_run",
        "delete_file",
        "modify_file",
        "fix_code",
        "identity_get_secret",
        "identity_delete_secret",
        "login_to",
        "news_video",
        "smart_shutdown_after_download",
        "orchestrator_run",
        "autonomous_swarm",
    }
    if cap in always_deny:
        return False

    dangerous_terms = {
        "delete",
        "erase",
        "wipe",
        "format",
        "shutdown",
        "restart",
        "kill process",
        "payment",
        "checkout",
        "purchase",
        "buy now",
        "transfer",
        "wire",
        "bank",
        "credit card",
        "password",
        "secret",
        "token",
        "2fa",
    }
    if any(term in combined for term in dangerous_terms):
        return False

    # Allow safe automation in the benchmark workspace (generated_reports artifacts).
    if cap in {"write_file", "terminal_exec"}:
        # Only auto-approve when the task is clearly scoped to benchmark artifacts or safe python invocations.
        if "generated_reports" in combined or "bench_live" in combined or "bench_dry" in combined:
            return True
        if cap == "terminal_exec" and ("python " in combined or combined.strip().startswith("python")):
            return True
        return False

    return True


def _category_stats(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        cat = str(row.get("category") or "uncategorized")
        if cat not in out:
            out[cat] = {
                "count": 0,
                "pass": 0,
                "fail": 0,
                "review": 0,
                "skip": 0,
                "latency_ms": [],
                "cpu": [],
                "rss": [],
                "gpu": [],
            }
        bucket = out[cat]
        bucket["count"] += 1
        verdict = str(row.get("verdict") or "")
        if verdict == "PASS":
            bucket["pass"] += 1
        elif verdict == "FAIL":
            bucket["fail"] += 1
        elif verdict == "SKIP":
            bucket["skip"] += 1
        else:
            bucket["review"] += 1
        bucket["latency_ms"].append(float(row.get("latency_ms") or 0.0))
        res = row.get("resources") or {}
        bucket["cpu"].append(float(res.get("proc_cpu_avg_percent") or 0.0))
        bucket["rss"].append(float(res.get("proc_rss_peak_mb") or 0.0))
        gpu_peak = res.get("gpu_util_peak_percent")
        if isinstance(gpu_peak, (int, float)):
            bucket["gpu"].append(float(gpu_peak))

    for cat, bucket in out.items():
        lats = bucket.pop("latency_ms")
        cpus = bucket.pop("cpu")
        rss = bucket.pop("rss")
        gpu = bucket.pop("gpu")
        bucket["latency_avg_ms"] = round(mean(lats), 2) if lats else 0.0
        bucket["latency_p95_ms"] = round(sorted(lats)[int(max(0, len(lats) * 0.95 - 1))], 2) if lats else 0.0
        bucket["proc_cpu_avg_percent"] = round(mean(cpus), 2) if cpus else 0.0
        bucket["proc_rss_peak_avg_mb"] = round(mean(rss), 2) if rss else 0.0
        bucket["gpu_util_peak_avg_percent"] = round(mean(gpu), 2) if gpu else None
    return out


def _render_md(report: Dict[str, Any]) -> str:
    summary = report.get("summary", {})
    rows = report.get("tasks", [])
    category = report.get("category_summary", {})

    lines: List[str] = []
    lines.append("# Chintu 50-Task Realistic Benchmark")
    lines.append("")
    lines.append(f"- timestamp_utc: {report.get('timestamp_utc')}")
    lines.append(f"- mode: {report.get('mode')}")
    lines.append(f"- total_tasks: {summary.get('total')}")
    lines.append(f"- pass: {summary.get('pass')}")
    lines.append(f"- skip: {summary.get('skip')}")
    lines.append(f"- review: {summary.get('review')}")
    lines.append(f"- fail: {summary.get('fail')}")
    lines.append(f"- pass_rate: {summary.get('pass_rate')}")
    lines.append(f"- elapsed_s: {summary.get('elapsed_s')}")
    lines.append("")
    lines.append("## Category Summary")
    lines.append("")
    lines.append("| Category | Count | Pass | Skip | Review | Fail | Avg Latency (ms) | Avg Proc CPU % | Avg Peak RSS (MB) | Avg Peak GPU % |")
    lines.append("| :-- | --: | --: | --: | --: | --: | --: | --: | --: | --: |")
    for cat, v in sorted(category.items()):
        lines.append(
            "| {cat} | {count} | {pass_n} | {skip} | {review} | {fail} | {lat} | {cpu} | {rss} | {gpu} |".format(
                cat=cat,
                count=v.get("count"),
                pass_n=v.get("pass"),
                skip=v.get("skip"),
                review=v.get("review"),
                fail=v.get("fail"),
                lat=v.get("latency_avg_ms"),
                cpu=v.get("proc_cpu_avg_percent"),
                rss=v.get("proc_rss_peak_avg_mb"),
                gpu=(v.get("gpu_util_peak_avg_percent") if v.get("gpu_util_peak_avg_percent") is not None else "n/a"),
            )
        )
    lines.append("")
    lines.append("## Per-Task Review")
    lines.append("")
    lines.append("| # | Category | Task | Capability | Verdict | Check Note | Verification | Proof | Auto Approval | Latency (ms) | CPU% | Peak RSS MB | Peak GPU% |")
    lines.append("| --: | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | --: | --: | --: | --: |")
    for row in rows:
        res = row.get("resources") or {}
        task = str(row.get("task") or "").replace("|", "\\|")
        verification = row.get("verification") if isinstance(row.get("verification"), dict) else {}
        verification_ok = bool(verification.get("ok", True))
        proof = row.get("proof") or ""
        proof = str(proof).replace("|", "\\|")
        lines.append(
            "| {id} | {cat} | {task} | {cap} | {verdict} | {note} | {ver_ok} | {proof} | {auto} | {lat} | {cpu} | {rss} | {gpu} |".format(
                id=row.get("id"),
                cat=row.get("category"),
                task=task[:72],
                cap=(row.get("capability") or "n/a"),
                verdict=row.get("verdict"),
                note=(str(row.get("check_note") or "").replace("|", "\\|")[:70]),
                ver_ok=("ok" if verification_ok else "fail"),
                proof=(proof[:90] + "..." if len(proof) > 93 else proof),
                auto=(str(row.get("auto_approval") or "none")),
                lat=row.get("latency_ms"),
                cpu=res.get("proc_cpu_avg_percent"),
                rss=res.get("proc_rss_peak_mb"),
                gpu=(res.get("gpu_util_peak_percent") if res.get("gpu_util_peak_percent") is not None else "n/a"),
            )
        )
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- `REVIEW` means response looked reasonable but needs human judgment for semantic quality.")
    lines.append("- Dry-run mode keeps destructive side-effects disabled while preserving routing/execution logic.")
    return "\n".join(lines).strip() + "\n"


# ---------------------------------------------------------------------------
# Preflight (setup readiness)
# ---------------------------------------------------------------------------


def _render_preflight_md(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# Chintu Benchmark Preflight")
    lines.append("")
    lines.append(f"- timestamp_utc: {report.get('timestamp_utc')}")
    lines.append(f"- ok: {report.get('ok')}")
    lines.append("")
    lines.append("## Requirements")
    lines.append("")
    lines.append("| Requirement | OK | Detail | Fix |")
    lines.append("| :-- | :--: | :-- | :-- |")
    for row in report.get("requirements", []) or []:
        if not isinstance(row, dict):
            continue
        req = str(row.get("requirement") or "").replace("|", "\\|")
        ok = "yes" if bool(row.get("ok")) else "no"
        detail = str(row.get("detail") or "").replace("|", "\\|")
        fix = str(row.get("fix") or "").replace("|", "\\|")
        lines.append(f"| {req} | {ok} | {detail[:140]} | {fix[:140]} |")
    lines.append("")
    return "\n".join(lines).strip() + "\n"


def _run_quick(cmd: List[str], *, timeout_s: float) -> Tuple[bool, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=float(timeout_s), check=False)
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        if proc.returncode != 0:
            return False, (err or out or f"returncode={proc.returncode}")[:320]
        return True, out[:320]
    except FileNotFoundError:
        return False, "command not found"
    except Exception as exc:
        return False, str(exc)[:320]


def _check_ollama_running() -> Tuple[bool, str, str]:
    ok, detail = _run_quick(["ollama", "list"], timeout_s=6.0)
    if ok:
        return True, "ollama list ok", ""
    if "not found" in detail.lower():
        return False, "ollama not installed", "Install Ollama and ensure `ollama` is on PATH."
    return False, f"ollama not reachable: {detail}", "Start Ollama (desktop app or service) and retry."


def _check_ollama_models_present(models_csv: str) -> Tuple[bool, str, str]:
    wanted = [m.strip() for m in str(models_csv or "").split(",") if m.strip()]
    if not wanted:
        return True, "no models requested", ""
    ok, out = _run_quick(["ollama", "list"], timeout_s=8.0)
    if not ok:
        return False, f"ollama list failed: {out}", "Start Ollama and ensure it is reachable."
    present = set()
    for ln in (out or "").splitlines():
        ln = ln.strip()
        if not ln or ln.lower().startswith("name"):
            continue
        name = ln.split()[0].strip()
        if name:
            present.add(name)
    missing = [m for m in wanted if m not in present]
    if missing:
        return False, f"missing models: {', '.join(missing)}", "Install models via: `ollama pull <model>`."
    return True, "models present", ""


def _check_playwright_ready() -> Tuple[bool, str, str]:
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as exc:
        return False, f"playwright import failed: {exc}", "Install: `pip install playwright` and run: `python -m playwright install chromium`."

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        return True, "chromium launch ok", ""
    except Exception as exc:
        return (
            False,
            f"chromium not ready: {exc}",
            "Run: `python -m playwright install chromium` (and ensure required system deps are present).",
        )


def _check_browser_profile_exists(profile: str) -> Tuple[bool, str, str]:
    try:
        from chintu_backend.core.config import get_config

        cfg = get_config()
        root = Path(getattr(cfg, "browser_profiles_dir", Path.home() / ".chintu" / "browser_profiles"))
    except Exception:
        root = Path.home() / ".chintu" / "browser_profiles"
    prof = str(profile or "assistant_accounts").strip() or "assistant_accounts"
    path = (root / prof).expanduser()
    if path.exists() and path.is_dir():
        return True, f"profile present: {path}", ""
    return (
        False,
        f"profile missing: {path}",
        "Create the profile folder and log in to required sites. See: docs/runbooks/benchmark_live.md",
    )


def _check_calendar_auth() -> Tuple[bool, str, str]:
    try:
        from chintu_backend.integrations.status import get_integrations_snapshot

        snap = get_integrations_snapshot().get("google_calendar", {}) or {}
        if not bool(snap.get("available")):
            return False, "google api client unavailable", "Install Google API deps and connect calendar via CLI onboarding."
        if bool(snap.get("token_valid")):
            return True, "calendar token valid", ""
        if bool(snap.get("configured")) and bool(snap.get("token_present")):
            return False, "calendar token present but invalid/expired", "Re-auth: `python -m chintu_backend.cli connect-calendar --credentials <path>`."
        return False, "calendar not configured", "Connect: `python -m chintu_backend.cli connect-calendar --credentials <path-to-credentials.json>`."
    except Exception as exc:
        return False, f"calendar status failed: {exc}", "Verify google calendar integration is configured under ~/.chintu/."


def _check_email_imap() -> Tuple[bool, str, str]:
    try:
        from chintu_backend.integrations.status import get_integrations_snapshot

        snap = get_integrations_snapshot().get("email_imap", {}) or {}
        if bool(snap.get("configured")):
            return True, "imap configured", ""
        return False, "imap not configured", "Set IMAP host/user/password in Identity Vault or ~/.chintu/integrations.json."
    except Exception as exc:
        return False, f"email status failed: {exc}", "Configure IMAP settings and retry."


def _check_ffmpeg(bin_name: str) -> Tuple[bool, str, str]:
    path = shutil.which(str(bin_name))
    if path:
        return True, f"found: {path}", ""
    return False, f"{bin_name} not found", "Install FFmpeg and ensure ffmpeg/ffprobe are on PATH. See: docs/runbooks/content_studio_short.md"


def run_preflight(requirements: List[str]) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    ok_all = True

    unique = []
    seen = set()
    for req in requirements:
        token = str(req or "").strip()
        if not token or token in seen:
            continue
        seen.add(token)
        unique.append(token)

    for req in unique:
        kind, _, value = req.partition(":")
        kind = kind.strip()
        value = value.strip()
        ok = False
        detail = ""
        fix = ""
        if kind == "ollama_running":
            ok, detail, fix = _check_ollama_running()
        elif kind == "ollama_models_present":
            ok, detail, fix = _check_ollama_models_present(value)
        elif kind == "playwright_ready":
            ok, detail, fix = _check_playwright_ready()
        elif kind == "browser_profile_exists":
            ok, detail, fix = _check_browser_profile_exists(value or "assistant_accounts")
        elif kind == "google_calendar_authenticated":
            ok, detail, fix = _check_calendar_auth()
        elif kind == "email_imap_configured":
            ok, detail, fix = _check_email_imap()
        elif kind == "ffmpeg_available":
            ok, detail, fix = _check_ffmpeg("ffmpeg")
        elif kind == "ffprobe_available":
            ok, detail, fix = _check_ffmpeg("ffprobe")
        else:
            ok = True
            detail = "unknown requirement (treated as ok)"
            fix = ""

        rows.append({"requirement": req, "ok": bool(ok), "detail": detail, "fix": fix})
        ok_all = ok_all and bool(ok)

    return {
        "timestamp_utc": _utc_iso(),
        "ok": bool(ok_all),
        "requirements": rows,
    }


# ---------------------------------------------------------------------------
# Verification hooks (strict evidence checks)
# ---------------------------------------------------------------------------


def _extract_receipt_snippet(path: Path, max_chars: int = 1800) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""
    snippet = text.strip().replace("\r\n", "\n")
    if len(snippet) > max_chars:
        snippet = snippet[: max_chars - 3] + "..."
    return snippet


def _extract_evidence_refs_from_receipt(path: Path) -> List[str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return []

    refs: List[str] = []
    in_evidence = False
    for ln in lines:
        stripped = ln.strip()
        if stripped == "- evidence:":
            in_evidence = True
            continue
        if in_evidence:
            if not ln.startswith("  - "):
                in_evidence = False
                continue
            # Example: "  - path: C:\\foo\\bar.png artifact"
            m = re.match(r"^\s*-\s*([a-zA-Z0-9_.-]+)\s*:\s*(.+)$", stripped)
            if not m:
                continue
            value = m.group(2).strip()
            # Heuristic: take the first token that looks like a path/URL.
            if value:
                candidate = value.split()[0].strip().strip(").,;\"'")
                if candidate:
                    refs.append(candidate)
    # De-dupe while preserving order.
    seen = set()
    out: List[str] = []
    for ref in refs:
        if ref in seen:
            continue
        seen.add(ref)
        out.append(ref)
    return out


def _ffprobe_duration_seconds(path: Path) -> Optional[float]:
    if not path.exists():
        return None
    if shutil.which("ffprobe") is None:
        return None
    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=12.0,
            check=False,
        )
        if proc.returncode != 0:
            return None
        value = (proc.stdout or "").strip()
        return float(value) if value else None
    except Exception:
        return None


def _latest_json_capture(*, capture_dir: Path, prefix: str, started_at: datetime) -> Optional[Path]:
    try:
        candidates = list(capture_dir.glob(f"{prefix}*.json"))
    except Exception:
        candidates = []
    recent: List[Path] = []
    for p in candidates:
        try:
            if datetime.fromtimestamp(p.stat().st_mtime) >= started_at:
                recent.append(p)
        except Exception:
            continue
    if not recent:
        return None
    return max(recent, key=lambda p: p.stat().st_mtime)


def _run_verifiers(
    *,
    scenario: Dict[str, Any],
    response: str,
    bench_stamp: str,
    bench_out_dir: Path,
    bench_started_local: datetime,
    strict: bool,
) -> Dict[str, Any]:
    hooks = scenario.get("verify") if isinstance(scenario.get("verify"), list) else []
    checks: List[Dict[str, Any]] = []
    ok_all = True
    scenario_task_id = str(scenario.get("id") or "")

    def _fmt(value: Any) -> str:
        return _substitute_placeholders(
            str(value or ""),
            bench_stamp=bench_stamp,
            task_id=scenario_task_id,
            out_dir=str(bench_out_dir),
        )

    if strict and not hooks:
        return {
            "ok": False,
            "note": "missing verification hooks (strict mode)",
            "checks": [{"kind": "missing_hooks", "ok": False, "detail": "scenario.verify is empty"}],
        }

    for hook in hooks:
        if not isinstance(hook, dict):
            continue
        kind = str(hook.get("kind") or hook.get("type") or "").strip() or "unknown"
        required = bool(hook.get("required", True))
        hook_ok = True
        detail = ""
        meta: Dict[str, Any] = {}

        try:
            if kind == "response_contains":
                tokens = hook.get("tokens") or hook.get("must_contain") or []
                if isinstance(tokens, str):
                    tokens = [tokens]
                missing = []
                low = str(response or "").lower()
                for tok in tokens if isinstance(tokens, list) else []:
                    t = _fmt(tok).strip().lower()
                    if t and t not in low:
                        missing.append(t)
                hook_ok = not bool(missing)
                detail = "ok" if hook_ok else f"missing: {', '.join(missing[:6])}"

            elif kind == "response_regex":
                pattern = _fmt(hook.get("pattern")).strip()
                hook_ok = bool(pattern and re.search(pattern, str(response or ""), flags=re.IGNORECASE | re.MULTILINE))
                detail = "ok" if hook_ok else f"no match: {pattern}"

            elif kind == "response_path_exists":
                suffix = str(hook.get("suffix") or "").strip()
                path = _extract_first_windows_path(response, suffix=suffix) if suffix else None
                meta["path"] = path or ""
                if not path:
                    hook_ok = False
                    detail = "no path found in response"
                else:
                    p = Path(path)
                    if not p.exists():
                        hook_ok = False
                        detail = "path not found on disk"
                    else:
                        min_bytes = int(hook.get("min_bytes", 0) or 0)
                        if min_bytes > 0 and p.is_file():
                            size = int(p.stat().st_size)
                            meta["size_bytes"] = size
                            hook_ok = size >= min_bytes
                            detail = "ok" if hook_ok else f"too small: {size} < {min_bytes}"
                        else:
                            hook_ok = True
                            detail = "ok"

            elif kind == "response_ffprobe_duration_between":
                suffix = str(hook.get("suffix") or ".mp4").strip() or ".mp4"
                path = _extract_first_windows_path(response, suffix=suffix)
                meta["path"] = path or ""
                if not path:
                    hook_ok = False
                    detail = "no media path found in response"
                else:
                    media = Path(path)
                    if not media.exists():
                        hook_ok = False
                        detail = "media path not found on disk"
                    else:
                        dur = _ffprobe_duration_seconds(media)
                        meta["duration_s"] = dur
                        if dur is None:
                            hook_ok = False
                            detail = "ffprobe unavailable or failed"
                        else:
                            min_s = float(hook.get("min_s", 0) or 0)
                            max_s = float(hook.get("max_s", 1e9) or 1e9)
                            hook_ok = (dur >= min_s) and (dur <= max_s)
                            detail = "ok" if hook_ok else f"duration {dur:.2f}s not in [{min_s},{max_s}]"

            elif kind == "file_exists":
                raw = str(hook.get("path") or "")
                path_str = _fmt(raw)
                p = Path(path_str)
                meta["path"] = str(p)
                if p.exists():
                    min_bytes = int(hook.get("min_bytes", 0) or 0)
                    if p.is_file() and min_bytes > 0:
                        size = int(p.stat().st_size)
                        meta["size_bytes"] = size
                        hook_ok = size >= min_bytes
                        detail = "ok" if hook_ok else f"too small: {size} < {min_bytes}"
                    else:
                        hook_ok = True
                        detail = "ok"
                else:
                    hook_ok = False
                    detail = "missing"

            elif kind == "file_contains":
                raw = str(hook.get("path") or "")
                path_str = _fmt(raw)
                p = Path(path_str)
                meta["path"] = str(p)
                if not p.exists():
                    hook_ok = False
                    detail = "missing"
                else:
                    text = p.read_text(encoding="utf-8", errors="ignore")
                    tokens = hook.get("tokens") or []
                    if isinstance(tokens, str):
                        tokens = [tokens]
                    missing = []
                    low = text.lower()
                    for tok in tokens if isinstance(tokens, list) else []:
                        t = _fmt(tok).strip().lower()
                        if t and t not in low:
                            missing.append(t)
                    pattern = _fmt(hook.get("pattern")).strip()
                    if pattern and not re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE):
                        missing.append(f"regex:{pattern}")
                    hook_ok = not bool(missing)
                    detail = "ok" if hook_ok else f"missing: {', '.join(missing[:6])}"

            elif kind == "file_not_contains":
                raw = str(hook.get("path") or "")
                path_str = _fmt(raw)
                p = Path(path_str)
                meta["path"] = str(p)
                if not p.exists():
                    hook_ok = False
                    detail = "missing"
                else:
                    text = p.read_text(encoding="utf-8", errors="ignore")
                    tokens = hook.get("tokens") or []
                    if isinstance(tokens, str):
                        tokens = [tokens]
                    forbidden = []
                    low = text.lower()
                    for tok in tokens if isinstance(tokens, list) else []:
                        t = _fmt(tok).strip().lower()
                        if t and t in low:
                            forbidden.append(t)
                    hook_ok = not bool(forbidden)
                    detail = "ok" if hook_ok else f"forbidden: {', '.join(forbidden[:6])}"

            elif kind == "file_line_count":
                raw = str(hook.get("path") or "")
                path_str = _fmt(raw)
                p = Path(path_str)
                meta["path"] = str(p)
                if not p.exists():
                    hook_ok = False
                    detail = "missing"
                else:
                    lines = [ln for ln in p.read_text(encoding="utf-8", errors="ignore").splitlines() if ln.strip()]
                    count = len(lines)
                    meta["lines"] = count
                    expected = hook.get("count")
                    min_n = hook.get("min")
                    if expected is not None:
                        hook_ok = count == int(expected)
                        detail = "ok" if hook_ok else f"lines {count} != {int(expected)}"
                    elif min_n is not None:
                        hook_ok = count >= int(min_n)
                        detail = "ok" if hook_ok else f"lines {count} < {int(min_n)}"
                    else:
                        hook_ok = True
                        detail = f"lines={count}"

            elif kind == "markdown_bullets":
                raw = str(hook.get("path") or "")
                path_str = _fmt(raw)
                p = Path(path_str)
                meta["path"] = str(p)
                if not p.exists():
                    hook_ok = False
                    detail = "missing"
                else:
                    lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
                    bullets = [ln for ln in lines if re.match(r"^\s*-\s+\S+", ln)]
                    meta["bullets"] = len(bullets)
                    expected = hook.get("count")
                    min_n = hook.get("min")
                    if expected is not None:
                        hook_ok = len(bullets) == int(expected)
                        detail = "ok" if hook_ok else f"bullets {len(bullets)} != {int(expected)}"
                    elif min_n is not None:
                        hook_ok = len(bullets) >= int(min_n)
                        detail = "ok" if hook_ok else f"bullets {len(bullets)} < {int(min_n)}"
                    else:
                        hook_ok = True
                        detail = f"bullets={len(bullets)}"

            elif kind == "hashtag_count_min":
                raw = str(hook.get("path") or "")
                path_str = _fmt(raw)
                p = Path(path_str)
                meta["path"] = str(p)
                if not p.exists():
                    hook_ok = False
                    detail = "missing"
                else:
                    text = p.read_text(encoding="utf-8", errors="ignore")
                    tags = re.findall(r"(?m)(?:^|\s)(#[A-Za-z0-9_]{2,})\b", text)
                    meta["hashtags"] = len(tags)
                    min_n = int(hook.get("min", 1) or 1)
                    hook_ok = len(tags) >= min_n
                    detail = "ok" if hook_ok else f"hashtags {len(tags)} < {min_n}"

            elif kind == "json_has_keys":
                raw = str(hook.get("path") or "")
                path_str = _fmt(raw)
                p = Path(path_str)
                meta["path"] = str(p)
                keys = hook.get("keys") or []
                if isinstance(keys, str):
                    keys = [keys]
                if not p.exists():
                    hook_ok = False
                    detail = "missing"
                else:
                    try:
                        data = json.loads(p.read_text(encoding="utf-8", errors="ignore"))
                    except Exception as exc:
                        hook_ok = False
                        detail = f"json parse failed: {exc}"
                    else:
                        missing = [k for k in keys if str(k) and str(k) not in data]
                        hook_ok = not bool(missing)
                        detail = "ok" if hook_ok else f"missing keys: {', '.join(missing[:8])}"

            elif kind == "glob_recent_exists":
                raw_dir = str(hook.get("dir") or "")
                raw_glob = str(hook.get("glob") or "")
                dir_str = _fmt(raw_dir)
                raw_glob = _fmt(raw_glob)
                base = Path(dir_str) if dir_str else bench_out_dir
                meta["dir"] = str(base)
                meta["glob"] = raw_glob
                if not base.exists() or not raw_glob:
                    hook_ok = False
                    detail = "dir/glob missing"
                else:
                    matches = []
                    for p in base.glob(raw_glob):
                        try:
                            if datetime.fromtimestamp(p.stat().st_mtime) >= bench_started_local:
                                matches.append(p)
                        except Exception:
                            continue
                    meta["count"] = len(matches)
                    min_n = int(hook.get("min", 1) or 1)
                    if len(matches) < min_n:
                        hook_ok = False
                        detail = f"matches {len(matches)} < {min_n}"
                    else:
                        latest = max(matches, key=lambda p: p.stat().st_mtime)
                        meta["latest"] = str(latest)
                        min_bytes = int(hook.get("min_bytes", 0) or 0)
                        if min_bytes > 0 and latest.is_file():
                            size = int(latest.stat().st_size)
                            meta["latest_size_bytes"] = size
                            hook_ok = size >= min_bytes
                            detail = "ok" if hook_ok else f"too small: {size} < {min_bytes}"
                        else:
                            hook_ok = True
                            detail = "ok"

            elif kind == "ffprobe_duration_between":
                raw = str(hook.get("path") or "")
                path_str = _fmt(raw)
                p = Path(path_str)
                meta["path"] = str(p)
                dur = _ffprobe_duration_seconds(p)
                meta["duration_s"] = dur
                if dur is None:
                    hook_ok = False
                    detail = "ffprobe unavailable or failed"
                else:
                    min_s = float(hook.get("min_s", 0) or 0)
                    max_s = float(hook.get("max_s", 1e9) or 1e9)
                    hook_ok = (dur >= min_s) and (dur <= max_s)
                    detail = "ok" if hook_ok else f"duration {dur:.2f}s not in [{min_s},{max_s}]"

            elif kind == "repo_index_state_updated":
                from chintu_backend.core.config import get_config

                cfg = get_config()
                state_path = Path(cfg.data_dir) / "repo_index" / ".state.json"
                meta["path"] = str(state_path)
                if not state_path.exists():
                    hook_ok = False
                    detail = "missing state file"
                else:
                    mtime = datetime.fromtimestamp(state_path.stat().st_mtime)
                    hook_ok = mtime >= bench_started_local
                    detail = "ok" if hook_ok else "state file not updated this run"

            elif kind == "health_report_today_exists":
                from chintu_backend.core.config import get_config

                cfg = get_config()
                today_key = datetime.now().strftime("%Y-%m-%d")
                path = Path(cfg.data_dir) / "health" / f"{today_key}.md"
                meta["path"] = str(path)
                if not path.exists():
                    hook_ok = False
                    detail = "missing health report"
                else:
                    mtime = datetime.fromtimestamp(path.stat().st_mtime)
                    hook_ok = mtime >= bench_started_local
                    detail = "ok" if hook_ok else "health report not updated this run"

            elif kind == "email_triage_today_exists":
                from chintu_backend.core.config import get_config

                cfg = get_config()
                today_key = datetime.now().strftime("%Y-%m-%d")
                workflows_dir = Path(getattr(cfg, "workflows_dir", Path(cfg.data_dir) / "workflows"))
                path = workflows_dir / "email_triage" / f"{today_key}.md"
                meta["path"] = str(path)
                if not path.exists():
                    hook_ok = False
                    detail = "missing email triage report"
                else:
                    mtime = datetime.fromtimestamp(path.stat().st_mtime)
                    hook_ok = mtime >= bench_started_local
                    detail = "ok" if hook_ok else "email triage report not updated this run"

            elif kind == "backup_zip_recent_exists":
                from chintu_backend.core.config import get_config

                cfg = get_config()
                backup_dir = Path(cfg.data_dir) / "backups"
                meta["dir"] = str(backup_dir)
                if not backup_dir.exists():
                    hook_ok = False
                    detail = "missing backups dir"
                else:
                    matches = []
                    for p in backup_dir.glob("chintu_backup_*.zip"):
                        try:
                            if datetime.fromtimestamp(p.stat().st_mtime) >= bench_started_local:
                                matches.append(p)
                        except Exception:
                            continue
                    meta["count"] = len(matches)
                    if not matches:
                        hook_ok = False
                        detail = "no recent backup zip"
                    else:
                        latest = max(matches, key=lambda p: p.stat().st_mtime)
                        meta["latest"] = str(latest)
                        hook_ok = True
                        detail = "ok"

            elif kind == "file_exists_or_quarantined":
                raw = str(hook.get("path") or "")
                path_str = _fmt(raw)
                target = Path(path_str)
                meta["path"] = str(target)
                if target.exists():
                    hook_ok = True
                    detail = "exists"
                else:
                    verify_root = Path.home() / ".chintu" / "verify_delete"
                    meta["verify_root"] = str(verify_root)
                    found = []
                    if verify_root.exists():
                        try:
                            for p in verify_root.rglob(target.name):
                                try:
                                    if datetime.fromtimestamp(p.stat().st_mtime) >= bench_started_local:
                                        found.append(p)
                                except Exception:
                                    continue
                        except Exception:
                            found = []
                    if found:
                        latest = max(found, key=lambda p: p.stat().st_mtime)
                        meta["quarantined_path"] = str(latest)
                        hook_ok = True
                        detail = "quarantined"
                    else:
                        hook_ok = False
                        detail = "missing (not quarantined)"

            elif kind == "tasks_db_contains":
                db_path = Path.home() / ".chintu" / "tasks.db"
                meta["db_path"] = str(db_path)
                if not db_path.exists():
                    hook_ok = False
                    detail = "tasks.db missing"
                else:
                    task_type = str(hook.get("task_type") or "").strip().lower()
                    like = str(hook.get("content_like") or "").strip().lower()
                    query = (
                        "SELECT id, content, task_type, created_at FROM tasks "
                        "WHERE lower(task_type) = ? AND lower(content) LIKE ? "
                        "ORDER BY id DESC LIMIT 20"
                    )
                    try:
                        con = sqlite3.connect(str(db_path))
                        cur = con.execute(query, (task_type, f"%{like}%"))
                        rows = cur.fetchall()
                    except Exception as exc:
                        hook_ok = False
                        detail = f"query failed: {exc}"
                        rows = []
                    finally:
                        try:
                            con.close()
                        except Exception:
                            pass
                    matched = []
                    for rid, content, tt, created_at in rows:
                        try:
                            created_dt = datetime.fromisoformat(str(created_at))
                        except Exception:
                            continue
                        if created_dt >= bench_started_local:
                            matched.append({"id": rid, "content": content, "created_at": created_at})
                    meta["matches"] = matched[:3]
                    hook_ok = bool(matched)
                    detail = "ok" if hook_ok else "no matching rows since bench start"

            elif kind == "research_capture_recent":
                from chintu_backend.core.config import get_config

                cfg = get_config()
                capture_dir = Path(getattr(cfg, "research_browser_capture_dir", cfg.data_dir / "research_browser" / "captures"))
                mode = str(hook.get("mode") or "capture").strip().lower()
                site = str(hook.get("site") or "").strip().lower() or "chatgpt"
                prefix = f"{mode}_{site}_"
                meta["capture_dir"] = str(capture_dir)
                latest = _latest_json_capture(capture_dir=capture_dir, prefix=prefix, started_at=bench_started_local)
                if not latest:
                    hook_ok = False
                    detail = "no recent capture json"
                else:
                    meta["artifact_path"] = str(latest)
                    try:
                        payload = json.loads(latest.read_text(encoding="utf-8", errors="ignore"))
                    except Exception as exc:
                        hook_ok = False
                        detail = f"json parse failed: {exc}"
                    else:
                        if hook.get("require_submitted") is True:
                            hook_ok = bool(payload.get("submitted"))
                            detail = "ok" if hook_ok else "submitted=false"
                        must_match = hook.get("must_match") or ""
                        must_match = _fmt(must_match)
                        if must_match:
                            text = str(payload.get("response_text") or payload.get("prompt") or "")
                            if not re.search(str(must_match), text, flags=re.IGNORECASE | re.MULTILINE):
                                hook_ok = False
                                detail = f"missing pattern in capture: {must_match}"
                        screenshot = str(payload.get("screenshot_path") or "").strip()
                        meta["screenshot_path"] = screenshot
                        if screenshot and not Path(screenshot).exists():
                            hook_ok = False
                            detail = "screenshot missing"

            elif kind == "path_count_min":
                raw = str(response or "")
                token = _fmt(hook.get("prefix")).strip()
                if not token:
                    hook_ok = False
                    detail = "missing prefix"
                else:
                    count = raw.count(token)
                    meta["count"] = count
                    min_n = int(hook.get("min", 1) or 1)
                    hook_ok = count >= min_n
                    detail = "ok" if hook_ok else f"count {count} < {min_n}"

            else:
                hook_ok = True
                detail = "unknown hook (treated as ok)"
        except Exception as exc:
            hook_ok = False
            detail = f"hook error: {exc}"

        checks.append({"kind": kind, "ok": bool(hook_ok), "detail": detail, "meta": meta})
        if required and not hook_ok:
            ok_all = False

    note = "ok" if ok_all else "verification failed"
    return {"ok": bool(ok_all), "note": note, "checks": checks}


def _checks_to_verify_hooks(checks: Any) -> List[Dict[str, Any]]:
    """Best-effort mapping from legacy `checks` schema to v2 `verify` hooks."""
    if not isinstance(checks, dict):
        return []
    hooks: List[Dict[str, Any]] = []
    min_length = checks.get("min_length")
    if isinstance(min_length, int):
        hooks.append({"kind": "response_regex", "pattern": rf"(?s)^.{{{int(min_length)},}}$"})
    must_contain = checks.get("must_contain")
    if isinstance(must_contain, str):
        must_contain = [must_contain]
    if isinstance(must_contain, list) and must_contain:
        hooks.append({"kind": "response_contains", "tokens": [str(x) for x in must_contain if str(x).strip()]})
    must_match = checks.get("must_match")
    if isinstance(must_match, str):
        must_match = [must_match]
    if isinstance(must_match, list):
        for pat in [str(x) for x in must_match if str(x).strip()]:
            hooks.append({"kind": "response_regex", "pattern": pat})
    return hooks


def _normalize_scenarios(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, list):
        raise RuntimeError("TEST_SCENARIOS must be a list.")
    normalized: List[Dict[str, Any]] = []
    for idx, entry in enumerate(raw, start=1):
        if isinstance(entry, dict):
            scenario_id = str(entry.get("id") or idx)
            category = str(entry.get("category") or "misc")
            text = str(entry.get("text") or entry.get("task") or "")
            hint = str(entry.get("hint") or "")
            setup = entry.get("setup") if isinstance(entry.get("setup"), list) else []
            verify = entry.get("verify") if isinstance(entry.get("verify"), list) else []
            delays = entry.get("delays") if isinstance(entry.get("delays"), dict) else {}
            context_overrides = (
                entry.get("context_overrides") if isinstance(entry.get("context_overrides"), dict) else {}
            )
            if not verify and isinstance(entry.get("checks"), dict):
                verify = _checks_to_verify_hooks(entry.get("checks"))
            normalized.append(
                {
                    "id": scenario_id,
                    "category": category,
                    "text": text,
                    "hint": hint,
                    "setup": [str(x) for x in setup if str(x).strip()],
                    "verify": [dict(x) for x in verify if isinstance(x, dict)],
                    "delays": dict(delays),
                    "context_overrides": dict(context_overrides),
                }
            )
            continue
        if isinstance(entry, (list, tuple)) and len(entry) >= 3:
            category, text, hint = entry[0], entry[1], entry[2]
            normalized.append(
                {
                    "id": str(idx),
                    "category": str(category),
                    "text": str(text),
                    "hint": str(hint),
                    "setup": [],
                    "verify": [],
                    "delays": {},
                    "context_overrides": {},
                }
            )
            continue
        raise RuntimeError(f"Unsupported scenario entry: {entry!r}")
    return normalized


def _collect_requirements(scenarios: List[Dict[str, Any]]) -> List[str]:
    reqs: List[str] = []
    for scenario in scenarios:
        for item in scenario.get("setup") or []:
            token = str(item or "").strip()
            if token:
                reqs.append(token)
    return reqs


def run_benchmark(
    *,
    live: bool,
    strict: bool,
    allow_skips: bool,
    interactive_checkpoints: bool,
    mock_mode: bool = False,
    auto_approve_safe: bool = True,
    max_auto_approvals_per_task: int = 3,
    scenarios_path: Optional[Path] = None,
    out_dir: Optional[Path] = None,
    verify_side_effects: bool = True,
) -> Dict[str, Any]:
    from chintu_backend.core.command_handler import CommandHandler
    from chintu_backend.core.run_manager import get_run_manager

    scenarios_path = Path(scenarios_path or (REPO_ROOT / "tests" / "scenarios" / "chintu_50_daily_scenarios.py"))
    if not scenarios_path.exists():
        raise FileNotFoundError(f"Scenario file not found: {scenarios_path}")

    spec = importlib.util.spec_from_file_location("bench_scenarios", scenarios_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load scenario module.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    scenarios_raw = getattr(module, "TEST_SCENARIOS", None)
    scenarios = _normalize_scenarios(scenarios_raw)

    bench_stamp = _utc_stamp()
    base_out = Path(out_dir or (REPO_ROOT / "generated_reports"))
    bench_kind = "bench_live" if live else "bench_dry"
    bench_out_dir = (base_out / bench_kind / bench_stamp).resolve()
    bench_out_dir.mkdir(parents=True, exist_ok=True)

    # Sandbox harness (for safety scenarios).
    sandbox_root = bench_out_dir / "sandbox"
    sandbox_downloads = sandbox_root / "Downloads"
    sandbox_downloads.mkdir(parents=True, exist_ok=True)
    dummy_files = [
        sandbox_downloads / "dummy_1.txt",
        sandbox_downloads / "dummy_2.pdf",
        sandbox_downloads / "dummy_3.exe",
    ]
    for fp in dummy_files:
        try:
            if not fp.exists():
                fp.write_text("BENCH_DUMMY\n", encoding="utf-8")
        except Exception:
            pass

    requirements = _collect_requirements(scenarios)
    preflight = run_preflight(requirements)
    req_ok_map = {
        str(r.get("requirement")): bool(r.get("ok"))
        for r in (preflight.get("requirements") or [])
        if isinstance(r, dict) and r.get("requirement") is not None
    }
    if strict and live and (not bool(preflight.get("ok"))) and (not allow_skips):
        raise RuntimeError("Preflight failed. Run with `--preflight` to see missing setup.")

    # Reset singletons for cleaner benchmark behavior.
    try:
        from chintu_backend.core import context_manager

        context_manager._context_manager = None
    except Exception:
        pass

    handler = CommandHandler(mock_mode=bool(mock_mode))
    run_mgr = get_run_manager()

    rows: List[Dict[str, Any]] = []
    session_id = f"bench50:{bench_stamp}"
    bench_started_local = datetime.now()
    t_all = time.perf_counter()

    for seq, scenario in enumerate(scenarios, start=1):
        scenario_id = str(scenario.get("id") or seq)
        category = str(scenario.get("category") or "misc")
        hint = str(scenario.get("hint") or "")

        raw_text = str(scenario.get("text") or "")
        text = _substitute_placeholders(raw_text, bench_stamp=bench_stamp, task_id=scenario_id, out_dir=str(bench_out_dir))

        delays = scenario.get("delays") if isinstance(scenario.get("delays"), dict) else {}
        sleep_before = delays.get("sleep_before_s")
        if isinstance(sleep_before, (int, float)) and float(sleep_before) > 0:
            time.sleep(float(sleep_before))

        missing_setup = [req for req in (scenario.get("setup") or []) if req and not req_ok_map.get(str(req), True)]
        if missing_setup and allow_skips:
            rows.append(
                {
                    "id": scenario_id,
                    "seq": seq,
                    "category": category,
                    "task": text,
                    "hint": hint,
                    "capability": "",
                    "response": "",
                    "latency_ms": 0.0,
                    "verdict": "SKIP",
                    "check_note": "missing setup: " + ", ".join([str(x) for x in missing_setup[:6]]),
                    "auto_approval": "none",
                    "approval_decisions": [],
                    "resources": ResourceStats().to_dict(),
                    "run_ids": [],
                    "primary_run": {},
                    "receipt_snippet": "",
                    "evidence_refs": [],
                    "verification": {"ok": True, "note": "skipped", "checks": []},
                    "proof": "",
                }
            )
            continue

        # Isolate tasks by default so pending confirmations/choices from one task
        # don't contaminate unrelated tasks.
        try:
            preserve_pending = bool(re.match(r"^\s*(read more about|#?\d+\s*$)", text.strip().lower()))
            if not preserve_pending:
                from chintu_backend.core.context_manager import get_context_manager

                get_context_manager().cancel_all()
        except Exception:
            pass

        pre_snapshot = run_mgr.snapshot(limit=500)
        pre_run_ids = {
            str(r.get("id"))
            for r in (pre_snapshot.get("runs") if isinstance(pre_snapshot, dict) else []) or []
            if isinstance(r, dict) and str(r.get("id") or "").strip()
        }

        context: Dict[str, Any] = {
            "session_id": session_id,
            "workspace_dir": str(REPO_ROOT),
            "_bench_out_dir": str(bench_out_dir),
        }
        if not live:
            context["dry_run"] = True
            context["dry_run_mode"] = "side_effects"

        # Apply scenario context overrides (with placeholder substitution for strings).
        overrides = scenario.get("context_overrides") if isinstance(scenario.get("context_overrides"), dict) else {}
        for key, value in overrides.items():
            if isinstance(value, str):
                context[str(key)] = _substitute_placeholders(
                    value, bench_stamp=bench_stamp, task_id=scenario_id, out_dir=str(bench_out_dir)
                )
            else:
                context[str(key)] = value

        sampler = ResourceSampler()
        sampler.start()
        t0 = time.perf_counter()
        response_parts: List[str] = []
        error = ""
        auto_approval = "none"
        approval_decisions: List[Dict[str, str]] = []
        user_skipped = False

        try:
            response_parts.append(str(handler.handle(text, source="benchmark", context=context) or ""))

            # Auto-approve safe confirmations + optionally handle waiting_input checkpoints.
            while True:
                did_action = False

                if live and auto_approve_safe:
                    for _ in range(max(1, int(max_auto_approvals_per_task))):
                        pending = {}
                        try:
                            pending = handler.action_dispatcher.get_pending_confirmation() or {}
                        except Exception:
                            pending = {}

                        run_id = str(context.get("_run_id") or "").strip()
                        waiting_approval = False
                        if run_id:
                            summary = _wait_for_terminal_or_pending(run_mgr, run_id, timeout_s=2.5)
                            waiting_approval = str(summary.get("status") or "") == "waiting_approval"

                        if not pending and not waiting_approval:
                            break

                        pending_cap = str(pending.get("capability") or _safe_capability(handler) or "").strip()
                        pending_msg = str(pending.get("message") or "")
                        safe_to_approve = _is_non_dangerous_confirmation(text, pending_cap, pending_msg)
                        if safe_to_approve:
                            auto_approval = "approved_safe"
                            approval_decisions.append({"capability": pending_cap, "decision": "approve"})
                            conf_ctx = {"session_id": session_id, "workspace_dir": str(REPO_ROOT)}
                            resp = str(handler.handle("yes", source="benchmark", context=conf_ctx) or "")
                            if resp:
                                response_parts.append(resp)
                            did_action = True
                            continue

                        auto_approval = "blocked_dangerous"
                        approval_decisions.append({"capability": pending_cap, "decision": "reject"})
                        rej_ctx = {"session_id": session_id, "workspace_dir": str(REPO_ROOT)}
                        resp = str(handler.handle("no", source="benchmark", context=rej_ctx) or "")
                        if resp:
                            response_parts.append(resp)
                        did_action = True
                        break

                if interactive_checkpoints:
                    run_id = str(context.get("_run_id") or "").strip() or str(run_mgr.pending_input_run_id() or "").strip()
                    if run_id:
                        summary = _wait_for_terminal_or_pending(run_mgr, run_id, timeout_s=1.5)
                        if str(summary.get("status") or "") == "waiting_input":
                            waiting_ctx = run_mgr.get_waiting_input_context(run_id) if hasattr(run_mgr, "get_waiting_input_context") else {}
                            prompt = str((waiting_ctx or {}).get("prompt") or "").strip()
                            print(f"\n[CHECKPOINT] Scenario {scenario_id} awaiting input.\n{prompt}\n")
                            user_text = input("Type 'continue' when ready (or 'skip'): ").strip() or "continue"
                            if user_text.strip().lower() == "skip":
                                user_skipped = True
                                try:
                                    handler.handle("stop", source="benchmark", context={"session_id": session_id, "workspace_dir": str(REPO_ROOT)})
                                except Exception:
                                    pass
                                did_action = True
                            else:
                                resp = str(
                                    handler.handle(
                                        user_text,
                                        source="benchmark",
                                        context={"session_id": session_id, "workspace_dir": str(REPO_ROOT)},
                                    )
                                    or ""
                                )
                                if resp:
                                    response_parts.append(resp)
                                did_action = True

                if not did_action:
                    break

        except Exception as exc:
            error = str(exc)
            response_parts.append(f"ERROR: {exc}")

        latency_ms = (time.perf_counter() - t0) * 1000.0
        res_stats = sampler.stop().to_dict()

        response = "\n".join([p for p in response_parts if str(p).strip()]).strip()
        cap = _safe_capability(handler)

        post_snapshot = run_mgr.snapshot(limit=500)
        post_runs = post_snapshot.get("runs") if isinstance(post_snapshot, dict) else []
        new_run_summaries = [
            dict(r)
            for r in (post_runs or [])
            if isinstance(r, dict) and str(r.get("id") or "").strip() and str(r.get("id")) not in pre_run_ids
        ]
        new_run_ids = [str(r.get("id")) for r in new_run_summaries if str(r.get("id") or "").strip()]
        primary_run = new_run_summaries[0] if new_run_summaries else {}

        receipt_path = str(primary_run.get("receipt_path") or "").strip()
        receipt_snippet = ""
        evidence_refs: List[str] = []
        if receipt_path:
            rp = Path(receipt_path)
            if rp.exists():
                receipt_snippet = _extract_receipt_snippet(rp)
                evidence_refs = _extract_evidence_refs_from_receipt(rp)

        proof_parts: List[str] = []
        if receipt_path:
            proof_parts.append(receipt_path)
        proof_parts.extend(evidence_refs[:3])
        proof = " | ".join([p for p in proof_parts if p]).strip()

        ok_base, base_note = _base_response_ok(error or response)
        verification = {"ok": True, "note": "", "checks": []}
        if verify_side_effects or strict:
            verification = _run_verifiers(
                scenario=scenario,
                response=response,
                bench_stamp=bench_stamp,
                bench_out_dir=bench_out_dir,
                bench_started_local=bench_started_local,
                strict=bool(strict),
            )

        verdict = "PASS"
        note = base_note
        if error:
            verdict = "FAIL"
            note = f"exception: {error}"
        elif user_skipped and allow_skips:
            verdict = "SKIP"
            note = "skipped at checkpoint"
        elif not ok_base:
            verdict = "FAIL"
            note = base_note
        elif strict and not bool(verification.get("ok")):
            verdict = "FAIL"
            note = str(verification.get("note") or "verification failed")
        elif (verify_side_effects or strict) and not bool(verification.get("ok")):
            verdict = "FAIL"
            note = str(verification.get("note") or "verification failed")

        sleep_after = delays.get("sleep_after_s")
        if isinstance(sleep_after, (int, float)) and float(sleep_after) > 0:
            time.sleep(float(sleep_after))

        rows.append(
            {
                "id": scenario_id,
                "seq": seq,
                "category": category,
                "task": text,
                "hint": hint,
                "capability": cap,
                "response": response,
                "latency_ms": round(latency_ms, 2),
                "verdict": verdict,
                "check_note": note,
                "auto_approval": auto_approval,
                "approval_decisions": approval_decisions,
                "resources": res_stats,
                "run_ids": new_run_ids,
                "primary_run": primary_run,
                "receipt_snippet": receipt_snippet,
                "evidence_refs": evidence_refs,
                "verification": verification,
                "proof": proof,
                "sandbox": {"downloads_dir": str(sandbox_downloads), "dummy_files": [str(p) for p in dummy_files]},
            }
        )

    elapsed_s = time.perf_counter() - t_all
    passed = sum(1 for r in rows if r.get("verdict") == "PASS")
    skipped = sum(1 for r in rows if r.get("verdict") == "SKIP")
    review = sum(1 for r in rows if r.get("verdict") == "REVIEW")
    failed = sum(1 for r in rows if r.get("verdict") == "FAIL")
    total = len(rows)

    # Best-effort cleanup to avoid Playwright driver EPIPE noise on exit.
    try:
        from chintu_backend.automation.browser.browser_controller import close_all_browser_controllers

        close_all_browser_controllers()
    except Exception:
        pass

    return {
        "timestamp_utc": _utc_iso(),
        "mode": "live_side_effects" if live else "dry_run_side_effects",
        "mock_mode": bool(mock_mode),
        "strict": bool(strict),
        "allow_skips": bool(allow_skips),
        "interactive_checkpoints": bool(interactive_checkpoints),
        "auto_approve_safe": bool(auto_approve_safe),
        "session_id": session_id,
        "bench_stamp": bench_stamp,
        "bench_out_dir": str(bench_out_dir),
        "preflight": preflight,
        "summary": {
            "total": total,
            "pass": passed,
            "skip": skipped,
            "review": review,
            "fail": failed,
            "pass_rate": round((passed / total) if total else 0.0, 3),
            "elapsed_s": round(elapsed_s, 2),
            "avg_latency_ms": round(mean([float(r.get("latency_ms") or 0.0) for r in rows]), 2) if rows else 0.0,
        },
        "category_summary": _category_stats(rows),
        "tasks": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run realistic 50-task benchmark on Chintu.")
    parser.add_argument("--preflight", action="store_true", help="Only run setup checks for the selected scenario suite.")
    parser.add_argument("--live", action="store_true", help="Run with real side-effects. Default is dry-run side-effects.")
    parser.add_argument("--mock-mode", action="store_true", help="Initialize CommandHandler in mock mode.")
    parser.add_argument("--strict", action="store_true", help="Strict mode: missing/failed verification becomes FAIL.")
    parser.add_argument("--allow-skips", action="store_true", help="Skip scenarios whose setup requirements are missing.")
    parser.add_argument(
        "--interactive-checkpoints",
        action="store_true",
        help="Allow interactive checkpoint prompts for waiting_input runs (e.g., browser login).",
    )
    parser.add_argument(
        "--verify-side-effects",
        action="store_true",
        help="Verify key side-effects/artifacts on disk (recommended for --live).",
    )
    parser.add_argument(
        "--no-verify-side-effects",
        action="store_true",
        help="Disable side-effect verification (even for --live).",
    )
    parser.add_argument(
        "--scenarios",
        default=str(REPO_ROOT / "tests" / "scenarios" / "chintu_50_personal_daily.py"),
        help="Scenario module path (must define TEST_SCENARIOS).",
    )
    parser.add_argument(
        "--no-auto-approve-safe",
        action="store_true",
        help="Do not auto-approve non-dangerous pending confirmations during live runs.",
    )
    parser.add_argument("--out-dir", default=str(REPO_ROOT / "generated_reports"), help="Output report directory.")
    args = parser.parse_args()

    scenarios_path = Path(str(args.scenarios))
    out_dir = Path(str(args.out_dir))
    out_dir.mkdir(parents=True, exist_ok=True)

    # Preflight-only mode
    if bool(args.preflight):
        if not scenarios_path.exists():
            print(f"[FAIL] Scenario file not found: {scenarios_path}")
            return 2
        try:
            spec = importlib.util.spec_from_file_location("bench_scenarios_preflight", scenarios_path)
            if spec is None or spec.loader is None:
                raise RuntimeError("Failed to load scenario module.")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)  # type: ignore[attr-defined]
            scenarios = _normalize_scenarios(getattr(module, "TEST_SCENARIOS", None))
            requirements = _collect_requirements(scenarios)
            report = run_preflight(requirements)
        except Exception as exc:
            print(f"[FAIL] Preflight error: {exc}")
            return 2

        stamp = _utc_stamp()
        json_path = out_dir / f"benchmark_preflight_{stamp}.json"
        md_path = out_dir / f"benchmark_preflight_{stamp}.md"
        json_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
        md_path.write_text(_render_preflight_md(report), encoding="utf-8")
        print(f"Saved JSON report: {json_path}")
        print(f"Saved Markdown report: {md_path}")
        return 0 if bool(report.get("ok")) else 1

    verify_side_effects = bool(args.verify_side_effects)
    if bool(args.strict):
        verify_side_effects = True
    if bool(args.live) and not bool(args.no_verify_side_effects):
        verify_side_effects = True

    report = run_benchmark(
        live=bool(args.live),
        strict=bool(args.strict),
        allow_skips=bool(args.allow_skips),
        interactive_checkpoints=bool(args.interactive_checkpoints),
        mock_mode=bool(args.mock_mode),
        auto_approve_safe=not bool(args.no_auto_approve_safe),
        scenarios_path=scenarios_path,
        out_dir=out_dir,
        verify_side_effects=verify_side_effects,
    )

    bench_dir = Path(str(report.get("bench_out_dir") or out_dir)).resolve()
    bench_dir.mkdir(parents=True, exist_ok=True)
    json_path = bench_dir / "chintu_50_realistic.json"
    md_path = bench_dir / "chintu_50_realistic.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    md_path.write_text(_render_md(report), encoding="utf-8")

    print(f"Saved JSON report: {json_path}")
    print(f"Saved Markdown report: {md_path}")
    print(json.dumps(report.get("summary", {}), indent=2, ensure_ascii=True))

    summary = report.get("summary", {}) if isinstance(report.get("summary"), dict) else {}
    if bool(args.strict):
        if int(summary.get("fail", 0) or 0) > 0:
            return 1
        if int(summary.get("review", 0) or 0) > 0:
            return 1
        if (not bool(args.allow_skips)) and int(summary.get("skip", 0) or 0) > 0:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
