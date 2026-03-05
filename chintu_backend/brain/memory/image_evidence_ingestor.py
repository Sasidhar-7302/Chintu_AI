"""Index screenshot/image evidence into HybridMemory for "image RAG".

Goal:
- When a Run step produces a screenshot/image artifact, extract a short caption and
  visible text (best-effort) and store it in HybridMemory.
- This makes screenshots searchable via the existing `memory_search` tool and UI.

Design:
- Best-effort and non-blocking: ingestion runs in a background worker.
- Safe by default: we only call cloud vision when a Gemini key is present (or when
  explicitly allowed for Ollama). We always redact extracted text for PII/keys.
- De-dupe: HybridMemory maintains an `artifacts` table keyed by sha256.
"""

from __future__ import annotations

import hashlib
import io
import logging
import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

logger = logging.getLogger(__name__)


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def _is_image_path(path: Path) -> bool:
    try:
        return path.suffix.lower() in _IMAGE_EXTS
    except Exception:
        return False


def _redact_text(text: str) -> str:
    masked = str(text or "")
    if not masked:
        return ""
    try:
        from chintu_backend.privacy.pii import mask_pii

        masked = mask_pii(masked)
    except Exception:
        pass
    try:
        from chintu_backend.core.credential_detector import get_credential_detector

        detector = get_credential_detector()
        for cred in detector.detect_all(masked):
            if cred.value and cred.value in masked:
                masked = masked.replace(cred.value, f"<redacted:{cred.service_name.lower()}>")
    except Exception:
        pass
    return masked


def _to_png_bytes(path: Path) -> Tuple[bytes, str]:
    """Return (png_bytes, sha256) for an image on disk.

    We hash the original file bytes for stable de-dupe, but we convert to PNG bytes
    for vision APIs (OmniParser currently tags mime_type as image/png).
    """
    raw = path.read_bytes()
    sha256 = hashlib.sha256(raw).hexdigest()
    try:
        from PIL import Image

        img = Image.open(path)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue(), sha256
    except Exception:
        # Fallback: use raw bytes as-is.
        return raw, sha256


def _safe_tag(tag: str) -> str:
    tag = str(tag or "").strip()
    if not tag:
        return ""
    # tags are comma-separated in HybridMemory; keep them single-token.
    return tag.replace(",", "_").replace("\n", " ").replace("\r", " ").strip()


@dataclass
class ImageEvidenceJob:
    path: str
    run_id: str = ""
    step_id: str = ""
    capability: str = ""


