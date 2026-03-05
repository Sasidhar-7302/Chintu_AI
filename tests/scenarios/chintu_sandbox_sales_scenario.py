"""Single-scenario test: sandboxed sales CSV cleaning + chart generation."""

TEST_SCENARIOS = [
    {
        "category": "code",
        "text": "I have a messy dataset called sales_2025.csv in my Downloads. Write a Python script to clean the null values, generate a matplotlib trend chart, and save the chart to my Desktop. Do not run the code on my main OS—execute it in the sandbox.",
        "hint": "Sandboxed code execution with artifact output",
        "checks": {
            "must_contain": ["sales_2025.csv", "matplotlib"],
            "min_length": 40,
            "strict": False,
        },
    }
]
