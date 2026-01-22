"""
Self-Coding Agent - Allows Chintu to debug and modify its own code.
Implements a safe "propose -> review -> apply" workflow.
"""

import logging
import os
import uuid
import asyncio
import difflib
from typing import Dict, Any, List, Optional
from pathlib import Path

from ..core.capabilities import ActionResult
from ..core.events import get_event_bus, EventType, Event
from ..core.websocket_server import get_ws_server
from ..llm.ollama_client import OllamaClient
from ..files.file_manager import FileManager

logger = logging.getLogger(__name__)

class CodingAgent:
    """
    Agent responsible for analyzing codebase and proposing changes.
    """
    
    def __init__(self, llm_client: OllamaClient):
        self.llm = llm_client
        self.file_manager = FileManager()
        self.project_root = Path(os.getcwd())
        self._pending_approvals: Dict[str, asyncio.Future] = {}
        
        # Subscribe to approval responses
        get_event_bus().subscribe(EventType.CODE_APPROVAL_RESPONSE, self._handle_approval_response, is_async=True)
        
    async def _handle_approval_response(self, event: Event):
        """Handle approval response from UI."""
        data = event.data
        request_id = data.get("request_id")
        approved = data.get("approved", False)
        
        if request_id in self._pending_approvals:
            future = self._pending_approvals.pop(request_id)
            if not future.done():
                future.set_result(approved)

    def analyze_issue(self, issue_description: str) -> str:
        """Analyze a reported issue and suggest files to check."""
        prompt = f"""You are a senior python developer debugging an assistant.
Issue: {issue_description}

List 3 most likely files in the project structure that might cause this.
Return ONLY the filenames (relative paths).
"""
        return self.llm.generate(prompt)

    async def propose_fix(self, issue: str, file_path: str) -> Dict[str, Any]:
        """
        Read a file, generate a fix, asking user for approval.
        Returns result dict.
        """
        content = self.file_manager.read_file(file_path)
        if not content:
            return {"error": f"Could not read {file_path}", "success": False}
        
        # 1. Generate Fix with LLM
        prompt = f"""You are fixing a bug in {file_path}.
Issue: {issue}

File Content:
{content}

Return the FULL CORRECTED CONTENT of the function or block that needs changing.
Surround it with ```python blocks.
Do not return the whole file if only a small part changes, but allow context matching.
Ideally return the WHOLE FILE if it's small (<200 lines).
"""
        response = self.llm.generate(prompt)
        
        # Extract code block
        new_content = self._extract_code(response, content)
        if not new_content:
             return {"error": "Failed to generate valid code fix", "success": False}

        # 2. Generate Diff
        diff = difflib.unified_diff(
            content.splitlines(), 
            new_content.splitlines(), 
            fromfile='original', 
            tofile='proposed', 
            lineterm=''
        )
        diff_text = '\n'.join(diff)

        if not diff_text:
             return {"error": "No changes generated", "success": False}

        # 3. Request Approval
        request_id = str(uuid.uuid4())
        future = asyncio.Future()
        self._pending_approvals[request_id] = future
        
        # Send to UI
        ws = get_ws_server()
        if ws:
            await ws.broadcast_message({
                "type": "code_approval_request",
                "request_id": request_id,
                "file": file_path,
                "diff": diff_text
            })
            
            # Wait for User
            try:
                approved = await asyncio.wait_for(future, timeout=300) # 5 min timeout
            except asyncio.TimeoutError:
                self._pending_approvals.pop(request_id, None)
                return {"error": "Approval timed out", "success": False}
                
            if approved:
                # Apply Fix
                success = self.file_manager.write_file(file_path, new_content)
                return {"success": success, "message": "Fix applied successfully" if success else "Failed to write file"}
            else:
                return {"success": False, "message": "User rejected the fix"}
        
        return {"error": "UI not connected", "success": False}

    def _extract_code(self, llm_response: str, original_content: str) -> Optional[str]:
        """Extract code from LLM response. Naive implementation."""
        # Check for ```python blocks
        if "```python" in llm_response:
             parts = llm_response.split("```python")
             if len(parts) > 1:
                 code = parts[1].split("```")[0].strip()
                 return code
        elif "```" in llm_response:
             parts = llm_response.split("```")
             if len(parts) > 1:
                 code = parts[1].strip()
                 return code
        
        # Fallback: if LLM returns just code (rare)
        return None # Safer to fail than overwrite with chat text

# Singleton
_agent: Optional[CodingAgent] = None

def get_coding_agent(llm=None):
    global _agent
    if not _agent and llm:
        _agent = CodingAgent(llm)
    return _agent
