import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from chintu_backend.core.app import ChintuAssistant
from chintu_backend.core.state import get_state_manager

async def verify():
    print("Initializing Chintu for Verification...")
    assistant = ChintuAssistant()
    sm = get_state_manager()
    reg = assistant.command_handler.capability_registry
    
    print(f"Registered Capabilities ({len(reg.list_capabilities())}):")
    for cap in reg.list_capabilities():
        print(f" - {cap['name']}")

    test_cases = [
        "Check my battery level",
        "Vibrate my phone",
        "What is my phone's battery level?",
        "Where is my phone right now?"
    ]
    
    print("\n--- Hallucination Fix Verification ---\n")
    
    for cmd in test_cases:
        print(f"Command: {cmd}")
        # Introspect match
        match = reg.match(cmd)
        if match:
            score = match.get_match_score(cmd)
            print(f"  Matched: {match.name} (Score: {score:.2f})")
        else:
            print("  Matched: None (LLM Fallback)")
            
        # Process
        assistant.command_handler.handle(cmd, source="verification")
        
        # Wait for processing
        await asyncio.sleep(5)
        
        state = sm.state
        response = getattr(state, 'last_response', "No response")
        print(f"Response: {response}\n")

if __name__ == "__main__":
    asyncio.run(verify())
