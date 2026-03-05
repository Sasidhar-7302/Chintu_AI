
import sys
import os
import logging
from typing import Dict, Any

# Setup Check
current_dir = os.getcwd()
sys.path.append(current_dir)

# Mock Objects
class MockMemory:
    def search_facts(self, query):
        print(f"DEBUG: Memory searched for: '{query}'")
        return []

def test_policy_fixes():
    print("\n=== Testing Policy Fixes ===")
    from chintu_backend.policy.policy_engine import ActionPolicyEngine, RiskLevel, PolicyDecision, CapabilityContract
    
    engine = ActionPolicyEngine()
    
    # 1. Check get_system_specs (Should be LOW, No Confirmation)
    contract = engine.DEFAULT_CONTRACTS.get("get_system_specs")
    if contract:
        print(f"get_system_specs Contract: Level={contract.risk_level}, Confirm={contract.requires_confirmation}")
        if contract.risk_level == RiskLevel.LOW and not contract.requires_confirmation:
            print("PASS: get_system_specs is optimized.")
        else:
            print("FAIL: get_system_specs is not optimized.")
    else:
        print("FAIL: get_system_specs contract not found.")

    # 2. Check identity (Should be LOW)
    contract = engine.DEFAULT_CONTRACTS.get("identity")
    if contract:
        print(f"identity Contract: Level={contract.risk_level}")
        if contract.risk_level == RiskLevel.LOW:
            print("PASS: identity is optimized.")
        else:
            print("FAIL: identity is not optimized.")
    else:
        print("FAIL: identity contract not found.")

def test_memory_cleaning():
    print("\n=== Testing Memory Query Cleaning ===")
    from chintu_backend.brain.memory import memory_capabilities
    
    # Mock handlers
    # We'll just trace the logic by inspecting the code or running a mock function
    # But since we can't easily import handle_recall_facts without full backend, we will verify the REGEX here
    
    test_queries = [
        "What is my favorite color?", 
        "Tell me what are my preferences",
        "Do you know my secret code?"
    ]
    
    import re
    for text in test_queries:
        text_lower = text.lower()
        query = None
        
        # Logic copied from handle_recall_facts
        if any(p in text_lower for p in ["what is", "what are", "do you know", "do i like", "tell me"]):
            for prefix in ["what is", "what are", "do you know", "tell me", "do i like"]:
                if prefix in text_lower:
                    query = text_lower.replace(prefix, "").strip()
                    break
            
            # Remove ownership words for better matching
            if query:
                query = re.sub(r"\b(my|the)\b", "", query).strip()
        
        print(f"Input: '{text}' -> Cleaned: '{query}'")
        
    print("Optimization Verified if inputs are stripped correctly (e.g. 'favorite color').")

if __name__ == "__main__":
    try:
        test_policy_fixes()
        test_memory_cleaning()
    except ImportError as e:
        print(f"Import Error: {e}")
        print("Ensure you are running from the project root.")
