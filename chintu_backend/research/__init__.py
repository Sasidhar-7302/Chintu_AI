"""Research pipeline capabilities."""

from typing import Dict

from chintu_backend.core.capabilities import Capability, CapabilityType, ActionResult
from .verified_research import VerifiedResearcher


def register_research_capabilities(registry) -> None:
    researcher = VerifiedResearcher()

    def handle_research(text: str, context: Dict) -> ActionResult:
        data = researcher.research(text, max_results=3)
        response = data.get("response", "No results.")
        sources = data.get("sources", [])
        ui_rows = [[s.get("title", "Source"), s.get("url", "")] for s in sources]
        return ActionResult.ok(
            response,
            data={
                "query": text,
                "sources": sources,
                "ui_table": {
                    "title": "Research Sources",
                    "columns": ["Title", "URL"],
                    "rows": ui_rows,
                }
            },
            capability="web_research",
        )

    registry.register(
        Capability(
            name="web_research",
            triggers=["research", "latest news", "look up", "find sources"],
            handler=handle_research,
            requires_confirmation=False,
            description="Verified web research with citations",
            capability_type=CapabilityType.AI_AGENT,
            examples=["Research latest GPU prices", "Find sources about quantum computing"],
        )
    )
