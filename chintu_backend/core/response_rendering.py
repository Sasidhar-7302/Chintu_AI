"""Shared text/speech rendering helpers for command responses."""

from __future__ import annotations

import re
from typing import Dict

_TTS_URL_RE = re.compile(r"https?://\S+|www\.\S+", flags=re.IGNORECASE)
_TTS_EMAIL_RE = re.compile(r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[A-Za-z]{2,}\b")
_TTS_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)", flags=re.IGNORECASE)
_TTS_WIN_PATH_RE = re.compile(r"[A-Za-z]:(?:\\\\|\\)[^\n]+")
_TTS_UNIX_PATH_RE = re.compile(r"(?:^|\s)/[\w./-]+")
_TTS_CITATION_RE = re.compile(r"\[(?:\s*source\s*)?\d+\]", flags=re.IGNORECASE)
_TTS_SOURCE_LABEL_RE = re.compile(r"\b(?:sources?|citations?)\s*:\s*", flags=re.IGNORECASE)
_TTS_NEWS_AGE_RE = re.compile(r"\(\s*(?:just now|\d+\s*[mhd]\s*ago)\s*\)", flags=re.IGNORECASE)
_TTS_DUP_SOURCE_RE = re.compile(r"\s*-\s*([A-Za-z0-9&.' ]{2,80})\s*-\s*\1\b", flags=re.IGNORECASE)
_TTS_BULLET_INDEX_RE = re.compile(r"^\s*\d{1,2}\.\s*")
_TTS_CATEGORY_RE = re.compile(r"^\s*\[[A-Za-z]+\]\s*")
_TTS_ESCAPED_SEQUENCE_RE = re.compile(r"(?:\\[nrt])+")
_TTS_INLINE_DECOR_RE = re.compile(r"(?:={3,}|_{3,}|~{3,})")
_TTS_LABEL_ONLY_RE = re.compile(r"^(?:sources?|citations?|links?|urls?)\s*[:=-]?\s*$", flags=re.IGNORECASE)
_TTS_PUNCT_ONLY_RE = re.compile(r"^[,.;:!?|\-_/\\]+$")
_TTS_STACKTRACE_RE = re.compile(
    r"^(?:traceback \(most recent call last\)|file \".*\", line \d+|at [\w./\\:-]+:\d+|exception:|error:|[a-z_]*error:)",
    flags=re.IGNORECASE,
)
_TTS_KEYVALUE_LINE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_ -]{0,40}:\s*.+$")
_TTS_ACTION_SENTENCE_RE = re.compile(
    r"\b(?:completed|done|created|saved|opened|installed|updated|moved|generated|finished|failed)\b",
    flags=re.IGNORECASE,
)
_TTS_NEXT_STEP_RE = re.compile(
    r"\b(?:next|next step|you can|if you want|say ['\"]read|to continue|would you like)\b",
    flags=re.IGNORECASE,
)
_TTS_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_TTS_SLASH_TOKEN_RE = re.compile(r"\b\S*[\\/]\S*\b")
_TTS_UNDERSCORE_TOKEN_RE = re.compile(r"\b[A-Za-z0-9]+(?:_[A-Za-z0-9]+)+\b")
_TTS_PATH_FRAGMENT_RE = re.compile(r"(?:\busers\b|\.chintu|desktop|downloads|documents|appdata)", flags=re.IGNORECASE)
_TTS_SECRETISH_TOKEN_RE = re.compile(r"\b[A-Za-z0-9_\-]{28,}\b")


