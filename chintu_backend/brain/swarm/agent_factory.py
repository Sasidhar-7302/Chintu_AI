"""
Agent Factory - Dynamic agent creation and management.

Creates specialized agents on demand with:
- Role-based templates (Founder, PM, Dev, Growth, Ops)
- Scoped tool access per agent
- Auto-registration with SwarmOrchestrator
"""

import logging
from typing import Dict, Any, Optional, List, Type
from dataclasses import dataclass, field
from enum import Enum

from chintu_backend.brain.swarm.base_agent import BaseAgent
from chintu_backend.swarm.agent_runtime import create_agent_runtime

logger = logging.getLogger(__name__)


class AgentRole(Enum):
    """Standard agent roles."""
    FOUNDER = "founder"      # High-level strategist, PM
    DEVELOPER = "developer"  # Coding, implementation
    OPS = "ops"              # Deployment, monitoring
    GROWTH = "growth"        # Marketing, user acquisition
    ANALYST = "analyst"      # Data analysis, insights
    RESEARCHER = "researcher"  # Deep research
    CUSTOM = "custom"        # User-defined


@dataclass
class AgentTemplate:
    """Template for creating agents."""
    role: AgentRole
    name: str
    description: str
    allowed_tools: List[str]
    system_prompt: str
    priority: int = 5  # 1-10, higher = more important


# Standard agent templates
AGENT_TEMPLATES: Dict[AgentRole, AgentTemplate] = {
    AgentRole.FOUNDER: AgentTemplate(
        role=AgentRole.FOUNDER,
        name="Founder",
        description="Product Manager / CEO - researches, plans, estimates, coordinates",
        allowed_tools=["research", "plan", "delegate", "budget", "approve"],
        system_prompt="""You are a Product Manager / Founder. Your job is to:
1. Understand what the user wants
2. Research the problem domain
3. Create a detailed plan with time estimates
4. Identify ALL resources needed upfront
5. Coordinate agents to execute the plan
6. Report results""",
        priority=10
    ),
    
    AgentRole.DEVELOPER: AgentTemplate(
        role=AgentRole.DEVELOPER,
        name="Developer",
        description="Writes code, implements features, fixes bugs",
        allowed_tools=["code", "test", "debug", "terminal", "file_edit"],
        system_prompt="""You are a Senior Developer. Your job is to:
1. Write clean, working code
2. Test your implementations
3. Handle errors gracefully
4. Follow best practices""",
        priority=8
    ),
    
    AgentRole.OPS: AgentTemplate(
        role=AgentRole.OPS,
        name="Ops",
        description="Deployment, infrastructure, monitoring",
        allowed_tools=["deploy", "monitor", "terminal", "config", "secrets"],
        system_prompt="""You are a DevOps Engineer. Your job is to:
1. Deploy applications to production
2. Monitor health and performance
3. Manage secrets securely
4. Handle rollbacks when needed""",
        priority=7
    ),
    
    AgentRole.GROWTH: AgentTemplate(
        role=AgentRole.GROWTH,
        name="Growth",
        description="Marketing, user acquisition, analytics",
        allowed_tools=["research", "content", "analytics", "email"],
        system_prompt="""You are a Growth Marketer. Your job is to:
1. Create marketing content
2. Analyze user acquisition channels
3. Optimize for growth
4. Track key metrics""",
        priority=5
    ),
    
    AgentRole.ANALYST: AgentTemplate(
        role=AgentRole.ANALYST,
        name="Analyst",
        description="Data analysis, insights, reporting",
        allowed_tools=["data", "charts", "research", "report"],
        system_prompt="""You are a Data Analyst. Your job is to:
1. Analyze data and find insights
2. Create visualizations
3. Generate reports
4. Provide actionable recommendations""",
        priority=5
    ),
    
    AgentRole.RESEARCHER: AgentTemplate(
        role=AgentRole.RESEARCHER,
        name="Researcher",
        description="Deep research, competitive analysis, documentation",
        allowed_tools=["web_search", "browser", "summarize", "document"],
        system_prompt="""You are a Research Analyst. Your job is to:
1. Conduct deep research on topics
2. Analyze competitors
3. Synthesize information
4. Create comprehensive reports""",
        priority=6
    ),
}


