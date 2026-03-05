"""
Ops Agent - Deployment, Infrastructure, and Monitoring.

Handles:
- Deployment to Vercel/Fly.io/Railway
- Secrets management (with approval gates)
- Health monitoring and error detection
- Rollback on failures
"""

import asyncio
import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from enum import Enum

from chintu_backend.brain.swarm.base_agent import BaseAgent, AgentState
from chintu_backend.swarm.agent_runtime import create_agent_runtime
from chintu_backend.core.config import get_config
from chintu_backend.core.events import get_event_bus, Event, EventType
from chintu_backend.core.safe_exec import get_safe_executor, SafeExecutor

logger = logging.getLogger(__name__)


class DeploymentPlatform(Enum):
    VERCEL = "vercel"
    FLY = "fly"
    RAILWAY = "railway"
    NETLIFY = "netlify"
    RENDER = "render"


class DeploymentStatus(Enum):
    PENDING = "pending"
    BUILDING = "building"
    DEPLOYING = "deploying"
    DEPLOYED = "deployed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


@dataclass
class DeploymentRecord:
    """Record of a deployment."""
    id: str
    platform: DeploymentPlatform
    project_name: str
    url: Optional[str]
    status: DeploymentStatus
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    logs: List[str] = field(default_factory=list)
    error: Optional[str] = None
    rollback_to: Optional[str] = None  # Previous deployment ID


@dataclass
class SecretEntry:
    """A secret/credential entry."""
    key: str
    description: str
    required: bool = True
    provided: bool = False
    # Value stored encrypted, not in memory


