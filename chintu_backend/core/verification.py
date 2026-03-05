"""Lightweight, deterministic verification for capability results.

Goal: when Chintu says "done", we should have *some* evidence that a side-effect
likely happened (file exists, window visible, etc).

Design constraints:
- Never throws (verification must not break execution).
- Runs fast (no heavy scraping or long network calls).
- Prefer "strong" checks (files, windows) over "weak" checks (URL syntax).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse


@dataclass
class VerificationCheck:
    kind: str
    ok: bool
    value: str = ""
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "ok": bool(self.ok),
            "value": self.value,
            "detail": self.detail,
        }


def _safe_str(v: Any) -> str:
    try:
        return str(v)
    except Exception:
        return ""


_SYSTEM_WINDOWS_TO_HIDE = {
    "program manager",
    "windows input experience",
    "windows shell experience host",
    "default ime",
    "msctfime ui",
}

_BROWSER_MARKERS = (
    "google chrome",
    "chrome",
    "microsoft edge",
    "edge",
    "mozilla firefox",
    "firefox",
    "brave",
    "opera",
    "safari",
)


def _normalize_process_name(name: str) -> str:
    raw = (name or "").strip().lower()
    if raw.endswith(".exe"):
        raw = raw[:-4]
    return raw


def _list_running_process_names() -> set[str]:
    """Return a set of running process names (normalized), best-effort."""
    try:
        import psutil  # type: ignore
    except Exception:
        return set()

    names: set[str] = set()
    try:
        for proc in psutil.process_iter(attrs=["name"]):
            try:
                name = proc.info.get("name") if isinstance(proc.info, dict) else None
                norm = _normalize_process_name(_safe_str(name))
                if norm:
                    names.add(norm)
            except Exception:
                continue
    except Exception:
        return set()
    return names


def _candidates_for_process(label: str) -> List[str]:
    raw = (label or "").strip().lower()
    if not raw:
        return []

    # Normalize common display names to executable/process names.
    aliases = {
        "google chrome": ["chrome"],
        "chrome": ["chrome"],
        "microsoft edge": ["msedge", "edge"],
        "edge": ["msedge", "edge"],
        "mozilla firefox": ["firefox"],
        "firefox": ["firefox"],
        "visual studio code": ["code"],
        "vs code": ["code"],
        "vscode": ["code"],
        "notepad": ["notepad"],
        "calculator": ["calculatorapp", "calc"],
        "file explorer": ["explorer"],
        "explorer": ["explorer"],
        "task manager": ["taskmgr"],
        "windows terminal": ["wt"],
        "terminal": ["wt"],
        "powershell": ["powershell"],
        "command prompt": ["cmd"],
    }

    out: set[str] = set()
    out.add(_normalize_process_name(raw))
    for prefix in ("microsoft ", "google "):
        if raw.startswith(prefix):
            out.add(_normalize_process_name(raw[len(prefix) :].strip()))

    if raw in aliases:
        out.update([_normalize_process_name(x) for x in aliases[raw]])

    return [x for x in sorted(out) if x]


def _list_visible_window_titles() -> List[str]:
    """Return best-effort visible window titles (Windows-only in practice)."""
    try:
        import pygetwindow as gw  # type: ignore
    except Exception:
        return []

    titles: List[str] = []
    try:
        for w in gw.getAllWindows() or []:
            try:
                title = _safe_str(getattr(w, "title", "")).strip()
                visible = bool(getattr(w, "visible", True))
            except Exception:
                title = ""
                visible = True
            if not title or not visible:
                continue
            if title.lower() in _SYSTEM_WINDOWS_TO_HIDE:
                continue
            titles.append(title)
    except Exception:
        return []
    return titles


def _candidates_for_app(app_name: str) -> List[str]:
    raw = (app_name or "").strip().lower()
    if not raw:
        return []

    candidates = {raw}
    for prefix in ("microsoft ", "google "):
        if raw.startswith(prefix):
            candidates.add(raw[len(prefix) :].strip())

    # Simple aliases for common apps where window title often differs.
    aliases = {
        "visual studio code": ["vscode", "vs code", "code"],
        "google chrome": ["chrome"],
        "microsoft edge": ["edge"],
        "mozilla firefox": ["firefox"],
        "microsoft word": ["word"],
        "microsoft excel": ["excel"],
        "microsoft powerpoint": ["powerpoint"],
    }
    for key, vals in aliases.items():
        if raw == key:
            candidates.update(vals)

    return [c for c in sorted(candidates) if c]


def verify_action_result(result: Any) -> Dict[str, Any]:
    """Best-effort verification from ActionResult-like objects."""
    checks: List[VerificationCheck] = []

    cap_name = ""
    try:
        cap_name = _safe_str(getattr(result, "capability_name", "")).strip()
    except Exception:
        cap_name = ""

    try:
        success = bool(getattr(result, "success", False))
    except Exception:
        success = False

    # If the tool reported failure, we don't pretend it's verified.
    if not success:
        return {"ok": False, "checks": []}

    data: Optional[Any] = getattr(result, "data", None)
    if not isinstance(data, dict):
        return {"ok": False, "checks": []}

    # Exit code: deterministic signal for exec-like tools.
    if "exit_code" in data:
        try:
            exit_code = int(data.get("exit_code"))
            ok = exit_code == 0
            checks.append(
                VerificationCheck(
                    kind="exit_code_zero",
                    ok=ok,
                    value=str(exit_code),
                    detail="exit_code == 0" if ok else f"exit_code == {exit_code}",
                )
            )
        except Exception:
            checks.append(
                VerificationCheck(
                    kind="exit_code_zero",
                    ok=False,
                    value=_safe_str(data.get("exit_code")),
                    detail="error parsing exit_code",
                )
            )

    # Path artifacts: strongest, deterministic signal.
    seen_paths: set[str] = set()
    for key in ("path", "artifact_path", "file_path", "report_path", "screenshot", "filepath", "filename"):
        raw_value = data.get(key)
        if not raw_value:
            continue
        value = _safe_str(raw_value).strip()
        if not value or value in seen_paths:
            continue
        seen_paths.add(value)

        p = Path(value)
        ok = False
        detail = ""
        try:
            ok = p.exists()
            if ok and p.is_file():
                try:
                    size = p.stat().st_size
                    detail = f"{key}: file exists ({size} bytes)"
                except Exception:
                    detail = f"{key}: file exists"
            elif ok and p.is_dir():
                detail = f"{key}: dir exists"
            else:
                detail = f"{key}: missing"
        except Exception:
            ok = False
            detail = f"{key}: error checking path"
        checks.append(VerificationCheck(kind="path_exists", ok=ok, value=value, detail=detail))

    # URL: verify it's at least a valid absolute URL. (No network calls here.)
    url_value = data.get("url") or data.get("new_url")
    if url_value:
        raw = _safe_str(url_value)
        ok = False
        detail = ""
        try:
            parsed = urlparse(raw)
            ok = bool(parsed.scheme and parsed.netloc)
            detail = "valid url" if ok else "invalid url"
        except Exception:
            ok = False
            detail = "error parsing url"
        checks.append(VerificationCheck(kind="url_valid", ok=ok, value=raw, detail=detail))

        # For fetch/search tools that do not necessarily open a browser, content presence
        # is a strong success signal.
        if cap_name in {"browse_url", "page_content", "web_search", "news_search", "deep_search", "live_search"}:
            content = data.get("content")
            if isinstance(content, str):
                c_ok = len(content.strip()) > 0
                checks.append(
                    VerificationCheck(
                        kind="content_nonempty",
                        ok=c_ok,
                        value=str(len(content)),
                        detail="content present" if c_ok else "content empty",
                    )
                )

        # Best-effort: is a browser window visible?
        titles = _list_visible_window_titles()
        browser_ok = False
        try:
            lowered = " ".join([t.lower() for t in titles])
            browser_ok = any(m in lowered for m in _BROWSER_MARKERS)
        except Exception:
            browser_ok = False
        if titles:
            checks.append(
                VerificationCheck(
                    kind="browser_window_visible",
                    ok=browser_ok,
                    value="",
                    detail="browser window detected" if browser_ok else "no browser window detected",
                )
            )

        # Best-effort: is a browser process running?
        procs = _list_running_process_names()
        if procs:
            browser_candidates = {
                "chrome",
                "msedge",
                "firefox",
                "brave",
                "opera",
                "safari",
            }
            found = sorted([p for p in browser_candidates if p in procs])
            checks.append(
                VerificationCheck(
                    kind="process_running",
                    ok=bool(found),
                    value="browser",
                    detail=f"running: {', '.join(found)}" if found else "no known browser process running",
                )
            )

    # App/window: best-effort verify a window matching the app name is visible.
    app_value = data.get("app") or data.get("window_title")
    if app_value:
        app_raw = _safe_str(app_value)
        titles = _list_visible_window_titles()
        ok = False
        detail = ""
        try:
            candidates = _candidates_for_app(app_raw)
            titles_lower = [t.lower() for t in titles]
            ok = any(any(c in t for t in titles_lower) for c in candidates)
            if ok:
                detail = "matching window visible"
            else:
                detail = "no matching window visible" if titles else "window list unavailable"
        except Exception:
            ok = False
            detail = "error checking windows"
        checks.append(VerificationCheck(kind="app_window_visible", ok=ok, value=app_raw, detail=detail))

        # Best-effort: process-based verification (more robust than window listing).
        procs = _list_running_process_names()
        if procs:
            candidates = _candidates_for_process(app_raw)
            found = sorted([c for c in candidates if c in procs])
            checks.append(
                VerificationCheck(
                    kind="process_running",
                    ok=bool(found),
                    value=app_raw,
                    detail=f"running: {', '.join(found)}" if found else "no matching process found",
                )
            )

    # Overall verdict:
    # - If we have path checks, require all of them to pass (deterministic artifacts).
    # - Otherwise, accept any strong "presence" signal (window visible OR process running).
    path_checks = [c for c in checks if c.kind == "path_exists"]
    exit_checks = [c for c in checks if c.kind == "exit_code_zero"]
    content_checks = [c for c in checks if c.kind == "content_nonempty"]
    url_checks = [c for c in checks if c.kind == "url_valid"]
    presence_checks = [c for c in checks if c.kind in {"app_window_visible", "browser_window_visible", "process_running"}]
    if path_checks:
        overall = all(c.ok for c in path_checks)
    elif exit_checks:
        overall = all(c.ok for c in exit_checks)
    elif content_checks:
        overall = all(c.ok for c in content_checks)
    elif presence_checks:
        overall = any(c.ok for c in presence_checks)
    elif url_checks and cap_name in {"web_search", "news_search", "deep_search", "live_search"}:
        # For pure-search tools, URL validity alone is the best deterministic signal we can get.
        overall = all(c.ok for c in url_checks)
    else:
        overall = False
    return {"ok": bool(overall), "checks": [c.to_dict() for c in checks]}
