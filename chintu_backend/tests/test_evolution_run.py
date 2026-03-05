import os
import sys
from pathlib import Path

# Add the project root to sys.path
root = Path(__file__).parent.parent.parent
sys.path.append(str(root))

from chintu_backend.core.evolution import get_evolution_manager

def test_evolution():
    ev = get_evolution_manager()
    file_path = "evolution_test_dummy.py"
    
    # Initial state
    with open(file_path, "r") as f:
        print(f"Initial Content:\n{f.read()}")
        
    new_content = """# Dummy File for Evolution Test
# This file was modified autonomously!
def hello():
    print("Hello Evolution")
"""
    
    print("\nProposing change...")
    res = ev.propose_change(file_path, new_content, "Testing un-stubbed apply_patch")
    print(f"Proposal result: {res}")
    
    if "patch_" not in res:
        print("Failed to get patch ID from result.")
        return
        
    patch_id = res.split("(")[1].split(")")[0]
    print(f"Extracted Patch ID: {patch_id}")
    
    print("\nApplying patch...")
    success = ev.apply_patch(patch_id)
    print(f"Apply Success: {success}")
    
    if success:
        with open(file_path, "r") as f:
            print(f"\nModified Content:\n{f.read()}")
    else:
        print("\nPatch application failed. Check logs for details.")

if __name__ == "__main__":
    test_evolution()