def _build_tts_digest(clean_text: str, max_sentences: int = 3, max_words: int = 70) -> str:
    """Build a concise spoken digest: core answer + actions + next step."""
    body = str(clean_text or "").strip()
    if not body:
        return ""

    sentences = [s.strip() for s in _TTS_SENTENCE_SPLIT_RE.split(body) if s.strip()]
    if not sentences:
        return body

    if len(sentences) <= max_sentences and len(body.split()) <= max_words:
        return body

    selected: list[str] = []
    selected_set = set()

    def _add(sentence: str) -> None:
        key = sentence.lower()
        if key in selected_set:
            return
        selected.append(sentence)
        selected_set.add(key)

    _add(sentences[0])

    for sentence in sentences[1:]:
        if _TTS_ACTION_SENTENCE_RE.search(sentence):
            _add(sentence)
        if len(selected) >= max_sentences:
            break

    next_step_sentence = ""
    if len(selected) < max_sentences:
        for sentence in sentences[1:]:
            if _TTS_NEXT_STEP_RE.search(sentence):
                next_step_sentence = sentence
                _add(sentence)
            if len(selected) >= max_sentences:
                break
    else:
        for sentence in sentences[1:]:
            if _TTS_NEXT_STEP_RE.search(sentence):
                next_step_sentence = sentence
                break

    if next_step_sentence and next_step_sentence.lower() not in selected_set and max_sentences >= 2:
        selected[-1] = next_step_sentence
        selected_set.add(next_step_sentence.lower())

    if len(selected) < max_sentences:
        for sentence in sentences[1:]:
            _add(sentence)
            if len(selected) >= max_sentences:
                break

    digest = " ".join(selected).strip()
    if len(sentences) > len(selected) or len(body.split()) > max_words:
        digest = f"{digest} I can read more details if you want."
    return re.sub(r"\s+", " ", digest).strip()


def sanitize_for_tts(
    text: str,
    preserve_links: bool = False,
    summarize: bool = False,
    max_sentences: int = 3,
    max_words: int = 70,
    include_meta_hints: bool = False,
) -> str:
    """Convert markdown/log-heavy output into natural speech-friendly text."""
    raw_text = str(text or "").strip()
    if not raw_text:
        return ""

    lines = raw_text.splitlines()
    cleaned_lines = []
    skipped_link_line = False
    skipped_table_rows = 0
    skipped_code_rows = 0
    skipped_stack_rows = 0
    skipped_path_rows = 0

    for line in lines:
        raw = str(line or "").strip()
        if not raw:
            continue

        if raw.startswith("```"):
            skipped_code_rows += 1
            continue
        if raw.startswith("|"):
            skipped_table_rows += 1
            continue

        if _TTS_STACKTRACE_RE.match(raw):
            skipped_stack_rows += 1
            continue

        banner = re.match(r"^=+\s*(.*?)\s*=+$", raw)
        if banner:
            raw = banner.group(1).strip()

        if re.fullmatch(r"[-=*_~`|\\/.]{3,}", raw):
            continue

        if not preserve_links and _TTS_LABEL_ONLY_RE.fullmatch(raw):
            continue

        raw = re.sub(r"^\s*[-*]\s+", "", raw)
        raw = _TTS_BULLET_INDEX_RE.sub("", raw)
        raw = re.sub(r"^\s*#+\s*", "", raw)
        raw = _TTS_CATEGORY_RE.sub("", raw)

        raw = _TTS_MD_LINK_RE.sub(r"\1", raw)
        had_path = bool(_TTS_WIN_PATH_RE.search(raw) or _TTS_UNIX_PATH_RE.search(raw))

        if not preserve_links:
            had_url = bool(_TTS_URL_RE.search(raw))
            raw = _TTS_URL_RE.sub("", raw)
            if had_url and not raw.strip():
                skipped_link_line = True
                continue
            raw = _TTS_EMAIL_RE.sub("", raw)
            raw = _TTS_SECRETISH_TOKEN_RE.sub("", raw)

        if not preserve_links:
            raw = _TTS_SOURCE_LABEL_RE.sub("", raw)
            raw = _TTS_CITATION_RE.sub("", raw)

        if not preserve_links:
            raw = _TTS_WIN_PATH_RE.sub("", raw)
            raw = _TTS_UNIX_PATH_RE.sub(" ", raw)
            slashy_before = raw
            raw = _TTS_SLASH_TOKEN_RE.sub(" ", raw)
            raw = _TTS_UNDERSCORE_TOKEN_RE.sub(" ", raw)
            if had_path or raw != slashy_before:
                skipped_path_rows += 1
                line_low = raw.lower()
                if any(token in line_low for token in ["saved to", "written to", "exported to", "stored at"]):
                    raw = "Saved output file."

        raw = _TTS_NEWS_AGE_RE.sub("", raw)
        raw = _TTS_DUP_SOURCE_RE.sub(r" - \1", raw)
        raw = _TTS_ESCAPED_SEQUENCE_RE.sub(" ", raw)
        raw = _TTS_INLINE_DECOR_RE.sub(" ", raw)

        if not preserve_links:
            raw = re.sub(r"\bsource\b", "", raw, flags=re.IGNORECASE)

        raw = raw.replace("`", "")
        raw = raw.replace("\\\\", " ")
        raw = raw.replace("\\", " ")
        raw = raw.replace("*", " ")
        raw = re.sub(r"\s+", " ", raw).strip()
        raw = re.sub(r"\s+([,.;:!?])", r"\1", raw)
        raw = raw.strip(" -|")

        if not preserve_links and _TTS_PATH_FRAGMENT_RE.search(raw):
            skipped_path_rows += 1
            lowered = raw.lower()
            if any(token in lowered for token in ["saved", "written", "exported", "stored", "receipt"]):
                raw = "Saved output file."
            else:
                continue

        if _TTS_PUNCT_ONLY_RE.fullmatch(raw):
            continue
        if raw in {"{", "}", "[", "]"}:
            continue
        if not preserve_links and _TTS_KEYVALUE_LINE_RE.match(raw):
            low = raw.lower()
            has_url_token = "http://" in low or "https://" in low
            if not has_url_token and not any(
                token in low for token in ["status", "result", "summary", "next", "action"]
            ):
                continue
        if not raw:
            continue
        cleaned_lines.append(raw)

    if include_meta_hints and skipped_link_line and cleaned_lines:
        cleaned_lines.append("Links are available in chat.")
    if include_meta_hints and skipped_path_rows and cleaned_lines:
        cleaned_lines.append("File paths are available in chat.")
    if include_meta_hints and (skipped_table_rows or skipped_code_rows) and cleaned_lines:
        cleaned_lines.append("Detailed tables and code are available in chat.")
    if skipped_stack_rows and cleaned_lines:
        cleaned_lines.append("Technical error details are available in chat.")

    if not cleaned_lines:
        if not preserve_links:
            return "I shared the details in chat."
        fallback = re.sub(r"\s+", " ", raw_text).strip()
        return fallback

    out = " ".join(cleaned_lines).strip()
    out = re.sub(r"\s+", " ", out)
    if summarize and not preserve_links:
        out = _build_tts_digest(out, max_sentences=max_sentences, max_words=max_words)
    return out


