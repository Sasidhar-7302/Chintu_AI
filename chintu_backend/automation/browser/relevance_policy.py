"""Browser relevance and prompt-injection sanitization helpers.

Kept as a standalone module to keep browser capabilities focused on orchestration
instead of policy internals.
"""

from __future__ import annotations

import re
from typing import Any, Dict
from urllib.parse import urlparse


def normalize_domain(value: str) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    try:
        host = (urlparse(raw).netloc or "").strip().lower()
    except Exception:
        host = ""
    if not host:
        host = str(value or "").strip().lower()
    if ":" in host:
        host = host.split(":", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    return host


def domain_matches(host: str, expected: str) -> bool:
    left = normalize_domain(host)
    right = normalize_domain(expected)
    if not left or not right:
        return False
    return left == right or left.endswith("." + right) or right.endswith("." + left)


def extract_requested_domains(text: str) -> set[str]:
    raw = str(text or "").lower()
    matches = re.findall(
        r"(?:https?://|www\.)?([a-z0-9][a-z0-9.-]*\.(?:com|org|net|io|ai|co|edu|gov))",
        raw,
        flags=re.IGNORECASE,
    )
    domains = {normalize_domain(m) for m in matches if m}
    alias_map = {
        "twitter": "x.com",
        "x.com": "x.com",
        "x dot com": "x.com",
        "reddit": "reddit.com",
        "youtube": "youtube.com",
        "instagram": "instagram.com",
        "facebook": "facebook.com",
        "linkedin": "linkedin.com",
    }
    for phrase, domain in alias_map.items():
        if re.search(r"\b" + re.escape(phrase) + r"\b", raw):
            domains.add(domain)
    return {d for d in domains if d}


def browser_relevance_policy() -> Dict[str, Any]:
    try:
        from ...core.config import get_config

        cfg = get_config()
        enabled = bool(getattr(cfg, "browser_relevance_policy_enabled", True))
        blocked = list(getattr(cfg, "browser_relevance_blocked_domains", []) or [])
        search_domains = list(getattr(cfg, "browser_relevance_allow_search_domains", []) or [])
        min_score = float(getattr(cfg, "browser_relevance_min_score", 0.28) or 0.28)
        min_sources = int(getattr(cfg, "browser_relevance_factual_min_sources", 2) or 2)
    except Exception:
        enabled = True
        blocked = []
        search_domains = []
        min_score = 0.28
        min_sources = 2

    if not blocked:
        blocked = ["x.com", "twitter.com", "t.co"]
    if not search_domains:
        search_domains = ["google.com", "bing.com", "duckduckgo.com", "search.brave.com"]

    return {
        "enabled": enabled,
        "blocked_domains": [normalize_domain(d) for d in blocked if d],
        "search_domains": [normalize_domain(d) for d in search_domains if d],
        "min_score": max(0.0, min(1.0, float(min_score))),
        "factual_min_sources": max(1, int(min_sources)),
    }


def _goal_terms(text: str) -> set[str]:
    raw = re.findall(r"[a-z0-9]{3,}", str(text or "").lower())
    stop = {
        "open",
        "browser",
        "search",
        "find",
        "give",
        "show",
        "this",
        "that",
        "with",
        "from",
        "into",
        "about",
        "what",
        "when",
        "where",
        "which",
        "today",
        "latest",
        "best",
        "more",
        "read",
        "detail",
        "please",
        "need",
        "want",
        "using",
        "website",
        "site",
    }
    return {token for token in raw if token not in stop and not token.isdigit()}


def _claim_candidates(text: str, *, max_claims: int = 6) -> list[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    pieces = re.split(r"(?<=[.!?])\s+", raw)
    claims: list[str] = []
    for piece in pieces:
        candidate = str(piece or "").strip(" \t\r\n-")
        if not candidate:
            continue
        word_count = len(candidate.split())
        if word_count < 6:
            continue
        # Skip pure instruction/generative lines that are not factual claims.
        low = candidate.lower()
        if any(token in low for token in ("i can", "would you like", "next step", "you can")):
            continue
        claims.append(candidate)
        if len(claims) >= max(1, int(max_claims)):
            break
    return claims


def _is_search_domain(domain: str) -> bool:
    policy = browser_relevance_policy()
    dom = normalize_domain(domain)
    if not dom:
        return False
    return any(domain_matches(dom, search_domain) for search_domain in policy.get("search_domains", []))


def relevance_score_for_target(
    goal: str,
    target_url: str,
    *,
    title: str = "",
    snippet: str = "",
    min_score: float | None = None,
) -> Dict[str, Any]:
    policy = browser_relevance_policy()
    threshold = float(policy.get("min_score", 0.28) if min_score is None else min_score)
    target_domain = normalize_domain(target_url)

    blocked, blocked_reason = is_domain_blocked_for_goal(target_domain or target_url, goal)
    if blocked:
        return {
            "score": 0.0,
            "threshold": threshold,
            "pass": False,
            "domain": target_domain,
            "reason": blocked_reason or "blocked_domain",
        }

    requested_domains = extract_requested_domains(goal)
    if requested_domains and not any(domain_matches(target_domain, req) for req in requested_domains):
        return {
            "score": 0.0,
            "threshold": threshold,
            "pass": False,
            "domain": target_domain,
            "reason": "domain_not_requested",
        }

    goal_terms = _goal_terms(goal)
    target_terms = _goal_terms(" ".join([target_domain, title, snippet]))
    overlap_ratio = 0.0
    if goal_terms and target_terms:
        overlap_ratio = len(goal_terms & target_terms) / float(len(goal_terms))

    score = 0.15
    reason = "low_signal"
    if requested_domains:
        score += 0.75
        reason = "requested_domain"
    elif target_terms:
        score += min(0.75, overlap_ratio * 0.95)
        reason = "term_overlap"
    if _is_search_domain(target_domain):
        score = max(score, 0.4)
        reason = "search_domain"

    score = max(0.0, min(1.0, float(score)))
    return {
        "score": score,
        "threshold": threshold,
        "pass": bool(score >= threshold),
        "domain": target_domain,
        "reason": reason,
        "overlap_ratio": round(float(overlap_ratio), 4),
    }


def is_probably_factual_goal(goal: str) -> bool:
    low = str(goal or "").lower()
    keywords = (
        "research",
        "compare",
        "vs",
        "versus",
        "best price",
        "headline",
        "news",
        "latest",
        "fact",
        "proof",
        "source",
        "evidence",
        "what is",
        "who is",
        "when did",
    )
    return any(token in low for token in keywords)


def evaluate_source_coverage(goal: str, visited_domains: set[str]) -> Dict[str, Any]:
    policy = browser_relevance_policy()
    clean_domains = {normalize_domain(d) for d in (visited_domains or set()) if normalize_domain(d)}
    non_search = {d for d in clean_domains if not _is_search_domain(d)}
    requested_domains = extract_requested_domains(goal)
    low = str(goal or "").lower()
    compare_like = any(token in low for token in ("compare", " vs ", " versus ", "best price", "cross-check"))

    required = 1
    if len(requested_domains) >= 2:
        required = len(requested_domains)
    elif compare_like or is_probably_factual_goal(goal):
        required = max(2, int(policy.get("factual_min_sources", 2) or 2))
    elif len(requested_domains) == 1:
        required = 1

    covered_requested = {d for d in non_search if any(domain_matches(d, req) for req in requested_domains)}
    coverage_count = len(non_search)
    ok = bool(coverage_count >= required)
    reason = "ok" if ok else "insufficient_sources"
    if requested_domains and len(requested_domains) >= 2 and len(covered_requested) < len(requested_domains):
        ok = False
        reason = "missing_requested_domains"

    return {
        "ok": ok,
        "reason": reason,
        "required_sources": int(required),
        "non_search_sources": sorted(non_search),
        "covered_requested_sources": sorted(covered_requested),
        "requested_sources": sorted(normalize_domain(d) for d in requested_domains),
    }


def evaluate_claim_support(
    final_answer: str,
    sources: list[Dict[str, Any]],
    *,
    min_supported_ratio: float = 0.6,
    min_claim_score: float = 0.16,
    max_claims: int = 6,
) -> Dict[str, Any]:
    claims = _claim_candidates(final_answer, max_claims=max_claims)
    if not claims:
        return {
            "ok": True,
            "reason": "no_claims_detected",
            "claims_total": 0,
            "claims_supported": 0,
            "supported_ratio": 1.0,
            "items": [],
        }

    source_rows = sources or []
    evaluations: list[Dict[str, Any]] = []
    supported_count = 0
    for claim in claims:
        claim_terms = _goal_terms(claim)
        best_score = 0.0
        best_url = ""
        best_domain = ""
        for source in source_rows:
            source_url = str(source.get("url") or "").strip()
            source_domain = normalize_domain(str(source.get("domain") or source_url))
            source_text = " ".join(
                [
                    str(source.get("title") or ""),
                    str(source.get("text") or ""),
                    source_domain,
                ]
            )
            source_terms = _goal_terms(source_text)
            if not claim_terms:
                overlap_ratio = 0.0
            else:
                overlap_ratio = len(claim_terms & source_terms) / float(len(claim_terms))
            if overlap_ratio > best_score:
                best_score = overlap_ratio
                best_url = source_url
                best_domain = source_domain
        supported = bool(best_score >= float(min_claim_score))
        if supported:
            supported_count += 1
        evaluations.append(
            {
                "claim": claim,
                "supported": supported,
                "score": round(float(best_score), 4),
                "best_source_url": best_url,
                "best_source_domain": best_domain,
            }
        )

    ratio = supported_count / float(len(claims))
    ok = bool(ratio >= float(min_supported_ratio))
    return {
        "ok": ok,
        "reason": "ok" if ok else "insufficient_claim_support",
        "claims_total": len(claims),
        "claims_supported": int(supported_count),
        "supported_ratio": round(float(ratio), 4),
        "min_supported_ratio": float(min_supported_ratio),
        "min_claim_score": float(min_claim_score),
        "items": evaluations,
    }


def is_domain_blocked_for_goal(domain_or_url: str, goal: str) -> tuple[bool, str]:
    policy = browser_relevance_policy()
    if not policy.get("enabled"):
        return False, ""

    domain = normalize_domain(domain_or_url)
    if not domain:
        return False, ""

    if any(domain_matches(domain, search_domain) for search_domain in policy.get("search_domains", [])):
        return False, ""

    requested = extract_requested_domains(goal)
    if requested:
        if any(domain_matches(domain, req) for req in requested):
            return False, ""
        return True, "domain_not_requested"

    blocked_domains = policy.get("blocked_domains", [])
    if any(domain_matches(domain, blocked) for blocked in blocked_domains):
        return True, "blocked_domain"

    return False, ""


def sanitize_untrusted_page_text(text: str, max_chars: int = 1200) -> Dict[str, Any]:
    raw = str(text or "")
    lines = raw.splitlines()
    sanitized_lines = []
    dropped_lines = []
    markers = [
        "ignore previous instruction",
        "ignore all previous instruction",
        "disregard previous",
        "you are chatgpt",
        "you are now",
        "system prompt",
        "developer message",
        "reveal your prompt",
        "send your secrets",
        "jailbreak",
        "act as",
        "do not follow",
    ]
    for line in lines:
        candidate = str(line or "").strip()
        lower = candidate.lower()
        if any(marker in lower for marker in markers):
            dropped_lines.append(candidate[:180])
            continue
        sanitized_lines.append(candidate)

    sanitized_text = "\n".join([line for line in sanitized_lines if line]).strip()
    if max_chars > 0:
        sanitized_text = sanitized_text[: int(max_chars)]

    return {
        "text": sanitized_text,
        "dropped_count": len(dropped_lines),
        "dropped_samples": dropped_lines[:3],
    }
