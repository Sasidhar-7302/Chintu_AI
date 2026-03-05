"""
Self-Coding Agent - Allows Chintu to debug and modify its own code.
Implements a safe "propose -> review -> apply" workflow.
"""

import logging
import os
import uuid
import asyncio
import difflib
import shutil
import tempfile
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path

from ..core.capabilities import ActionResult
from ..core.events import get_event_bus, EventType, Event
from ..core.websocket_server import get_ws_server
from ..brain.llm.ollama_client import OllamaClient
from ..files.file_manager import FileManager
from ..sandbox import SandboxExecutor

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

    async def propose_fix(
        self,
        issue: str,
        file_path: str,
        test_command: Optional[str] = None,
        max_retries: int = 3,
        run_tests: bool = True,
    ) -> Dict[str, Any]:
        """
        Read a file, generate a fix, asking user for approval.
        Returns result dict.
        """
        content = self.file_manager.read_file(file_path)
        if not content:
            return {"error": f"Could not read {file_path}", "success": False}
        test_command = test_command or "python -m pytest -q"

        new_content, test_result = self._reflexion_loop(
            issue=issue,
            file_path=file_path,
            original_content=content,
            test_command=test_command if run_tests else None,
            max_retries=max_retries,
        )

        if not new_content:
            error_msg = "Failed to generate valid code fix"
            if test_result:
                error_msg = f"{error_msg}. Last error: {test_result}"
            return {"error": error_msg, "success": False}

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
            # Also render an A2UI approval view (future-proof UI protocol).
            try:
                from ..ui import get_a2ui_service

                get_a2ui_service().render_code_approval(
                    request_id=request_id,
                    file_path=file_path,
                    diff_text=diff_text,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("A2UI code approval render failed: %s", exc)
            # Emit a structured notification for remote gateways (Telegram, etc.).
            try:
                preview_lines = diff_text.splitlines()[:80]
                diff_preview = "\n".join(preview_lines)[:4000]
                get_event_bus().publish_sync(
                    Event(
                        type=EventType.NOTIFICATION,
                        source="coding_agent",
                        data={
                            "category": "code_approval",
                            "severity": "high",
                            "title": f"Code Approval Needed: {Path(file_path).name}",
                            "message": "Chintu proposed a code change that needs approval.",
                            "metadata": {
                                "request_id": request_id,
                                "file_path": file_path,
                                "diff_preview": diff_preview,
                            },
                        },
                    )
                )
            except Exception:
                pass
            
            # Wait for User
            try:
                approved = await asyncio.wait_for(future, timeout=300) # 5 min timeout
            except asyncio.TimeoutError:
                self._pending_approvals.pop(request_id, None)
                return {"error": "Approval timed out", "success": False}
                
            if approved:
                # Apply Fix
                success = self.file_manager.write_file(file_path, new_content)
                message = "Fix applied successfully" if success else "Failed to write file"
                if success and test_result and run_tests:
                    message += f"\n\nSandbox tests passed: {test_command}"
                if success:
                    try:
                        from .change_journal import record_change, maybe_git_commit
                        from ..core.config import get_config
                        config = get_config()
                        record_change(request_id, file_path, issue, diff_text, applied=True)
                        commit_msg = str(getattr(config, "coding_agent_commit_message", "chintu: {file} {issue}"))
                        commit_msg = commit_msg.format(file=Path(file_path).name, issue=issue[:80] if issue else "")
                        committed, info = maybe_git_commit(file_path, commit_msg)
                        if committed:
                            message += f"\n\nGit commit: {info}"
                        else:
                            message += f"\n\nChange recorded for review."
                    except Exception:
                        message += f"\n\nChange recorded for review."
                return {"success": success, "message": message}
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

    def _reflexion_loop(
        self,
        issue: str,
        file_path: str,
        original_content: str,
        test_command: Optional[str],
        max_retries: int,
    ) -> Tuple[Optional[str], Optional[str]]:
        last_error = None
        error_context = ""

        for attempt in range(1, max_retries + 1):
            prompt = self._build_fix_prompt(
                issue=issue,
                file_path=file_path,
                content=original_content,
                error_context=error_context,
                attempt=attempt,
            )
            response = self.llm.generate(prompt)
            new_content = self._extract_code(response, original_content)
            if not new_content:
                last_error = "Failed to extract code block"
                error_context = last_error
                continue

            if test_command:
                test_ok, test_error = self._run_tests_in_sandbox(
                    file_path=file_path,
                    new_content=new_content,
                    test_command=test_command,
                )
                if not test_ok:
                    last_error = test_error or "Tests failed"
                    error_context = last_error
                    continue

            return new_content, None if test_command is None else "ok"

        return None, last_error

    def _build_fix_prompt(
        self,
        issue: str,
        file_path: str,
        content: str,
        error_context: str,
        attempt: int,
    ) -> str:
        extra = f"\nPrevious error:\n{error_context}\n" if error_context else ""
        return f"""You are fixing a bug in {file_path}.
Issue: {issue}
Attempt: {attempt}{extra}

File Content:
{content}

Return the FULL CORRECTED CONTENT of the function or block that needs changing.
Surround it with ```python blocks.
Do not return the whole file if only a small part changes, but allow context matching.
Ideally return the WHOLE FILE if it's small (<200 lines).
"""

    def _run_tests_in_sandbox(
        self,
        file_path: str,
        new_content: str,
        test_command: str,
    ) -> Tuple[bool, Optional[str]]:
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_root = Path(temp_dir)
                self._copy_repo(temp_root)
                target = self._resolve_in_workspace(temp_root, file_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(new_content, encoding="utf-8")

                executor = SandboxExecutor()
                result = executor.run(
                    command=test_command,
                    workspace_dir=str(temp_root),
                )
                if result.exit_code == 0:
                    return True, None
                error = result.stderr.strip() or result.stdout.strip()
                return False, error or "Sandbox tests failed"
        except Exception as exc:
            return False, str(exc)

    def _copy_repo(self, destination: Path) -> None:
        ignore = shutil.ignore_patterns(
            ".git",
            "venv",
            ".venv",
            "__pycache__",
            "logs",
            "memory_store",
            ".chintu",
            "chintu_ui/build",
            "chintu_mobile/build",
            "*.pyc",
            "*.log",
        )
        shutil.copytree(self.project_root, destination, dirs_exist_ok=True, ignore=ignore)

    def _resolve_in_workspace(self, workspace: Path, file_path: str) -> Path:
        target = Path(file_path)
        if target.is_absolute():
            try:
                relative = target.relative_to(self.project_root)
                return workspace / relative
            except ValueError:
                return workspace / target.name
        return workspace / target

# Singleton
_agent: Optional[CodingAgent] = None

def get_coding_agent(llm=None):
    global _agent
    if not _agent and llm:
        _agent = CodingAgent(llm)
    return _agent
