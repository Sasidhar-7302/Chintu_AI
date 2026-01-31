"""
Tech News Capability.
Searches for latest tech news in the background and provides summaries.
"""

import logging
import asyncio
from typing import Dict, Any, List

from ..core.capabilities import Capability, CapabilityType, ActionResult
from ..core.model_router import get_model_router, Intent, TaskComplexity

logger = logging.getLogger(__name__)

class NewsCapability:
    def __init__(self):
        self.running_tasks = {}

    def _generate_news_search_queries(self, topic: str) -> List[str]:
        """Generate search queries based on topic."""
        base = topic.replace("news", "").replace("latest", "").strip()
        if not base:
            base = "technology"
        
        return [
            f"latest {base} news today",
            f"breaking {base} news",
            f"most important {base} updates this week",
        ]

    async def _fetch_and_summarize(self, queries: List[str], context: Dict[str, Any]):
        """Background task to fetch and summarize."""
        try:
            from ..web.live_search import get_live_search
            search = get_live_search()
            
            if not search.is_available:
                logger.error("Live search unavailable for news.")
                return

            all_results = []
            for q in queries:
                results = search.search(q, max_results=3)
                all_results.extend(results)
                await asyncio.sleep(1) # Be polite

            # Deduplicate by URL
            seen_urls = set()
            unique_results = []
            for r in all_results:
                if r['url'] not in seen_urls:
                    unique_results.append(r)
                    seen_urls.add(r['url'])
            
            if not unique_results:
                logger.info("No news found.")
                return

            # Summarize using Local LLM (strict preference)
            router = get_model_router()
            
            # Format context for LLM
            articles_text = "\n\n".join([f"Title: {r['title']}\nSnippet: {r['snippet']}" for r in unique_results[:7]])
            
            prompt = (
                f"You are a Tech News Anchor. Summarize these news items into a concise, engaging update.\n"
                f"Identify the 3 most important stories.\n\n"
                f"News Data:\n{articles_text}\n\n"
                f"Format:\n"
                f"Here are the latest updates:\n"
                f"1. [Headline] - [One sentence summary]\n..."
            )
            
            # Force local route for summary
            response = router.route_to_model(
                prompt, 
                intent=Intent.SIMPLE_CHAT, 
                complexity=TaskComplexity.MEDIUM, 
                prefer_cloud=False
            )
            
            summary = response.response
            
            # Store for retrieval/feedback
            from ..core.state import get_state_manager
            state = get_state_manager()
            state.set_last_response(summary, raw=summary) 
            
            # Proactive notification (if supported) or just log/store
            # For now, we assume the user asked for this, so we should try to deliver it.
            # Ideally, we push this to the UI or TTS queue.
            
            # Check if there's a command handler to callback
            handler = context.get("command_handler")
            if handler and hasattr(handler, "speak"):
                 handler.speak("I've found the latest news. Here is a summary.")
                 handler.speak(summary)
            
            logger.info("News summary delivered.")

        except Exception as e:
            logger.error(f"News fetch failed: {e}")

    def handle_tech_news(self, text: str, context: Dict[str, Any]) -> ActionResult:
        """
        Handle request for tech news.
        Triggers background processing to avoid blocking.
        """
        text_lower = text.lower()
        topic = "technology"
        
        # Extract topic
        if "about" in text_lower:
            parts = text_lower.split("about", 1)
            if len(parts) > 1:
                topic = parts[1].strip()
        
        queries = self._generate_news_search_queries(topic)
        
        # Start background task
        loop = asyncio.get_event_loop()
        loop.create_task(self._fetch_and_summarize(queries, context))
        
        return ActionResult.ok(
            f"I'm searching for the latest {topic} news in the background. I'll summarize it for you shortly.",
            {"topic": topic, "background": True},
            "tech_news"
        )

# Factory
_news_capability = None

def get_news_capability():
    global _news_capability
    if not _news_capability:
        _news_capability = NewsCapability()
    return _news_capability

def register_news_capabilities():
    from ..core.capabilities import get_registry
    registry = get_registry()
    
    cap = get_news_capability()
    
    registry.register(Capability(
        name="tech_news",
        triggers=["tech news", "latest news", "technology news", "technews", "update me on"],
        handler=cap.handle_tech_news,
        description="Search and summarize tech news in background",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=["Get me the latest tech news", "Find news about AI"]
    ))
