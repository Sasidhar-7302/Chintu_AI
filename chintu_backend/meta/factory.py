"""Capability Factory - Self-upgrade mechanism for Chintu.

The crown jewel of v6.0: When Chintu can't handle a request, it builds the tool itself.
Flow: Research → Draft → Test → Register → Execute
"""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from chintu_backend.core.config import get_config

logger = logging.getLogger(__name__)


class CapabilityFactory:
    """Builds new capabilities when Chintu can't handle a request.
    
    This enables Chintu to evolve by creating its own tools through:
    1. Research - Find relevant Python libraries
    2. Draft - Generate capability code
    3. Test - Validate in sandbox
    4. Register - Hot-reload into the system
    """
    
    # Template for new capabilities
    CAPABILITY_TEMPLATE = '''"""Auto-generated capability: {name}

Created by Capability Factory on {timestamp}
Original request: {request}
"""

import logging
from typing import Any, Dict
from chintu_backend.core.capabilities import Capability, CapabilityType, ActionResult, get_registry

logger = logging.getLogger(__name__)

{imports}

def {function_name}(text: str, context: Dict[str, Any] = None) -> ActionResult:
    """
    {docstring}
    """
    try:
{implementation}
        return ActionResult.ok(result, capability="{name}")
    except Exception as exc:
        logger.warning("{name} failed: %s", exc)
        return ActionResult.fail(f"Failed: {{exc}}", capability="{name}")


def register_capability():
    """Register this capability with the registry."""
    registry = get_registry()
    
    cap = Capability(
        name="{name}",
        description="{description}",
        triggers={triggers},
        handler={function_name},
        capability_type=CapabilityType.AI_AGENT,
    )
    
    registry.register(cap)
    logger.info("Registered auto-generated capability: {name}")


# Auto-register on import
if __name__ != "__main__":
    try:
        register_capability()
    except Exception as exc:
        logger.warning("Failed to auto-register {name}: %s", exc)
'''

    # Common libraries for different task types
    LIBRARY_HINTS = {
        "sentiment": ("textblob", "from textblob import TextBlob"),
        "web scrape": ("requests", "import requests\nfrom bs4 import BeautifulSoup"),
        "stock": ("yfinance", "import yfinance as yf"),
        "weather": ("requests", "import requests"),
        "email": ("smtplib", "import smtplib\nfrom email.mime.text import MIMEText"),
        "pdf": ("PyPDF2", "import PyPDF2"),
        "csv": ("pandas", "import pandas as pd"),
        "image": ("Pillow", "from PIL import Image"),
        "qr code": ("qrcode", "import qrcode"),
        "translate": ("deep-translator", "from deep_translator import GoogleTranslator"),
        "compress": ("zipfile", "import zipfile\nimport gzip"),
        "json": ("json", "import json"),
        "calculate": ("math", "import math"),
        "date": ("datetime", "from datetime import datetime, timedelta"),
    }

    def __init__(self) -> None:
        self.config = get_config()
        self.capabilities_dir = Path(__file__).parent.parent / "capabilities" / "generated"
        self.capabilities_dir.mkdir(parents=True, exist_ok=True)
        
        self._llm = None  # Lazy load
        self._sandbox = None  # Lazy load
        
        logger.info("CapabilityFactory initialized at %s", self.capabilities_dir)

    def _get_llm(self):
        """Lazy load LLM client."""
        if self._llm is None:
            try:
                from chintu_backend.brain.llm.model_router import get_model_router
                self._llm = get_model_router()
            except ImportError:
                from chintu_backend.brain.llm.ollama_client import get_ollama_client
                self._llm = get_ollama_client()
        return self._llm

    def _get_sandbox(self):
        """Lazy load Docker sandbox."""
        if self._sandbox is None:
            try:
                from chintu_backend.sandbox.docker_sandbox import DockerSandbox
                self._sandbox = DockerSandbox()
            except ImportError:
                self._sandbox = None
        return self._sandbox

    async def detect_missing_capability(self, query: str) -> bool:
        """Check if query requires a capability we don't have.
        
        Args:
            query: User's request
            
        Returns:
            True if no matching capability exists
        """
        try:
            from chintu_backend.core.capabilities import get_registry
            registry = get_registry()
            match = registry.match(query)
            return match is None
        except Exception:
            return True

    async def research(self, task: str) -> Dict[str, Any]:
        """Research how to implement the capability.
        
        Args:
            task: Description of what the capability should do
            
        Returns:
            Dict with library recommendations and approach
        """
        task_lower = task.lower()
        
        # Check our library hints first
        for keyword, (library, import_stmt) in self.LIBRARY_HINTS.items():
            if keyword in task_lower:
                return {
                    "library": library,
                    "import": import_stmt,
                    "approach": f"Use {library} library to {task}",
                    "source": "hints",
                }
        
        # Fall back to LLM for research
        llm = self._get_llm()
        if llm:
            prompt = f"""Research the best Python library for this task: {task}

Return JSON with:
- library: package name to pip install
- import: the import statement(s) needed
- approach: brief description of how to use it

Prefer well-known, stable libraries. Response must be valid JSON only."""

            try:
                response = await llm.query(prompt)
                # Try to parse JSON from response
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group())
            except Exception as exc:
                logger.warning("LLM research failed: %s", exc)
        
        # Default fallback
        return {
            "library": "none",
            "import": "",
            "approach": f"Implement {task} using Python standard library",
            "source": "fallback",
        }

    async def draft_capability(
        self, 
        task: str, 
        research: Dict[str, Any]
    ) -> Dict[str, str]:
        """Generate the capability code.
        
        Args:
            task: What the capability should do
            research: Research results with library info
            
        Returns:
            Dict with code and metadata
        """
        # Generate a clean name
        name = self._generate_name(task)
        function_name = name.replace("-", "_").replace(" ", "_")
        
        # Generate triggers from the task
        triggers = self._generate_triggers(task)
        
        llm = self._get_llm()
        implementation = ""
        description = task[:100]
        
        if llm:
            prompt = f"""Generate Python implementation for this capability:
Task: {task}
Library: {research.get('library', 'standard library')}
Import: {research.get('import', '')}

Write ONLY the implementation code (indented with 8 spaces).
The code should:
1. Parse any needed info from 'text' parameter
2. Perform the task
3. Set 'result' variable with a user-friendly message

No function definition needed, just the body code."""

            try:
                response = await llm.query(prompt)
                # Clean up the implementation
                implementation = self._clean_implementation(response)
            except Exception as exc:
                logger.warning("LLM draft failed: %s", exc)
        
        # Fallback implementation
        if not implementation:
            implementation = f'        result = f"Processing: {{text}}"\n        # TODO: Implement {task}'
        
        # Format the full code
        code = self.CAPABILITY_TEMPLATE.format(
            name=name,
            timestamp=datetime.now().isoformat(),
            request=task[:200],
            imports=research.get("import", ""),
            function_name=function_name,
            docstring=f"Auto-generated capability: {task}",
            implementation=implementation,
            description=description,
            triggers=triggers,
        )
        
        return {
            "name": name,
            "function_name": function_name,
            "code": code,
            "triggers": triggers,
        }

    def _generate_name(self, task: str) -> str:
        """Generate a clean capability name from task description."""
        # Extract key words
        stop_words = {"a", "an", "the", "to", "of", "for", "and", "or", "in", "on"}
        words = [w.lower() for w in task.split() if w.lower() not in stop_words][:3]
        
        if not words:
            words = ["custom", "tool"]
        
        return "_".join(words)

    def _generate_triggers(self, task: str) -> str:
        """Generate trigger phrases from task description."""
        task_lower = task.lower()
        triggers = []
        
        # Add the task keywords
        key_words = [w for w in task.split() if len(w) > 3][:4]
        for word in key_words:
            triggers.append(word.lower())
        
        # Add common variations
        if "analyze" in task_lower:
            triggers.extend(["analyze", "analysis"])
        if "get" in task_lower or "fetch" in task_lower:
            triggers.extend(["get", "fetch", "retrieve"])
        if "create" in task_lower or "generate" in task_lower:
            triggers.extend(["create", "generate", "make"])
        
        return repr(list(set(triggers)))

    def _clean_implementation(self, code: str) -> str:
        """Clean LLM-generated code for inclusion in template."""
        # Remove markdown code blocks
        code = re.sub(r'```\w*\n?', '', code)
        code = code.strip()
        
        # Ensure proper indentation (8 spaces for template)
        lines = code.split('\n')
        cleaned = []
        for line in lines:
            stripped = line.lstrip()
            if stripped:
                cleaned.append("        " + stripped)
            else:
                cleaned.append("")
        
        return '\n'.join(cleaned)

    async def test_capability(self, code: str) -> Tuple[bool, str]:
        """Test the capability code (syntax check).
        
        Args:
            code: Python code to test
            
        Returns:
            Tuple of (success, error_message)
        """
        try:
            # Syntax check with compile
            compile(code, "<capability>", "exec")
            return True, ""
        except SyntaxError as exc:
            return False, f"Syntax error at line {exc.lineno}: {exc.msg}"
        except Exception as exc:
            return False, str(exc)

    async def register_capability(self, name: str, code: str) -> Tuple[bool, str]:
        """Save and hot-reload the new capability.
        
        Args:
            name: Capability name
            code: Python code
            
        Returns:
            Tuple of (success, message)
        """
        file_name = f"{name}_tool.py"
        file_path = self.capabilities_dir / file_name
        
        try:
            # Save the file
            file_path.write_text(code, encoding="utf-8")
            logger.info("Saved capability: %s", file_path)
            
            # Hot reload
            module_name = f"chintu_backend.capabilities.generated.{name}_tool"
            
            # Remove from cache if exists
            if module_name in sys.modules:
                del sys.modules[module_name]
            
            # Add parent to path if needed
            parent = str(self.capabilities_dir.parent)
            if parent not in sys.path:
                sys.path.insert(0, parent)
            
            # Import the module (triggers register_capability)
            module = importlib.import_module(module_name)
            
            return True, f"Registered new capability: {name}"
            
        except Exception as exc:
            logger.warning("Registration failed: %s", exc)
            return False, str(exc)

    async def build(self, query: str, max_retries: int = 3) -> Dict[str, Any]:
        """Full pipeline: research → draft → test → register.
        
        Args:
            query: User's original request
            max_retries: Maximum fix attempts
            
        Returns:
            Dict with success status and details
        """
        logger.info("Capability Factory: Building tool for '%s'", query[:50])
        
        # 1. Research
        research = await self.research(query)
        logger.info("Research: using %s", research.get("library", "standard lib"))
        
        # 2. Draft
        draft = await self.draft_capability(query, research)
        code = draft["code"]
        name = draft["name"]
        
        # 3. Test with retries
        success = False
        error = ""
        
        for attempt in range(max_retries):
            success, error = await self.test_capability(code)
            if success:
                break
            
            logger.warning("Attempt %d failed: %s", attempt + 1, error)
            
            # Try to fix the code
            code = await self._fix_code(code, error)
        
        if not success:
            return {
                "success": False,
                "error": f"Failed after {max_retries} attempts: {error}",
                "name": name,
            }
        
        # 4. Register
        reg_success, reg_msg = await self.register_capability(name, code)
        
        return {
            "success": reg_success,
            "message": reg_msg,
            "name": name,
            "library": research.get("library"),
            "file": str(self.capabilities_dir / f"{name}_tool.py"),
        }

    async def _fix_code(self, code: str, error: str) -> str:
        """Attempt to fix broken code using LLM."""
        llm = self._get_llm()
        if not llm:
            return code
        
        prompt = f"""Fix this Python code error:

Error: {error}

Code:
{code}

Return ONLY the fixed complete code, no explanation."""

        try:
            fixed = await llm.query(prompt)
            # Extract code from response
            if "```python" in fixed:
                fixed = fixed.split("```python")[1].split("```")[0]
            elif "```" in fixed:
                fixed = fixed.split("```")[1].split("```")[0]
            return fixed.strip()
        except Exception:
            return code

    def list_generated(self) -> List[Dict[str, str]]:
        """List all auto-generated capabilities."""
        capabilities = []
        
        for file_path in self.capabilities_dir.glob("*_tool.py"):
            try:
                content = file_path.read_text(encoding="utf-8")
                # Extract name from first docstring line
                match = re.search(r'"""Auto-generated capability: (.+?)\n', content)
                name = match.group(1) if match else file_path.stem
                
                capabilities.append({
                    "name": file_path.stem.replace("_tool", ""),
                    "description": name,
                    "path": str(file_path),
                    "created": datetime.fromtimestamp(
                        file_path.stat().st_mtime
                    ).isoformat(),
                })
            except Exception:
                pass
        
        return capabilities


# Ensure generated capabilities __init__.py exists
def _ensure_capabilities_init():
    try:
        path = Path(__file__).parent.parent / "capabilities"
        path.mkdir(exist_ok=True)
        init_file = path / "__init__.py"
        if not init_file.exists():
            init_file.write_text('"""Auto-generated capabilities."""\n')
        
        gen_path = path / "generated"
        gen_path.mkdir(exist_ok=True)
        gen_init = gen_path / "__init__.py"
        if not gen_init.exists():
            gen_init.write_text('"""Auto-generated capabilities by Capability Factory."""\n')
    except Exception:
        pass

_ensure_capabilities_init()


# Singleton
_factory: Optional[CapabilityFactory] = None


def get_capability_factory() -> CapabilityFactory:
    """Get or create the global Capability Factory instance."""
    global _factory
    if _factory is None:
        _factory = CapabilityFactory()
    return _factory
