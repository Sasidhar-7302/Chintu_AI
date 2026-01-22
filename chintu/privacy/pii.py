"""
PII (Personally Identifiable Information) Masking Layer.
Redacts sensitive data from logs and telemetry to ensure privacy in distributed edge-cloud systems.
"""

import re
# str is builtin, no import needed

class PIIMasker:
    """Masks sensitive PII patterns in text."""
    
    PATTERNS = {
        "EMAIL": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
        "PHONE": r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",
        "IP": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
        "SSN": r"\b\d{3}-\d{2}-\d{4}\b",
        "CREDIT_CARD": r"\b(?:\d{4}[-\s]?){3}\d{4}\b"
    }

    @staticmethod
    def mask(text: str) -> str:
        """Redact PII from the input text."""
        if not text:
            return ""
            
        masked = text
        for label, pattern in PIIMasker.PATTERNS.items():
            masked = re.sub(pattern, f"[{label}]", masked)
            
        return masked

_global_masker = PIIMasker()

def mask_pii(text: str) -> str:
    return _global_masker.mask(text)
