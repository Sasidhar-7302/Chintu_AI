"""OpenClaw workflows subset scenarios (Phase 2)."""

TEST_SCENARIOS = [
    {
        "category": "workflow",
        "text": "Set up background health checks daily and run background health checks now.",
        "hint": "Schedule + immediate markdown artifact run",
        "checks": {
            "must_contain": ["background_health_checks", "report_path", "schedule"],
            "strict": False,
        },
    },
    {
        "category": "workflow",
        "text": "/summarize https://example.com and save it",
        "hint": "Summarize URL and write markdown artifact",
        "checks": {
            "must_contain": ["web_summarize", "summary_path", ".md"],
            "strict": False,
        },
    },
]
