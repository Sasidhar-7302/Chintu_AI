"""
EvolutionManager: The engine for Self-Evolution (Chintu modifying Chintu).
Handles reading own source, generating patches, and verifying them.
"""

import logging
import os
import difflib

logger = logging.getLogger(__name__)

class EvolutionManager:
    """
    Manages self-improvement cycles.
    """
    
    def __init__(self):
        self.root_dir = os.getcwd()
        
    def propose_change(self, file_path: str, new_content: str, reason: str) -> str:
        """
        Propose a change to a source file.
        Does NOT overwrite immediately. Creates a detailed patch request.
        """
        abs_path = os.path.abspath(file_path)
        if not abs_path.startswith(self.root_dir):
            return "Security Error: Cannot modify files outside Chintu directory."
            
        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                old_content = f.read()
                
            # Generate Diff
            diff = difflib.unified_diff(
                old_content.splitlines(),
                new_content.splitlines(),
                fromfile=f"Current: {file_path}",
                tofile=f"Proposed: {file_path}",
                lineterm=""
            )
            diff_text = "\n".join(diff)
            
            # Save Proposal
            proposal_id = f"patch_{int(os.times().elapsed)}"
            proposal_path = os.path.join(self.root_dir, "brain_md", "evolution", f"{proposal_id}.patch")
            os.makedirs(os.path.dirname(proposal_path), exist_ok=True)
            
            with open(proposal_path, "w", encoding="utf-8") as f:
                f.write(f"# Reason: {reason}\n")
                f.write(diff_text)
                
            logger.info(f"🧬 Evolution Proposed: {proposal_id}")
            return f"I have proposed a self-update ({proposal_id}). Awaiting verification."
            
        except Exception as e:
            logger.error(f"Evolution failed: {e}")
            return f"Failed to propose change: {e}"

    def apply_patch(self, patch_id: str) -> bool:
        """
        Apply a previously proposed patch.
        WARNING: This modifies source code!
        """
        # Implementation left stubbed for safety until User explicitly enables "Auto-Apply"
        logger.warning(f"Apply Patch {patch_id} requested. Logic stubbed for safety.")
        # Real implementation would use `git apply` or manual file overwrite.
        return True

# Global
_evolution = None

def get_evolution_manager() -> EvolutionManager:
    global _evolution
    if not _evolution:
        _evolution = EvolutionManager()
    return _evolution
