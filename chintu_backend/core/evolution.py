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
            if os.path.exists(abs_path):
                with open(abs_path, "r", encoding="utf-8") as f:
                    old_content = f.read()
            else:
                old_content = "" # New file creation
                
            # Generate Git-compatible Diff
            diff = difflib.unified_diff(
                old_content.splitlines(),
                new_content.splitlines(),
                fromfile=f"a/{file_path}",
                tofile=f"b/{file_path}",
                lineterm=""
            )
            diff_list = list(diff)
            if not diff_list:
                return "No changes detected."
            
            diff_text = "\n".join(diff_list) + "\n"
            
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
        Apply a previously proposed patch using git apply.
        WARNING: This modifies source code!
        """
        import subprocess
        
        proposal_path = os.path.join(self.root_dir, "brain_md", "evolution", f"{patch_id}.patch")
        if not os.path.exists(proposal_path):
            logger.error(f"Patch file not found: {proposal_path}")
            return False
            
        try:
            # We use git apply --ignore-space-change --ignore-whitespace
            # First, check if the patch can be applied
            check_cmd = ["git", "apply", "--check", proposal_path]
            result = subprocess.run(check_cmd, capture_output=True, text=True, cwd=self.root_dir)
            
            if result.returncode != 0:
                logger.error(f"Patch check failed for {patch_id}: {result.stderr}")
                return False
                
            # Actually apply the patch
            apply_cmd = ["git", "apply", proposal_path]
            result = subprocess.run(apply_cmd, capture_output=True, text=True, cwd=self.root_dir)
            
            if result.returncode == 0:
                logger.info(f"🧬 Evolution Patch Applied: {patch_id}")
                return True
            else:
                logger.error(f"Failed to apply patch {patch_id}: {result.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Error applying patch {patch_id}: {e}")
            return False

# Global
_evolution = None

def get_evolution_manager() -> EvolutionManager:
    global _evolution
    if not _evolution:
        _evolution = EvolutionManager()
    return _evolution
