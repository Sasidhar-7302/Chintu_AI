"""
Project Sandbox - Isolated workspaces per project.

Features:
- Per-project workspace directories
- Scoped secrets vault (encrypted)
- Tool allowlist per project
- Environment isolation
- Resource limits and cleanup
"""

import json
import logging
import os
import shutil
import secrets
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Set
from dataclasses import dataclass, field
from enum import Enum
from cryptography.fernet import Fernet
from base64 import urlsafe_b64encode

from chintu_backend.core.config import get_config

logger = logging.getLogger(__name__)


class SandboxStatus(Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


@dataclass
class ProjectConfig:
    """Configuration for a project sandbox."""
    id: str
    name: str
    description: str
    workspace_path: Path
    status: SandboxStatus = SandboxStatus.ACTIVE
    created_at: datetime = field(default_factory=datetime.now)
    
    # Permissions
    allowed_tools: List[str] = field(default_factory=lambda: ["read", "write", "terminal"])
    allowed_domains: List[str] = field(default_factory=list)  # For web access
    max_storage_mb: int = 500
    
    # Metadata
    owner: str = "user"
    tags: List[str] = field(default_factory=list)


@dataclass
class SecretVault:
    """Encrypted secrets storage for a project."""
    project_id: str
    secrets: Dict[str, str] = field(default_factory=dict)  # Stored encrypted
    _cipher: Optional[Fernet] = field(default=None, repr=False)
    
    def __post_init__(self):
        # Generate or load encryption key
        config = get_config()
        key_file = config.data_dir / "vault_keys" / f"{self.project_id}.key"
        
        if key_file.exists():
            key = key_file.read_bytes()
        else:
            key = Fernet.generate_key()
            key_file.parent.mkdir(parents=True, exist_ok=True)
            key_file.write_bytes(key)
        
        self._cipher = Fernet(key)
    
    def set_secret(self, key: str, value: str):
        """Store an encrypted secret."""
        encrypted = self._cipher.encrypt(value.encode()).decode()
        self.secrets[key] = encrypted
    
    def get_secret(self, key: str) -> Optional[str]:
        """Retrieve and decrypt a secret."""
        if key not in self.secrets:
            return None
        try:
            decrypted = self._cipher.decrypt(self.secrets[key].encode())
            return decrypted.decode()
        except Exception:
            return None
    
    def list_keys(self) -> List[str]:
        """List all secret keys (not values)."""
        return list(self.secrets.keys())
    
    def delete_secret(self, key: str) -> bool:
        """Delete a secret."""
        if key in self.secrets:
            del self.secrets[key]
            return True
        return False


class ProjectSandbox:
    """
    Manages isolated project workspaces.
    
    Each project gets:
    - Dedicated workspace directory
    - Encrypted secrets vault
    - Scoped tool permissions
    - Environment isolation
    """
    
    def __init__(self):
        self.config = get_config()
        self.projects_dir = self.config.data_dir / "projects"
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        
        self.projects: Dict[str, ProjectConfig] = {}
        self.vaults: Dict[str, SecretVault] = {}
        
        self._load_projects()
    
    def create_project(
        self,
        name: str,
        description: str = "",
        allowed_tools: List[str] = None,
        tags: List[str] = None
    ) -> ProjectConfig:
        """
        Create a new isolated project workspace.
        
        Args:
            name: Project name
            description: Project description
            allowed_tools: List of allowed tools for this project
            tags: Optional tags for categorization
            
        Returns:
            ProjectConfig for the new project
        """
        import uuid
        project_id = str(uuid.uuid4())[:8]
        
        # Create workspace directory
        workspace = self.projects_dir / project_id
        workspace.mkdir(parents=True, exist_ok=True)
        
        # Create subdirectories
        (workspace / "src").mkdir()
        (workspace / "data").mkdir()
        (workspace / "logs").mkdir()
        (workspace / ".cache").mkdir()
        
        # Default allowed tools
        default_tools = ["read", "write", "terminal", "code", "test"]
        
        config = ProjectConfig(
            id=project_id,
            name=name,
            description=description,
            workspace_path=workspace,
            allowed_tools=allowed_tools or default_tools,
            tags=tags or []
        )
        
        self.projects[project_id] = config
        
        # Create vault
        self.vaults[project_id] = SecretVault(project_id=project_id)
        
        # Save project config
        self._save_project_config(config)
        
        logger.info(f"Created project sandbox: {name} ({project_id})")
        return config
    
    def get_project(self, project_id: str) -> Optional[ProjectConfig]:
        """Get project by ID."""
        return self.projects.get(project_id)
    
    def get_project_by_name(self, name: str) -> Optional[ProjectConfig]:
        """Get project by name."""
        for project in self.projects.values():
            if project.name.lower() == name.lower():
                return project
        return None
    
    def list_projects(self, status: SandboxStatus = None) -> List[ProjectConfig]:
        """List all projects, optionally filtered by status."""
        projects = list(self.projects.values())
        if status:
            projects = [p for p in projects if p.status == status]
        return sorted(projects, key=lambda p: p.created_at, reverse=True)
    
    def update_project(self, project_id: str, **updates) -> bool:
        """Update project configuration."""
        project = self.projects.get(project_id)
        if not project:
            return False
        
        for key, value in updates.items():
            if hasattr(project, key):
                setattr(project, key, value)
        
        self._save_project_config(project)
        return True
    
    def archive_project(self, project_id: str) -> bool:
        """Archive a project (soft delete)."""
        project = self.projects.get(project_id)
        if not project:
            return False
        
        project.status = SandboxStatus.ARCHIVED
        self._save_project_config(project)
        logger.info(f"Archived project: {project.name}")
        return True
    
    def delete_project(self, project_id: str, confirm: bool = False) -> Dict[str, Any]:
        """
        Delete a project and all its data.
        Requires confirmation for safety.
        """
        project = self.projects.get(project_id)
        if not project:
            return {"success": False, "error": "Project not found"}
        
        if not confirm:
            return {
                "success": False,
                "requires_confirmation": True,
                "message": f"This will permanently delete project '{project.name}' and all its data. "
                          f"Total size: {self._get_project_size_mb(project_id):.1f} MB"
            }
        
        try:
            # Remove workspace directory
            if project.workspace_path.exists():
                shutil.rmtree(project.workspace_path)
            
            # Remove vault key
            key_file = self.config.data_dir / "vault_keys" / f"{project_id}.key"
            if key_file.exists():
                key_file.unlink()
            
            # Remove from memory
            self.projects.pop(project_id, None)
            self.vaults.pop(project_id, None)
            
            logger.info(f"Deleted project: {project.name}")
            return {"success": True, "message": f"Deleted project '{project.name}'"}
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # --- Secrets Management ---
    
    def set_secret(self, project_id: str, key: str, value: str) -> bool:
        """Set a secret for a project."""
        vault = self.vaults.get(project_id)
        if not vault:
            return False
        
        vault.set_secret(key, value)
        self._save_vault(project_id)
        logger.info(f"Set secret '{key}' for project {project_id}")
        return True
    
    def get_secret(self, project_id: str, key: str) -> Optional[str]:
        """Get a secret (requires approval in practice)."""
        vault = self.vaults.get(project_id)
        if not vault:
            return None
        return vault.get_secret(key)
    
    def list_secrets(self, project_id: str) -> List[str]:
        """List secret keys (not values) for a project."""
        vault = self.vaults.get(project_id)
        if not vault:
            return []
        return vault.list_keys()
    
    def delete_secret(self, project_id: str, key: str) -> bool:
        """Delete a secret."""
        vault = self.vaults.get(project_id)
        if not vault:
            return False
        
        result = vault.delete_secret(key)
        if result:
            self._save_vault(project_id)
        return result
    
    # --- Tool Access Control ---
    
    def is_tool_allowed(self, project_id: str, tool: str) -> bool:
        """Check if a tool is allowed for this project."""
        project = self.projects.get(project_id)
        if not project:
            return False
        
        # Wildcard 'all' allows everything
        if "all" in project.allowed_tools:
            return True
        
        return tool.lower() in [t.lower() for t in project.allowed_tools]
    
    def add_tool(self, project_id: str, tool: str) -> bool:
        """Add a tool to project's allowed list."""
        project = self.projects.get(project_id)
        if not project:
            return False
        
        if tool not in project.allowed_tools:
            project.allowed_tools.append(tool)
            self._save_project_config(project)
        return True
    
    def remove_tool(self, project_id: str, tool: str) -> bool:
        """Remove a tool from project's allowed list."""
        project = self.projects.get(project_id)
        if not project:
            return False
        
        if tool in project.allowed_tools:
            project.allowed_tools.remove(tool)
            self._save_project_config(project)
        return True
    
    # --- Environment Isolation ---
    
    def get_project_env(self, project_id: str) -> Dict[str, str]:
        """Get environment variables for project execution."""
        project = self.projects.get(project_id)
        vault = self.vaults.get(project_id)
        
        if not project:
            return {}
        
        env = {
            "PROJECT_ID": project_id,
            "PROJECT_NAME": project.name,
            "PROJECT_WORKSPACE": str(project.workspace_path),
            "PROJECT_DATA_DIR": str(project.workspace_path / "data"),
            "PROJECT_LOG_DIR": str(project.workspace_path / "logs"),
        }
        
        # Add decrypted secrets
        if vault:
            for key in vault.list_keys():
                value = vault.get_secret(key)
                if value:
                    env[key] = value
        
        return env
    
    def run_in_sandbox(
        self, 
        project_id: str, 
        command: List[str],
        timeout: int = 60
    ) -> Dict[str, Any]:
        """
        Run a command in the project's isolated environment.
        
        Args:
            command: Command as list of arguments (NOT a shell string)
        """
        from chintu_backend.core.safe_exec import get_safe_executor
        
        project = self.projects.get(project_id)
        if not project:
            return {"success": False, "error": "Project not found"}
        
        if project.status != SandboxStatus.ACTIVE:
            return {"success": False, "error": f"Project is {project.status.value}"}
        
        # Check tool permission
        if not self.is_tool_allowed(project_id, "terminal"):
            return {"success": False, "error": "Terminal access not allowed for this project"}
        
        env = {**os.environ, **self.get_project_env(project_id)}
        executor = get_safe_executor()
        
        result = executor.run(
            command,
            cwd=project.workspace_path,
            env=env,
            timeout=timeout
        )
        
        return {
            "success": result.success,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.return_code,
            "error": result.error
        }
    
    # --- Persistence ---
    
    def _load_projects(self):
        """Load all projects from disk."""
        for project_dir in self.projects_dir.iterdir():
            if project_dir.is_dir():
                config_file = project_dir / "project.json"
                if config_file.exists():
                    try:
                        data = json.loads(config_file.read_text())
                        config = ProjectConfig(
                            id=data["id"],
                            name=data["name"],
                            description=data.get("description", ""),
                            workspace_path=Path(data["workspace_path"]),
                            status=SandboxStatus(data.get("status", "active")),
                            created_at=datetime.fromisoformat(data["created_at"]),
                            allowed_tools=data.get("allowed_tools", []),
                            tags=data.get("tags", [])
                        )
                        self.projects[config.id] = config
                        
                        # Load vault
                        self._load_vault(config.id)
                        
                    except Exception as e:
                        logger.warning(f"Could not load project {project_dir.name}: {e}")
    
    def _save_project_config(self, config: ProjectConfig):
        """Save project configuration to disk."""
        config_file = config.workspace_path / "project.json"
        data = {
            "id": config.id,
            "name": config.name,
            "description": config.description,
            "workspace_path": str(config.workspace_path),
            "status": config.status.value,
            "created_at": config.created_at.isoformat(),
            "allowed_tools": config.allowed_tools,
            "tags": config.tags,
            "owner": config.owner,
            "max_storage_mb": config.max_storage_mb
        }
        config_file.write_text(json.dumps(data, indent=2))
    
    def _load_vault(self, project_id: str):
        """Load vault for a project."""
        vault_file = self.projects_dir / project_id / "vault.json"
        try:
            vault = SecretVault(project_id=project_id)
            if vault_file.exists():
                data = json.loads(vault_file.read_text())
                vault.secrets = data.get("secrets", {})
            self.vaults[project_id] = vault
        except Exception as e:
            logger.warning(f"Could not load vault for {project_id}: {e}")
    
    def _save_vault(self, project_id: str):
        """Save vault to disk."""
        vault = self.vaults.get(project_id)
        project = self.projects.get(project_id)
        if not vault or not project:
            return
        
        vault_file = project.workspace_path / "vault.json"
        data = {"secrets": vault.secrets}
        vault_file.write_text(json.dumps(data, indent=2))
    
    def _get_project_size_mb(self, project_id: str) -> float:
        """Get total size of project workspace in MB."""
        project = self.projects.get(project_id)
        if not project or not project.workspace_path.exists():
            return 0.0
        
        total = 0
        for path in project.workspace_path.rglob("*"):
            if path.is_file():
                total += path.stat().st_size
        
        return total / (1024 * 1024)


# Singleton instance
_sandbox: Optional[ProjectSandbox] = None


def get_project_sandbox() -> ProjectSandbox:
    """Get or create the project sandbox singleton."""
    global _sandbox
    if _sandbox is None:
        _sandbox = ProjectSandbox()
    return _sandbox
