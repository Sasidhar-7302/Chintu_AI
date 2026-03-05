"""
Agent Evolver - Self-creation and self-updating of agents.

Allows Chintu to:
- Create new agents when capability gaps are detected
- Update existing agents with improvements
- All with approval gates for safety
"""

import json
import logging
import os
import re
import ast
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from enum import Enum

from chintu_backend.core.config import get_config
from chintu_backend.core.events import get_event_bus, Event, EventType

logger = logging.getLogger(__name__)


class EvolutionType(Enum):
    CREATE = "create"
    UPDATE = "update"
    ENHANCE = "enhance"
    DEPRECATE = "deprecate"


@dataclass
class AgentBlueprint:
    """Blueprint for a new or updated agent."""
    name: str
    description: str
    capabilities: List[str]
    tools_needed: List[str]
    code: str
    evolution_type: EvolutionType
    reason: str  # Why this agent is needed
    approved: bool = False
    created_at: datetime = field(default_factory=datetime.now)


@dataclass 
class EvolutionRecord:
    """Record of an agent evolution (create/update)."""
    id: str
    agent_name: str
    evolution_type: EvolutionType
    description: str
    code_diff: str
    approved: bool
    applied: bool
    timestamp: datetime = field(default_factory=datetime.now)
    result: Optional[str] = None


