"""Heuristics to detect payment/checkout actions.

This is a hard safety layer: the assistant must not complete purchases without
explicit user approval. We keep this lightweight and conservative, triggering
only on obvious checkout/pay/buy actions to avoid interrupting normal browsing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple


# "Add to cart" is intentionally *not* included by default (it's not payment),
# but "checkout/pay/place order" must always be confirmed.
_PAYMENT_PATTERNS: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bcheckout\b", re.IGNORECASE), "checkout"),
    (re.compile(r"\bplace\s+order\b", re.IGNORECASE), "place order"),
    (re.compile(r"\bconfirm\s+purchase\b", re.IGNORECASE), "confirm purchase"),
    (re.compile(r"\bconfirm\s+order\b", re.IGNORECASE), "confirm order"),
    (re.compile(r"\bcomplete\s+(?:your\s+)?order\b", re.IGNORECASE), "complete order"),
    (re.compile(r"\bbuy\s+now\b", re.IGNORECASE), "buy now"),
    (re.compile(r"\bconfirm\s+(?:and\s+)?pay\b", re.IGNORECASE), "confirm and pay"),
    (re.compile(r"\bsubmit\s+payment\b", re.IGNORECASE), "submit payment"),
    (re.compile(r"\bpay\s+now\b", re.IGNORECASE), "pay now"),
    (re.compile(r"\bpayment\b", re.IGNORECASE), "payment"),
    (re.compile(r"\bsubscribe\b", re.IGNORECASE), "subscribe"),
    (re.compile(r"\bpurchase\b", re.IGNORECASE), "purchase"),
    (re.compile(r"\bgift\s+card\b", re.IGNORECASE), "gift card"),
]


@dataclass(frozen=True)
class PaymentSignal:
    matched: bool
    keyword: Optional[str] = None


def detect_payment_signal(text: str, extra_keywords: Optional[Iterable[str]] = None) -> PaymentSignal:
    """Return a payment signal if the text looks like a checkout/payment action."""
    raw = (text or "").strip()
    if not raw:
        return PaymentSignal(matched=False)

    for pattern, keyword in _PAYMENT_PATTERNS:
        if pattern.search(raw):
            return PaymentSignal(matched=True, keyword=keyword)

    lowered = raw.lower()
    # Strong purchase intent: "buy ..." combined with money/order cues.
    if re.search(r"\bbuy\b", lowered):
        if re.search(r"\$\s*\d+|\b\d+\s*dollars?\b|\bgift\s+card\b|\border\b", lowered):
            return PaymentSignal(matched=True, keyword="buy")

    if extra_keywords:
        for kw in extra_keywords:
            kw_norm = str(kw or "").strip().lower()
            if not kw_norm:
                continue
            if kw_norm in lowered:
                return PaymentSignal(matched=True, keyword=kw_norm)

    return PaymentSignal(matched=False)


def is_payment_action(text: str, extra_keywords: Optional[Iterable[str]] = None) -> bool:
    """Convenience wrapper: returns True when a click/action should be approved."""
    return bool(detect_payment_signal(text, extra_keywords=extra_keywords).matched)