class OpsAgent(BaseAgent):
    """
    Operations agent for deployment and infrastructure management.
    
    Features:
    - Deploy to Vercel/Fly.io/Railway
    - Manage secrets with approval gates
    - Monitor deployment health
    - Rollback on failures
    """
    
    def __init__(self):
        super().__init__(
            name="Ops",
            description="DevOps - deploy, monitor, manage infrastructure"
        )
        try:
            runtime = create_agent_runtime("ops")
            self.attach_runtime(runtime)
        except Exception:
            pass
        
        self.config = get_config()
        self.event_bus = get_event_bus()
        self.executor = get_safe_executor()
        self.deployments: Dict[str, DeploymentRecord] = {}
        self.secrets_pending: Dict[str, SecretEntry] = {}
        
        # Deployment history file
        self.history_file = self.config.data_dir / "deployment_history.json"
        self._load_history()
    
    def run(self, goal: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute ops task based on goal."""
        self.update_state(AgentState.EXECUTING)
        self.log_step("Starting", f"Goal: {goal}")
        
        goal_lower = goal.lower()
        
        # Detect intent
        if any(kw in goal_lower for kw in ["deploy", "ship", "push", "release"]):
            return self._handle_deploy(goal, context or {})
        elif any(kw in goal_lower for kw in ["rollback", "revert"]):
            return self._handle_rollback(goal, context or {})
        elif any(kw in goal_lower for kw in ["status", "health", "monitor"]):
            return self._handle_status(goal, context or {})
        elif any(kw in goal_lower for kw in ["secret", "credential", "env", "api key"]):
            return self._handle_secrets(goal, context or {})
        else:
            return self._handle_generic_ops(goal, context or {})
    
    def _handle_deploy(self, goal: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Handle deployment requests."""
        self.log_step("Deploy", "Analyzing deployment requirements")
        
        # Detect platform
        platform = self._detect_platform(goal, context)
        project_path = context.get("project_path", Path.cwd())
        project_name = context.get("project_name", "chintu-project")
        
        # Check if platform CLI is available
        cli_check = self._check_platform_cli(platform)
        if not cli_check["available"]:
            return {
                "success": False,
                "error": f"{platform.value} CLI not installed. Install with: {cli_check['install_cmd']}",
                "requires_action": "install_cli"
            }
        
        # Check for required secrets
        required_secrets = self._get_required_secrets(platform, project_path)
        missing_secrets = [s for s in required_secrets if not s.provided]
        
        if missing_secrets:
            # Request secrets from user
            return {
                "success": False,
                "requires_approval": True,
                "type": "secrets_needed",
                "secrets": [{"key": s.key, "description": s.description} for s in missing_secrets],
                "message": f"I need the following credentials to deploy to {platform.value}:\n" +
                          "\n".join(f"  - {s.key}: {s.description}" for s in missing_secrets)
            }
        
        # Generate deployment config
        deploy_config = self._generate_deploy_config(platform, project_path, project_name)
        
        # Request approval for deployment
        import uuid
        deploy_id = str(uuid.uuid4())[:8]
        
        record = DeploymentRecord(
            id=deploy_id,
            platform=platform,
            project_name=project_name,
            url=None,
            status=DeploymentStatus.PENDING
        )
        self.deployments[deploy_id] = record
        
        return {
            "success": True,
            "requires_approval": True,
            "type": "deploy_approval",
            "deployment_id": deploy_id,
            "platform": platform.value,
            "project": project_name,
            "config": deploy_config,
            "message": f"Ready to deploy **{project_name}** to **{platform.value}**.\n\n" +
                      f"Estimated time: ~2 minutes\n" +
                      f"URL will be: {self._estimate_url(platform, project_name)}\n\n" +
                      "Reply 'approve' to proceed with deployment."
        }
    
    def execute_deploy(self, deploy_id: str, secrets: Dict[str, str] = None) -> Dict[str, Any]:
        """Execute an approved deployment."""
        record = self.deployments.get(deploy_id)
        if not record:
            return {"success": False, "error": "Deployment not found"}
        
        record.status = DeploymentStatus.BUILDING
        self.log_step("Building", f"Deploying to {record.platform.value}")
        
        try:
            # Apply secrets if provided
            if secrets:
                self._apply_secrets(record.platform, secrets)
            
            # Execute deployment based on platform
            result = self._execute_platform_deploy(record)
            
            if result["success"]:
                record.status = DeploymentStatus.DEPLOYED
                record.url = result.get("url")
                record.completed_at = datetime.now()
                self._save_history()
                
                return {
                    "success": True,
                    "deployment_id": deploy_id,
                    "url": record.url,
                    "message": f"✅ Deployed successfully!\n\nURL: {record.url}"
                }
            else:
                record.status = DeploymentStatus.FAILED
                record.error = result.get("error")
                return result
                
        except Exception as e:
            record.status = DeploymentStatus.FAILED
            record.error = str(e)
            return {"success": False, "error": str(e)}
    
    def _handle_rollback(self, goal: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Handle rollback requests."""
        deploy_id = context.get("deployment_id")
        
        if not deploy_id:
            # Find latest deployment
            if self.deployments:
                deploy_id = max(self.deployments.keys(), 
                              key=lambda k: self.deployments[k].created_at)
            else:
                return {"success": False, "error": "No deployments found"}
        
        record = self.deployments.get(deploy_id)
        if not record:
            return {"success": False, "error": "Deployment not found"}
        
        # Execute rollback
        result = self._execute_rollback(record)
        
        if result["success"]:
            record.status = DeploymentStatus.ROLLED_BACK
            self._save_history()
        
        return result
    
    def _handle_status(self, goal: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Handle status/health check requests."""
        deploy_id = context.get("deployment_id")
        
        if deploy_id:
            record = self.deployments.get(deploy_id)
            if record:
                return {
                    "success": True,
                    "deployment": {
                        "id": record.id,
                        "platform": record.platform.value,
                        "status": record.status.value,
                        "url": record.url,
                        "created_at": record.created_at.isoformat()
                    }
                }
        
        # Return all recent deployments
        recent = sorted(self.deployments.values(), 
                       key=lambda r: r.created_at, reverse=True)[:5]
        
        return {
            "success": True,
            "deployments": [
                {
                    "id": r.id,
                    "project": r.project_name,
                    "platform": r.platform.value,
                    "status": r.status.value,
                    "url": r.url
                }
                for r in recent
            ]
        }
    
    def _handle_secrets(self, goal: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Handle secrets management requests."""
        # This requires approval for any secret access
        return {
            "success": False,
            "requires_approval": True,
            "type": "secrets_access",
            "message": "Secrets management requires explicit approval. What would you like to do?\n" +
                      "1. Add new secret\n2. List secrets\n3. Update secret"
        }
    
    def _handle_generic_ops(self, goal: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Handle generic ops requests."""
        self.log_step("Ops", f"Processing: {goal}")
        return {
            "success": True,
            "message": f"Ops task received: {goal}\nPlease specify: deploy, rollback, status, or secrets."
        }
    
    def _detect_platform(self, goal: str, context: Dict[str, Any]) -> DeploymentPlatform:
        """Detect which platform to deploy to."""
        goal_lower = goal.lower()
        
        if "vercel" in goal_lower:
            return DeploymentPlatform.VERCEL
        elif "fly" in goal_lower:
            return DeploymentPlatform.FLY
        elif "railway" in goal_lower:
            return DeploymentPlatform.RAILWAY
        elif "netlify" in goal_lower:
            return DeploymentPlatform.NETLIFY
        elif "render" in goal_lower:
            return DeploymentPlatform.RENDER
        
        # Default based on project type
        project_path = context.get("project_path", Path.cwd())
        
        if (Path(project_path) / "package.json").exists():
            return DeploymentPlatform.VERCEL  # Good for Next.js/React
        elif (Path(project_path) / "requirements.txt").exists():
            return DeploymentPlatform.FLY  # Good for Python
        elif (Path(project_path) / "Dockerfile").exists():
            return DeploymentPlatform.FLY  # Good for containers
        
        return DeploymentPlatform.VERCEL  # Default
    
    def _check_platform_cli(self, platform: DeploymentPlatform) -> Dict[str, Any]:
        """Check if platform CLI is installed."""
        cli_map = {
            DeploymentPlatform.VERCEL: ("vercel", "npm i -g vercel"),
            DeploymentPlatform.FLY: ("flyctl", "iwr https://fly.io/install.ps1 -useb | iex"),
            DeploymentPlatform.RAILWAY: ("railway", "npm i -g @railway/cli"),
            DeploymentPlatform.NETLIFY: ("netlify", "npm i -g netlify-cli"),
            DeploymentPlatform.RENDER: ("render", "pip install render-cli"),
        }
        
        cli_name, install_cmd = cli_map.get(platform, ("", ""))
        
        result = self.executor.run([cli_name, "--version"], timeout=5)
        return {"available": result.success, "install_cmd": install_cmd}
    
    def _get_required_secrets(self, platform: DeploymentPlatform, project_path: Path) -> List[SecretEntry]:
        """Get required secrets for deployment."""
        secrets = []
        
        # Platform-specific token
        token_map = {
            DeploymentPlatform.VERCEL: ("VERCEL_TOKEN", "Vercel access token"),
            DeploymentPlatform.FLY: ("FLY_API_TOKEN", "Fly.io API token"),
            DeploymentPlatform.RAILWAY: ("RAILWAY_TOKEN", "Railway API token"),
        }
        
        if platform in token_map:
            key, desc = token_map[platform]
            provided = bool(os.environ.get(key))
            secrets.append(SecretEntry(key=key, description=desc, provided=provided))
        
        # Check for .env file secrets
        env_file = project_path / ".env.example"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if "=" in line and not line.startswith("#"):
                    key = line.split("=")[0].strip()
                    provided = bool(os.environ.get(key))
                    secrets.append(SecretEntry(key=key, description=f"From .env.example", provided=provided))
        
        return secrets
    
    def _generate_deploy_config(self, platform: DeploymentPlatform, project_path: Path, project_name: str) -> Dict[str, Any]:
        """Generate deployment configuration."""
        config = {
            "platform": platform.value,
            "project": project_name,
            "path": str(project_path),
        }
        
        if platform == DeploymentPlatform.VERCEL:
            config["framework"] = "auto"
            config["build_command"] = "npm run build"
            config["output_directory"] = ".next" if (project_path / "next.config.js").exists() else "dist"
            
        elif platform == DeploymentPlatform.FLY:
            if (project_path / "Dockerfile").exists():
                config["type"] = "dockerfile"
            else:
                config["type"] = "python" if (project_path / "requirements.txt").exists() else "node"
            config["region"] = "ord"  # Chicago, good default
            
        elif platform == DeploymentPlatform.RAILWAY:
            config["framework"] = "auto"
        
        return config
    
    def _estimate_url(self, platform: DeploymentPlatform, project_name: str) -> str:
        """Estimate deployment URL."""
        safe_name = project_name.lower().replace(" ", "-").replace("_", "-")
        
        url_patterns = {
            DeploymentPlatform.VERCEL: f"https://{safe_name}.vercel.app",
            DeploymentPlatform.FLY: f"https://{safe_name}.fly.dev",
            DeploymentPlatform.RAILWAY: f"https://{safe_name}.up.railway.app",
            DeploymentPlatform.NETLIFY: f"https://{safe_name}.netlify.app",
            DeploymentPlatform.RENDER: f"https://{safe_name}.onrender.com",
        }
        
        return url_patterns.get(platform, f"https://{safe_name}.example.com")
    
    def _apply_secrets(self, platform: DeploymentPlatform, secrets: Dict[str, str]):
        """Apply secrets to environment for deployment."""
        for key, value in secrets.items():
            os.environ[key] = value
            self.log_step("Secrets", f"Applied {key}")
    
    def _execute_platform_deploy(self, record: DeploymentRecord) -> Dict[str, Any]:
        """Execute deployment on specific platform."""
        record.status = DeploymentStatus.DEPLOYING
        
        try:
            if record.platform == DeploymentPlatform.VERCEL:
                return self._deploy_vercel(record)
            elif record.platform == DeploymentPlatform.FLY:
                return self._deploy_fly(record)
            elif record.platform == DeploymentPlatform.RAILWAY:
                return self._deploy_railway(record)
            else:
                return {"success": False, "error": f"Platform {record.platform.value} not yet implemented"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _deploy_vercel(self, record: DeploymentRecord) -> Dict[str, Any]:
        """Deploy to Vercel."""
        result = self.executor.run(
            ["vercel", "--prod", "--yes"],
            timeout=300,
            approval_granted=True  # Already approved via execute_deploy
        )
        
        record.logs.extend(result.stdout.splitlines())
        
        if result.success:
            # Extract URL from output
            url = None
            for line in result.stdout.splitlines():
                if "https://" in line and "vercel" in line:
                    url = line.strip()
                    break
            
            return {"success": True, "url": url or self._estimate_url(record.platform, record.project_name)}
        else:
            return {"success": False, "error": result.stderr or result.error}
    
    def _deploy_fly(self, record: DeploymentRecord) -> Dict[str, Any]:
        """Deploy to Fly.io."""
        # Check if fly.toml exists, create if not
        if not Path("fly.toml").exists():
            self.executor.run(
                ["flyctl", "launch", "--name", record.project_name, "--no-deploy", "--yes"],
                timeout=60,
                approval_granted=True
            )
        
        result = self.executor.run(
            ["flyctl", "deploy", "--yes"],
            timeout=600,
            approval_granted=True
        )
        
        record.logs.extend(result.stdout.splitlines())
        
        if result.success:
            return {"success": True, "url": self._estimate_url(record.platform, record.project_name)}
        else:
            return {"success": False, "error": result.stderr or result.error}
    
    def _deploy_railway(self, record: DeploymentRecord) -> Dict[str, Any]:
        """Deploy to Railway."""
        result = self.executor.run(
            ["railway", "up"],
            timeout=300,
            approval_granted=True
        )
        
        record.logs.extend(result.stdout.splitlines())
        
        if result.success:
            return {"success": True, "url": self._estimate_url(record.platform, record.project_name)}
        else:
            return {"success": False, "error": result.stderr or result.error}
    
    def _execute_rollback(self, record: DeploymentRecord) -> Dict[str, Any]:
        """Execute rollback for a deployment."""
        if record.platform == DeploymentPlatform.VERCEL:
            result = self.executor.run(
                ["vercel", "rollback"],
                timeout=60,
                approval_granted=True
            )
        elif record.platform == DeploymentPlatform.FLY:
            result = self.executor.run(
                ["flyctl", "releases", "rollback"],
                timeout=60,
                approval_granted=True
            )
        else:
            return {"success": False, "error": "Rollback not supported for this platform"}
        
        return {"success": result.success, "output": result.stdout}
    
    def _load_history(self):
        """Load deployment history from file."""
        if self.history_file.exists():
            try:
                data = json.loads(self.history_file.read_text())
                for d in data:
                    record = DeploymentRecord(
                        id=d["id"],
                        platform=DeploymentPlatform(d["platform"]),
                        project_name=d["project_name"],
                        url=d.get("url"),
                        status=DeploymentStatus(d["status"]),
                        created_at=datetime.fromisoformat(d["created_at"])
                    )
                    self.deployments[record.id] = record
            except Exception as e:
                logger.warning(f"Could not load deployment history: {e}")
    
    def _save_history(self):
        """Save deployment history to file."""
        try:
            data = [
                {
                    "id": r.id,
                    "platform": r.platform.value,
                    "project_name": r.project_name,
                    "url": r.url,
                    "status": r.status.value,
                    "created_at": r.created_at.isoformat()
                }
                for r in self.deployments.values()
            ]
            self.history_file.parent.mkdir(parents=True, exist_ok=True)
            self.history_file.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.warning(f"Could not save deployment history: {e}")
    
    def stop(self):
        """Stop the agent."""
        self.update_state(AgentState.IDLE)
