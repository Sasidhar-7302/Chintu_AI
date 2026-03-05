"""
Self-Modification Protocol - Safe code changes with approval flow.

Workflow: Propose → Diff → Test → Approve → Apply

Features:
- Generate code changes using LLM
- Validate syntax before applying
- Run tests to verify changes
- Require user approval via A2UI
- Rollback mechanism if tests fail
- Audit log of all modifications
"""

import difflib
import hashlib
import json
import logging
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from enum import Enum

from chintu_backend.core.config import get_config
from chintu_backend.core.events import get_event_bus, Event, EventType

logger = logging.getLogger(__name__)


class ModificationType(Enum):
    CREATE = "create"
    MODIFY = "modify"
    DELETE = "delete"


@dataclass
class CodeChange:
    """Represents a proposed code change."""
    id: str
    file_path: str
    modification_type: ModificationType
    description: str
    original_content: str
    new_content: str
    diff: str
    created_at: datetime = field(default_factory=datetime.now)
    approved: bool = False
    applied: bool = False
    test_passed: Optional[bool] = None
    error: Optional[str] = None


@dataclass
class AuditEntry:
    """Audit log entry for code modifications."""
    change_id: str
    timestamp: datetime
    action: str  # proposed, approved, rejected, applied, rolled_back
    file_path: str
    user: str
    details: Dict[str, Any] = field(default_factory=dict)


