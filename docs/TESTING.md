# Chintu Capabilities Testing Guide

## Quick Start
```bash
# Start Chintu
python run_chintu_backend.py

# Or with Flutter UI
python run_chintu_backend.py --with-ui
```

---

## All 45 Capabilities & Test Commands

### 🖥️ System Actions (6)
| Say This | What Happens |
|----------|--------------|
| "Open Chrome" | Opens Chrome browser |
| "Launch Notepad" | Opens Notepad |
| "Go to YouTube" | Opens youtube.com |
| "What time is it?" | Shows current time |
| "What's today's date?" | Shows current date |
| "System status" | Shows assistant status |

### 🔍 Search (3)
| Say This | What Happens |
|----------|--------------|
| "Search for Python tutorials" | DuckDuckGo web search |
| "Deep search quantum computing" | Multi-page research |
| "Browser search machine learning" | Opens browser with results |

### 📝 Notes & Memory (7)
| Say This | What Happens |
|----------|--------------|
| "Remember that my favorite color is blue" | Saves fact to memory |
| "What do you remember about me?" | Recalls saved facts |
| "Take a note: buy groceries" | Saves note |
| "Show my notes" | Lists all notes |
| "Forget everything" | ⚠️ Requires confirmation |
| "Recall facts" | Shows quick facts |
| "What did we talk about last time?" | Context recall |

### ⏰ Tasks & Reminders (5)
| Say This | What Happens |
|----------|--------------|
| "Remind me in 5 minutes to take a break" | Sets reminder |
| "Set a reminder for tomorrow at 9am" | Scheduled reminder |
| "Show my reminders" | Lists pending reminders |
| "Cancel all reminders" | Clears reminders |
| "What's on my schedule?" | Shows tasks |

### 🌐 Browser Automation (6)
| Say This | What Happens |
|----------|--------------|
| "Open browser" | Opens Playwright browser |
| "Go to github.com" | Navigates to URL |
| "Click the sign in button" | ⚠️ Clicks element |
| "Type hello in the search box" | ⚠️ Types text |
| "Take a screenshot" | Captures page |
| "Close browser" | Closes browser |

### 📁 Files (5)
| Say This | What Happens |
|----------|--------------|
| "Read my resume.pdf" | Reads PDF content |
| "What's in my clipboard?" | Shows clipboard |
| "Copy this to clipboard: Hello" | Copies text |
| "List my documents" | Shows recent files |
| "Summarize the last file" | Summarizes content |

### 🤖 Automation (6)
| Say This | What Happens |
|----------|--------------|
| "Create a workflow to open Chrome and go to gmail" | Creates plan |
| "Execute workflow morning routine" | ⚠️ Runs workflow |
| "Schedule this to run daily at 9am" | Adds schedule |
| "Show scheduled tasks" | Lists schedules |
| "Run tasks in parallel" | Parallel execution |
| "Transfer data from clipboard to notes" | Cross-app transfer |

### 💬 General (4)
| Say This | What Happens |
|----------|--------------|
| "Help" | Shows capabilities |
| "What can you do?" | Lists features |
| "Stop" / "Cancel" | Cancels current action |
| "Read it" | TTS reads last response |

### 🧠 AI Agents (3)
| Say This | What Happens |
|----------|--------------|
| "Plan a trip to Paris" | Multi-step planning |
| "Research best laptops 2026" | Agent research |
| "Analyze my schedule" | Task analysis |

---

## Testing the NEW Reliability Features

### Policy Engine (Safety)
```
Say: "Forget everything"
Expected: Chintu asks for confirmation first (HIGH risk action)

Say: "Search the web" (while offline)
Expected: Chintu denies with reason "No internet"
```

### Budget Manager (Rate Limiting)
The budget manager works in the background:
- After ~25 Groq calls/minute, auto-switches to Gemini
- After ~800 calls/day, switches to local LLM
- Check logs for: "Using provider: groq" or "groq"

### Degraded Mode (Offline)
Disconnect internet, then try:
```
Say: "Open Chrome"        → Works (offline-safe)
Say: "Search the web"     → Denied (requires internet)
Say: "What time is it?"   → Works (offline-safe)
```

```

### Deep Reasoning (Phase 3)
```
Say: "Think deeply: What are the pros and cons of Rust vs C++?"
Expected:
1. Chintu says "Decomposing problem..."
2. Breaks down into steps (Performance, Safety, Ecosystem)
3. Synthesizes final answer (~30 seconds)
```

### Metrics (Debug)
Check the Flutter UI debug panel or run:
```python
from chintu_backend.core import get_metrics
print(get_metrics().get_stats())
```

---

## 🧠 Brain Architecture Testing (Phase 6-7)

### Verified Research
```
Say: "Verify the efficacy of vitamin D supplements"
Expected:
1. Searches multiple sources
2. Scores by credibility (⭐⭐⭐ = .gov/.edu)
3. Returns cited synthesis
```

### Learning Signals (Preference Detection)
```
Say: "Don't use Notepad"
Expected: "Noted. I will avoid using Notepad."

Say: "Be concise"
Expected: "I've noticed you prefer concise responses. Should I save that?"
Then say: "Yes"
Expected: "Preference saved: Response style set to concise."
```

### RAG Retrieval Router
```
Say: "What's my name?"
Expected: Retrieves from personal_facts (check logs for "RAG retrieved X context items")

Say: "What is Python?"
Expected: Skips RAG ("Skipping RAG for knowledge query"), uses LLM directly
```

---

## Confirmation Required (⚠️)
These actions ask "Are you sure?" before executing:
- "Forget everything"
- "Execute workflow"
- "Click" / "Type" (browser automation)
- "Delete" / "Cancel all"

---

## Voice Commands
Wake word: **"Hey Chintu"**

Example session:
1. "Hey Chintu" → *beep*
2. "What time is it?" → "It's 12:30 PM"
3. "Hey Chintu" → *beep*
4. "Open Chrome" → "Opening Chrome..."

## ??? Self-Check Tools (New in v4.5)

To verify system health, features, and code quality, run the included audit tools:

**1. Full System Audit (Recommended)**
Runs dependency check, feature verification, and code quality scan.
\\\ash
tools/audit_all.bat
\\\

**2. Individual Tools**
| Tool | Purpose |
|------|---------|
| \	ools/check_deps.py\ | Verifies Python libraries and OS dependencies (ffmpeg, etc.) |
| \	ools/audit_features.py\ | Verifies that all 20+ capabilities have valid code handlers |
| \	ools/audit_code.py\ | Scans source code for blocking calls and risky exceptions |



## 🛠️ Self-Check Tools (New in v4.5)
To verify system health, features, and code quality, run the included audit tools:

**1. Full System Audit (Recommended)**
Runs dependency check, feature verification, and code quality scan.
	ools/audit_all.bat

**2. Individual Tools**
| Tool | Purpose |
|------|---------|
| 	ools/check_deps.py | Verifies Python libraries and OS dependencies (ffmpeg, etc.) |
| 	ools/audit_features.py | Verifies that all 20+ capabilities have valid code handlers |
| 	ools/audit_code.py | Scans source code for blocking calls and risky exceptions |
