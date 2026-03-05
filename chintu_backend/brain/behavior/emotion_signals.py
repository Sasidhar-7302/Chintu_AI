"""Emotion and intent signal extraction for Chintu."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
import re

try:
    from textblob import TextBlob
    HAS_TEXTBLOB = True
except Exception:
    TextBlob = None
    HAS_TEXTBLOB = False


@dataclass
class EmotionSignal:
    sentiment: str = "neutral"
    urgency: str = "normal"
    frustration: str = "low"
    confusion: str = "low"
    confidence: float = 0.6
    indicators: Dict[str, Any] = field(default_factory=dict)

    def to_context(self) -> str:
        parts = [
            f"sentiment={self.sentiment}",
            f"urgency={self.urgency}",
            f"frustration={self.frustration}",
            f"confusion={self.confusion}",
            f"confidence={self.confidence:.2f}",
        ]
        return ", ".join(parts)


class EmotionIntentAnalyzer:
    """Lightweight, dependency-optional emotion and intent signals."""

    POSITIVE_WORDS: List[str] = [
        "good", "great", "awesome", "love", "like", "happy", "thanks", "appreciate",
        "excellent", "amazing", "perfect", "nice",
    ]
    NEGATIVE_WORDS: List[str] = [
        "bad", "hate", "awful", "terrible", "annoyed", "frustrated", "angry",
        "upset", "disappointed", "worse", "broken", "stuck", "failed", "fail",
    ]
    URGENT_KEYWORDS: List[str] = [
        "urgent", "asap", "immediately", "right now", "now", "today", "deadline",
        "quick", "soon", "emergency",
    ]
    FRUSTRATION_KEYWORDS: List[str] = [
        "not working", "still", "again", "wtf", "sucks", "broken", "annoying",
        "frustrated", "angry", "upset", "ridiculous",
    ]
    CONFUSION_KEYWORDS: List[str] = [
        "confused", "not sure", "don't understand", "dont understand",
        "what do you mean", "unclear", "i don't get",
    ]
    UNCERTAINTY_KEYWORDS: List[str] = [
        "maybe", "not sure", "not certain", "i guess", "unsure", "probably",
    ]

    def analyze(self, text: str, context: Optional[Dict[str, Any]] = None) -> EmotionSignal:
        raw = text or ""
        text_lower = raw.lower().strip()
        tokens = re.findall(r"[a-z']+", text_lower)
        indicators: Dict[str, Any] = {}

        # Sentiment
        sentiment = "neutral"
        polarity = 0.0
        if HAS_TEXTBLOB and TextBlob is not None:
            try:
                polarity = float(TextBlob(raw).sentiment.polarity)
            except Exception:
                polarity = 0.0
        else:
            pos_hits = sum(1 for t in tokens if t in self.POSITIVE_WORDS)
            neg_hits = sum(1 for t in tokens if t in self.NEGATIVE_WORDS)
            if pos_hits or neg_hits:
                polarity = (pos_hits - neg_hits) / max(1, pos_hits + neg_hits)

        if polarity > 0.2:
            sentiment = "positive"
        elif polarity < -0.2:
            sentiment = "negative"

        # Urgency
        urgency = "normal"
        urgent_hits = sum(1 for kw in self.URGENT_KEYWORDS if kw in text_lower)
        if urgent_hits or raw.isupper() or "!" in raw:
            urgency = "high" if urgent_hits or raw.isupper() else "medium"

        # Frustration
        frustration = "low"
        frustration_hits = sum(1 for kw in self.FRUSTRATION_KEYWORDS if kw in text_lower)
        if frustration_hits >= 2 or "!!!" in raw:
            frustration = "high"
        elif frustration_hits == 1:
            frustration = "medium"

        # Confusion
        confusion = "low"
        confusion_hits = sum(1 for kw in self.CONFUSION_KEYWORDS if kw in text_lower)
        if confusion_hits >= 2:
            confusion = "high"
        elif confusion_hits == 1:
            confusion = "medium"

        # Confidence (rough heuristic)
        confidence = 0.6
        if len(tokens) <= 3:
            confidence -= 0.2
        if any(kw in text_lower for kw in self.UNCERTAINTY_KEYWORDS):
            confidence -= 0.2
        if any(v in text_lower for v in ["please", "need", "want", "do", "build"]):
            confidence += 0.05
        if "?" in raw and confidence > 0.5:
            confidence -= 0.05

        confidence = max(0.05, min(confidence, 0.95))

        indicators.update({
            "polarity": polarity,
            "urgent_hits": urgent_hits,
            "frustration_hits": frustration_hits,
            "confusion_hits": confusion_hits,
            "token_count": len(tokens),
        })

        return EmotionSignal(
            sentiment=sentiment,
            urgency=urgency,
            frustration=frustration,
            confusion=confusion,
            confidence=confidence,
            indicators=indicators,
        )
