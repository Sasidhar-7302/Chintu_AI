"""
Verified Research Service for Chintu.
Implements the "Verified Research" pipeline:
1. Query Planning
2. Multi-source Retrieval
3. Source Quality Scoring
4. Fact Cross-checking
5. Cited Synthesis
"""

import logging
import asyncio
import re
from typing import List, Dict, Any, Set, Optional
from dataclasses import dataclass
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor

from ..core.capabilities import ActionResult
from ..search.web_search import get_search_engine

logger = logging.getLogger(__name__)

@dataclass
class ResearchResult:
    title: str
    snippet: str
    url: str
    source_type: str  # web, news, academic
    credibility_score: float  # 0.0 to 1.0
    domain: str

class SourceScorer:
    """Evaluates the credibility of information sources."""
    
    TIER_A_DOMAINS = {
        ".gov", ".edu", ".mil", ".org",
        "wikipedia.org", "arxiv.org", "nih.gov", "cdc.gov",
        "nasa.gov", "who.int", "nature.com", "science.org",
        "ieee.org", "acm.org"
    }
    
    TIER_B_DOMAINS = {
        "bbc.com", "reuters.com", "apnews.com", "npr.org",
        "nytimes.com", "wsj.com", "bloomberg.com", "techcrunch.com",
        "wired.com", "arstechnica.com", "theverge.com", "github.com",
        "stackoverflow.com", "medium.com", "lovesdata.com"
    }

    @staticmethod
    def score(url: str) -> float:
        """Calculate credibility score (0.0 - 1.0) based on domain."""
        try:
            domain = urlparse(url).netloc.lower()
            if domain.startswith("www."):
                domain = domain[4:]
            
            # Check TLD and suffix matches
            for d in SourceScorer.TIER_A_DOMAINS:
                if domain.endswith(d):
                    return 0.95
            
            for d in SourceScorer.TIER_B_DOMAINS:
                if domain.endswith(d):
                    return 0.8
            
            return 0.5  # Neutral default for unknown domains
            
        except Exception:
            return 0.4

class VerifiedResearcher:
    """Orchestrates the verified research pipeline."""
    
    def __init__(self):
        self.scorer = SourceScorer()
        self.engine = get_search_engine()

    def research(self, query: str, deep: bool = False) -> Dict[str, Any]:
        """
        Perform verified research on a query.
        Returns a structured report with citations.
        """
        # 1. Query Planning (Basic expansion for now)
        queries = [query]
        if deep:
            queries.append(f"{query} scientific consensus")
            queries.append(f"{query} statistics data")
        
        # 2. Multi-source Retrieval
        raw_results = self._fetch_results(queries)
        
        # 3. Score & Filter
        scored_results = self._score_results(raw_results)
        top_results = sorted(scored_results, key=lambda x: x.credibility_score, reverse=True)
        
        # 4. Cross-check (Simulated for this phase - checks overlap)
        # In a full implementation, this would use LLM to check fact consistency.
        consensus_points = self._extract_consensus(top_results)
        
        # 5. Synthesis
        report = self._synthesize_report(query, top_results, consensus_points)
        
        return {
            "report": report,
            "sources": [r.__dict__ for r in top_results],
            "consensus": consensus_points
        }

    def _fetch_results(self, queries: List[str]) -> List[Dict]:
        """Fetch results from multiple queries."""
        all_results = []
        for q in queries:
            try:
                # Use news search for "latest" queries, else web
                if "news" in q or "latest" in q:
                    res = self.engine.search_news(q, max_results=5)
                else:
                    res = self.engine.search(q, max_results=5)
                all_results.extend(res)
            except Exception as e:
                logger.warning(f"Search failed for query '{q}': {e}")
        return all_results

    def _score_results(self, raw_results: List[Any]) -> List[ResearchResult]:
        """Convert raw results to scored ResearchResult objects."""
        scored = []
        seen_urls = set()
        
        for r in raw_results:
            if r.url in seen_urls:
                continue
            seen_urls.add(r.url)
            
            score = self.scorer.score(r.url)
            domain = urlparse(r.url).netloc
            
            scored.append(ResearchResult(
                title=r.title,
                snippet=r.snippet,
                url=r.url,
                source_type="web",
                credibility_score=score,
                domain=domain
            ))
        return scored

    def _extract_consensus(self, results: List[ResearchResult]) -> List[str]:
        """Identify key points mentioned by high-credibility sources."""
        # This is a placeholder for semantic consensus extraction.
        # For now, it returns the snippets of Tier A sources.
        consensus = []
        for r in results:
            if r.credibility_score >= 0.9:
                consensus.append(r.snippet)
        return consensus[:3]

    def _synthesize_report(self, query: str, results: List[ResearchResult], consensus: List[str]) -> str:
        """Generate a markdown report with citations."""
        lines = [f"# Verified Research: {query}\n"]
        
        # Summary Section
        lines.append("## Executive Summary")
        if consensus:
            lines.append("**Key Findings (from high-credibility sources):**")
            for point in consensus:
                lines.append(f"- {point}")
        else:
            lines.append(f"Found {len(results)} sources. No Tier A sources identified specifically, but here is the synthesis:")
        lines.append("")
        
        # Detailed Findings
        lines.append("## Source Detail")
        for i, r in enumerate(results[:5], 1):
            tier = "⭐⭐⭐" if r.credibility_score >= 0.9 else ("⭐⭐" if r.credibility_score >= 0.8 else "⭐")
            lines.append(f"### {i}. {r.title} {tier}")
            lines.append(f"**Source:** {r.domain}")
            lines.append(f"**Snippet:** {r.snippet}")
            lines.append(f"**Link:** [{r.url}]({r.url})")
            lines.append("")
        
        lines.append("---\n*Ratings: ⭐⭐⭐ (Gov/Edu/Official), ⭐⭐ (Reputable Media), ⭐ (General Web)*")
        return "\n".join(lines)

# Capability Handler
def handle_verified_research(text: str, context: Dict[str, Any]) -> ActionResult:
    """
    Handler for verified research requests.
    Triggers: "verify ", "fact check ", "research sources for "
    """
    start_phrases = ["verify ", "fact check ", "find sources for ", "verified search ", "research "]
    query = text.lower()
    for p in start_phrases:
        if query.startswith(p):
            query = query[len(p):].strip()
            break
    
    try:
        researcher = VerifiedResearcher()
        result = researcher.research(query, deep=("deep" in text.lower()))
        return ActionResult.ok(result["report"], {"query": query}, "verified_research")
    except Exception as e:
        logger.error(f"Verified research failed: {e}")
        return ActionResult.fail(f"Research failed: {e}", "verified_research")
