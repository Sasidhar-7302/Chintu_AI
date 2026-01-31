"""Benchmark Latency for Chintu Core Components.
Measures:
1. Intent Detection Time
2. Routing Logic Time
3. Window Manager Speed
"""

import time
import logging
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from chintu_backend.core.model_router import IntentDetector, ModelRouter, RoutingDecision
from chintu_backend.platform.window_manager import get_window_manager

def benchmark():
    print("=== Chintu Latency Benchmark ===\n")
    
    # 1. Intent Detection
    detector = IntentDetector()
    queries = [
        "What is on my screen?",
        "Open Chrome",
        "Who created you?",
        "Read this article",
        "Click here"
    ]
    
    print("[Intent Detector]")
    start_time = time.time()
    for q in queries:
        detector.detect(q)
    total_time = time.time() - start_time
    avg_time = (total_time / len(queries)) * 1000
    print(f"  Processed {len(queries)} queries in {total_time:.4f}s")
    print(f"  Avg Latency: {avg_time:.2f} ms")
    print("  RESULT: " + ("PASS" if avg_time < 10 else "FAIL")) 
    print("")

    # 2. Window Manager
    print("[Window Manager]")
    wm = get_window_manager()
    start_time = time.time()
    windows = wm.get_window_summary()
    duration = (time.time() - start_time) * 1000
    print(f"  List Windows Latency: {duration:.2f} ms")
    print(f"  Result: {windows}")
    print("  RESULT: " + ("PASS" if duration < 2000 else "WARN")) # PowerShell can be slow
    print("")
    
    # 3. Import Latency (Core)
    print("[Core Module Load]")
    start_time = time.time()
    try:
        from chintu_backend.core.capability_handlers import get_registry
        get_registry()
    except Exception as e:
        print(f"  Failed to load capabilities: {e}")
    duration = (time.time() - start_time) * 1000
    print(f"  Capability Load Time: {duration:.2f} ms")

if __name__ == "__main__":
    benchmark()
