"""Inbox triage (Unread email summarization) capability.

Design goals:
- Read-only: never sends emails and never marks them as read (best-effort).
- Local-first: by default, summarization is done with the local Ollama model
  to avoid sending email content to cloud LLM providers.
- Robust: if local LLM is unavailable, fall back to lightweight heuristics.
"""

from __future__ import annotations

import email
import imaplib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from chintu_backend.core.capabilities import ActionResult, Capability, CapabilityType
from chintu_backend.core.config import get_config

logger = logging.getLogger(__name__)


class EmailTriageSchema(BaseModel):
    max_unread: int = Field(12, ge=1, le=50, description="Max unread messages to scan.")
    lookback_hours: int = Field(72, ge=1, le=24 * 31, description="How far back to consider unread messages.")
    include_snippets: bool = Field(True, description="Include short snippets in the output.")


@dataclass(frozen=True)
class UnreadEmail:
    uid: str
    sender: str
    subject: str
    date_utc: Optional[datetime]
    snippet: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uid": self.uid,
            "sender": self.sender,
            "subject": self.subject,
            "date_utc": self.date_utc.isoformat() if self.date_utc else None,
            "snippet": self.snippet,
        }


def _decode_header(value: str) -> str:
    from email.header import decode_header

    parts = decode_header(value or "")
    decoded: List[str] = []
    for text, encoding in parts:
        if isinstance(text, bytes):
            try:
                decoded.append(text.decode(encoding or "utf-8", errors="ignore"))
            except Exception:  # noqa: BLE001
                decoded.append(text.decode("utf-8", errors="ignore"))
        else:
            decoded.append(str(text))
    return "".join(decoded).strip()


def _parse_date(value: str) -> Optional[datetime]:
    from email.utils import parsedate_to_datetime

    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:  # noqa: BLE001
        return None


def _strip_html(value: str) -> str:
    text = re.sub(r"<style[\s\S]*?</style>", " ", value, flags=re.IGNORECASE)
    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_text(msg: email.message.Message) -> str:
    if msg.is_multipart():
        parts = msg.walk()
    else:
        parts = [msg]

    best_text = ""
    best_score = -1

    for part in parts:
        content_type = (part.get_content_type() or "").lower()
        if content_type not in {"text/plain", "text/html"}:
            continue
        try:
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            charset = part.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="ignore")
        except Exception:  # noqa: BLE001
            continue

        if content_type == "text/html":
            text = _strip_html(text)

        score = len(text)
        if score > best_score:
            best_score = score
            best_text = text

    return best_text.strip()


def _mask_sender(sender: str) -> str:
    s = (sender or "").strip()
    if not s:
        return ""
    # keep display name, mask email local-part when present
    m = re.search(r"([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})", s)
    if not m:
        return s
    local, domain = m.group(1), m.group(2)
    if len(local) <= 2:
        masked = local[:1] + "*"
    else:
        masked = local[:1] + ("*" * (len(local) - 2)) + local[-1]
    return s.replace(m.group(0), f"{masked}@{domain}")


def _connect_imap() -> imaplib.IMAP4_SSL:
    cfg = get_config()
    host = str(cfg.email_imap_host or "")
    port = int(cfg.email_imap_port or 993)
    user = str(cfg.email_imap_user or "")
    password = str(cfg.email_imap_password or "")
    folder = str(cfg.email_imap_folder or "INBOX")
    if not host or not user or not password:
        raise RuntimeError("Missing IMAP settings (host/user/password). Configure them in UI > Integrations.")

    client = imaplib.IMAP4_SSL(host, port)
    client.login(user, password)
    client.select(folder)
    return client


def _scan_unread_uids(client: imaplib.IMAP4_SSL, limit: int) -> List[str]:
    typ, data = client.uid("search", None, "UNSEEN")
    if typ != "OK" or not data or not data[0]:
        return []
    uids = data[0].decode("utf-8", errors="ignore").split()
    # newest last; return newest first
    return list(reversed(uids[-max(1, int(limit)) :]))


def fetch_unread_emails(*, max_unread: int, lookback_hours: int) -> Tuple[List[UnreadEmail], str]:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=max(1, int(lookback_hours)))
    items: List[UnreadEmail] = []

    try:
        client = _connect_imap()
    except Exception as exc:  # noqa: BLE001
        return [], f"Email connection failed: {exc}"

    try:
        uids = _scan_unread_uids(client, max_unread)
        for uid in uids:
            try:
                # BODY.PEEK avoids marking as read (best-effort).
                typ, data = client.uid("fetch", uid, "(BODY.PEEK[])")
                if typ != "OK" or not data:
                    continue
                raw_bytes = None
                for part in data:
                    if isinstance(part, tuple) and part[1]:
                        raw_bytes = part[1]
                        break
                if not raw_bytes:
                    continue
                msg = email.message_from_bytes(raw_bytes)
                sender = _decode_header(msg.get("From", ""))
                subject = _decode_header(msg.get("Subject", "")) or "(no subject)"
                date_utc = _parse_date(msg.get("Date", ""))
                if date_utc and date_utc < cutoff:
                    continue
                body = _extract_text(msg)
                snippet = re.sub(r"\s+", " ", body).strip()[:240]
                items.append(
                    UnreadEmail(
                        uid=str(uid),
                        sender=_mask_sender(sender),
                        subject=subject,
                        date_utc=date_utc,
                        snippet=snippet,
                    )
                )
                if len(items) >= max_unread:
                    break
            except Exception:
                continue
    finally:
        try:
            client.logout()
        except Exception:  # noqa: BLE001
            pass

    return items, ""