def build_dual_view_response(
    text: str,
    *,
    preserve_links_in_speech: bool = False,
    summarize_speech: bool = False,
    speech_max_sentences: int = 3,
    speech_max_words: int = 70,
) -> Dict[str, str]:
    """Return separate text and speech views for human-quality output handling."""
    text_view = str(text or "").strip()
    speech_view = sanitize_for_tts(
        text_view,
        preserve_links=bool(preserve_links_in_speech),
        summarize=bool(summarize_speech),
        max_sentences=max(1, int(speech_max_sentences)),
        max_words=max(20, int(speech_max_words)),
    )
    return {"text_view": text_view, "speech_view": speech_view}


def ensure_readable_completion(text: str) -> str:
    """
    Add a gentle continuation hint when a long response appears cut mid-thought.
    This avoids abrupt UI/chat endings like "... Scope: JavaSc".
    """
    msg = str(text or "").rstrip()
    if not msg:
        return ""
    tail_token_match = re.search(r"([A-Za-z0-9_]+)$", msg)
    tail_token = tail_token_match.group(1) if tail_token_match else ""
    suspicious_tail = bool(
        re.search(r"\b[A-Za-z]{1,2}$", msg)
        or re.search(r"[a-z][A-Z][A-Za-z]*$", msg)
        or (tail_token and "_" in tail_token and not tail_token.isupper())
    )
    if len(msg) < 220 and not suspicious_tail:
        return msg
    if msg.endswith(("```", "...", "…")):
        return msg
    if re.search(r"[.!?\"')\]]\s*$", msg):
        return msg
    if re.search(r"(?:\n\s*[-*]|\n\s*\d+\.)", msg):
        # Keep list outputs unchanged unless they are clearly cut.
        tail = msg[-25:]
        if re.search(r"[.!?\"')\]]\s*$", tail):
            return msg
    if re.search(r"[A-Za-z0-9]$", msg):
        return f"{msg} ... Say 'continue' if you want the rest."
    return msg
