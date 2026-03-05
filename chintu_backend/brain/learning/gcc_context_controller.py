"""Git-style context controller for long-horizon agent memory."""

from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from chintu_backend.core.config import get_config

try:
    import yaml
except Exception:  # pragma: no cover - optional dependency
    yaml = None

try:  # pragma: no cover - optional dependency
    from chintu_backend.privacy.pii import mask_pii as _mask_pii
except Exception:  # pragma: no cover - keep controller usable in minimal envs.
    def _mask_pii(text: str) -> str:  # type: ignore[return-type]
        return text


def _redact_sensitive(text: str) -> str:
    """Redact secrets/PII before persisting to .GCC/ (durable context)."""
    raw = (text or "").strip()
    if not raw:
        return ""
    masked = _mask_pii(raw)
    try:
        from chintu_backend.core.credential_detector import get_credential_detector

        detector = get_credential_detector()
        for cred in detector.detect_all(raw):
            if cred.value and cred.value in masked:
                masked = masked.replace(cred.value, f"<redacted:{cred.service_name.lower()}>")
    except Exception:
        pass
    return masked


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sanitize_branch_name(name: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "-", (name or "").strip())
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
    return normalized or "main"


class GitContextController:
    """Versioned context layer inspired by Git operations."""

    def __init__(self, root_dir: Optional[Path] = None) -> None:
        self.config = get_config()
        default_root = Path.cwd() / ".GCC"
        configured_root = getattr(self.config, "gcc_root_dir", None)
        self.root = Path(root_dir or configured_root or default_root)
        self.branches_dir = self.root / "branches"
        self.main_path = self.root / "main.md"
        self.head_path = self.root / "HEAD"
        self._lock = threading.RLock()

    def initialize(self, project_goal: str = "", roadmap: Optional[List[str]] = None) -> Dict[str, Any]:
        with self._lock:
            self.branches_dir.mkdir(parents=True, exist_ok=True)
            if not self.main_path.exists():
                goal = (project_goal or "").strip() or str(
                    getattr(self.config, "gcc_default_goal", "Long-horizon task execution and learning")
                )
                goal = _redact_sensitive(goal)
                lines = [
                    "# GCC Main Roadmap",
                    "",
                    f"Project Goal: {goal}",
                    "",
                    "## Milestones",
                ]
                for item in (roadmap or []):
                    lines.append(f"- {item}")
                lines.append("")
                self.main_path.write_text("\n".join(lines), encoding="utf-8")

            if not self.head_path.exists():
                self.head_path.write_text("main\n", encoding="utf-8")

            self._ensure_branch("main", purpose="Primary execution branch")
            return {
                "root": str(self.root),
                "current_branch": self.get_current_branch(),
                "branches": self.list_branches(),
                "main_path": str(self.main_path),
            }

    def get_current_branch(self) -> str:
        if not self.head_path.exists():
            return "main"
        text = self.head_path.read_text(encoding="utf-8", errors="ignore").strip()
        return _sanitize_branch_name(text or "main")

    def checkout(self, branch: str) -> Dict[str, Any]:
        branch_name = _sanitize_branch_name(branch)
        with self._lock:
            self._ensure_branch(branch_name)
            self.head_path.write_text(f"{branch_name}\n", encoding="utf-8")
        return {"current_branch": branch_name}

    def list_branches(self) -> List[str]:
        if not self.branches_dir.exists():
            return []
        return sorted([p.name for p in self.branches_dir.iterdir() if p.is_dir()])

    def create_branch(
        self,
        name: str,
        purpose: str = "",
        from_branch: Optional[str] = None,
        switch: bool = True,
    ) -> Dict[str, Any]:
        branch_name = _sanitize_branch_name(name)
        source = _sanitize_branch_name(from_branch or self.get_current_branch())
        safe_purpose = _redact_sensitive(purpose)
        with self._lock:
            self.initialize()
            self._ensure_branch(source)
            self._ensure_branch(branch_name, purpose=safe_purpose, inherit_from=source)
            if switch:
                self.head_path.write_text(f"{branch_name}\n", encoding="utf-8")
        return {
            "branch": branch_name,
            "from_branch": source,
            "current_branch": self.get_current_branch(),
            "purpose": safe_purpose or self._read_metadata(branch_name).get("purpose", ""),
        }

    def append_log(
        self,
        observation: str,
        thought: str,
        action: str,
        result: str = "",
        branch: Optional[str] = None,
    ) -> Dict[str, Any]:
        branch_name = _sanitize_branch_name(branch or self.get_current_branch())
        obs = _redact_sensitive(observation)
        th = _redact_sensitive(thought)
        act = _redact_sensitive(action)
        res = _redact_sensitive(result)
        with self._lock:
            self.initialize()
            self._ensure_branch(branch_name)
            log_path = self._log_path(branch_name)
            entry = [
                f"## OTA {_utc_now()}",
                f"Observation: {obs}",
                f"Thought: {th}",
                f"Action: {act}",
            ]
            if res:
                entry.append(f"Result: {res}")
            entry.append("")
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write("\n".join(entry))

            metadata = self._read_metadata(branch_name)
            metadata["updated_at"] = _utc_now()
            metadata["pending_events_since_commit"] = int(metadata.get("pending_events_since_commit", 0)) + 1
            self._write_metadata(branch_name, metadata)
            return {
                "branch": branch_name,
                "pending_events_since_commit": metadata["pending_events_since_commit"],
            }

    def commit(
        self,
        summary: str,
        branch: Optional[str] = None,
        contribution: str = "",
        update_main: bool = False,
        roadmap_note: str = "",
    ) -> Dict[str, Any]:
        branch_name = _sanitize_branch_name(branch or self.get_current_branch())
        commit_id = f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
        summary_text = _redact_sensitive((summary or "").strip() or "Progress checkpoint")

        with self._lock:
            self.initialize()
            self._ensure_branch(branch_name)

            metadata = self._read_metadata(branch_name)
            prev_summary = str(metadata.get("progress_summary") or "").strip()
            branch_purpose = str(metadata.get("purpose") or "No purpose specified.")
            contribution_text = _redact_sensitive((contribution or "").strip() or summary_text)
            log_tail = self._tail_lines(self._log_path(branch_name), 40)

            block = [
                f"## Commit: {commit_id}",
                f"Timestamp: {_utc_now()}",
                "",
                "### Branch Purpose",
                branch_purpose,
                "",
                "### Previous Progress Summary",
                prev_summary or "No previous commits.",
                "",
                "### This Commit's Contribution",
                contribution_text,
                "",
                "### Commit Summary",
                summary_text,
                "",
                "### Linked Log Tail",
                "```text",
                log_tail or "(no recent logs)",
                "```",
                "",
            ]
            with self._commit_path(branch_name).open("a", encoding="utf-8") as handle:
                handle.write("\n".join(block))

            merged_summary = summary_text if not prev_summary else f"{prev_summary}; {summary_text}"
            metadata["updated_at"] = _utc_now()
            metadata["last_commit"] = commit_id
            metadata["commit_count"] = int(metadata.get("commit_count", 0)) + 1
            metadata["progress_summary"] = merged_summary[:3000]
            metadata["pending_events_since_commit"] = 0
            self._write_metadata(branch_name, metadata)

            if update_main or roadmap_note:
                note = _redact_sensitive(roadmap_note.strip()) if roadmap_note else f"[{branch_name}] {summary_text}"
                self._append_main_milestone(note)

            return {
                "branch": branch_name,
                "commit_id": commit_id,
                "summary": summary_text,
                "commit_count": metadata["commit_count"],
            }

    def merge(
        self,
        source_branch: str,
        into_branch: str = "main",
        summary: str = "",
    ) -> Dict[str, Any]:
        source = _sanitize_branch_name(source_branch)
        target = _sanitize_branch_name(into_branch)
        if source == target:
            raise ValueError("Source and target branches must be different.")

        with self._lock:
            self.initialize()
            self._ensure_branch(source)
            self._ensure_branch(target)

            source_meta = self._read_metadata(source)
            source_progress = str(source_meta.get("progress_summary") or "No summary available.")
            merge_summary = _redact_sensitive((summary or "").strip()) or f"Merged branch '{source}' into '{target}'."

            with self._commit_path(target).open("a", encoding="utf-8") as handle:
                handle.write(
                    "\n".join(
                        [
                            f"## Merge: {source} -> {target} ({_utc_now()})",
                            "",
                            "### Source Progress Summary",
                            source_progress,
                            "",
                            "### Merge Summary",
                            merge_summary,
                            "",
                        ]
                    )
                )

            source_log = self._tail_lines(self._log_path(source), 120)
            if source_log:
                with self._log_path(target).open("a", encoding="utf-8") as handle:
                    handle.write(
                        "\n".join(
                            [
                                f"\n## MERGED LOG FROM {source} ({_utc_now()})",
                                source_log,
                                "",
                            ]
                        )
                    )

            target_meta = self._read_metadata(target)
            merges = list(target_meta.get("merges", []))
            merges.append(
                {
                    "source": source,
                    "timestamp": _utc_now(),
                    "summary": merge_summary,
                    "source_last_commit": source_meta.get("last_commit", ""),
                }
            )
            target_meta["merges"] = merges[-200:]
            target_meta["updated_at"] = _utc_now()
            target_meta["progress_summary"] = f"{target_meta.get('progress_summary', '')}; {merge_summary}".strip("; ")
            self._write_metadata(target, target_meta)
            self._append_main_milestone(f"[merge] {source} -> {target}: {merge_summary}")
            self.head_path.write_text(f"{target}\n", encoding="utf-8")

            return {"source": source, "into": target, "summary": merge_summary}

    def context(
        self,
        branch: Optional[str] = None,
        commit_id: Optional[str] = None,
        log_lines: int = 20,
        metadata_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            self.initialize()
            target = _sanitize_branch_name(branch or self.get_current_branch())
            self._ensure_branch(target)

            result: Dict[str, Any] = {
                "root": str(self.root),
                "current_branch": self.get_current_branch(),
                "branch": target,
                "branches": self.list_branches(),
                "main_excerpt": self._tail_lines(self.main_path, 40),
            }

            commit_text = self._commit_path(target).read_text(encoding="utf-8", errors="ignore")
            if commit_id:
                result["commit_block"] = self._find_commit_block(commit_text, commit_id)
            else:
                result["latest_commits"] = self._tail_sections(commit_text, "## ", 6)

            if log_lines > 0:
                result["log_tail"] = self._tail_lines(self._log_path(target), log_lines)

            metadata = self._read_metadata(target)
            if metadata_key:
                result["metadata"] = {metadata_key: metadata.get(metadata_key)}
            else:
                result["metadata"] = metadata

            return result

    def status(self) -> Dict[str, Any]:
        return self.context(log_lines=0)

    def record_event(self, event: Any) -> None:
        if not getattr(self.config, "gcc_enabled", True):
            return
        if not getattr(self.config, "gcc_auto_log", True):
            return

        user = str(getattr(event, "user_text", "") or "").strip()
        assistant = str(getattr(event, "assistant_text", "") or "").strip()
        category = str(getattr(event, "category", "") or "general")
        capability = str(getattr(event, "capability", "") or "unknown")
        source = str(getattr(event, "source", "") or "runtime")
        model = str(getattr(event, "model", "") or "unknown")
        content = str(getattr(event, "content", "") or "").strip()

        if not user and not assistant and not content:
            return

        log_res = self.append_log(
            observation=user[:500] or "(implicit event)",
            thought=f"category={category}; capability={capability}; source={source}",
            action=f"responded via model={model}",
            result=(assistant or content)[:800],
        )

        if not getattr(self.config, "gcc_auto_commit", True):
            return
        if not bool(getattr(event, "trainable", False)):
            return

        threshold = int(getattr(self.config, "gcc_auto_commit_every", 25))
        pending = int(log_res.get("pending_events_since_commit", 0))
        if pending < threshold:
            return
        summary = f"Auto-commit: {pending} new events ({category})"
        contribution = content or assistant or summary
        self.commit(summary=summary, contribution=contribution[:1200], update_main=False)

    def _ensure_branch(self, branch: str, purpose: str = "", inherit_from: Optional[str] = None) -> None:
        branch_name = _sanitize_branch_name(branch)
        branch_dir = self.branches_dir / branch_name
        branch_dir.mkdir(parents=True, exist_ok=True)
        commit_path = self._commit_path(branch_name)
        log_path = self._log_path(branch_name)
        metadata_path = self._metadata_path(branch_name)

        if not commit_path.exists():
            commit_path.write_text("# Commit History\n\n", encoding="utf-8")
        if not log_path.exists():
            log_path.write_text("# OTA Log\n\n", encoding="utf-8")
        if not metadata_path.exists():
            parent_meta = self._read_metadata(_sanitize_branch_name(inherit_from or "main"))
            payload = {
                "branch_name": branch_name,
                "purpose": (purpose or parent_meta.get("purpose") or "No purpose specified."),
                "created_at": _utc_now(),
                "updated_at": _utc_now(),
                "commit_count": 0,
                "last_commit": "",
                "progress_summary": parent_meta.get("progress_summary", ""),
                "pending_events_since_commit": 0,
                "merges": [],
            }
            self._write_metadata(branch_name, payload)
        elif purpose:
            metadata = self._read_metadata(branch_name)
            metadata["purpose"] = purpose
            metadata["updated_at"] = _utc_now()
            self._write_metadata(branch_name, metadata)

    def _read_metadata(self, branch: str) -> Dict[str, Any]:
        path = self._metadata_path(branch)
        if not path.exists():
            return {}
        text = path.read_text(encoding="utf-8", errors="ignore").strip()
        if not text:
            return {}
        if yaml is not None:
            try:
                data = yaml.safe_load(text)
                return data if isinstance(data, dict) else {}
            except Exception:
                pass
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _write_metadata(self, branch: str, data: Dict[str, Any]) -> None:
        path = self._metadata_path(branch)
        payload = dict(data or {})
        if yaml is not None:
            text = yaml.safe_dump(payload, sort_keys=False)
        else:
            text = json.dumps(payload, indent=2)
        path.write_text(text, encoding="utf-8")

    def _append_main_milestone(self, note: str) -> None:
        note_text = (note or "").strip()
        if not note_text:
            return
        if not self.main_path.exists():
            self.initialize()
        content = self.main_path.read_text(encoding="utf-8", errors="ignore")
        if "## Milestones" not in content:
            content = content.rstrip() + "\n\n## Milestones\n"
        content = content.rstrip() + f"\n- [{_utc_now()[:10]}] {note_text}\n"
        self.main_path.write_text(content, encoding="utf-8")

    def _find_commit_block(self, commit_text: str, commit_id: str) -> str:
        token = f"## Commit: {commit_id}"
        if token not in commit_text:
            return ""
        tail = commit_text.split(token, 1)[1]
        if "\n## " in tail:
            block = tail.split("\n## ", 1)[0]
            return token + block
        return token + tail

    @staticmethod
    def _tail_lines(path: Path, limit: int) -> str:
        if not path.exists() or limit <= 0:
            return ""
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        return "\n".join(lines[-limit:])

    @staticmethod
    def _tail_sections(text: str, section_prefix: str, limit: int) -> List[str]:
        if not text:
            return []
        lines = text.splitlines()
        chunks: List[str] = []
        current: List[str] = []
        for line in lines:
            if line.startswith(section_prefix):
                if current:
                    chunks.append("\n".join(current).strip())
                current = [line]
            elif current:
                current.append(line)
        if current:
            chunks.append("\n".join(current).strip())
        return chunks[-limit:] if limit > 0 else chunks

    def _branch_dir(self, branch: str) -> Path:
        return self.branches_dir / _sanitize_branch_name(branch)

    def _commit_path(self, branch: str) -> Path:
        return self._branch_dir(branch) / "commit.md"

    def _log_path(self, branch: str) -> Path:
        return self._branch_dir(branch) / "log.md"

    def _metadata_path(self, branch: str) -> Path:
        return self._branch_dir(branch) / "metadata.yaml"


_gcc_controller: Optional[GitContextController] = None


def get_gcc_controller(root_dir: Optional[Path] = None) -> GitContextController:
    global _gcc_controller
    if _gcc_controller is None or root_dir is not None:
        _gcc_controller = GitContextController(root_dir=root_dir)
    return _gcc_controller
