
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from chintu.core.memory import MemoryManager

def test_memory():
    print("Testing Memory Manager...")
    
    # Initialize
    # Use a temp directory or the real one
    path = "c:\\Users\\Sasidhar Yepuri\\Desktop\\My_Projects\\Chimptu\\.chintu\\test_memory_db"
    mm = MemoryManager(persistence_path=path)
    
    if not mm.client:
        print("skipped: ChromaDB not installed or failed to init.")
        return

    # Test 1: Save Interaction
    print("1. Saving interaction...")
    mm.save_interaction("user", "My favorite food is pizza.")
    mm.save_interaction("assistant", "I'll remember that you like pizza.")
    
    # Test 2: Retrieve Context
    print("2. Retrieving context...")
    context = mm.retrieve_context("What is my favorite food?")
    print(f"   Context retrieved:\n---\n{context}\n---")
    
    if "pizza" in context.lower():
        print("   [PASS] Found 'pizza' in context.")
    else:
        print("   [FAIL] 'pizza' not found in context.")

    # Test 3: Profile
    print("3. Testing Profile...")
    mm.update_profile("favorite_color", "blue")
    ctx = mm.get_profile_context()
    print(f"   Profile Context:\n---\n{ctx}\n---")
    
    if "blue" in ctx:
        print("   [PASS] Profile updated.")
    else:
        print("   [FAIL] Profile failed.")

    print("Memory Test Complete.")

if __name__ == "__main__":
    test_memory()
