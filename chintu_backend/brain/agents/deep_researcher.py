"""
Deep Research Agent: The "Ph.D. Student" module for Chintu AI.
Responsible for autonomous, deep, and structured learning from the web.
"""

import logging
import time
import json
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime

from chintu_backend.core.config import get_config
from chintu_backend.brain.memory.knowledge_store import KnowledgeStore
from chintu_backend.brain.memory.hybrid_memory import HybridMemoryManager, get_hybrid_memory
from chintu_backend.core.model_router import ModelRouter, TaskComplexity, Intent, RoutingDecision
from chintu_backend.search.search_capabilities import handle_web_search
from chintu_backend.brain.learning.learning_engine import get_learning_engine
try:
    from chintu_backend.research.verified_research import VerifiedResearcher
except Exception:  # pragma: no cover - optional dependency
    VerifiedResearcher = None

logger = logging.getLogger(__name__)

@dataclass
class ResearchChapter:
    title: str
    objectives: List[str]
    content: str = ""
    sources: List[str] = None

class DeepResearcher:
    def __init__(self):
        self.config = get_config()
        self.ks = KnowledgeStore(self.config.data_dir)
        self.memory = get_hybrid_memory()
        self.learning_engine = get_learning_engine()
        self.verified = VerifiedResearcher() if VerifiedResearcher else None
        
        # Initialize LLM Clients directly
        self.ollama = None
        try:
            from chintu_backend.brain.llm.ollama_client import OllamaClient
            self.ollama = OllamaClient(
                host=self.config.ollama_host,
                model=self.config.ollama_model
            )
        except ImportError:
            pass

        self.groq = None
        if self.config.groq_api_key:
            try:
                from chintu_backend.brain.llm.groq_client import GroqClient
                self.groq = GroqClient(model=self.config.groq_model, api_key=self.config.groq_api_key)
            except ImportError:
                pass
                
        self.google = None
        if self.config.google_ai_key:
            try:
                from chintu_backend.brain.llm.gemini_client import GeminiClient
                self.google = GeminiClient(api_key=self.config.google_ai_key, model="gemini-2.0-flash") 
            except ImportError:
                pass


    def learn_topic(self, topic: str, depth: str = "comprehensive") -> str:
        """
        Main entry point: Conduct deep research on a topic and produce a 'Book'.
        Returns a summary of what was completed.
        """
        depth_val = 3 if depth == "comprehensive" else 2
        logger.info(f"Starting Deep Research on: {topic} (Chapters: {depth_val})")
        
        # 1. Plan Curriculum
        curriculum = self._plan_curriculum(topic, depth_val)
        logger.info(f"Curriculum generated with {len(curriculum)} chapters.")
        
        # 2. Research & Write Chapters
        summary_path = ""
        learned_facts = 0
        
        for i, chapter in enumerate(curriculum):
            logger.info(f"Researching Chapter {i+1}: {chapter.title}")
            
            # Search & Synthesize
            chapter.content, chapter.sources = self._research_chapter(topic, chapter)
            
            # Save to Knowledge Store
            safe_name = f"chapter_{i+1}_{chapter.title.replace(' ', '_').lower()}"
            # Fix typo in lower_() -> lower() - caught it
            safe_name = f"chapter_{i+1}_{chapter.title.lower().replace(' ', '_')}.md" # Add extension
            
            # sanitize filename manually to be safe
            safe_name = "".join(x for x in safe_name if x.isalnum() or x in "._-")

            self.ks.save_document(
                category="research",
                topic=topic,
                filename=safe_name,
                content=chapter.content,
                metadata={"sources": chapter.sources, "depth": depth, "timestamp": datetime.now().isoformat()}
            )
            
            # Index into Hybrid Memory if available
            if self.memory:
                self.memory.add_knowledge_document(
                    content=chapter.content,
                    metadata={"category": "research", "topic": topic, "chapter": chapter.title}
                )
            learned_facts += 1

        # 3. Create Index/Summary
        summary_content = f"# Deep Dive: {topic}\n\n## Curriculum\n"
        for i, chap in enumerate(curriculum):
            safe_name = f"chapter_{i+1}_{chap.title.lower().replace(' ', '_')}.md"
            safe_name = "".join(x for x in safe_name if x.isalnum() or x in "._-")
            summary_content += f"{i+1}. [{chap.title}]({safe_name})\n"
            
        summary_path = self.ks.save_document(
            category="research",
            topic=topic,
            filename="index.md",
            content=summary_content,
            metadata={"type": "index", "topic": topic}
        )
            
        return f"Research complete. Created {len(curriculum)} chapters on '{topic}'. Saved to {summary_path}."

    def _plan_curriculum(self, topic: str, count: int) -> List[ResearchChapter]:
        """Ask LLM to generate a Table of Contents."""
        prompt = (
            f"Act as a Professor planning a course on '{topic}'. "
            f"Generate a structured Table of Contents with exactly {count} key chapters. "
            "Return ONLY raw JSON in this format: "
            "[{'title': 'Chapter Title', 'objectives': ['obj1', 'obj2']}]"
        )
        
        response = self._llm_call(prompt, complexity="high")
        
        try:
            # Flexible JSON parsing
            clean_json = response.strip()
            if "```json" in clean_json:
                clean_json = clean_json.split("```json")[1].split("```")[0]
            elif "```" in clean_json:
                clean_json = clean_json.split("```")[1].split("```")[0]
                
            data = json.loads(clean_json)
            chapters = [ResearchChapter(title=item['title'], objectives=item['objectives']) for item in data]
            return chapters
        except Exception as e:
            logger.error(f"Failed to parse curriculum: {e}. Fallback to generic.")
            return [ResearchChapter(title="Overview", objectives=[f"Understand basic {topic}"])]

    def _research_chapter(self, topic: str, chapter: ResearchChapter) -> tuple[str, List[str]]:
        """Perform web research and synthesis for a chapter."""
        
        search_query = f"{topic} {chapter.title} comprehensive details"
        sources: List[str] = []
        context = ""
        source_lines: List[str] = []
        
        # 1. Verified research (preferred if available)
        if self.verified:
            try:
                report = self.verified.research(search_query, max_results=3)
                context = report.get("response", "") or ""
                raw_sources = report.get("sources", []) or []
                for idx, src in enumerate(raw_sources, start=1):
                    title = src.get("title") or "Source"
                    url = src.get("url") or ""
                    if url:
                        sources.append(url)
                        source_lines.append(f"[{idx}] {title} - {url}")
            except Exception as e:
                logger.warning(f"Verified research failed for {chapter.title}: {e}")

        # 2. Fallback to simple search
        if not context:
            try:
                res = handle_web_search(search_query, {})
                if hasattr(res, "message") and res.message:
                    context = res.message
            except Exception as e:
                logger.warning(f"Search failed for {chapter.title}: {e}")
                context = "No web results available."

        # 3. Synthesize Content with citations
        sources_text = "\n".join(source_lines) if source_lines else "No sources available."
        prompt = (
            f"Write a detailed textbook chapter on '{chapter.title}' for the topic '{topic}'.\n"
            f"Objectives: {', '.join(chapter.objectives)}\n"
            f"Source Material: {context[:6000]}...\n\n"
            "Style: comprehensive, academic, markdown formatted. Use headers.\n"
            "Include inline citations like [1], [2] based on the Sources list.\n"
            f"Sources:\n{sources_text}\n"
        )
        
        content = self._llm_call(prompt, complexity="high")

        # Append sources section for traceability
        if source_lines:
            content = content.rstrip() + "\n\n## Sources\n" + "\n".join(source_lines) + "\n"
        
        # 4. Fact Check
        try:
            from chintu_backend.brain.middleware.fact_checker import get_fact_checker
            verifier = get_fact_checker()
            content = verifier.verify_content(content)
        except Exception as e:
            logger.warning(f"Fact check skipped: {e}")

        # 5. Continuous learning log
        try:
            if self.learning_engine:
                self.learning_engine.record_web_learning(search_query, content, sources=sources)
        except Exception:
            pass
            
        return content, sources


    def _llm_call(self, prompt: str, complexity: str = "low") -> str:
        """Helper to call proper LLM."""
        # Prefer Cloud Intellignece for Research
        if self.google:
            try: return self.google.chat(prompt)
            except: pass
        if self.groq:
            try: return self.groq.chat(prompt)
            except: pass
            
        # Fallback to local
        if self.ollama:
            return self.ollama.generate(prompt) # OllamaClient has generate or chat? check client.
            
        return "LLM Unavailable."

# Singleton / Factory
_researcher = None

def get_deep_researcher() -> DeepResearcher:
    global _researcher
    if not _researcher:
        _researcher = DeepResearcher()
    return _researcher