class AgentEvolver:
    """
    Enables Chintu to evolve its own agent capabilities.
    
    Features:
    - Detect capability gaps → propose new agents
    - Generate agent code using LLM
    - Update existing agents with improvements
    - Approval workflow for all changes
    - Rollback capability
    """
    
    def __init__(self):
        self.config = get_config()
        self.event_bus = get_event_bus()
        
        self.agents_dir = Path(__file__).parent / "agents"
        self.agents_dir.mkdir(parents=True, exist_ok=True)
        
        self.evolution_log = self.config.data_dir / "agent_evolution.json"
        self.pending_evolutions: Dict[str, AgentBlueprint] = {}
        self.evolution_history: List[EvolutionRecord] = []
        
        self._load_history()
    
    # --- Core Evolution Methods ---
    
    def propose_new_agent(
        self,
        name: str,
        description: str,
        capabilities: List[str],
        reason: str
    ) -> AgentBlueprint:
        """
        Propose creation of a new agent.
        Returns a blueprint that requires approval.
        """
        logger.info(f"Proposing new agent: {name}")
        
        # Generate agent code using LLM
        code = self._generate_agent_code(name, description, capabilities)
        
        # Determine tools needed
        tools = self._infer_tools_from_capabilities(capabilities)
        
        blueprint = AgentBlueprint(
            name=name,
            description=description,
            capabilities=capabilities,
            tools_needed=tools,
            code=code,
            evolution_type=EvolutionType.CREATE,
            reason=reason
        )
        
        import uuid
        evolution_id = str(uuid.uuid4())[:8]
        self.pending_evolutions[evolution_id] = blueprint
        
        return blueprint
    
    def propose_agent_update(
        self,
        agent_name: str,
        improvements: List[str],
        reason: str
    ) -> AgentBlueprint:
        """
        Propose updates to an existing agent.
        Returns a blueprint with the proposed changes.
        """
        logger.info(f"Proposing update to agent: {agent_name}")
        
        # Read current agent code
        agent_file = self.agents_dir / f"{agent_name.lower()}_agent.py"
        if not agent_file.exists():
            agent_file = self.agents_dir / f"{agent_name.lower()}.py"
        
        if not agent_file.exists():
            raise FileNotFoundError(f"Agent file not found: {agent_name}")
        
        current_code = agent_file.read_text()
        
        # Generate improved code
        improved_code = self._generate_improved_code(
            agent_name, 
            current_code, 
            improvements
        )
        
        blueprint = AgentBlueprint(
            name=agent_name,
            description=f"Updated {agent_name} with: {', '.join(improvements)}",
            capabilities=improvements,
            tools_needed=[],
            code=improved_code,
            evolution_type=EvolutionType.UPDATE,
            reason=reason
        )
        
        import uuid
        evolution_id = str(uuid.uuid4())[:8]
        self.pending_evolutions[evolution_id] = blueprint
        
        return blueprint
    
    def detect_capability_gap(self, failed_task: str, error: str) -> Optional[AgentBlueprint]:
        """
        Analyze a failed task to detect if a new agent is needed.
        Returns a proposed blueprint if a gap is detected.
        """
        logger.info(f"Analyzing capability gap for: {failed_task}")
        
        # Use LLM to analyze the failure
        analysis = self._analyze_failure(failed_task, error)
        
        if analysis.get("needs_new_agent"):
            return self.propose_new_agent(
                name=analysis["suggested_name"],
                description=analysis["description"],
                capabilities=analysis["capabilities"],
                reason=f"Task failed: {failed_task}. Error: {error[:100]}"
            )
        elif analysis.get("needs_update"):
            return self.propose_agent_update(
                agent_name=analysis["agent_to_update"],
                improvements=analysis["improvements"],
                reason=f"Task partially failed: {failed_task}"
            )
        
        return None
    
    def approve_evolution(self, evolution_id: str) -> Dict[str, Any]:
        """
        Approve a pending evolution (requires user confirmation).
        """
        blueprint = self.pending_evolutions.get(evolution_id)
        if not blueprint:
            return {"success": False, "error": "Evolution not found"}
        
        blueprint.approved = True
        return {
            "success": True,
            "message": f"Evolution approved: {blueprint.name}",
            "ready_to_apply": True
        }
    
    def apply_evolution(self, evolution_id: str) -> Dict[str, Any]:
        """
        Apply an approved evolution (create/update agent file).
        """
        blueprint = self.pending_evolutions.get(evolution_id)
        if not blueprint:
            return {"success": False, "error": "Evolution not found"}
        
        if not blueprint.approved:
            return {
                "success": False,
                "requires_approval": True,
                "message": "This evolution needs approval before applying."
            }
        
        try:
            # Validate the code
            if not self._validate_code(blueprint.code):
                return {"success": False, "error": "Generated code has syntax errors"}
            
            # Determine file path
            safe_name = blueprint.name.lower().replace(" ", "_")
            if not safe_name.endswith("_agent"):
                safe_name = f"{safe_name}_agent"
            
            agent_file = self.agents_dir / f"{safe_name}.py"
            
            # Backup if updating
            backup_path = None
            if agent_file.exists():
                backup_path = self._create_backup(agent_file)
            
            # Write the new code
            agent_file.write_text(blueprint.code)
            
            # Register the agent
            self._register_agent(safe_name, blueprint)
            
            # Record the evolution
            record = EvolutionRecord(
                id=evolution_id,
                agent_name=blueprint.name,
                evolution_type=blueprint.evolution_type,
                description=blueprint.description,
                code_diff=blueprint.code[:500],  # Store preview
                approved=True,
                applied=True,
                result="success"
            )
            self.evolution_history.append(record)
            self._save_history()
            
            # Clean up pending
            self.pending_evolutions.pop(evolution_id, None)
            
            logger.info(f"Applied evolution: {blueprint.name}")
            
            return {
                "success": True,
                "agent_file": str(agent_file),
                "backup": str(backup_path) if backup_path else None,
                "message": f"✅ Agent '{blueprint.name}' has been {'created' if blueprint.evolution_type == EvolutionType.CREATE else 'updated'}!"
            }
            
        except Exception as e:
            logger.error(f"Failed to apply evolution: {e}")
            return {"success": False, "error": str(e)}
    
    def rollback_evolution(self, evolution_id: str) -> Dict[str, Any]:
        """Rollback an applied evolution using backup."""
        # Find the record
        record = None
        for r in self.evolution_history:
            if r.id == evolution_id:
                record = r
                break
        
        if not record:
            return {"success": False, "error": "Evolution record not found"}
        
        # Find backup
        safe_name = record.agent_name.lower().replace(" ", "_")
        if not safe_name.endswith("_agent"):
            safe_name = f"{safe_name}_agent"
        
        backups_dir = self.config.data_dir / "agent_backups"
        backups = sorted(backups_dir.glob(f"{safe_name}_*.py.bak"), reverse=True)
        
        if not backups:
            return {"success": False, "error": "No backup found for rollback"}
        
        latest_backup = backups[0]
        agent_file = self.agents_dir / f"{safe_name}.py"
        
        # Restore
        agent_file.write_text(latest_backup.read_text())
        
        return {
            "success": True,
            "message": f"Rolled back {record.agent_name} to previous version"
        }
    
    # --- LLM-Based Code Generation ---
    
    def _generate_agent_code(
        self, 
        name: str, 
        description: str, 
        capabilities: List[str]
    ) -> str:
        """Generate agent code using LLM."""
        try:
            from chintu_backend.brain.llm.ollama_client import OllamaClient
            
            llm = OllamaClient(
                host=getattr(self.config, 'ollama_host', 'http://localhost:11434'),
                model=getattr(self.config, 'ollama_model', 'qwen2.5:3b')
            )
            
            prompt = f"""Generate a Python agent class for Chintu AI.

AGENT NAME: {name}
DESCRIPTION: {description}
CAPABILITIES: {', '.join(capabilities)}

The agent should:
1. Inherit from BaseAgent
2. Have a run(goal, context) method
3. Log steps using self.log_step()
4. Return structured results

Follow this template structure:
```python
\"\"\"
{name} Agent - {description}
\"\"\"

import logging
from typing import Dict, Any, Optional
from chintu_backend.brain.swarm.base_agent import BaseAgent, AgentState

logger = logging.getLogger(__name__)


class {name.replace(' ', '')}Agent(BaseAgent):
    \"\"\"
    {description}
    
    Capabilities:
    {chr(10).join(f'    - {c}' for c in capabilities)}
    \"\"\"
    
    def __init__(self):
        super().__init__(
            name="{name}",
            description="{description}"
        )
    
    def run(self, goal: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        \"\"\"Execute the agent's task.\"\"\"
        self.update_state(AgentState.EXECUTING)
        self.log_step("Starting", f"Goal: {{goal}}")
        
        context = context or {{}}
        
        # TODO: Implement agent logic
        
        return {{"success": True, "message": "Task completed"}}
    
    def stop(self):
        self.update_state(AgentState.IDLE)
```

Generate the complete agent code. Be specific about the implementation based on the capabilities."""
            
            response = llm.generate(prompt) if hasattr(llm, 'generate') else llm.chat(prompt)
            
            # Extract code from response
            if "```python" in response:
                code = response.split("```python")[1].split("```")[0]
            elif "```" in response:
                code = response.split("```")[1].split("```")[0]
            else:
                code = response
            
            return code.strip()
            
        except Exception as e:
            logger.error(f"LLM code generation failed: {e}")
            # Return a template
            return self._get_agent_template(name, description, capabilities)
    
    def _generate_improved_code(
        self,
        agent_name: str,
        current_code: str,
        improvements: List[str]
    ) -> str:
        """Generate improved agent code using LLM."""
        try:
            from chintu_backend.brain.llm.ollama_client import OllamaClient
            
            llm = OllamaClient(
                host=getattr(self.config, 'ollama_host', 'http://localhost:11434'),
                model=getattr(self.config, 'ollama_model', 'qwen2.5:3b')
            )
            
            prompt = f"""Improve this Python agent code.

CURRENT CODE:
```python
{current_code[:3000]}
```

REQUIRED IMPROVEMENTS:
{chr(10).join(f'- {imp}' for imp in improvements)}

Generate the improved code. Keep the same structure but add/modify to incorporate the improvements.
Output only the Python code, no explanations."""
            
            response = llm.generate(prompt) if hasattr(llm, 'generate') else llm.chat(prompt)
            
            if "```python" in response:
                code = response.split("```python")[1].split("```")[0]
            elif "```" in response:
                code = response.split("```")[1].split("```")[0]
            else:
                code = response
            
            return code.strip()
            
        except Exception as e:
            logger.error(f"LLM improvement failed: {e}")
            return current_code  # Return unchanged on failure
    
    def _analyze_failure(self, task: str, error: str) -> Dict[str, Any]:
        """Analyze a failure to determine if new agent is needed."""
        try:
            from chintu_backend.brain.llm.ollama_client import OllamaClient
            
            llm = OllamaClient(
                host=getattr(self.config, 'ollama_host', 'http://localhost:11434'),
                model=getattr(self.config, 'ollama_model', 'qwen2.5:3b')
            )
            
            # Get list of existing agents
            existing_agents = [f.stem for f in self.agents_dir.glob("*.py") if not f.name.startswith("_")]
            
            prompt = f"""Analyze this task failure and determine if a new agent is needed.

TASK: {task}
ERROR: {error}

EXISTING AGENTS:
{', '.join(existing_agents)}

Determine:
1. Is a new agent needed, or can an existing one be updated?
2. What capabilities are missing?

Output as JSON:
{{
    "needs_new_agent": true/false,
    "needs_update": true/false,
    "suggested_name": "AgentName" (if new),
    "agent_to_update": "existing_agent" (if update),
    "description": "what the agent does",
    "capabilities": ["capability1", "capability2"],
    "improvements": ["improvement1"] (if update)
}}"""
            
            response = llm.generate(prompt) if hasattr(llm, 'generate') else llm.chat(prompt)
            
            # Parse JSON
            if "{" in response and "}" in response:
                start = response.find("{")
                end = response.rfind("}") + 1
                return json.loads(response[start:end])
            
            return {"needs_new_agent": False, "needs_update": False}
            
        except Exception as e:
            logger.error(f"Failure analysis failed: {e}")
            return {"needs_new_agent": False, "needs_update": False}
    
    # --- Utility Methods ---
    
    def _validate_code(self, code: str) -> bool:
        """Validate Python code syntax."""
        try:
            ast.parse(code)
            return True
        except SyntaxError:
            return False
    
    def _infer_tools_from_capabilities(self, capabilities: List[str]) -> List[str]:
        """Infer required tools from capabilities."""
        tool_keywords = {
            "web": ["browser", "http"],
            "file": ["read", "write"],
            "terminal": ["command", "shell", "execute"],
            "code": ["code", "generate"],
            "search": ["search", "find"],
            "deploy": ["deploy", "vercel", "fly"],
        }
        
        tools = []
        for cap in capabilities:
            cap_lower = cap.lower()
            for tool, keywords in tool_keywords.items():
                if any(kw in cap_lower for kw in keywords):
                    if tool not in tools:
                        tools.append(tool)
        
        return tools
    
    def _create_backup(self, file_path: Path) -> Path:
        """Create a backup of an agent file."""
        backups_dir = self.config.data_dir / "agent_backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backups_dir / f"{file_path.stem}_{timestamp}.py.bak"
        backup_path.write_text(file_path.read_text())
        
        return backup_path
    
    def _register_agent(self, agent_name: str, blueprint: AgentBlueprint):
        """Register the new agent with the system."""
        try:
            from chintu_backend.brain.swarm.agent_factory import get_agent_factory
            
            factory = get_agent_factory()
            
            # Add to factory templates
            if hasattr(factory, 'ROLE_TEMPLATES'):
                factory.ROLE_TEMPLATES[agent_name.upper()] = {
                    "system_prompt": f"You are a {blueprint.name}. {blueprint.description}",
                    "tools": blueprint.tools_needed,
                    "capabilities": blueprint.capabilities
                }
            
            logger.info(f"Registered agent: {agent_name}")
            
        except Exception as e:
            logger.warning(f"Could not register agent with factory: {e}")
    
    def _get_agent_template(self, name: str, description: str, capabilities: List[str]) -> str:
        """Get a basic agent template."""
        class_name = name.replace(" ", "").replace("-", "").replace("_", "")
        
        return f'''"""
{name} Agent - {description}
"""

import logging
from typing import Dict, Any, Optional
from chintu_backend.brain.swarm.base_agent import BaseAgent, AgentState

logger = logging.getLogger(__name__)


class {class_name}Agent(BaseAgent):
    """
    {description}
    
    Capabilities:
{chr(10).join(f"    - {c}" for c in capabilities)}
    """
    
    def __init__(self):
        super().__init__(
            name="{name}",
            description="{description}"
        )
    
    def run(self, goal: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute the agent's task."""
        self.update_state(AgentState.EXECUTING)
        self.log_step("Starting", f"Goal: {{goal}}")
        
        context = context or {{}}
        result = {{"success": True}}
        
        # Implement capabilities
{chr(10).join(f"        # TODO: {c}" for c in capabilities)}
        
        self.log_step("Complete", "Task finished")
        return result
    
    def stop(self):
        self.update_state(AgentState.IDLE)
'''
    
    def _load_history(self):
        """Load evolution history from disk."""
        if self.evolution_log.exists():
            try:
                data = json.loads(self.evolution_log.read_text())
                for item in data:
                    record = EvolutionRecord(
                        id=item["id"],
                        agent_name=item["agent_name"],
                        evolution_type=EvolutionType(item["evolution_type"]),
                        description=item["description"],
                        code_diff=item.get("code_diff", ""),
                        approved=item["approved"],
                        applied=item["applied"],
                        timestamp=datetime.fromisoformat(item["timestamp"])
                    )
                    self.evolution_history.append(record)
            except Exception as e:
                logger.warning(f"Could not load evolution history: {e}")
    
    def _save_history(self):
        """Save evolution history to disk."""
        data = [
            {
                "id": r.id,
                "agent_name": r.agent_name,
                "evolution_type": r.evolution_type.value,
                "description": r.description,
                "code_diff": r.code_diff,
                "approved": r.approved,
                "applied": r.applied,
                "timestamp": r.timestamp.isoformat(),
                "result": r.result
            }
            for r in self.evolution_history
        ]
        self.evolution_log.parent.mkdir(parents=True, exist_ok=True)
        self.evolution_log.write_text(json.dumps(data, indent=2))
    
    # --- Query Methods ---
    
    def list_pending_evolutions(self) -> List[Dict[str, Any]]:
        """List all pending evolutions awaiting approval."""
        return [
            {
                "id": eid,
                "name": bp.name,
                "type": bp.evolution_type.value,
                "reason": bp.reason,
                "approved": bp.approved
            }
            for eid, bp in self.pending_evolutions.items()
        ]
    
    def list_existing_agents(self) -> List[str]:
        """List all existing agent files."""
        return [f.stem for f in self.agents_dir.glob("*.py") if not f.name.startswith("_")]
    
    def get_evolution_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent evolution history."""
        return [
            {
                "id": r.id,
                "agent": r.agent_name,
                "type": r.evolution_type.value,
                "applied": r.applied,
                "timestamp": r.timestamp.isoformat()
            }
            for r in self.evolution_history[-limit:]
        ]


# Singleton instance
_evolver: Optional[AgentEvolver] = None


def get_agent_evolver() -> AgentEvolver:
    """Get or create the agent evolver singleton."""
    global _evolver
    if _evolver is None:
        _evolver = AgentEvolver()
    return _evolver
