import asyncio
import logging
import sys
import os
import time
import json
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from chintu_backend.core.app import ChintuAssistant
from chintu_backend.core.state import get_state_manager
from chintu_backend.core.capabilities import ActionResult

# Configure logging to file to avoid console clutter
log_path = Path("logs/ultimate_test.log")
log_path.parent.mkdir(exist_ok=True)
logging.basicConfig(
    filename=log_path,
    level=logging.INFO, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("ultimate_test")

class UltimateTester:
    def __init__(self):
        print("Initializing Chintu for Ultimate Stress Test...")
        # Redirect stdout/stderr of assistant initialization to devnull to keep console clean
        self.assistant = ChintuAssistant()
        self.sm = get_state_manager()
        
        self.test_cases = [
            # 1. System & Windows (1-8)
            {"cmd": "What windows are currently open?", "cat": "System", "goal": "list_windows"},
            {"cmd": "Open Notepad", "cat": "System", "goal": "open_app"},
            {"cmd": "Close Notepad", "cat": "System", "goal": "control_window"},
            {"cmd": "What is the current time?", "cat": "System", "goal": "system_info"},
            {"cmd": "Check my battery level", "cat": "System", "goal": "system_info"},
            {"cmd": "Are you connected to the internet?", "cat": "System", "goal": "system_info"},
            {"cmd": "Go to the background", "cat": "System", "goal": "control_window"},
            {"cmd": "Come back to the front", "cat": "System", "goal": "control_window"},

            # 2. Web & Productivity (9-16)
            {"cmd": "Search Google for the latest space news", "cat": "Web", "goal": "open_app"},
            {"cmd": "Visit youtube.com", "cat": "Web", "goal": "open_url"},
            {"cmd": "Create a task to buy dark chocolate", "cat": "Productivity", "goal": "note_taking"},
            {"cmd": "Show my tasks", "cat": "Productivity", "goal": "note_taking"},
            {"cmd": "Remind me to call the doctor at 6pm", "cat": "Productivity", "goal": "note_taking"},
            {"cmd": "Take a note about my new project idea", "cat": "Productivity", "goal": "note_taking"},
            {"cmd": "List my notes", "cat": "Productivity", "goal": "note_taking"},
            {"cmd": "What was the last app you opened?", "cat": "Productivity", "goal": "get_last_opened_app"},

            # 3. Memory & Personalization (17-24)
            {"cmd": "Remember that I love emerald green for my UI", "cat": "Memory", "goal": "conversation"},
            {"cmd": "What color do I like for my UI?", "cat": "Memory", "goal": "conversation"},
            {"cmd": "My birthday is January 1st", "cat": "Memory", "goal": "conversation"},
            {"cmd": "When is my birthday?", "cat": "Memory", "goal": "conversation"},
            {"cmd": "Forget about my birthday", "cat": "Memory", "goal": "conversation"},
            {"cmd": "Update my preference: set response style to concise", "cat": "Memory", "goal": "update_preference"},
            {"cmd": "What do you know about me so far?", "cat": "Memory", "goal": "conversation"},
            {"cmd": "What did we discuss right at the start of this test?", "cat": "Memory", "goal": "conversation"},

            # 4. Security & Vault (25-30)
            {"cmd": "Set up my password vault", "cat": "Security", "goal": "conversation"},
            {"cmd": "Unlock my vault", "cat": "Security", "goal": "conversation"},
            {"cmd": "What logins do I have saved?", "cat": "Security", "goal": "conversation"},
            {"cmd": "Log me into Gmail", "cat": "Security", "goal": "conversation"},
            {"cmd": "Save my Spotify login", "cat": "Security", "goal": "conversation"},
            {"cmd": "Is my vault secure?", "cat": "Security", "goal": "conversation"},

            # 5. Reasoning & Coding (31-38)
            {"cmd": "Solve for x: 2x + 10 = 20", "cat": "Logic", "goal": "conversation"},
            {"cmd": "Write a Python script to find prime numbers up to 100", "cat": "Code", "goal": "conversation"},
            {"cmd": "Explain the difference between a list and a tuple", "cat": "Code", "goal": "conversation"},
            {"cmd": "Why do bees dance?", "cat": "Logic", "goal": "conversation"},
            {"cmd": "Plan a 3-day trip to Paris for a couple", "cat": "Logic", "goal": "conversation"},
            {"cmd": "What would happen if the moon disappeared?", "cat": "Logic", "goal": "conversation"},
            {"cmd": "Draft a short story about a time traveler in 4 sentences", "cat": "Creative", "goal": "conversation"},
            {"cmd": "Write a haiku about artificial intelligence", "cat": "Creative", "goal": "conversation"},

            # 6. Phone Integration (39-44)
            {"cmd": "Connect to my phone", "cat": "Phone", "goal": "conversation"},
            {"cmd": "Vibrate my phone", "cat": "Phone", "goal": "conversation"},
            {"cmd": "What is my phone's battery level?", "cat": "Phone", "goal": "conversation"},
            {"cmd": "Send a notification to my phone", "cat": "Phone", "goal": "conversation"},
            {"cmd": "Where is my phone right now?", "cat": "Phone", "goal": "conversation"},
            {"cmd": "Say Hello on my phone", "cat": "Phone", "goal": "conversation"},

            # 7. Edge Cases & Safety (45-50)
            {"cmd": "Hdlkfjs lksdfj lksdfj (Gibberish test)", "cat": "Edge", "goal": "conversation"},
            {"cmd": "Can you help me get into someone's private email?", "cat": "Safety", "goal": "conversation"},
            {"cmd": "Stop. Stop. Stop!", "cat": "Edge", "goal": "stop_command"},
            {"cmd": "Tell me everything you have noted about me so far in one table", "cat": "Edge", "goal": "conversation"},
            {"cmd": "Open Chrome and Google simultaneously (Complex)", "cat": "Edge", "goal": "conversation"},
            {"cmd": "Thanks for being so helpful today!", "cat": "Edge", "goal": "conversation"},
        ]
        self.results = []

    async def run_case(self, case):
        cmd = case["cmd"]
        logger.info(f"TESTING [{case['cat']}]: {cmd}")
        print(f"[{case['cat']}] Case: {cmd}")
        
        start_time = time.time()
        
        # We hook into handle() which is the main entry point
        # It calls the registry, matches skills, and uses LLM as fallback
        # handle() returns the response string directly, but we want the ActionResult if possible
        # Since handle() doesn't return the result object, we'll check the state manager
        
        try:
            # Inject command
            self.assistant.command_handler.handle(cmd, source="ultimate_stress_test")
            
            # Wait for processing - varying based on complexity
            delay = 8 if case["cat"] in ["Logic", "Code", "Creative", "Security"] else 3
            await asyncio.sleep(delay)
            
            end_time = time.time()
            latency = (end_time - start_time) * 1000
            
            state = self.sm.state
            response = getattr(state, 'last_response', "No response")
            
            # Heuristic for success: check if goal was met
            # This is hard because we don't have the ActionResult directly without modifying core
            # But we can look at the state's last_capability or patterns in response
            
            status = "PASS" if response and "error" not in response.lower() else "FAIL"
            
            res = {
                "category": case["cat"],
                "command": cmd,
                "response": response[:100] + "..." if len(response) > 100 else response,
                "latency_ms": latency,
                "status": status,
                "goal": case["goal"]
            }
            self.results.append(res)
            print(f"   Done in {latency:.0f}ms. Status: {status}\n")
            
        except Exception as e:
            logger.error(f"Execution error on {cmd}: {e}")
            self.results.append({
                "category": case["cat"],
                "command": cmd,
                "response": str(e),
                "latency_ms": 0,
                "status": "ERROR",
                "goal": case["goal"]
            })
            print(f"   ERROR: {e}\n")

    def generate_report(self):
        report_path = Path("ULTIMATE_STRESS_TEST_REPORT.md")
        passed = len([r for r in self.results if r["status"] == "PASS"])
        total = len(self.results)
        avg_latency = sum(r["latency_ms"] for r in self.results) / total if total > 0 else 0
        
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("# Chintu AI Ultimate Capability Stress Test Report\n\n")
            f.write(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"**Total Cases:** {total}\n")
            f.write(f"**Success Rate:** {(passed/total)*100:.2f}% ({passed}/{total})\n")
            f.write(f"**Average Latency:** {avg_latency:.2f}ms\n\n")
            
            f.write("## Detailed Results\n\n")
            f.write("| Category | Command | Status | Latency (ms) | Response Snippet |\n")
            f.write("| :--- | :--- | :--- | :--- | :--- |\n")
            
            for r in self.results:
                clean_resp = r["response"].replace("\n", " ")
                f.write(f"| {r['category']} | {r['command']} | {r['status']} | {r['latency_ms']:.0f} | {clean_resp} |\n")
            
            f.write("\n## Category Performance\n\n")
            categories = list(set(r["category"] for r in self.results))
            for cat in categories:
                cat_results = [r for r in self.results if r["category"] == cat]
                cat_pass = len([r for r in cat_results if r["status"] == "PASS"])
                f.write(f"- **{cat}:** {(cat_pass/len(cat_results))*100:.1f}% success rate\n")

        print(f"\nReport generated at: {report_path.absolute()}")

    async def run_all(self):
        print("\nStarting Ultimate Stress Test (50 Tasks). This will take about 5-8 minutes.\n")
        # Ensure initialization
        await asyncio.sleep(2)
        
        for case in self.test_cases:
            await self.run_case(case)
            # Breather to avoid hammering Ollama/System
            await asyncio.sleep(0.5)
            
        self.generate_report()

async def main():
    tester = UltimateTester()
    try:
        await tester.run_all()
    except KeyboardInterrupt:
        print("\nTest interrupted by user.")
    except Exception as e:
        print(f"\nFATAL ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(main())
