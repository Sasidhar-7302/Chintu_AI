
import sys
import os
import logging
from pathlib import Path

# Setup Path
current_dir = os.getcwd()
sys.path.append(current_dir)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("VerifySwarm")

from chintu_backend.brain.swarm.agents.coder import AutonCoder
from chintu_backend.brain.swarm.agents.coder import AutonCoder
from chintu_backend.brain.swarm.agents.shopper import ShoppingAgent
from chintu_backend.brain.swarm.agents.task_master import TaskMaster
from chintu_backend.brain.swarm.orchestrator import SwarmOrchestrator
from chintu_backend.core.config import get_config
from chintu_backend.core.capability_loader import register_all_capabilities
from chintu_backend.core.capabilities import CapabilityRegistry, get_registry

def test_auton_coder():
    print("\n=== Testing AutonCoder ===")
    
    # Initialize
    coder = AutonCoder()
    if not coder.llm:
         print("WARN: No LLM found (Ollama/Groq). Checks might fail or mock needed.")
         # Inject a mock for testing if no LLM is actually live
         class MockLLM:
             def chat(self, prompt):
                 if "Fix this" in prompt: return "print('Fixed Hello World')"
                 return '```json\n{ "filename": "swarm_test.py", "content": "print(\'Hello Swarm\')" }\n```'
         coder.llm = MockLLM()
         print("INFO: Injected Mock LLM for safety.")

    # Goal
    goal = "Create a python script that prints 'Hello Swarm' named swarm_test.py"
    
    # Run
    result = coder.run(goal)
    print(f"Result: {result}")
    
    if result.get("success"):
        path = Path(result["path"])
        if path.exists():
            content = path.read_text("utf-8")
            print(f"File Content: {content}")
            if "print" in content:
                print("PASS: Coder generated and wrote file.")
            else:
                print("FAIL: Content incorrect.")
        else:
             print("FAIL: File not created.")
    else:
        print(f"FAIL: Agent returned error: {result.get('error')}")

def test_orchestrator():
    print("\n=== Testing Orchestrator ===")
    orch = SwarmOrchestrator()
    
    # Inject Mock LLM for Plan
    class MockLLM:
        def chat(self, prompt):
             return '```json\n[ {"agent": "AutonCoder", "task": "Write a script"} ]\n```'
    orch.llm = MockLLM()
    
    # Register Mock Agent
    class MockCoder(AutonCoder):
        def run(self, goal, context=None):
            return "Simulated Code Created"
            
    orch.register_agent(MockCoder())
    
    res = orch.run("Build a small script")
    print(f"Result: {res}")
    
    if res["success"] and res["results"][0]["status"] == "completed":
        print("PASS: Orchestrator delegated task.")
    else:
        print("FAIL: Orchestrator failed.")

def test_shopper():
    print("\n=== Testing ShoppingAgent ===")
    shopper = ShoppingAgent()
    
    # Mock Browser Logic for reliability
    class MockBrowser:
        def search(self, query):
             print(f"Mock Search: {query}")
             return [
                 {"title": "Cheap Mouse", "link": "http://cheap.com", "price": "$10"},
                 {"title": "Pro Mouse", "link": "http://pro.com", "price": "$100"},
                 {"title": "Best Value Mouse", "link": "http://value.com", "price": "$45"}
             ]
        def navigate(self, url):
             print(f"Mock Visit: {url}")
             if "value" in url: return "Best Value Mouse. 16000 DPI. Price: $45."
             return "Product details..."
        def extract_price(self, content):
             return "$45" if "45" in content else "$10"
             
    shopper.browser = MockBrowser()
    
    # Mock LLM
    class MockLLM:
        def chat(self, prompt): return "Best Value Mouse because it is under $50."
    shopper.llm = MockLLM()
    
    res = shopper.run("Buy a gaming mouse under $50")
    print(f"Result: {res}")
    
    if res["success"] and "Best Value Mouse" in str(res["picked"]):
         print("PASS: Shopper picked the correct item.")
    else:
         print("FAIL: Shopper logic failed.")

def test_task_master():
    print("\n=== Testing TaskMaster ===")
    tm = TaskMaster()
    # Use test db to avoid polluting main
    tm.db_path = Path("data_test/tasks_test.db")
    tm._init_db()
    
    # 1. Add
    res1 = tm.run("Add task Buy Milk")
    print(f"Add: {res1}")
    if not res1["success"]: print("FAIL: Add task failed"); return

    # 2. List
    res2 = tm.run("List tasks")
    print(f"List: {res2}")
    has_milk = any("Buy Milk" in t["title"] for t in res2["tasks"])
    if not has_milk: print("FAIL: Task not listed"); return

    # 3. Complete
    res3 = tm.run("Complete Buy Milk")
    print(f"Complete: {res3}")
    
    # 4. Verify
    res4 = tm.run("List tasks")
    still_has_milk = any("Buy Milk" in t["title"] for t in res4["tasks"])
    if not still_has_milk:
        print("PASS: Task lifecycle managed.")
    else:
        print("FAIL: Task not marked completed.")

def test_integration():
    print("\n=== Testing Integration (Capability Registration) ===")
    registry = get_registry()
    config = get_config()
    
    # Run loader
    register_all_capabilities(registry, config)
    
    # Check
    caps = registry.list_capabilities()
    # It might return list or dict. Let's check keys if dict or iterate if list.
    found = False
    
    # Depending on implementation, registry might store by name or dict
    # Assuming list_capabilities() returns list of dicts or names
    # Let's inspect
    
    # Simpler check: registry.get('autonomous_swarm')
    cap = registry.get('autonomous_swarm')
    if cap:
        print(f"PASS: Capability 'autonomous_swarm' registered. Handler: {cap.handler}")
    else:
        print("FAIL: Capability 'autonomous_swarm' NOT found.")

if __name__ == "__main__":
    # test_auton_coder()
    # test_shopper()
    # test_task_master()
    # test_orchestrator()
    test_integration()
