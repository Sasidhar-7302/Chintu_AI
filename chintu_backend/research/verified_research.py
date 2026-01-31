"""Verified web research pipeline with citations."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Dict

import requests
from bs4 import BeautifulSoup

from chintu_backend.core.config import get_config

logger = logging.getLogger(__name__)


@dataclass
class ResearchSource:
    title: str
    url: str
    snippet: str


class VerifiedResearcher:
    def __init__(self):
        self.config = get_config()

    def research(self, query: str, max_results: int = 3) -> Dict:
        sources = self._search(query, max_results=max_results)
        summaries = []
        for src in sources:
            summary = self._fetch_summary(src.url)
            if summary:
                summaries.append(summary)
        response = self._synthesize(query, sources, summaries)
        return {
            "response": response,
            "sources": [src.__dict__ for src in sources],
        }

    def _search(self, query: str, max_results: int) -> List[ResearchSource]:
        results: List[ResearchSource] = []
        try:
            from ddgs import DDGS

            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=max_results):
                    title = r.get("title") or r.get("heading") or "Source"
                    url = r.get("href") or r.get("url") or ""
                    snippet = r.get("body") or r.get("snippet") or ""
                    if url:
                        results.append(ResearchSource(title=title, url=url, snippet=snippet))
        except Exception as exc:
            logger.warning("DDGS search failed: %s", exc)
        return results

    def _fetch_summary(self, url: str) -> str:
        try:
            res = requests.get(url, timeout=10, headers={"User-Agent": "ChintuResearch/1.0"})
            if res.status_code != 200:
                return ""
            soup = BeautifulSoup(res.text, "html.parser")
            paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
            text = " ".join(paragraphs[:6])
            return text[:1200]
        except Exception:
            return ""

    def _synthesize(self, query: str, sources: List[ResearchSource], summaries: List[str]) -> str:
        lines = [f"Query: {query}", ""]
        if summaries:
            lines.append("Summary:")
            lines.append(" ".join(summaries[:2])[:1600])
            lines.append("")
        lines.append("Sources:")
        for idx, src in enumerate(sources, start=1):
            lines.append(f"[{idx}] {src.title} - {src.url}")
        return "\n".join(lines)
