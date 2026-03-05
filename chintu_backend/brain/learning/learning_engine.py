"""Learning engine for logging, categorizing, and storing new knowledge."""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from chintu_backend.core.config import get_config
from chintu_backend.core.credential_detector import get_credential_detector
from chintu_backend.core.state import get_state_manager
from chintu_backend.brain.memory.tiered_memory import get_memory_store


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class LearningEvent:
    id: str
    timestamp: str
    category: str
    content: str
    user_text: Optional[str] = None
    assistant_text: Optional[str] = None
    source: str = ""
    capability: str = ""
    model: str = ""
    confidence: float = 0.6
    trainable: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "category": self.category,
            "content": self.content,
            "user_text": self.user_text,
            "assistant_text": self.assistant_text,
            "source": self.source,
            "capability": self.capability,
            "model": self.model,
            "confidence": self.confidence,
            "trainable": self.trainable,
            "metadata": dict(self.metadata or {}),
        }


class LearningStore:
    """Append-only JSONL storage for learning events."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir / "learning"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.base_dir / "events.jsonl"
        self.state_path = self.base_dir / "state.json"
        self._lock = threading.Lock()

    def log_event(self, event: LearningEvent) -> None:
        payload = event.to_dict()
        with self._lock:
            with self.events_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=True) + "\n")

    def iter_events(self, limit: Optional[int] = None) -> Iterable[LearningEvent]:
        if not self.events_path.exists():
            return []
        events: List[LearningEvent] = []
        with self.events_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                try:
                    events.append(LearningEvent(**data))
                except TypeError:
                    continue
        if limit:
            return events[-limit:]
        return events

    def get_stats(self) -> Dict[str, Any]:
        counts: Dict[str, int] = {}
        total = 0
        for event in self.iter_events():
            counts[event.category] = counts.get(event.category, 0) + 1
            total += 1
        return {"total": total, "by_category": counts}

    def load_state(self) -> Dict[str, Any]:
        if not self.state_path.exists():
            return {}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def save_state(self, state: Dict[str, Any]) -> None:
        with self._lock:
            self.state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")


class LearningJournal:
    """Append learning events to a human-readable markdown journal."""

    def __init__(self, base_dir: Path) -> None:
        self.path = Path(base_dir) / "Learning.md"
        self._lock = threading.Lock()
        if not self.path.exists():
            self.path.write_text("# Learning Journal\n\n", encoding="utf-8")

    def append(self, event: LearningEvent) -> None:
        category = event.category.replace("_", " ").title()
        timestamp = event.timestamp[:19].replace("T", " ")
        entry = f"- [{timestamp}] {event.content}\n"
        with self._lock:
            content = self.path.read_text(encoding="utf-8", errors="ignore")
            if f"## {category}" not in content:
                content += f"\n## {category}\n\n"
            parts = content.split(f"## {category}", 1)
            if len(parts) == 2:
                header = f"## {category}"
                prefix = parts[0]
                rest = parts[1]
                if rest.startswith("\n\n"):
                    rest = rest[2:]
                updated = prefix + header + "\n\n" + entry + rest
            else:
                updated = content + f"\n## {category}\n\n" + entry
            self.path.write_text(updated, encoding="utf-8")


class LearningEngine:
    """Core learning engine that logs and stores knowledge."""

    def __init__(self, memory_manager=None) -> None:
        self.config = get_config()
        self.store = LearningStore(self.config.data_dir)
        self.memory_store = get_memory_store()
        self.memory_manager = memory_manager
        self.journal = LearningJournal(self.config.memory_markdown_dir)
        self.credential_detector = get_credential_detector()
        self.state_manager = get_state_manager()
        self.gcc_controller = None
        if getattr(self.config, "gcc_enabled", True):
            try:
                from chintu_backend.brain.learning.gcc_context_controller import get_gcc_controller

                self.gcc_controller = get_gcc_controller()
                self.gcc_controller.initialize(project_goal=getattr(self.config, "gcc_default_goal", ""))
            except Exception:
                self.gcc_controller = None

    def observe_interaction(
        self,
        user_text: str,
        assistant_text: str,
        result: Any,
        meta: Dict[str, Any],
        source: str,
        sensitive: bool = False,
    ) -> None:
        if not getattr(self.config, "learning_enabled", True):
            return
        if not user_text or not assistant_text:
            return
        if sensitive or getattr(result, "requires_confirmation", False):
            return

        clean_user = self._sanitize_text(user_text)
        clean_assistant = self._sanitize_text(assistant_text)

        capability = getattr(result, "capability_name", "") if result else ""
        category = self._categorize(clean_user, clean_assistant, capability, meta, result)

        content = self._build_content(category, clean_user, clean_assistant)
        metadata = self._extract_metadata(result, meta)

        event = LearningEvent(
            id=str(uuid.uuid4()),
            timestamp=_utc_now(),
            category=category,
            content=content,
            user_text=clean_user,
            assistant_text=clean_assistant,
            source=source or "",
            capability=capability,
            model=str(meta.get("model_source", "")) if meta else "",
            confidence=0.7 if getattr(result, "success", True) else 0.4,
            trainable=self._is_trainable(
                result,
                category,
                meta=meta,
                user_text=clean_user,
                assistant_text=clean_assistant,
            ),
            metadata=metadata,
        )

        self._record_event(event)

    def record_correction(self, user_text: str, last_response: str, last_capability: str = "") -> None:
        if not getattr(self.config, "learning_enabled", True):
            return
        if not user_text:
            return

        clean_user = self._sanitize_text(user_text)
        clean_response = self._sanitize_text(last_response or "")

        content = f"Correction noted: {clean_user}"
        if clean_response:
            content += f" | Previous response: {clean_response[:400]}"

        event = LearningEvent(
            id=str(uuid.uuid4()),
            timestamp=_utc_now(),
            category="correction",
            content=content,
            user_text=clean_user,
            assistant_text=clean_response or None,
            source="feedback",
            capability=last_capability,
            confidence=0.9,
            trainable=False,
            metadata={"type": "user_correction"},
        )
        self._record_event(event)

    def record_web_learning(self, query: str, response: str, sources: Optional[List[str]] = None) -> None:
        if not getattr(self.config, "learning_enabled", True):
            return
        clean_query = self._sanitize_text(query)
        clean_response = self._sanitize_text(response)
        if not clean_query or not clean_response:
            return
        content = f"Research summary for '{clean_query}': {clean_response[:600]}"
        event = LearningEvent(
            id=str(uuid.uuid4()),
            timestamp=_utc_now(),
            category="research",
            content=content,
            user_text=clean_query,
            assistant_text=clean_response,
            source="web",
            capability="web_research",
            confidence=0.7,
            trainable=True,
            metadata={"sources": sources or []},
        )
        self._record_event(event)

    def export_training_dataset(self, output_path: Path, format: str = "chat") -> int:
        """Export trainable events to JSONL dataset."""
        count = 0
        with output_path.open("w", encoding="utf-8") as handle:
            for event in self.store.iter_events():
                if not event.trainable:
                    continue
                if not event.user_text or not event.assistant_text:
                    continue
                if format == "instruction":
                    payload = {
                        "instruction": event.user_text,
                        "output": event.assistant_text,
                        "metadata": {"category": event.category, **(event.metadata or {})},
                    }
                else:
                    payload = {
                        "messages": [
                            {"role": "user", "content": event.user_text},
                            {"role": "assistant", "content": event.assistant_text},
                        ]
                    }
                handle.write(json.dumps(payload, ensure_ascii=True) + "\n")
                count += 1
        
        # Export Knowledge Base "Books"
        count += self._export_knowledge_base(output_path, format)
        return count

    def _export_knowledge_base(self, output_path: Path, format: str) -> int:
        """Export structured knowledge as training data."""
        knowledge_dir = self.config.data_dir / "knowledge"
        if not knowledge_dir.exists():
            return 0
            
        count = 0
        with output_path.open("a", encoding="utf-8") as handle:
            # Walk directory
            for category_dir in knowledge_dir.iterdir():
                if not category_dir.is_dir(): continue
                
                for topic_dir in category_dir.iterdir():
                    if not topic_dir.is_dir(): continue
                    
                    topic = topic_dir.name.replace("_", " ")
                    for file in topic_dir.glob("*.md"):
                        if file.name == "index.md": continue
                        
                        try:
                            content = file.read_text(encoding="utf-8")
                            # Extract Frontmatter? Assuming raw markdown for now.
                            # Ideally we parse topic/chapter from filename or content
                            
                            chapter_title = file.stem.replace("chapter_", "").replace("_", " ").title()
                            
                            prompt = f"Explain {chapter_title} regarding {topic}."
                            
                            if format == "instruction":
                                payload = {
                                    "instruction": prompt,
                                    "output": content,
                                    "metadata": {"source": "knowledge_base", "topic": topic}
                                }
                            else:
                                payload = {
                                    "messages": [
                                        {"role": "user", "content": prompt},
                                        {"role": "assistant", "content": content}
                                    ]
                                }
                            handle.write(json.dumps(payload, ensure_ascii=True) + "\n")
                            count += 1
                        except Exception:
                            pass
        return count

    def _record_event(self, event: LearningEvent) -> None:
        self.store.log_event(event)
        self._save_to_memory(event)
        self._append_journal(event)
        if self.gcc_controller:
            try:
                self.gcc_controller.record_event(event)
            except Exception:
                pass

    def record_gap(self, gap: str, context: Optional[Dict[str, Any]] = None) -> None:
        if not getattr(self.config, "learning_enabled", True):
            return
        event = LearningEvent(
            id=str(uuid.uuid4()),
            timestamp=_utc_now(),
            category="gap",
            content=gap,
            source="system",
            metadata=context or {},
            trainable=False,
        )
        self._record_event(event)
        try:
            self.state_manager.update_feature("memory", enabled=True, status="active")
        except Exception:
            pass

    def _save_to_memory(self, event: LearningEvent) -> None:
        if not getattr(self.config, "learning_auto_save", True):
            return

        metadata = {"category": event.category, "source": event.source}
        metadata.update(event.metadata or {})

        if event.category in ("fact", "preference"):
            self.memory_store.add_fact(event.content, metadata=metadata, importance=0.7)
        elif event.category in ("correction", "mistake", "lesson"):
            self.memory_store.add_note(event.content, metadata=metadata)
        elif event.category == "research":
            self.memory_store.add_note(event.content, metadata=metadata)
        else:
            self.memory_store.add_note(event.content, metadata=metadata)

        if self.memory_manager:
            try:
                self.memory_manager.save_interaction("learning", event.content, metadata=metadata)
            except Exception:
                pass

    def _append_journal(self, event: LearningEvent) -> None:
        try:
            self.journal.append(event)
        except Exception:
            pass

    def _categorize(
        self,
        user_text: str,
        assistant_text: str,
        capability: str,
        meta: Dict[str, Any],
        result: Any,
    ) -> str:
        if result is not None and getattr(result, "success", True) is False:
            return "mistake"

        cap_lower = (capability or "").lower()
        if cap_lower in {
            "web_search",
            "news_search",
            "deep_search",
            "live_search",
            "browse_url",
            "read_document",
            "web_research",
        }:
            return "research"

        if "workflow" in cap_lower:
            return "workflow"

        if cap_lower in {"remember_fact", "recall_facts"}:
            return "fact"

        if "code" in user_text.lower() or "app" in user_text.lower():
            return "developer"

        if "preference" in user_text.lower() or "prefer" in user_text.lower():
            return "preference"

        return "general"

    def _build_content(self, category: str, user_text: str, assistant_text: str) -> str:
        if category == "research":
            return f"Research: {assistant_text[:800]}"
        if category == "mistake":
            return f"Mistake observed. User: {user_text[:200]} | Assistant: {assistant_text[:400]}"
        if category == "workflow":
            return f"Workflow outcome: {assistant_text[:400]}"
        if category == "developer":
            return f"Dev task: {assistant_text[:600]}"
        return assistant_text[:800]

    def _extract_metadata(self, result: Any, meta: Dict[str, Any]) -> Dict[str, Any]:
        data = {}
        if meta:
            data["command_type"] = meta.get("command_type")
            data["intent"] = meta.get("intent")
            data["model_source"] = meta.get("model_source")
        if result and isinstance(getattr(result, "data", None), dict):
            payload = dict(result.data)
            url = payload.get("url")
            if url:
                data["url"] = url
            sources = payload.get("sources")
            if sources:
                data["sources"] = sources
            query = payload.get("query")
            if query:
                data["query"] = query
        return data

    def _sanitize_text(self, text: str) -> str:
        text = (text or "").strip()
        if not text:
            return ""
        masked = text
        try:
            for cred in self.credential_detector.detect_all(text):
                if cred.value in masked:
                    masked = masked.replace(cred.value, f"<redacted:{cred.service_name.lower()}>")
        except Exception:
            pass
        return masked

    def _is_trainable(
        self,
        result: Any,
        category: str,
        meta: Optional[Dict[str, Any]] = None,
        user_text: str = "",
        assistant_text: str = "",
    ) -> bool:
        if not getattr(self.config, "learning_train_enabled", True):
            return False
        if category in {"mistake"}:
            return False
        if result is None:
            # Conversation and web learning can still be trainable if model output is substantive.
            model_source = str((meta or {}).get("model_source", "")).strip().lower()
            if model_source in {"", "rule", "error", "none"}:
                return False
            if len((user_text or "").strip().split()) < 2:
                return False
            if len((assistant_text or "").strip().split()) < 5:
                return False
            return category in {"general", "research", "developer", "workflow"}
        if not getattr(result, "success", True):
            return False
        if getattr(result, "requires_confirmation", False):
            return False
        return True


_learning_engine: Optional[LearningEngine] = None


def get_learning_engine(memory_manager=None) -> LearningEngine:
    global _learning_engine
    if _learning_engine is None:
        _learning_engine = LearningEngine(memory_manager=memory_manager)
    return _learning_engine