class SelfModifier:
    """
    Manages safe self-modification of Chintu's code.
    
    All changes go through:
    1. Propose: Generate change using LLM
    2. Validate: Check syntax
    3. Test: Run relevant tests
    4. Approve: Request user approval
    5. Apply: Write changes
    6. Verify: Confirm working
    """
    
    def __init__(self, project_root: Path = None):
        self.project_root = project_root or Path.cwd()
        self.config = get_config()
        self.event_bus = get_event_bus()
        
        # Storage
        self.pending_changes: Dict[str, CodeChange] = {}
        self.audit_log: List[AuditEntry] = []
        self.backups: Dict[str, Tuple[str, str]] = {}  # change_id -> (path, backup_path)
        
        # Backup directory
        self.backup_dir = self.config.data_dir / "code_backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        
        # Audit log file
        self.audit_file = self.config.data_dir / "self_mod_audit.json"
        self._load_audit()
    
    def propose_change(
        self,
        file_path: str,
        description: str,
        context: str = ""
    ) -> CodeChange:
        """
        Propose a code change using LLM.
        
        Args:
            file_path: Path to file to modify (relative to project root)
            description: What change to make
            context: Additional context for the LLM
            
        Returns:
            CodeChange object with diff
        """
        import uuid
        change_id = str(uuid.uuid4())[:8]
        
        full_path = self.project_root / file_path
        
        # Read current content
        if full_path.exists():
            original_content = full_path.read_text(encoding='utf-8')
            mod_type = ModificationType.MODIFY
        else:
            original_content = ""
            mod_type = ModificationType.CREATE
        
        # Generate new content using LLM
        new_content = self._generate_change(
            file_path=file_path,
            original_content=original_content,
            description=description,
            context=context
        )
        
        # Generate diff
        diff = self._generate_diff(original_content, new_content, file_path)
        
        change = CodeChange(
            id=change_id,
            file_path=file_path,
            modification_type=mod_type,
            description=description,
            original_content=original_content,
            new_content=new_content,
            diff=diff
        )
        
        self.pending_changes[change_id] = change
        self._audit("proposed", change)
        
        logger.info(f"Proposed change {change_id}: {description}")
        return change
    
    def validate_change(self, change_id: str) -> Tuple[bool, str]:
        """
        Validate a proposed change (syntax check).
        
        Returns:
            (is_valid, error_message)
        """
        change = self.pending_changes.get(change_id)
        if not change:
            return False, "Change not found"
        
        # Python syntax check
        if change.file_path.endswith('.py'):
            try:
                compile(change.new_content, change.file_path, 'exec')
                return True, ""
            except SyntaxError as e:
                error = f"Syntax error: {e}"
                change.error = error
                return False, error
        
        # For other files, assume valid
        return True, ""
    
    def test_change(self, change_id: str, test_command: str = None) -> Tuple[bool, str]:
        """
        Test a proposed change by temporarily applying and running tests.
        
        Returns:
            (tests_passed, output)
        """
        change = self.pending_changes.get(change_id)
        if not change:
            return False, "Change not found"
        
        full_path = self.project_root / change.file_path
        
        # Create backup
        backup_path = None
        if full_path.exists():
            backup_path = self._create_backup(change_id, full_path)
        
        try:
            # Temporarily apply change
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(change.new_content, encoding='utf-8')
            
            # Run tests
            if test_command:
                from chintu_backend.core.safe_exec import get_safe_executor
                executor = get_safe_executor()
                
                # test_command should be a list like ["pytest", "tests/"]
                if isinstance(test_command, str):
                    test_command = test_command.split()
                
                result = executor.run(
                    test_command,
                    cwd=self.project_root,
                    timeout=60
                )
                
                change.test_passed = result.success
                output = result.stdout + result.stderr
                
            else:
                # Default: try importing if Python
                if change.file_path.endswith('.py'):
                    try:
                        # Quick import test
                        exec(compile(change.new_content, change.file_path, 'exec'))
                        change.test_passed = True
                        output = "Import test passed"
                    except Exception as e:
                        change.test_passed = False
                        output = f"Import failed: {e}"
                else:
                    change.test_passed = True
                    output = "No tests defined"
            
            return change.test_passed, output
            
        except subprocess.TimeoutExpired:
            change.test_passed = False
            return False, "Test timed out"
            
        except Exception as e:
            change.test_passed = False
            return False, str(e)
            
        finally:
            # Restore original if we have a backup
            if backup_path and Path(backup_path).exists():
                shutil.copy2(backup_path, full_path)
    
    def request_approval(self, change_id: str) -> Dict[str, Any]:
        """
        Request user approval for a change via A2UI.
        
        Returns approval request data.
        """
        change = self.pending_changes.get(change_id)
        if not change:
            return {"success": False, "error": "Change not found"}
        
        # Emit approval request event
        approval_request = {
            "type": "code_change",
            "change_id": change_id,
            "file": change.file_path,
            "description": change.description,
            "diff": change.diff,
            "modification_type": change.modification_type.value,
            "test_passed": change.test_passed,
        }
        
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self.event_bus.publish(Event(
                    type=EventType.CODE_APPROVAL_REQUEST,
                    data=approval_request
                )))
            else:
                loop.run_until_complete(self.event_bus.publish(Event(
                    type=EventType.CODE_APPROVAL_REQUEST,
                    data=approval_request
                )))
        except Exception as e:
            logger.warning(f"Could not emit approval event: {e}")
        
        return {"success": True, "request": approval_request}
    
    def approve(self, change_id: str, user: str = "user") -> bool:
        """Mark a change as approved."""
        change = self.pending_changes.get(change_id)
        if not change:
            return False
        
        change.approved = True
        self._audit("approved", change, user=user)
        logger.info(f"Change {change_id} approved by {user}")
        return True
    
    def reject(self, change_id: str, user: str = "user", reason: str = "") -> bool:
        """Reject a proposed change."""
        change = self.pending_changes.pop(change_id, None)
        if not change:
            return False
        
        self._audit("rejected", change, user=user, details={"reason": reason})
        logger.info(f"Change {change_id} rejected by {user}: {reason}")
        return True
    
    def apply(self, change_id: str) -> Tuple[bool, str]:
        """
        Apply an approved change.
        
        Returns:
            (success, message)
        """
        change = self.pending_changes.get(change_id)
        if not change:
            return False, "Change not found"
        
        if not change.approved:
            return False, "Change not approved"
        
        full_path = self.project_root / change.file_path
        
        # Create backup before applying
        if full_path.exists():
            self._create_backup(change_id, full_path)
        
        try:
            # Apply change
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(change.new_content, encoding='utf-8')
            
            change.applied = True
            self._audit("applied", change)
            
            logger.info(f"Applied change {change_id} to {change.file_path}")
            return True, "Change applied successfully"
            
        except Exception as e:
            error = f"Failed to apply: {e}"
            change.error = error
            self._audit("failed", change, details={"error": error})
            return False, error
    
    def rollback(self, change_id: str) -> Tuple[bool, str]:
        """
        Rollback an applied change.
        
        Returns:
            (success, message)
        """
        if change_id not in self.backups:
            return False, "No backup found"
        
        file_path, backup_path = self.backups[change_id]
        
        try:
            shutil.copy2(backup_path, file_path)
            
            change = self.pending_changes.get(change_id)
            if change:
                self._audit("rolled_back", change)
            
            logger.info(f"Rolled back change {change_id}")
            return True, "Rollback successful"
            
        except Exception as e:
            return False, f"Rollback failed: {e}"
    
    def _generate_change(
        self,
        file_path: str,
        original_content: str,
        description: str,
        context: str
    ) -> str:
        """Use LLM to generate new file content."""
        try:
            from chintu_backend.brain.llm.ollama_client import OllamaClient
            
            llm = OllamaClient(
                host=getattr(self.config, 'ollama_host', 'http://localhost:11434'),
                model=getattr(self.config, 'ollama_model', 'qwen2.5-coder:7b')
            )
            
            if original_content:
                prompt = f"""Modify this file to: {description}

FILE: {file_path}
CURRENT CONTENT:
```
{original_content}
```

{f'CONTEXT: {context}' if context else ''}

Output ONLY the complete new file content, no explanations."""
            else:
                prompt = f"""Create a new file: {description}

FILE: {file_path}
{f'CONTEXT: {context}' if context else ''}

Output ONLY the complete file content, no explanations."""
            
            response = llm.generate(prompt) if hasattr(llm, 'generate') else llm.chat(prompt)
            
            # Clean up response
            content = response
            if "```" in content:
                # Extract code block
                parts = content.split("```")
                if len(parts) >= 3:
                    content = parts[1]
                    if content.startswith(('python', 'json', 'yaml', 'javascript')):
                        content = '\n'.join(content.split('\n')[1:])
            
            return content.strip()
            
        except Exception as e:
            logger.error(f"Failed to generate change: {e}")
            return original_content
    
    def _generate_diff(self, original: str, new: str, file_path: str) -> str:
        """Generate unified diff."""
        original_lines = original.splitlines(keepends=True)
        new_lines = new.splitlines(keepends=True)
        
        diff = difflib.unified_diff(
            original_lines,
            new_lines,
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}"
        )
        
        return ''.join(diff)
    
    def _create_backup(self, change_id: str, file_path: Path) -> str:
        """Create backup of a file."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{file_path.name}.{timestamp}.bak"
        backup_path = self.backup_dir / backup_name
        
        shutil.copy2(file_path, backup_path)
        self.backups[change_id] = (str(file_path), str(backup_path))
        
        return str(backup_path)
    
    def _audit(
        self,
        action: str,
        change: CodeChange,
        user: str = "system",
        details: Dict = None
    ):
        """Add entry to audit log."""
        entry = AuditEntry(
            change_id=change.id,
            timestamp=datetime.now(),
            action=action,
            file_path=change.file_path,
            user=user,
            details=details or {}
        )
        self.audit_log.append(entry)
        self._save_audit()
    
    def _load_audit(self):
        """Load audit log from file."""
        if self.audit_file.exists():
            try:
                data = json.loads(self.audit_file.read_text())
                self.audit_log = [
                    AuditEntry(
                        change_id=e["change_id"],
                        timestamp=datetime.fromisoformat(e["timestamp"]),
                        action=e["action"],
                        file_path=e["file_path"],
                        user=e["user"],
                        details=e.get("details", {})
                    )
                    for e in data
                ]
            except Exception as e:
                logger.warning(f"Could not load audit log: {e}")
    
    def _save_audit(self):
        """Save audit log to file."""
        try:
            data = [
                {
                    "change_id": e.change_id,
                    "timestamp": e.timestamp.isoformat(),
                    "action": e.action,
                    "file_path": e.file_path,
                    "user": e.user,
                    "details": e.details
                }
                for e in self.audit_log[-1000:]  # Keep last 1000 entries
            ]
            self.audit_file.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.warning(f"Could not save audit log: {e}")
    
    def get_pending_changes(self) -> List[Dict[str, Any]]:
        """Get all pending changes."""
        return [
            {
                "id": c.id,
                "file": c.file_path,
                "description": c.description,
                "type": c.modification_type.value,
                "approved": c.approved,
                "test_passed": c.test_passed
            }
            for c in self.pending_changes.values()
        ]
    
    def get_audit_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent audit entries."""
        return [
            {
                "change_id": e.change_id,
                "timestamp": e.timestamp.isoformat(),
                "action": e.action,
                "file": e.file_path,
                "user": e.user
            }
            for e in self.audit_log[-limit:]
        ]


# Singleton instance
_self_modifier: Optional[SelfModifier] = None


def get_self_modifier(project_root: Path = None) -> SelfModifier:
    """Get or create the self-modifier singleton."""
    global _self_modifier
    if _self_modifier is None:
        _self_modifier = SelfModifier(project_root)
    return _self_modifier
