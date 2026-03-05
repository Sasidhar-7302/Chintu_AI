"""Focused 5-phase autonomy validation scenarios (10 tasks)."""

TEST_SCENARIOS = [
    {
        "category": "phase1_os_productivity",
        "text": "Chintu, find all PDFs in my Downloads folder from the last 7 days, summarize them into a single Markdown file, and move the originals to a new folder named Recent Research.",
        "hint": "File navigation + PDF summary + organization workflow",
        "checks": {
            "must_contain": ["pdf", "markdown", "recent research"],
            "min_length": 40,
            "strict": False,
        },
    },
    {
        "category": "phase1_os_productivity",
        "text": "Monitor my active windows. If I open LinkedIn, automatically search my local Resume folder for my latest CV and have it ready in the clipboard.",
        "hint": "Background monitoring + proactive retrieval",
        "checks": {
            "must_contain": ["linkedin", "resume", "clipboard"],
            "min_length": 30,
            "strict": False,
        },
    },
    {
        "category": "phase2_engineering_research",
        "text": "Research the top 3 trending open-source projects for Automated Visa Bots on GitHub. Compare their features to my current Visa Bot project idea and tell me if mine is unique.",
        "hint": "GitHub research + competitive analysis",
        "checks": {
            "must_contain": ["github", "visa", "unique"],
            "min_length": 50,
            "strict": False,
        },
    },
    {
        "category": "phase2_engineering_research",
        "text": "Create a boilerplate Python FastAPI project for an SOP Library manager. Verify that the code is bug-free by running a test script, then open the project folder in VS Code.",
        "hint": "Autonomous coding + local verification + app launch",
        "checks": {
            "must_contain": ["fastapi", "test", "vs code"],
            "min_length": 40,
            "strict": False,
        },
    },
    {
        "category": "phase3_hardware_resource",
        "text": "I need to run a heavy data scraping task. Calculate the estimated CPU and GPU load, and if it exceeds 50%, schedule it to start tonight at 2 AM on the RTX 3060.",
        "hint": "Resource estimation + conditional scheduling + GPU placement",
        "checks": {
            "must_contain": ["cpu", "gpu", "2 am", "rtx 3060"],
            "min_length": 30,
            "strict": False,
        },
    },
    {
        "category": "phase3_hardware_resource",
        "text": "Check my i5-12600K thermals. If the temperature exceeds 80C while I am gaming, automatically close non-essential background AI processes running on the CPU.",
        "hint": "Thermal monitoring + conditional process control",
        "checks": {
            "must_contain": ["i5-12600k", "80", "close", "process"],
            "min_length": 30,
            "strict": False,
        },
    },
    {
        "category": "phase4_personalization_memory",
        "text": "Search our past conversations from last month. What were the 3 main features I wanted for the YouTube Shorts Bot? Create a Jira ticket for each of them.",
        "hint": "Memory retrieval + Jira task creation",
        "checks": {
            "must_contain": ["youtube shorts bot", "3", "jira"],
            "min_length": 40,
            "strict": False,
        },
    },
    {
        "category": "phase4_personalization_memory",
        "text": "Based on my Statement of Purpose draft and my resume, identify 3 gaps in my profile for a Data Science PhD and suggest specific online courses to fill them.",
        "hint": "Deep context reasoning + personalized recommendations",
        "checks": {
            "must_contain": ["gap", "course", "data science phd"],
            "min_length": 50,
            "strict": False,
        },
    },
    {
        "category": "phase5_advanced_automation",
        "text": "Open my email and find any messages regarding my F1 OPT status. If there is an update, draft a reply asking for the next steps and wait for my approval before sending.",
        "hint": "Email triage + draft reply + approval gate",
        "checks": {
            "must_contain": ["email", "f1", "opt", "approval"],
            "min_length": 40,
            "strict": False,
        },
    },
    {
        "category": "phase5_advanced_automation",
        "text": "Record my screen for the next 5 minutes while I demonstrate a bug in my code. Analyze the video, explain what went wrong, and suggest a fix.",
        "hint": "Screen recording + video analysis + debugging",
        "checks": {
            "must_contain": ["screen", "5 minute", "analyze", "fix"],
            "min_length": 40,
            "strict": False,
        },
    },
]

