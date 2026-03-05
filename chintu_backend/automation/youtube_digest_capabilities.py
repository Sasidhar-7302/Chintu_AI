"""YouTube digest capability: summarize a YouTube video from its transcript."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel, Field

from chintu_backend.core.capabilities import ActionResult, Capability, CapabilityType

logger = logging.getLogger(__name__)


class YouTubeDigestSchema(BaseModel):
    url: str = Field(..., description="YouTube URL to summarize.")
    max_chars: int = Field(12000, ge=2000, le=60000, description="Max transcript chars to send to summarizer.")


def _extract_url(text: str) -> str:
    m = re.search(r"(https?://[^\s]+)", text or "", flags=re.IGNORECASE)
    if not m:
        return ""
    url = m.group(1).strip().rstrip(").,;\"'")
    return url


def _try_get_open_browser_url(context: Dict[str, Any]) -> str:
    """Best-effort: reuse an already-open Chintu browser session and return its URL.

    Notes:
    - This does NOT read the user's external browser URL. It only checks Playwright
      sessions opened via Chintu's browser controller.
    - We intentionally do not auto-launch a new browser for privacy and UX reasons.
    """
    try:
        from chintu_backend.automation.browser import browser_controller as bc

        controllers = []
        try:
            controllers = list(getattr(bc, "_browser_controllers", {}).values())
        except Exception:
            controllers = []

        # Prefer any currently-open controller.
        for controller in controllers:
            try:
                if not getattr(controller, "is_open", False):
                    continue
                info = controller.get_page_info()
                url = str(getattr(info, "url", "") or "").strip()
                if url:
                    return url
            except Exception:
                continue

        # Fallback: check default singleton keys (headless True/False) without opening a new page.
        for headless in (False, True):
            try:
                controller = bc.get_browser_controller(headless=headless, profile_name=None)
                if not getattr(controller, "is_open", False):
                    continue
                info = controller.get_page_info()
                url = str(getattr(info, "url", "") or "").strip()
                if url:
                    return url
            except Exception:
                continue
    except Exception:
        return ""

    return ""


def _video_id(url: str) -> str:
    try:
        parsed = urlparse(url)
        host = (parsed.netloc or "").lower()
        if host.endswith("youtu.be"):
            vid = parsed.path.strip("/").split("/")[0]
            return vid
        qs = parse_qs(parsed.query or "")
        if "v" in qs and qs["v"]:
            return str(qs["v"][0])
        # /embed/<id>
        parts = [p for p in (parsed.path or "").split("/") if p]
        if "embed" in parts:
            idx = parts.index("embed")
            if idx + 1 < len(parts):
                return parts[idx + 1]
        return ""
    except Exception:
        return ""


def _format_ts(seconds: float) -> str:
    s = int(max(0, seconds))
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _fetch_transcript(video_id: str) -> Tuple[List[Dict[str, Any]], str]:
    """Return (segments, error)."""
    if not video_id:
        return [], "Missing video id."
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound  # noqa: PLC2701

        try:
            segments = YouTubeTranscriptApi.get_transcript(video_id)
            if isinstance(segments, list):
                return segments, ""
        except (TranscriptsDisabled, NoTranscriptFound):
            return [], "Transcript not available for this video."
        except Exception as exc:  # noqa: BLE001
            return [], str(exc)
    except ImportError:
        return [], "Missing dependency: youtube-transcript-api"

    return [], "Failed to fetch transcript."


def _summarize(router, transcript_text: str) -> str:
    system = (
        "You summarize YouTube videos accurately. "
        "Use only the transcript provided. If you are unsure, say so."
    )
    prompt = (
        "Summarize this YouTube video transcript.\n\n"
        "Return Markdown with:\n"
        "- Key takeaways (5-10 bullets)\n"
        "- Timeline (bullets with timestamps)\n"
        "- If applicable: actionable steps\n\n"
        "Transcript:\n"
        f"{transcript_text}\n"
    )
    try:
        if hasattr(router, "route_and_execute"):
            resp, _src = router.route_and_execute(prompt, system_prompt=system)
            return str(resp or "").strip()
    except Exception:
        return ""
    return ""


def handle_youtube_digest(text: str, context: Dict[str, Any]) -> ActionResult:
    validated = context.get("_validated_params")
    url = ""
    max_chars = 12000
    if validated and isinstance(validated, YouTubeDigestSchema):
        url = str(validated.url or "").strip()
        max_chars = int(validated.max_chars or max_chars)
    if not url:
        url = _extract_url(text)
    if not url:
        url = _try_get_open_browser_url(context)
    if not url:
        return ActionResult.fail(
            "Provide a YouTube URL to summarize (or open the video in Chintu's browser first).",
            "youtube_digest",
        )

    vid = _video_id(url)
    if not vid:
        return ActionResult.fail("That doesn't look like a valid YouTube URL (couldn't extract video id).", "youtube_digest")

    segments, err = _fetch_transcript(vid)
    if err:
        return ActionResult.fail(
            f"Could not fetch transcript: {err}. If needed, install: pip install youtube-transcript-api",
            "youtube_digest",
        )
    if not segments:
        return ActionResult.fail("Transcript was empty.", "youtube_digest")

    # Build compact transcript text with timestamps.
    lines: List[str] = []
    for seg in segments:
        try:
            start = float(seg.get("start") or 0.0)
            text_line = str(seg.get("text") or "").replace("\n", " ").strip()
            if not text_line:
                continue
            lines.append(f"[{_format_ts(start)}] {text_line}")
        except Exception:
            continue
    transcript_text = "\n".join(lines).strip()
    if len(transcript_text) > max_chars:
        transcript_text = transcript_text[:max_chars].rstrip() + "\n...(truncated)..."

    # Summarize (router decides local vs cloud).
    router = None
    try:
        if context.get("model_router"):
            router = context.get("model_router")
    except Exception:
        router = None
    if not router:
        try:
            from chintu_backend.core.model_router import get_router

            router = get_router()
        except Exception:
            router = None

    summary = _summarize(router, transcript_text) if router else ""
    if not summary:
        summary = "Transcript fetched, but summarization is unavailable (model router not ready)."

    # Evidence artifacts (best-effort).
    run_id = context.get("_run_id") if isinstance(context, dict) else None
    artifacts: Dict[str, str] = {}
    try:
        from chintu_backend.core.run_manager import get_run_manager

        rm = get_run_manager()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        if run_id:
            t_path = rm.write_artifact(str(run_id), f"youtube_transcript_{stamp}.txt", transcript_text)
            s_path = rm.write_artifact(str(run_id), f"youtube_digest_{stamp}.md", summary)
            if t_path:
                artifacts["transcript_path"] = t_path
            if s_path:
                artifacts["summary_path"] = s_path
    except Exception:
        pass

    msg = f"**YouTube Digest**\n- URL: {url}\n\n{summary}".strip()
    data = {"url": url, "video_id": vid, "segments": len(segments), **artifacts}
    return ActionResult.ok(msg, data, "youtube_digest")


def register_youtube_digest_capabilities(registry) -> None:
    registry.register(
        Capability(
            name="youtube_digest",
            triggers=[
                "youtube digest",
                "summarize this youtube",
                "summarize this video",
                "summarize the youtube video",
                "i don't have time to watch",
            ],
            handler=handle_youtube_digest,
            requires_confirmation=False,
            description="summarize a YouTube video from its transcript",
            capability_type=CapabilityType.PRODUCTIVITY,
            examples=[
                "Summarize this YouTube video: https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "I don't have time to watch this 20-minute video. Summarize it for me: <url>",
            ],
            schema=YouTubeDigestSchema,
        )
    )