def _heuristic_triage(items: List[UnreadEmail]) -> str:
    if not items:
        return "You have no unread emails (in the scanned window)."

    urgent_terms = [
        "urgent",
        "action required",
        "asap",
        "interview",
        "offer",
        "invoice",
        "payment",
        "meeting",
        "schedule",
        "deadline",
        "security",
        "verify",
    ]

    def score(item: UnreadEmail) -> int:
        text = f"{item.subject} {item.snippet}".lower()
        s = 0
        for term in urgent_terms:
            if term in text:
                s += 2
        if "unsubscribe" in text:
            s -= 2
        if "no-reply" in item.sender.lower():
            s -= 1
        return s

    ranked = sorted(items, key=score, reverse=True)
    top = ranked[: min(6, len(ranked))]
    lines = [f"Unread emails scanned: {len(items)}", "", "Top items:"]
    for i, it in enumerate(top, start=1):
        when = it.date_utc.isoformat() if it.date_utc else ""
        lines.append(f"{i}. {it.subject} ({it.sender}) {when}".strip())
        if it.snippet:
            lines.append(f"   - {it.snippet}")
    lines.append("")
    lines.append("Tip: say 'summarize my unread emails' after configuring IMAP for a deeper triage.")
    return "\n".join(lines).strip()


def _llm_triage(items: List[UnreadEmail]) -> str:
    """Local-only LLM triage using Ollama."""
    if not items:
        return "You have no unread emails (in the scanned window)."
    try:
        from chintu_backend.brain.llm.ollama_client import OllamaClient

        cfg = get_config()
        llm = OllamaClient(host=cfg.ollama_host, model=cfg.ollama_model)
        if not llm.is_available:
            return _heuristic_triage(items)
    except Exception:
        return _heuristic_triage(items)

    # Keep prompt compact.
    rows = []
    for i, it in enumerate(items, start=1):
        ts = it.date_utc.isoformat() if it.date_utc else ""
        rows.append(
            f"[{i}] from: {it.sender}\nsubject: {it.subject}\ndate_utc: {ts}\nsnippet: {it.snippet}\n"
        )

    system = (
        "You are an email triage assistant. "
        "Classify emails by urgency and whether a reply is needed. "
        "Do not invent details that are not in the snippet/subject."
    )
    prompt = (
        "Unread emails (masked senders, short snippets):\n\n"
        + "\n".join(rows)
        + "\n\n"
        "Return Markdown with these sections:\n"
        "1) Important (need action today): up to 6 items with why + suggested next step.\n"
        "2) Needs reply (not urgent): up to 6 items.\n"
        "3) Probably newsletters/low priority: short list.\n"
        "4) Action Items: bullet list.\n"
    )
    return llm.generate(prompt, system_prompt=system).strip() or _heuristic_triage(items)


def handle_email_inbox_triage(text: str, context: Dict[str, Any]) -> ActionResult:
    cfg = get_config()
    if not bool(getattr(cfg, "email_reader_enabled", True)):
        return ActionResult.fail("Email reader is disabled in config.", "email_inbox_triage")

    max_unread = 12
    lookback_hours = 72
    include_snippets = True
    validated = context.get("_validated_params")
    if validated and isinstance(validated, EmailTriageSchema):
        max_unread = int(validated.max_unread)
        lookback_hours = int(validated.lookback_hours)
        include_snippets = bool(validated.include_snippets)

    items, err = fetch_unread_emails(max_unread=max_unread, lookback_hours=lookback_hours)
    if err:
        return ActionResult.fail(err, "email_inbox_triage")

    if not include_snippets:
        items = [UnreadEmail(uid=i.uid, sender=i.sender, subject=i.subject, date_utc=i.date_utc, snippet="") for i in items]

    summary = _llm_triage(items)
    data = {"count": len(items), "emails": [i.to_dict() for i in items]}
    return ActionResult.ok(summary, data, "email_inbox_triage")


def register_email_triage_capabilities(registry) -> None:
    registry.register(
        Capability(
            name="email_inbox_triage",
            triggers=[
                "check my unread emails",
                "unread emails",
                "email triage",
                "inbox zero",
                "summarize my emails",
                "summarize my unread emails",
            ],
            handler=handle_email_inbox_triage,
            requires_confirmation=False,
            description="read unread emails via IMAP and summarize action items (local-only)",
            capability_type=CapabilityType.PRODUCTIVITY,
            examples=[
                "Check my unread emails. Summarize important ones and list any that need a reply today.",
                "Inbox zero triage",
            ],
            schema=EmailTriageSchema,
        )
    )

