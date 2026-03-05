import asyncio
import logging
import sys
import os
from pathlib import Path
from datetime import datetime

# Ensure project root is in path
sys.path.append(str(Path(__file__).parent.parent))

from chintu_backend.core.app import ChintuAssistant
from chintu_backend.core import get_state_manager, AssistantState

# Configure logging for test
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("extensive_test")

class ChintuStressTester:
    def __init__(self):
        self.assistant = ChintuAssistant()
        self.sm = get_state_manager()
        self.test_results = []

    async def run_command(self, text, delay=3):
        logger.info(f"TEST INPUT: {text}")
        # Simulate the transcript process
        await self.assistant._process_transcript(text, source="stress_test")
        
        # Give some time for background processing
        await asyncio.sleep(delay)
        
        response = self.sm.state.last_response
        logger.info(f"CHINTU RESPONSE: {response}")
        return response

    async def run_suite(self):
        logger.info("Starting Extensive Stress Test Suite (30+ Commands)")
        
        test_cases = [
            # 1-5: Identity and Small Talk
            "Who are you?",
            "What is your name?",
            "How are you today?",
            "What can you do?",
            "Tell me a joke.",
            
            # 6-10: Memory and Personalization (Set & Retrieve)
            "My name is Sasidhar.",
            "What is my name?",
            "Remember that I like black tea.",
            "What kind of tea do I like?",
            "Do you know who I am?",
            
            # 11-15: System and Control
            "Open Notepad.",
            "What time is it?",
            "Check the system health.",
            "What is the battery level?",
            "Turn on hand gesture control.", # This will trigger _toggle_hand_gestures
            
            # 16-20: Knowledge and Reasoning
            "What is the capital of France?",
            "Explain how quantum computing works in one sentence.",
            "Calculate 256 multiplied by 12.",
            "Who won the last FIFA world cup?",
            "What are the latest news headlines?",
            
            # 21-25: Productivity and Tools
            "Search for remote Python developer jobs on LinkedIn.",
            "Schedule a meeting for tomorrow at 10 AM.",
            "What is on my schedule for today?",
            "Create a to-do list for my weekend trip.",
            "Write a short python script to scrape a website.",
            
            # 26-30: Edge Cases and Ambiguity
            "uuh... hmmm...", # Filler handling
            "Play something.", # Ambiguity
            "Can you help me with that thing we talked about earlier?", # Context/Memory
            "Error test: non_existent_command_12345", # Fallback
            "Stop everything.", # Control
            
            # 31-35: Follow-ups and Context
            "What's the weather like in New York?",
            "And what about tomorrow?", # Follow-up context
            "Tell me more about the first thing you mentioned.", # Contextual retrieval
            "Is it going to rain there?", # Pronoun resolution
            "Thanks for the help, Chintu!"
        ]

        # Note: We need the assistant loop or some components to be active for some tools
        # For this stress test, we are mainly testing the reasoning/router flow
        
        for i, cmd in enumerate(test_cases, 1):
            print(f"\n--- Test Case {i}/35: {cmd} ---")
            response = await self.run_command(cmd)
            self.test_results.append({"command": cmd, "response": response})
            
        self.report()

    def report(self):
        print("\n" + "="*50)
        print("FINAL STRESS TEST REPORT")
        print("="*50)
        success_count = sum(1 for r in self.test_results if r["response"] and r["response"] != "No response")
        print(f"Total Commands: {len(self.test_results)}")
        print(f"Successful Responses: {success_count}")
        print(f"Success Rate: {(success_count/len(self.test_results))*100:.2f}%")
        print("="*50)

async def main():
    # We need to mock some things if Ollama is not running, 
    # but for a real stress test, we assume dependencies are up.
    tester = ChintuStressTester()
    try:
        await tester.run_suite()
    except Exception as e:
        logger.error(f"Test suite failed: {e}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(main())
