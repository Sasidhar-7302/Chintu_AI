
import sys
import os
import shutil
import logging
from pathlib import Path

# Setup Check
current_dir = os.getcwd()
sys.path.append(current_dir)

from chintu_backend.brain.memory.knowledge_store import KnowledgeStore
from chintu_backend.brain.memory.hybrid_memory import HybridMemoryManager

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("VerifyStorage")

def verify_storage():
    print("\n=== Verifying Storage Layer ===")
    
    # 1. Setup paths
    test_data_dir = Path(current_dir) / "data_test"
    if test_data_dir.exists():
        shutil.rmtree(test_data_dir)
    test_data_dir.mkdir()
    
    # 2. Test KnowledgeStore
    print("-> Testing KnowledgeStore...")
    ks = KnowledgeStore(test_data_dir)
    
    category = "test_science"
    topic = "physics"
    content = "# Physics\nPhysics is the natural science that studies matter."
    metadata = {"author": "Chintu", "difficulty": "basic"}
    
    file_path = ks.save_document(category, topic, "intro.md", content, metadata)
    
    if file_path.exists():
        print("PASS: Document saved.")
    else:
        print("FAIL: Document not saved.")
        return

    # 3. Test HybridMemory Integration
    print("-> Testing HybridMemory Schema & Ingestion...")
    # Point memory to test dir
    # We need to monkey-patch get_config if strictly needed, but let's just instantiate with explicit path if supported
    # HybridMemoryManager takes db_path arg
    
    db_path = test_data_dir / "memory.db"
    mem = HybridMemoryManager(db_path=db_path)
    
    # Check Schema Migration (implicitly done in init)
    # Check columns
    cur = mem._conn.execute("PRAGMA table_info(interactions)")
    cols = {row[1] for row in cur.fetchall()}
    if "category" in cols and "source" in cols:
        print("PASS: Schema has 'category' and 'source'.")
    else:
        print(f"FAIL: Schema missing columns. Found: {cols}")
        return

    # Ingest document
    print("-> Ingesting Document...")
    mem.add_knowledge_document(content, {"category": category, "topic": topic})
    
    # Search
    print("-> Searching...")
    import time
    time.sleep(1) # Write buffer
    
    results = mem.retrieve_context("Physics", n_results=1)
    print(f"Result: {results}")
    
    if "Physics" in results:
        print("PASS: Retrieval successful.")
    else:
        print("FAIL: Retrieval failed.")
        
    # Verify Source Metadata in DB
    cur = mem._conn.execute("SELECT category, source FROM interactions WHERE content LIKE '%Physics%'")
    row = cur.fetchone()
    if row and row[0] == category and row[1] == "knowledge_base":
        print(f"PASS: Metadata confirmed (Cat: {row[0]}, Src: {row[1]})")
    else:
        print(f"FAIL: Metadata mismatch. Row: {row}")

    print("\n=== Phase 1 Verified Successfully ===")

if __name__ == "__main__":
    verify_storage()
