"""IMAP email reader focused on extracting recent verification codes."""

from __future__ import annotations

import email
import imaplib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.header import decode_header
from email.utils import parsedate_to_datetime
from typing import Dict, Iterable, List, Optional, Tuple

from ...core.config import get_config

logger = logging.getLogger(__name__)

CODE_PATTERN = re.compile(r"\b(\d{4,8})\b")


def _decode_header(value: str) -> str:
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
    # Lightweight HTML stripping to avoid extra dependencies.
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


def _unique_codes(values: Iterable[str]) -> List[str]:
    seen = set()
    codes: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        codes.append(value)
    return codes


@dataclass
class EmailMatch:
    """A minimal, safe representation of a matching email."""

    uid: str
    sender: str
    subject: str
    date_utc: Optional[datetime]
    codes: List[str]
    snippet: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "uid": self.uid,
            "sender": self.sender,
            "subject": self.subject,
            "date_utc": self.date_utc.isoformat() if self.date_utc else None,
            "codes": list(self.codes),
            "snippet": self.snippet,
        }


class EmailReader:
    """IMAP client that scans recent emails for verification codes."""

    def __init__(self) -> None:
        self.config = get_config()

    @property
    def enabled(self) -> bool:
        return bool(getattr(self.config, "email_reader_enabled", False))

    @property
    def configured(self) -> Tuple[bool, str]:
        if not self.enabled:
            return False, "Email reader is disabled (CHINTU_EMAIL_READER_ENABLED=false)."
        required = {
            "email_imap_host": getattr(self.config, "email_imap_host", None),
            "email_imap_user": getattr(self.config, "email_imap_user", None),
            "email_imap_password": getattr(self.config, "email_imap_password", None),
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            return False, "Missing email settings: " + ", ".join(missing)
        return True, ""

    def _connect(self) -> imaplib.IMAP4_SSL:
        host = str(self.config.email_imap_host)
        port = int(self.config.email_imap_port or 993)
        user = str(self.config.email_imap_user)
        password = str(self.config.email_imap_password)

        client = imaplib.IMAP4_SSL(host, port)
        client.login(user, password)
        client.select(str(self.config.email_imap_folder or "INBOX"))
        return client

    def test_connection(self) -> tuple[bool, str]:
        """Best-effort IMAP connectivity check (no message bodies read)."""
        ok, reason = self.configured
        if not ok:
            return False, reason
        try:
            client = self._connect()
        except Exception as exc:  # noqa: BLE001
            return False, f"Email connection failed: {exc}"
        try:
            typ, data = client.uid("search", None, "UNSEEN")
            unseen = 0
            if typ == "OK" and data and data[0]:
                unseen = len(data[0].decode("utf-8", errors="ignore").split())
            return True, f"IMAP connection OK. Unread messages: {unseen}."
        finally:
            try:
                client.logout()
            except Exception:  # noqa: BLE001
                pass

    def _scan_uids(self, client: imaplib.IMAP4_SSL, limit: int) -> List[str]:
        typ, data = client.uid("search", None, "ALL")
        if typ != "OK" or not data or not data[0]:
            return []
        uids = data[0].decode("utf-8", errors="ignore").split()
        if not uids:
            return []
        # Scan a wider window than the requested max messages.
        scan_limit = max(limit * 6, 60)
        return uids[-scan_limit:]

    def _fetch_message(self, client: imaplib.IMAP4_SSL, uid: str) -> Optional[email.message.Message]:
        typ, data = client.uid("fetch", uid, "(RFC822)")
        if typ != "OK" or not data:
            return None
        for part in data:
            if not isinstance(part, tuple) or not part[1]:
                continue
            try:
                return email.message_from_bytes(part[1])
            except Exception:  # noqa: BLE001
                return None
        return None

    def fetch_recent_codes(
        self,
        site_hint: str = "",
        lookback_minutes: Optional[int] = None,
        max_messages: Optional[int] = None,
    ) -> Tuple[List[EmailMatch], str]:
        ok, reason = self.configured
        if not ok:
            return [], reason

        hint = (site_hint or "").strip().lower()
        lookback = int(lookback_minutes or self.config.email_reader_lookback_minutes)
        limit = int(max_messages or self.config.email_reader_max_messages)
        now_utc = datetime.now(timezone.utc)
        cutoff = now_utc - timedelta(minutes=max(1, lookback))

        allowed_senders = [s.lower() for s in (self.config.email_reader_allowed_senders or []) if s]
        keywords = [k.lower() for k in (self.config.email_reader_subject_keywords or []) if k]

        matches: List[EmailMatch] = []

        try:
            client = self._connect()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Email reader connection failed: %s", exc)
            return [], f"Email connection failed: {exc}"

        try:
            uids = self._scan_uids(client, limit)
            for uid in reversed(uids):
                msg = self._fetch_message(client, uid)
                if not msg:
                    continue

                sender_raw = msg.get("From", "")
                subject_raw = msg.get("Subject", "")
                date_raw = msg.get("Date", "")

                sender = _decode_header(sender_raw)
                subject = _decode_header(subject_raw)
                date_utc = _parse_date(date_raw)

                if date_utc and date_utc < cutoff:
                    continue

                sender_lower = sender.lower()
                subject_lower = subject.lower()

                if allowed_senders and not any(s in sender_lower for s in allowed_senders):
                    continue

                if hint and hint not in sender_lower and hint not in subject_lower:
                    continue

                if keywords and not any(k in subject_lower for k in keywords):
                    # Allow site-specific hints to bypass generic keyword filters.
                    if not hint:
                        continue

                body = _extract_text(msg)
                body_lower = body.lower()

                codes = _unique_codes(CODE_PATTERN.findall(body))
                if not codes:
                    # Some providers put codes in the subject line.
                    codes = _unique_codes(CODE_PATTERN.findall(subject))
                if not codes:
                    continue

                relevance_terms = ["code", "verify", "verification", "security", "login", "auth"]
                is_relevant = any(t in subject_lower or t in body_lower for t in relevance_terms)
                if not is_relevant and not hint:
                    continue

                snippet = re.sub(r"\s+", " ", body)[:200].strip()
                matches.append(
                    EmailMatch(
                        uid=uid,
                        sender=sender,
                        subject=subject,
                        date_utc=date_utc,
                        codes=codes,
                        snippet=snippet,
                    )
                )

                if len(matches) >= limit:
                    break
        finally:
            try:
                client.logout()
            except Exception:  # noqa: BLE001
                pass

        return matches, ""


_reader: Optional[EmailReader] = None


def get_email_reader() -> EmailReader:
    global _reader
    if _reader is None:
        _reader = EmailReader()
    return _reader