class DynamicAgent(BaseAgent):
    """A dynamically created agent from a template."""
    
    def __init__(self, template: AgentTemplate, custom_tools: List[str] = None):
        super().__init__(
            name=template.name,
            description=template.description
        )
        self.template = template
        self.allowed_tools = custom_tools or template.allowed_tools
        self.system_prompt = template.system_prompt
        
        try:
            runtime = create_agent_runtime(template.name.lower())
            self.attach_runtime(runtime)
        except Exception:
            pass
    
    def run(self, goal: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute the agent's task using its allowed tools."""
        from chintu_backend.brain.swarm.base_agent import AgentState
        
        self.update_state(AgentState.EXECUTING)
        self.log_step("Executing", f"Goal: {goal}")
        
        # Use LLM with system prompt to execute
        try:
            from chintu_backend.core.config import get_config
            from chintu_backend.brain.llm.ollama_client import OllamaClient
            
            config = get_config()
            llm = OllamaClient(
                host=getattr(config, 'ollama_host', 'http://localhost:11434'),
                model=getattr(config, 'ollama_model', 'qwen2.5:3b')
            )
            
            prompt = f"""{self.system_prompt}

TASK: {goal}

AVAILABLE TOOLS: {', '.join(self.allowed_tools)}

Execute this task and return the result."""
            
            response = llm.generate(prompt) if hasattr(llm, 'generate') else llm.chat(prompt)
            
            self.update_state(AgentState.COMPLETED)
            return {"success": True, "output": response}
            
        except Exception as e:
            from chintu_backend.brain.swarm.base_agent import AgentState
            self.update_state(AgentState.FAILED)
            return {"success": False, "error": str(e)}
    
    def stop(self):
        from chintu_backend.brain.swarm.base_agent import AgentState
        self.update_state(AgentState.IDLE)


class AgentFactory:
    """
    Factory for creating agents dynamically.
    
    Usage:
        factory = AgentFactory()
        founder = factory.create(AgentRole.FOUNDER)
        custom = factory.create_custom("DataEngineer", "ETL pipelines", ["sql", "python"])
    """
    
    def __init__(self):
        self.created_agents: Dict[str, BaseAgent] = {}
        self.templates = AGENT_TEMPLATES.copy()
    
    def create(self, role: AgentRole, custom_tools: List[str] = None) -> BaseAgent:
        """Create an agent from a standard template."""
        if role == AgentRole.FOUNDER:
            # Use the specialized Founder agent
            from chintu_backend.brain.swarm.agents.founder import FounderAgent
            agent = FounderAgent()
        elif role in self.templates:
            template = self.templates[role]
            agent = DynamicAgent(template, custom_tools)
        else:
            raise ValueError(f"Unknown agent role: {role}")
        
        self.created_agents[agent.id] = agent
        logger.info(f"Created agent: {agent.name} (role={role.value})")
        return agent
    
    def create_custom(
        self,
        name: str,
        description: str,
        allowed_tools: List[str],
        system_prompt: str = None,
        priority: int = 5
    ) -> BaseAgent:
        """Create a custom agent with specified capabilities."""
        template = AgentTemplate(
            role=AgentRole.CUSTOM,
            name=name,
            description=description,
            allowed_tools=allowed_tools,
            system_prompt=system_prompt or f"You are {name}. {description}",
            priority=priority
        )
        
        agent = DynamicAgent(template)
        self.created_agents[agent.id] = agent
        logger.info(f"Created custom agent: {name}")
        return agent
    
    def get_agent(self, agent_id: str) -> Optional[BaseAgent]:
        """Get an existing agent by ID."""
        return self.created_agents.get(agent_id)
    
    def list_agents(self) -> List[Dict[str, Any]]:
        """List all created agents."""
        return [
            {
                "id": agent.id,
                "name": agent.name,
                "description": agent.description,
                "state": agent.state
            }
            for agent in self.created_agents.values()
        ]
    
    def destroy(self, agent_id: str) -> bool:
        """Stop and remove an agent."""
        agent = self.created_agents.pop(agent_id, None)
        if agent:
            try:
                agent.stop()
            except Exception:
                pass
            logger.info(f"Destroyed agent: {agent.name}")
            return True
        return False
    
    def get_available_roles(self) -> List[Dict[str, Any]]:
        """Get list of available agent roles."""
        return [
            {
                "role": role.value,
                "name": template.name,
                "description": template.description,
                "tools": template.allowed_tools
            }
            for role, template in self.templates.items()
        ]


# Singleton instance
_factory: Optional[AgentFactory] = None


def get_agent_factory() -> AgentFactory:
    """Get or create the agent factory singleton."""
    global _factory
    if _factory is None:
        _factory = AgentFactory()
    return _factory
