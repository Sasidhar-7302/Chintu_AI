
import sys
import os
import logging
from pathlib import Path

# Setup Path
current_dir = os.getcwd()
sys.path.append(current_dir)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("VerifyFacts")

try:
    from chintu_backend.brain.middleware.fact_checker import get_fact_checker
except ImportError as e:
    print(f"Import Error: {e}")
    sys.exit(1)

def verify_facts():
    print("\n=== Verifying Fact Checker ===")
    checker = get_fact_checker()
    
    # Mock LLM for deterministic testing
    # We want to ensure the logic handles "START_DECISION FALSE" correctly.
    original_llm_call = checker._llm_call
    
    def mock_llm_call(prompt):
        if "Statement: \"2+2=1\"" in prompt or "Statement: \"Sky is green\"" in prompt:
            return "This is false. START_DECISION FALSE END_DECISION. Reason: 2+2=4."
        elif "Statement: \"Paris is in France\"" in prompt:
            return "This is true. START_DECISION TRUE END_DECISION."
        elif "Review the following text" in prompt: # verify_content
             if "2+2=1" in prompt and not "If it contains common misconceptions" in prompt: # checking content
                 return "Falsehood: 2+2=1 is incorrect."
             return "NONE"
        return "NONE"
        
    checker._llm_call = mock_llm_call
    
    # Test 1: False Claim
    print("Testing '2+2=1'...")
    valid, reason = checker.verify_fact("2+2=1")
    if not valid:
        print(f"PASS: Rejected '2+2=1'. Reason: {reason}")
    else:
        print(f"FAIL: Accepted '2+2=1'.")
        
    # Test 2: True Claim
    print("Testing 'Paris is in France'...")
    valid, reason = checker.verify_fact("Paris is in France")
    if valid:
        print(f"PASS: Accepted 'Paris is in France'.")
    else:
        print(f"FAIL: Rejected 'Paris is in France'. Reason: {reason}")

    # Test 3: Content Verification
    print("Testing verify_content with falsehood...")
    content = "The sky is blue. Also 2+2=1 in some timeline."
    # With our mock, verify_content returns "NONE" unless it triggers specific logic.
    # Our mock for verify_content: returns "Falsehood..." if "2+2=1" in prompt.
    # verify_content logs warnings but returns content (or corrected content).
    # Since my implementation of `verify_content` currently performs logging but returns content,
    # or would return corrected content if prompted differently.
    # In `fact_checker.py`: `if "NONE" in response... return content`.
    # Else log it.
    
    # Let's just run it to see no crash.
    checker.verify_content(content)
    print("PASS: verify_content ran without error.")

if __name__ == "__main__":
    verify_facts()
