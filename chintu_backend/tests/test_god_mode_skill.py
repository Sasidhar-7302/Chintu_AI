import os
import sys
from pathlib import Path
import json

# Add project root to sys.path
root = Path(__file__).parent.parent.parent
sys.path.append(str(root))

from chintu_backend.automation.skills.skill_proposals import create_proposal, approve_proposal, list_proposals
from chintu_backend.core.capabilities import get_registry
from chintu_backend.automation.skills.skill_registry import SkillRegistry
from chintu_backend.core.config import get_config

def test_god_mode_skill():
    config = get_config()
    config.skills_enabled = True
    config.skills_allow_shell = True
    config.skills_test_enabled = False
    os.environ["CHINTU_SKILLS_ALLOW_SHELL"] = "true"
    
    # 1. Create a God Mode Proposal
    content = """---
name: God Mode Test Skill
description: A skill that uses an autonomous python handler
triggers: god test, run god test
args: name
command: python {SKILL_DIR}/handlers/god_handler.py name={name}
---
# God Mode Test
This skill was created autonomously.

<!-- ASSOCIATED_FILE: god_handler.py -->
```python
import sys
import argparse

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--name', default='World')
    args = parser.parse_args()
    print(f"GOD MODE ACTIVE: Hello {args.name}")

if __name__ == "__main__":
    main()
```
"""
    print("Creating God Mode proposal...")
    proposal = create_proposal(content, source="test_god_mode", reason="End-to-end verification")
    print(f"Proposal Created: {proposal.id}")
    
    # 2. Approve Proposal
    print("\nApproving proposal...")
    approved = approve_proposal(proposal.id)
    print(f"Approval Result status: {approved.status}")
    
    if approved.status != "approved":
        print(f"Approval failed: {approved.issues}")
        return

    # 3. Verify handler file exists
    handler_path = Path(config.skills_learned_dir) / "handlers" / "god_handler.py"
    if handler_path.exists():
        print(f"Verified: Handler deployed to {handler_path}")
    else:
        print(f"Error: Handler NOT deployed to {handler_path}")
        return

    # 4. Reload Registry and Run
    print("\nReloading Skill Registry...")
    registry = get_registry()
    skill_registry = SkillRegistry()
    sources = [
        (config.skills_bundled_dir, "bundled"),
        (config.skills_learned_dir, "learned"),
        (config.skills_user_dir, "user"),
        (config.skills_dir, "workspace"),
    ]
    sources = [(Path(path), label) for path, label in sources if path]
    skill_registry.load_sources(sources)
    skill_registry.register_capabilities(registry)
    
    print("\nRunning Test Skill...")
    cap = registry.get("skill::god-mode-test-skill")
    if cap:
        res = cap.handler("run god test name=Antigravity", {"_confirmed": True})
        print(f"Execution Result: {res.message}")
    else:
        print("Error: Skill not found in registry after reload.")

if __name__ == "__main__":
    test_god_mode_skill()
