
import sys
import os
import logging
from pathlib import Path

current_dir = os.getcwd()
sys.path.append(current_dir)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("VerifyRAG")

try:
    from chintu_backend.brain.memory.hybrid_memory import HybridMemoryManager
    from chintu_backend.brain.rag.retrieval_router import get_retrieval_router
    from chintu_backend.brain.learning.learning_engine import get_learning_engine
except ImportError as e:
    print(f"Import Error: {e}")
    sys.exit(1)

def verify_rag():
    print("\n=== Verifying RAG & Fine-tuning pipeline ===")
    
    # 1. Setup Test DB
    test_db = Path("data_test/memory_hybrid.db")
    if test_db.exists():
        test_db.unlink()
        
    mem = HybridMemoryManager(test_db)
    
    # 2. Add Data
    logger.info("Adding data...")
    mem.save_interaction("assistant", "The capital of France is Paris.", category="knowledge", source="book")
    mem.save_interaction("user", "I want to go to France.", category="conversation", source="chat")
    
    # 3. Test Retrieval Router
    router = get_retrieval_router()
    # Mock router's memory to point to our test mem
    router.memory = mem 
    
    # Test A: History Query
    print("\n--- Test A: History Query ---")
    q1 = "what did i say about France?"
    res1 = router.retrieve(q1)
    print(f"Query: {q1}")
    print(f"Result: {res1[:100]}...")
    if "go to France" in res1:
        print("PASS: Found conversation.")
    else:
        print("FAIL: Did not find conversation.")
        
    # Test B: Knowledge Query
    print("\n--- Test B: Knowledge Query ---")
    q2 = "what is the capital of France?"
    # Note: Router heuristic maps "what is" to research/knowledge priority or generic.
    # Logic: if "what is", filter "research"? 
    # Let's check router logic implementation in previous step.
    # `elif "what is" ... filters["category"] = "research"`
    # So it applies filter `category='research'`.
    # My sample data used `category='knowledge'`.
    # Hmmm. `DeepResearcher` saves as `category='research'`. 
    # I should restart my data to `category='research'`.
    
    mem.save_interaction("assistant", "Paris is the capital.", category="research", source="book")
    
    res2 = router.retrieve(q2)
    print(f"Query: {q2}")
    print(f"Result: {res2[:100]}...")
    if "Paris" in res2:
        print("PASS: Found knowledge.")
    else:
        print("FAIL: Knowledge not found (maybe filter excluding it).")

    # 4. Test Export
    print("\n--- Test C: Export Dataset ---")
    engine = get_learning_engine()
    engine.config.data_dir = Path("data_test") # Redirect
    
    # Create fake knowledge book for export test
    k_dir = Path("data_test/knowledge/science/physics/")
    k_dir.mkdir(parents=True, exist_ok=True)
    (k_dir / "chapter_1.md").write_text("Atoms are small.", encoding="utf-8")
    
    out_file = Path("data_test/dataset.jsonl")
    count = engine.export_training_dataset(out_file, format="instruction")
    print(f"Exported {count} items.")
    
    if out_file.exists():
        text = out_file.read_text("utf-8")
        if "Atoms are small" in text:
            print("PASS: Knowledge base exported.")
        else:
            print("FAIL: Content missing from export.")
    else:
        print("FAIL: Export file missing.")

if __name__ == "__main__":
    verify_rag()
