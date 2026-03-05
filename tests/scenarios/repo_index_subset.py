"""Repo-index benchmark subset (Phase 1)."""

TEST_SCENARIOS = [
    {
        "category": "repo_index",
        "text": "repo index",
        "hint": "Build incremental repository index",
        "checks": {
            "must_contain": ["repository index build complete", "indexed files", "chunks added"],
            "capability_must_contain": ["repo_index_build"],
            "strict": False,
        },
    },
    {
        "category": "repo_index",
        "text": "repo search where is class ModelRouter defined top=3 ext=.py",
        "hint": "Find class definition location",
        "checks": {
            "must_contain": ["repo matches", "ModelRouter"],
            "capability_must_contain": ["repo_index_search"],
            "strict": False,
        },
    },
    {
        "category": "repo_index",
        "text": "repo search explain how tool call_tool is wired path=chintu_backend/interfaces/mcp ext=.py top=5",
        "hint": "Find MCP tool wiring references",
        "checks": {
            "must_contain": ["interfaces/mcp/server.py"],
            "capability_must_contain": ["repo_index_search"],
            "strict": False,
        },
    },
]
