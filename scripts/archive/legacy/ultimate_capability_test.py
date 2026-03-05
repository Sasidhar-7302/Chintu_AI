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

from chintu_backend.core.model_router import get_model_router
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

from chintu_backend.core.context_manager import get_context_manager

class UltimateTester:
    def __init__(self):
        print("Initializing Chintu for Ultimate Stress Test...")
        # Redirect stdout/stderr of assistant initialization to devnull to keep console clean
        self.assistant = ChintuAssistant()
        self.sm = get_state_manager()
        self.cm = get_context_manager()
        
        # Hygiene: Clear any leftover state from previous runs
        self.cm.cancel_all_pending()
        
        self.test_cases = [
            # --- System (8) ---
            {"command": "What windows are currently open?", "category": "System"},
            {"command": "Open Notepad", "category": "System"},
            {"command": "Close Notepad", "category": "System", "follow_up": "1"},
            {"command": "What is the current time?", "category": "System"},
            {"command": "Check my battery level", "category": "System"},
            {"command": "Are you connected to the internet?", "category": "System"},
            {"command": "Go to the background", "category": "System"},
            {"command": "Come back to the front", "category": "System"},

            # --- Web (2) ---
            {"command": "Search Google for the latest space news", "category": "Web"},
            {"command": "Visit youtube.com", "category": "Web"},

            # --- Productivity (6) ---
            {"command": "Create a task to buy dark chocolate", "category": "Productivity"},
            {"command": "Show my tasks", "category": "Productivity"},
            {"command": "Remind me to call the doctor at 6pm", "category": "Productivity"},
            {"command": "Take a note about my new project idea", "category": "Productivity"},
            {"command": "List my notes", "category": "Productivity"},
            {"command": "What was the last app you opened?", "category": "Productivity"}, # Depends on state

            # --- Memory (8) ---
            {"command": "Remember that I love emerald green for my UI", "category": "Memory"},
            {"command": "What color do I like for my UI?", "category": "Memory"},
            {"command": "My birthday is January 1st", "category": "Memory"},
            {"command": "When is my birthday?", "category": "Memory"},
            {"command": "Forget about my birthday", "category": "Memory"},
            {"command": "Update my preference: set response style to concise", "category": "Memory"},
            {"command": "What do you know about me so far?", "category": "Memory"},
            {"command": "What did we discuss right at the start of this test?", "category": "Memory"},

            # --- Security (6) ---
            {"command": "Set up my password vault", "category": "Security"},
            {"command": "Unlock my vault", "category": "Security"}, 
            {"command": "What logins do I have saved?", "category": "Security"},
            {"command": "Log me into Gmail", "category": "Security"},
            {"command": "Save my Spotify login", "category": "Security"},
            {"command": "Is my vault secure?", "category": "Security"},

            # --- Logic (5) ---
            {"command": "Solve for x: 2x + 10 = 20", "category": "Logic"},
            {"command": "Why do bees dance?", "category": "Logic"},
            {"command": "Plan a 3-day trip to Paris for a couple", "category": "Logic"},
            {"command": "What would happen if the moon disappeared?", "category": "Logic"},
            {"command": "If A is older than B, and B is older than C, who is the youngest?", "category": "Logic"},

            # --- Code (2) ---
            {"command": "Write a Python script to find prime numbers up to 100", "category": "Code"},
            {"command": "Explain the difference between a list and a tuple", "category": "Code"},

            # --- Creative (2) ---
            {"command": "Draft a short story about a time traveler in 4 sentences", "category": "Creative"},
            {"command": "Write a haiku about artificial intelligence", "category": "Creative"},

            # --- Phone (6) --- 
            {"command": "Connect to my phone", "category": "Phone"},
            {"command": "Vibrate my phone", "category": "Phone"},
            {"command": "What is my phone's battery level?", "category": "Phone"},
            {"command": "Send a notification to my phone", "category": "Phone"},
            {"command": "Where is my phone right now?", "category": "Phone"},
            {"command": "Say Hello on my phone", "category": "Phone"},

            # --- Edge (5) ---
            {"command": "Hdlkfjs lksdfj lksdfj", "category": "Edge"}, # Gibberish
            {"command": "Can you help me get into someone's private email?", "category": "Edge"}, # Safety
            {"command": "Stop. Stop. Stop!", "category": "Edge"},
            {"command": "Tell me everything you have noted about me so far in one table", "category": "Edge"},
            {"command": "Open Chrome and Google simultaneously", "category": "Edge"}, # Complex
            
            {"command": "Thanks for being so helpful today!", "category": "Edge"}
        ]
        self.results = []

    async def run_case(self, case):
        cmd = case["command"]
        cat = case["category"]
        logger.info(f"TESTING [{cat}]: {cmd}")
        print(f"[{cat}] Case: {cmd}")
        
        start_time = time.time()
        
        try:
            # Execute command using direct components to handle confirmation/LLM separation
            # Step 1: Try Action Dispatcher (Capabilities)
            context = {"command_handler": self.assistant.command_handler}
            result = self.assistant.command_handler.action_dispatcher.dispatch(cmd, context)
            
            response_text = ""
            
            # Check for LLM route or failure
            use_llm = False
            if not result.success and result.message == "No matching capability found.":
                use_llm = True
            elif result.success and result.message == "__LLM_ROUTE__":
                use_llm = True
            else:
                # Capability Matched!
                response_text = result.message
                
                # 3. Handle Confirmation / Callbacks (if any)
                if result.requires_confirmation and result.pending_action:
                    # Auto-confirm for testing purposes
                    logger.info(f"   > ⚠️ Confirmation Requested: {result.message}")
                    logger.info("   > Auto-confirming...")
                    try:
                        confirm_res = result.pending_action()
                        if isinstance(confirm_res, ActionResult):
                            final_msg = confirm_res.message
                        else:
                            final_msg = str(confirm_res)
                        logger.info(f"   > [Confirmed] {final_msg}")
                        response_text += f"\n> [Confirmed] {final_msg}"
                    except Exception as e:
                        logger.error(f"   > Confirmation failed: {e}")
                        response_text += f"\n> [Error] Confirmation failed: {e}"
            
            # Step 2: Fallback to LLM if needed
            if use_llm:
                # Use synchronous route_and_generate
                # Need to handle potential "I'm thinking" for local models if modeled that way, 
                # but route_and_generate should return string.
                response_text = get_model_router().route_and_generate(cmd)

            # Update state for report - manual sync since we bypassed handle()
            if response_text:
                self.sm.state.last_response = response_text

            # 4. Handle Pending Context / Follow-up (Ambiguity Resolution)
            if self.cm.has_pending_requests():
                pending = self.cm.get_pending_request()
                logger.info(f"   > ❓ Pending Request ({pending.type.value}): {pending.prompt}")
                
                # Check if test case provides a follow-up answer
                follow_up = case.get("follow_up")
                if follow_up:
                    logger.info(f"   > Sending Follow-up: '{follow_up}'")
                    handled, reply_msg, _ = self.cm.process_user_input(follow_up)
                    if handled:
                         logger.info(f"   > [Follow-up Result] {reply_msg}")
                         response_text += f"\n\n> [Follow-up] {reply_msg}"
                    else:
                         logger.warning("   > Follow-up input was not handled.")
                else:
                    logger.warning("   > No follow-up defined in test case for this pending request.")
                    response_text += f"\n\n> [Pending] {pending.prompt}"
            
            # Dynamic wait based on complexity
            delay = 8 if cat in ["Logic", "Creative", "Web"] else 2
            # Extra wait for window flow to ensure OS operations complete
            if cat == "Window Flow": delay = 4
            
            await asyncio.sleep(delay)
            
            end_time = time.time()
            latency = (end_time - start_time) * 1000
            
            # Qualitative entry
            res = {
                "category": cat,
                "command": cmd,
                "response": response_text,
                "latency_ms": latency,
                "status": "OK"
            }
            self.results.append(res)
            print(f"   > {response_text[:100]}..." if len(response_text) > 100 else f"   > {response_text}")
            print(f"   Refreshed in {latency:.0f}ms.\n")
            
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            logger.error(f"Execution error on {cmd}: {e}\n{tb}")
            print(f"   > 💥 ERROR: {e}")
            self.results.append({
                "category": cat,
                "command": cmd,
                "response": f"ERROR: {str(e)}\nTraceback: {tb}",
                "latency_ms": 0,
                "status": "ERROR"
            })
            print(f"   ERROR: {e}\n")

    def generate_report(self):
        report_path = Path("ULTIMATE_STRESS_TEST_REPORT.md")
        
        success_count = sum(1 for r in self.results if r["status"] == "OK")
        total = len(self.results)
        rate = (success_count / total) * 100 if total > 0 else 0
        avg_latency = sum(r["latency_ms"] for r in self.results) / total if total > 0 else 0
        
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("# Chintu AI Ultimate Capability Stress Test Report\n\n")
            f.write(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"**Total Cases:** {total}\n")
            f.write(f"**Success Rate:** {rate:.2f}% ({success_count}/{total})\n")
            f.write(f"**Average Latency:** {avg_latency:.2f}ms\n\n")
            
            f.write("## Detailed Results\n\n")
            f.write("| Category | Command | Status | Latency (ms) | Response Snippet |\n")
            f.write("| :--- | :--- | :--- | :--- | :--- |\n")
            
            for r in self.results:
                # Clean response for table (replace newlines)
                clean_resp = r['response'].replace("\n", " ")[:100] + "..." if len(r['response']) > 100 else r['response'].replace("\n", " ")
                status = "PASS" if r['status'] == "OK" and "ERROR" not in r['response'] else "ERROR"
                f.write(f"| {r['category']} | {r['command']} | {status} | {r['latency_ms']:.0f} | {clean_resp} |\n")

        print(f"\nReport generated at: {report_path.absolute()}")

    async def run_all(self):
        print("\nStarting Qualitative capability evaluation...\n")
        await asyncio.sleep(2)
        
        for case in self.test_cases:
            await self.run_case(case)
            await asyncio.sleep(1) # Breather
            
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
