"""Project watchdogs that monitor apps, URLs, and ports created by Chintu."""

from __future__ import annotations

import json
import logging
import socket
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from chintu_backend.core.config import get_config
from chintu_backend.core.state import get_state_manager
from chintu_backend.core.websocket_server import get_ws_server
from chintu_backend.core.events import get_event_bus, Event, EventType

logger = logging.getLogger(__name__)


@dataclass
class WatchdogEntry:
    id: int
    name: str
    kind: str
    target: str
    interval_seconds: float
    enabled: bool
    last_status: str = "unknown"
    last_message: str = ""
    last_checked: float = 0.0
    consecutive_failures: int = 0


class WatchdogStore:
    """SQLite-backed store for watchdog entries."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS watchdogs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    target TEXT NOT NULL,
                    interval_seconds REAL NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_status TEXT NOT NULL DEFAULT 'unknown',
                    last_message TEXT NOT NULL DEFAULT '',
                    last_checked REAL NOT NULL DEFAULT 0,
                    consecutive_failures INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.commit()

    def list(self) -> List[WatchdogEntry]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM watchdogs ORDER BY id ASC").fetchall()
        return [self._row_to_entry(r) for r in rows]

    def add(self, name: str, kind: str, target: str, interval_seconds: float) -> WatchdogEntry:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO watchdogs (name, kind, target, interval_seconds, enabled)
                VALUES (?, ?, ?, ?, 1)
                """,
                (name, kind, target, float(interval_seconds)),
            )
            conn.commit()
            row_id = int(cur.lastrowid)
            row = conn.execute("SELECT * FROM watchdogs WHERE id = ?", (row_id,)).fetchone()
        return self._row_to_entry(row)

    def remove(self, identifier: str) -> int:
        """Remove by numeric id or by name (case-insensitive). Returns rows removed."""
        identifier = (identifier or "").strip()
        if not identifier:
            return 0
        with self._connect() as conn:
            if identifier.isdigit():
                cur = conn.execute("DELETE FROM watchdogs WHERE id = ?", (int(identifier),))
            else:
                cur = conn.execute(
                    "DELETE FROM watchdogs WHERE lower(name) = lower(?)",
                    (identifier,),
                )
            conn.commit()
            return int(cur.rowcount or 0)

    def update_status(
        self,
        entry_id: int,
        status: str,
        message: str,
        checked_at: float,
        consecutive_failures: int,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE watchdogs
                SET last_status = ?, last_message = ?, last_checked = ?, consecutive_failures = ?
                WHERE id = ?
                """,
                (status, message, float(checked_at), int(consecutive_failures), int(entry_id)),
            )
            conn.commit()

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> WatchdogEntry:
        return WatchdogEntry(
            id=int(row["id"]),
            name=str(row["name"]),
            kind=str(row["kind"]),
            target=str(row["target"]),
            interval_seconds=float(row["interval_seconds"]),
            enabled=bool(row["enabled"]),
            last_status=str(row["last_status"]),
            last_message=str(row["last_message"]),
            last_checked=float(row["last_checked"]),
            consecutive_failures=int(row["consecutive_failures"]),
        )


class ProjectWatchdogManager:
    """Background watchdog engine with UI broadcasts."""

    def __init__(self):
        self.config = get_config()
        self.state_manager = get_state_manager()
        self.event_bus = get_event_bus()
        self.store = WatchdogStore(str(self.config.watchdog_db_path))
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._running = False

    def start(self) -> Tuple[bool, str]:
        if not self.config.watchdog_enabled:
            self.state_manager.update_feature("watchdog", enabled=False, status="inactive")
            return False, "Watchdogs disabled in config"
        if self._running:
            return True, "Watchdogs already running"

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="ProjectWatchdog")
        self._thread.start()
        self._running = True
        self.state_manager.update_feature("watchdog", enabled=True, status="active")
        return True, "Watchdogs started"

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self._running = False
        self.state_manager.update_feature("watchdog", status="inactive")

    def list_watchdogs(self) -> List[WatchdogEntry]:
        return self.store.list()

    def add_watchdog(
        self,
        kind: str,
        target: str,
        name: Optional[str] = None,
        interval_seconds: Optional[float] = None,
    ) -> WatchdogEntry:
        kind = (kind or "").strip().lower()
        if kind not in {"http", "port", "process"}:
            raise ValueError("kind must be one of: http, port, process")
        interval = float(interval_seconds or self.config.watchdog_interval_seconds)
        entry_name = (name or target).strip()[:80]
        entry = self.store.add(entry_name, kind, target.strip(), interval)
        logger.info("Added watchdog: %s (%s -> %s)", entry.name, entry.kind, entry.target)
        self._broadcast_event(
            {
                "type": "watchdog_update",
                "data": {"action": "added", "watchdog": self._entry_to_dict(entry)},
            }
        )
        return entry

    def remove_watchdog(self, identifier: str) -> int:
        removed = self.store.remove(identifier)
        if removed:
            self._broadcast_event(
                {"type": "watchdog_update", "data": {"action": "removed", "identifier": identifier}}
            )
        return removed

    def run_checks(self, force: bool = False) -> Dict[str, int]:
        entries = self.store.list()
        now = time.time()
        healthy = 0
        failing = 0
        skipped = 0

        for entry in entries:
            due = force or (now - entry.last_checked) >= entry.interval_seconds
            if not due or not entry.enabled:
                skipped += 1
                continue
            ok, message = self._check(entry)
            failures = 0 if ok else (entry.consecutive_failures + 1)
            status = "healthy" if ok else "failing"
            self.store.update_status(entry.id, status, message, now, failures)
            if ok:
                healthy += 1
            else:
                failing += 1
                self._maybe_alert(entry, failures, message)

        if failing:
            self.state_manager.update_feature("watchdog", status="testing")
        else:
            self.state_manager.update_feature("watchdog", status="active")

        return {"healthy": healthy, "failing": failing, "skipped": skipped}

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_checks(force=False)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Watchdog loop error: %s", exc)
                self.state_manager.update_feature("watchdog", status="testing", error=str(exc))
            self._stop_event.wait(self.config.watchdog_interval_seconds)

    def _check(self, entry: WatchdogEntry) -> Tuple[bool, str]:
        if entry.kind == "http":
            return self._check_http(entry.target)
        if entry.kind == "port":
            return self._check_port(entry.target)
        if entry.kind == "process":
            return self._check_process(entry.target)
        return False, f"Unknown watchdog kind: {entry.kind}"

    def _check_http(self, url: str) -> Tuple[bool, str]:
        try:
            import requests

            resp = requests.get(url, timeout=5.0)
            if resp.status_code < 500:
                return True, f"HTTP {resp.status_code}"
            return False, f"HTTP {resp.status_code}"
        except Exception as exc:  # noqa: BLE001
            return False, f"HTTP error: {exc}"

    def _check_port(self, target: str) -> Tuple[bool, str]:
        host, port = self._parse_host_port(target)
        try:
            with socket.create_connection((host, port), timeout=3.0):
                return True, f"Port open: {host}:{port}"
        except Exception as exc:  # noqa: BLE001
            return False, f"Port closed: {host}:{port} ({exc})"

    def _check_process(self, process_name: str) -> Tuple[bool, str]:
        try:
            import psutil

            name_lower = process_name.lower()
            for proc in psutil.process_iter(attrs=["name"]):
                name = (proc.info.get("name") or "").lower()
                if name_lower in name:
                    return True, f"Process running: {proc.info.get('name')}"
            return False, f"Process not found: {process_name}"
        except Exception as exc:  # noqa: BLE001
            return False, f"Process check failed: {exc}"

    def _maybe_alert(self, entry: WatchdogEntry, failures: int, message: str) -> None:
        if failures < int(self.config.watchdog_failure_threshold):
            return
        alert = {
            "type": "watchdog_alert",
            "data": {
                "id": entry.id,
                "name": entry.name,
                "kind": entry.kind,
                "target": entry.target,
                "failures": failures,
                "message": message,
                "timestamp": time.time(),
            },
        }
        logger.warning("Watchdog alert: %s", alert["data"])
        self._broadcast_event(alert)
        try:
            self.event_bus.publish_sync(
                Event(
                    type=EventType.NOTIFICATION,
                    source="watchdog",
                    data={
                        "category": "watchdog_alert",
                        "severity": "high",
                        "title": f"Watchdog Alert: {entry.name}",
                        "message": message,
                        "metadata": alert["data"],
                    },
                )
            )
        except Exception:
            # Never let notification wiring break watchdogs.
            pass

    def _broadcast_event(self, payload: Dict[str, object]) -> None:
        server = get_ws_server()
        if not server:
            return
        loop = server._loop
        if not loop or not loop.is_running():
            return
        try:
            import asyncio

            asyncio.run_coroutine_threadsafe(server.broadcast_message(payload), loop)
        except Exception:
            return

    @staticmethod
    def _parse_host_port(target: str) -> Tuple[str, int]:
        target = (target or "").strip()
        if ":" in target:
            host, port_str = target.rsplit(":", 1)
            host = host.strip() or "127.0.0.1"
            try:
                return host, int(port_str.strip())
            except ValueError:
                return host, 80
        if target.isdigit():
            return "127.0.0.1", int(target)
        return target or "127.0.0.1", 80

    @staticmethod
    def _entry_to_dict(entry: WatchdogEntry) -> Dict[str, object]:
        return {
            "id": entry.id,
            "name": entry.name,
            "kind": entry.kind,
            "target": entry.target,
            "interval_seconds": entry.interval_seconds,
            "enabled": entry.enabled,
            "last_status": entry.last_status,
            "last_message": entry.last_message,
            "last_checked": entry.last_checked,
            "consecutive_failures": entry.consecutive_failures,
        }


_manager: Optional[ProjectWatchdogManager] = None


def get_watchdog_manager() -> ProjectWatchdogManager:
    global _manager
    if _manager is None:
        _manager = ProjectWatchdogManager()
    return _manager
