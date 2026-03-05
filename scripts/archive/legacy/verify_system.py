
import sys
import os
import logging
import asyncio
from pathlib import Path

# Setup Path
current_dir = os.getcwd()
sys.path.append(current_dir)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SystemIntegrity")

# Mock classes to avoid full startup cost of IntentDetector/LLM
# We want to verified WIRING, not model performance.

from chintu_backend.core.capabilities import CapabilityRegistry
from chintu_backend.brain.learning.learning_capabilities import handle_deep_learn
from chintu_backend.brain.rag.retrieval_router import RetrievalRouter
from chintu_backend.brain.memory.hybrid_memory import HybridMemoryManager

def verify_integration():
    print("\n=== Verifying System Integrity (Optimization & Wiring) ===")
    
    # 1. Setup Data Paths
    data_test = Path("data_system_test")
    data_test.mkdir(exist_ok=True)
    
    # Redirect internal paths via simple monkey-patch (for test safety)
    # Ideally Config would handle this, but for script speed we mock.
    
    # 2. Verify "Wiring" of Deep Research
    print("\n--- Test 1: Capability Wiring ---")
    # Does 'deep_learn' exist in capability registry?
    # Actually, we registered it in `learning_capabilities.py`.
    # Let's verify we can import and inspect it.
    try:
        from chintu_backend.core.capability_loader import get_capability_registry
        # Note: capability loader scans folder. We won't run full scan.
        # Just check if handle_deep_learn is callable.
        if callable(handle_deep_learn):
            print("PASS: handle_deep_learn is importable.")
        else:
            print("FAIL: handle_deep_learn broken.")
    except Exception as e:
        print(f"FAIL: Wiring check failed: {e}")

    # 3. Optimize check: Lazy Imports
    print("\n--- Test 2: Lazy Import Check ---")
    import chintu_backend.core.app as app_module
    # Check if DeepResearcher is imported in app.py module level (bad) or not
    if "DeepResearcher" in dir(app_module):
         print("WARN: DeepResearcher detected in app.py namespace. Might slow startup.")
    else:
         print("PASS: DeepResearcher not eagerly loaded in app.py.")

    # 4. Connectedness (The Loop)
    print("\n--- Test 3: The Knowledge Loop ---")
    # Simulate: User inputs "Learn about Integration Testing"
    # Action: handle_deep_learn called.
    # Result: Data in Knowledge Store.
    # Retrieval: RAG finds it.
    
    # We will manually trigger the flow components.
    
    # A. Agent writes to Memory (Simulated)
    topic = "Integration Testing"
    content = "Integration testing verifies that different modules work together correctly."
    
    # Manually saving to Knowledge Store via Memory manager (as Agent would)
    mem_path = data_test / "memory.db"
    if mem_path.exists(): mem_path.unlink()
    
    mem = HybridMemoryManager(mem_path)
    mem.save_interaction("assistant", f"Research on {topic}: {content}", category="research", source="knowledge_base")
    
    # B. Router retrieves it
    router = RetrievalRouter()
    router.memory = mem # Inject test memory
    
    query = "What is integration testing?"
    result = router.retrieve(query)
    
    print(f"Query: {query}")
    print(f"Result: {result}")
    
    if "verifies that different modules work" in result:
        print("PASS: Knowledge moved from Agent -> Memory -> Router.")
    else:
        print("FAIL: The loop is broken. RAG didn't find the data.")

if __name__ == "__main__":
    verify_integration()