class ImageEvidenceIngestor:
    def __init__(self) -> None:
        self._q: "queue.Queue[ImageEvidenceJob]" = queue.Queue()
        self._started = False
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._per_run_count: Dict[str, int] = {}

    def start(self) -> None:
        if self._started:
            return
        self._thread = threading.Thread(target=self._worker, name="chintu-image-evidence", daemon=True)
        self._thread.start()
        self._started = True

    def stop(self, timeout_s: float = 1.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=max(0.0, float(timeout_s)))

    def enqueue_path(self, path: str, *, run_id: str = "", step_id: str = "", capability: str = "") -> None:
        path = str(path or "").strip()
        if not path:
            return
        self.start()
        self._q.put(ImageEvidenceJob(path=path, run_id=str(run_id or ""), step_id=str(step_id or ""), capability=str(capability or "")))

    def enqueue_from_evidence(self, evidence: Iterable[Any], *, run_id: str = "", step_id: str = "", capability: str = "") -> None:
        for ev in evidence or []:
            try:
                kind = ""
                value = ""
                if isinstance(ev, dict):
                    kind = str(ev.get("kind") or "")
                    value = str(ev.get("value") or "")
                else:
                    kind = str(getattr(ev, "kind", "") or "")
                    value = str(getattr(ev, "value", "") or "")
                if kind != "path":
                    continue
                if not value:
                    continue
                self.enqueue_path(value, run_id=run_id, step_id=step_id, capability=capability)
            except Exception:
                continue

    def drain_for_tests(self, timeout_s: float = 3.0) -> None:
        """Block until the queue is empty (best-effort)."""
        try:
            self.start()
            self._q.join()
        except Exception:
            return

    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._q.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                self._ingest_job(job)
            except Exception:
                logger.debug("Image evidence ingest failed (ignored)", exc_info=True)
            finally:
                try:
                    self._q.task_done()
                except Exception:
                    pass

    def _should_ingest_for_run(self, run_id: str, limit: int) -> bool:
        if not run_id:
            return True
        with self._lock:
            cur = int(self._per_run_count.get(run_id, 0))
            if cur >= max(1, int(limit)):
                return False
            self._per_run_count[run_id] = cur + 1
            return True

    def _vision_enabled(self, config) -> Tuple[bool, str]:
        """Return (enabled, reason)."""
        allow_cloud = bool(getattr(config, "memory_image_ingest_allow_cloud_vision", True))
        allow_ollama = bool(getattr(config, "memory_image_ingest_allow_ollama_vision", False))
        gemini_key = str(getattr(config, "google_ai_key", "") or "").strip()
        if allow_cloud and gemini_key:
            return True, "gemini"
        if allow_ollama:
            return True, "ollama"
        return False, "disabled"

    def _ingest_job(self, job: ImageEvidenceJob) -> None:
        from chintu_backend.core.config import get_config

        config = get_config()
        if not bool(getattr(config, "memory_enabled", True)):
            return
        if not bool(getattr(config, "memory_image_ingest_enabled", True)):
            return

        max_per_run = int(getattr(config, "memory_image_ingest_max_per_run", 40))
        if not self._should_ingest_for_run(job.run_id, max_per_run):
            return

        path = Path(str(job.path or "")).expanduser()
        if not path.exists() or not path.is_file():
            return
        if not _is_image_path(path):
            return

        try:
            max_bytes = int(getattr(config, "memory_image_ingest_max_bytes", 8 * 1024 * 1024))
            if path.stat().st_size > max(50_000, max_bytes):
                return
        except Exception:
            pass

        try:
            png_bytes, sha256 = _to_png_bytes(path)
        except Exception:
            return

        from chintu_backend.brain.memory.hybrid_memory import HybridMemoryManager, get_hybrid_memory

        mem = get_hybrid_memory()
        if mem is None:
            mem = HybridMemoryManager(db_path=getattr(config, "memory_sqlite_path", None))

        try:
            if hasattr(mem, "has_artifact") and mem.has_artifact(sha256):
                return
        except Exception:
            pass

        caption = ""
        text_content = ""
        vision_ok, vision_backend = self._vision_enabled(config)
        if vision_ok:
            try:
                from chintu_backend.vision.omniparser import get_omniparser

                parser = get_omniparser()
                analysis = parser.analyze_screen(image_bytes=png_bytes)
                if isinstance(analysis, dict) and "error" not in analysis:
                    caption = str(analysis.get("description") or "").strip()
                    text_content = str(analysis.get("text_content") or "").strip()
                if not caption:
                    # Fallback: short natural caption (one extra call only if needed).
                    caption = str(parser.describe_screen(image_bytes=png_bytes) or "").strip()
                if "vision is not available" in caption.lower():
                    caption = ""
            except Exception:
                caption = ""
                text_content = ""

        caption = _redact_text(caption).strip()
        text_content = _redact_text(text_content).strip()

        if not caption:
            caption = f"Screenshot captured ({path.name})."

        max_chars = int(getattr(config, "memory_image_ingest_max_chars", 1800))
        if text_content and len(text_content) > max_chars:
            text_content = text_content[:max_chars].rstrip() + "..."

        lines = ["[Image Evidence]"]
        lines.append(f"Caption: {caption}")
        if text_content:
            lines.append(f"Text: {text_content}")
        lines.append(f"Path: {str(path)}")
        if job.run_id:
            lines.append(f"Run: {job.run_id}")
        if job.step_id:
            lines.append(f"Step: {job.step_id}")
        if job.capability:
            lines.append(f"Capability: {job.capability}")
        if vision_ok:
            lines.append(f"Vision: {vision_backend}")
        content = "\n".join(lines).strip()

        tags = []
        if job.run_id:
            tags.append(_safe_tag(f"run:{job.run_id}"))
        if job.step_id:
            tags.append(_safe_tag(f"step:{job.step_id}"))
        if job.capability:
            tags.append(_safe_tag(f"cap:{job.capability}"))
        tags.append(_safe_tag(f"file:{path.name}"))
        tags.append(_safe_tag(f"sha256:{sha256[:16]}"))
        tags.append("kind:image")

        # Store in HybridMemory. We include the path in content so it's visible in the UI even
        # if the UI doesn't render metadata tags.
        mem.save_interaction(
            role="system",
            content=content,
            meta={
                "tags": [t for t in tags if t],
                "importance": 0.25,
                "category": "evidence",
                "source": "image_evidence",
            },
            category="evidence",
            source="image_evidence",
        )

        try:
            if hasattr(mem, "record_artifact"):
                mem.record_artifact(
                    sha256=sha256,
                    path=str(path),
                    kind="image",
                    run_id=str(job.run_id or ""),
                    step_id=str(job.step_id or ""),
                    interaction_id=None,
                )
        except Exception:
            pass


_ingestor: Optional[ImageEvidenceIngestor] = None


def get_image_evidence_ingestor() -> ImageEvidenceIngestor:
    global _ingestor
    if _ingestor is None:
        _ingestor = ImageEvidenceIngestor()
    return _ingestor

