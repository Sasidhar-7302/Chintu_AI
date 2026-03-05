from typing import Dict, Any, Optional, Type
from pydantic import BaseModel, Field
from ..capabilities import ActionResult
from ...brain.memory.hybrid_memory import get_hybrid_memory

class MemorySearchSchema(BaseModel):
    query: str = Field(..., description="The search query to find specific memories.")
    date: Optional[str] = Field(None, description="Optional date filter in YYYY-MM-DD format.")
    limit: int = Field(5, description="Maximum number of results to return.")

class MemoryToolCapability:
    """
    Allows chintu to explicitly search its own memory.
    """
    
    def get_metadata(self) -> Dict[str, Any]:
        return {
            "name": "memory_tool",
            "description": "Search long-term memory for specific information.",
            "examples": [
                "What did I say yesterday?",
                "Search memory for 'project delta'",
                "What was the last thing we discussed about apples?"
            ],
            "keywords": ["memory", "recall", "remember", "search", "history"],
            "parameters": {
                "query": "The search query",
                "date": "Optional date filter (YYYY-MM-DD)",
                "limit": "Max results (default 5)"
            },
            # We expose the schema class via metadata or property, 
            # but the new registry uses the .schema property on the instance.
        }
    
    @property
    def schema(self) -> Type[BaseModel]:
        return MemorySearchSchema

    def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> ActionResult:
        # Phase 4: Use validated params if available, else fall back to raw params
        validated_params = context.get("_validated_params")
        if validated_params and isinstance(validated_params, MemorySearchSchema):
            query = validated_params.query
            date_filter = validated_params.date
            limit = validated_params.limit
        else:
            # Legacy/Fallback
            query = params.get("query", "")
            date_filter = params.get("date")
            limit = params.get("limit", 5)

        mem = get_hybrid_memory()
        if not mem:
            return ActionResult(success=False, message="Memory system is offline.")
        
        # Date filtering implementation (logic remains similar)
        filters = {}
        if date_filter:
            # Pending strict implementation
            pass 

        results = mem.search(query, limit=limit)
        
        if not results:
            return ActionResult(success=True, message=f"I found no memories matching '{query}'.")
            
        # Format transparently parameters
        lines = [f"Found {len(results)} memories (Query: '{query}'):"]
        for r in results:
            lines.append(f"- [{r.created_at[:10]}] {r.content}")
            
        return ActionResult(success=True, message="\n".join(lines))
