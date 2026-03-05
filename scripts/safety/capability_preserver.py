"""
Capability Preserver for Chintu AI Refactoring

This module ensures that no capabilities, skills, or functionality 
are lost during refactoring by creating detailed capability maps
and preserving all existing functionality.
"""

import asyncio
import importlib
import inspect
import json
import ast
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable, Set
import logging

logger = logging.getLogger(__name__)

class CapabilityPreserver:
    """Maps and preserves all existing capabilities during refactoring."""
    
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.capabilities_map = {}
        self.skill_map = {}
        self.function_map = {}
        self.dependency_graph = {}
        
    async def create_capability_inventory(self) -> Dict[str, Any]:
        """Create complete inventory of all capabilities and skills."""
        logger.info("Creating capability inventory...")
        
        inventory = {
            "timestamp": datetime.now().isoformat(),
            "skills": await self._map_all_skills(),
            "capabilities": await self._map_all_capabilities(),
            "functions": await self._map_all_functions(),
            "dependencies": await self._map_dependencies(),
            "api_endpoints": await self._map_api_endpoints(),
            "integrations": await self._map_integrations()
        }
        
        # Save inventory
        inventory_file = self.repo_root / "scripts/safety/capability_inventory.json"
        with open(inventory_file, 'w') as f:
            json.dump(inventory, f, indent=2)
            
        logger.info(f"Capability inventory created: {len(inventory['skills'])} skills, "
                   f"{len(inventory['capabilities'])} capabilities, "
                   f"{len(inventory['functions'])} functions")
        
        return inventory
        
    async def _map_all_skills(self) -> Dict[str, Any]:
        """Map all skills in the skills directory."""
        skills_info = {}
        skills_dir = self.repo_root / "skills"
        
        if not skills_dir.exists():
            return skills_info
            
        for skill_dir in skills_dir.iterdir():
            if skill_dir.is_dir():
                skill_name = skill_dir.name
                skill_info = {
                    "path": str(skill_dir),
                    "files": [],
                    "functions": [],
                    "classes": [],
                    "imports": [],
                    "dependencies": [],
                    "status": "unknown"
                }
                
                # Map all files in skill directory
                for file_path in skill_dir.rglob("*"):
                    if file_path.is_file():
                        skill_info["files"].append(str(file_path.relative_to(skill_dir)))
                        
                        # If it's a Python file, extract functions/classes
                        if file_path.suffix == ".py":
                            file_info = await self._analyze_python_file(file_path)
                            skill_info["functions"].extend(file_info["functions"])
                            skill_info["classes"].extend(file_info["classes"])
                            skill_info["imports"].extend(file_info["imports"])
                            skill_info["dependencies"].extend(file_info["dependencies"])
                
                skills_info[skill_name] = skill_info
                
        return skills_info
        
    async def _map_all_capabilities(self) -> Dict[str, Any]:
        """Map all capabilities in the backend."""
        capabilities_info = {}
        
        # Check multiple capability locations
        capability_dirs = [
            self.repo_root / "chintu_backend" / "capabilities",
            self.repo_root / "chintu_backend" / "automation" / "capabilities",
            self.repo_root / "chintu_backend" / "security",
            self.repo_root / "chintu_backend" / "integrations"
        ]
        
        for cap_dir in capability_dirs:
            if cap_dir.exists():
                for py_file in cap_dir.rglob("*.py"):
                    if py_file.name.startswith("_"):
                        continue
                        
                    capability_name = py_file.stem
                    file_info = await self._analyze_python_file(py_file)
                    
                    capabilities_info[capability_name] = {
                        "path": str(py_file),
                        "directory": str(cap_dir),
                        "functions": file_info["functions"],
                        "classes": file_info["classes"],
                        "imports": file_info["imports"],
                        "dependencies": file_info["dependencies"]
                    }
                    
        return capabilities_info
        
    async def _map_all_functions(self) -> Dict[str, Any]:
        """Map all public functions across the codebase."""
        functions_info = {}
        
        # Search in critical directories
        search_dirs = [
            self.repo_root / "chintu_backend",
            self.repo_root / "scripts",
            self.repo_root / "tests"
        ]
        
        for search_dir in search_dirs:
            if search_dir.exists():
                for py_file in search_dir.rglob("*.py"):
                    if py_file.name.startswith("_"):
                        continue
                        
                    try:
                        file_info = await self._analyze_python_file(py_file)
                        module_name = str(py_file.relative_to(self.repo_root)).replace("/", ".")
                        
                        for func_info in file_info["functions"]:
                            func_name = f"{module_name[:-3]}.{func_info['name']}"  # Remove .py
                            functions_info[func_name] = {
                                "file": str(py_file),
                                "module": module_name[:-3],
                                "function": func_info['name'],
                                "signature": func_info['signature'],
                                "docstring": func_info['docstring'],
                                "is_async": func_info['is_async']
                            }
                    except Exception as e:
                        logger.warning(f"Failed to analyze {py_file}: {e}")
                        continue
                        
        return functions_info
        
    async def _analyze_python_file(self, file_path: Path) -> Dict[str, Any]:
        """Analyze a Python file to extract functions, classes, imports, etc."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            tree = ast.parse(content)
            info = {
                "functions": [],
                "classes": [],
                "imports": [],
                "dependencies": []
            }
            
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                    func_info = {
                        "name": node.name,
                        "signature": self._get_function_signature(node),
                        "docstring": ast.get_docstring(node) or "",
                        "is_async": isinstance(node, ast.AsyncFunctionDef),
                        "line_number": node.lineno
                    }
                    info["functions"].append(func_info)
                    
                elif isinstance(node, ast.ClassDef):
                    class_info = {
                        "name": node.name,
                        "docstring": ast.get_docstring(node) or "",
                        "line_number": node.lineno,
                        "methods": []
                    }
                    
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            class_info["methods"].append({
                                "name": item.name,
                                "signature": self._get_function_signature(item),
                                "is_async": isinstance(item, ast.AsyncFunctionDef)
                            })
                            
                    info["classes"].append(class_info)
                    
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            info["imports"].append(alias.name)
                    else:  # ImportFrom
                        module = node.module or ""
                        for alias in node.names:
                            full_import = f"{module}.{alias.name}" if module else alias.name
                            info["imports"].append(full_import)
                            
                            # Extract potential dependency
                            if module and not module.startswith("."):
                                info["dependencies"].append(module)
                                
            return info
            
        except Exception as e:
            logger.warning(f"Failed to analyze {file_path}: {e}")
            return {"functions": [], "classes": [], "imports": [], "dependencies": []}
            
    def _get_function_signature(self, node: ast.FunctionDef) -> str:
        """Get function signature as string."""
        args = []
        for arg in node.args.args:
            args.append(arg.arg)
            
        # Handle *args and **kwargs
        if node.args.vararg:
            args.append(f"*{node.args.vararg.arg}")
        if node.args.kwarg:
            args.append(f"**{node.args.kwarg.arg}")
            
        return f"{node.name}({', '.join(args)})"
        
    async def _map_dependencies(self) -> Dict[str, List[str]]:
        """Map import dependencies between modules."""
        dependency_graph = {}
        
        # Get all Python files
        py_files = list(self.repo_root.rglob("*.py"))
        
        for py_file in py_files:
            try:
                rel_path = str(py_file.relative_to(self.repo_root))
                module_name = rel_path.replace("/", ".").replace(".py", "")
                
                # Analyze imports
                file_info = await self._analyze_python_file(py_file)
                dependencies = []
                
                for imp in file_info["imports"]:
                    # Filter out standard library and built-in modules
                    if not self._is_stdlib_module(imp):
                        dependencies.append(imp)
                        
                dependency_graph[module_name] = dependencies
                
            except Exception as e:
                logger.warning(f"Failed to map dependencies for {py_file}: {e}")
                
        return dependency_graph
        
    def _is_stdlib_module(self, module_name: str) -> bool:
        """Check if module is standard library."""
        stdlib_modules = {
            'os', 'sys', 'json', 'asyncio', 'pathlib', 'datetime', 'typing',
            'logging', 'collections', 'dataclasses', 'abc', 'functools',
            'itertools', 'operator', 're', 'string', 'textwrap', 'copy',
            'pickle', 'shutil', 'tempfile', 'uuid', 'hashlib', 'hmac',
            'base64', 'urllib', 'http', 'email', 'sqlite3', 'csv', 'configparser',
            'argparse', 'getpass', 'subprocess', 'threading', 'multiprocessing',
            'queue', 'sched', 'contextlib', 'weakref', 'gc', 'inspect',
            'importlib', 'pkgutil', 'zipfile', 'tarfile', 'gzip', 'bz2', 'lzma',
            'zlib', 'math', 'random', 'statistics', 'decimal', 'fractions',
            'complex', 'array', 'struct', 'codecs', 'unicodedata', 'stringprep',
            'locale', 'platform', 'resource', 'select', 'selectors', 'mmap',
            'timeit', 'profile', 'pstats', 'cProfile', 'pdb', 'traceback',
            'sysconfig', 'test', 'unittest', 'doctest', 'pdb', 'bdb', 'cmd',
            'shlex', 'subprocess', 'socket', 'ssl', 'ipaddress', 'asyncio',
            'concurrent.futures', 'threading', 'multiprocessing', 'queue'
        }
        
        # Check if module starts with any stdlib module
        root_module = module_name.split('.')[0]
        return root_module in stdlib_modules
        
    async def _map_api_endpoints(self) -> List[Dict[str, Any]]:
        """Map API endpoints and routes."""
        endpoints = []
        
        # Look for route decorators and URL patterns
        search_dirs = [self.repo_root / "chintu_backend"]
        for search_dir in search_dirs:
            if search_dir.exists():
                for py_file in search_dir.rglob("*.py"):
                    try:
                        file_info = await self._analyze_python_file(py_file)
                        
                        for func_info in file_info["functions"]:
                            # Look for route indicators
                            docstring = func_info["docstring"].lower()
                            if any(keyword in docstring for keyword in ["route", "endpoint", "api"]):
                                endpoints.append({
                                    "file": str(py_file),
                                    "function": func_info["name"],
                                    "description": func_info["docstring"],
                                    "is_async": func_info["is_async"]
                                })
                                
                    except Exception as e:
                        logger.warning(f"Failed to analyze {py_file} for endpoints: {e}")
                        
        return endpoints
        
    async def _map_integrations(self) -> Dict[str, Any]:
        """Map external integrations and their configurations."""
        integrations = {}
        
        # Look for integration modules
        integrations_dir = self.repo_root / "chintu_backend" / "integrations"
        if integrations_dir.exists():
            for py_file in integrations_dir.glob("*.py"):
                integration_name = py_file.stem
                file_info = await self._analyze_python_file(py_file)
                
                integrations[integration_name] = {
                    "path": str(py_file),
                    "classes": [cls["name"] for cls in file_info["classes"]],
                    "functions": [func["name"] for func in file_info["functions"]],
                    "dependencies": file_info["dependencies"]
                }
                
        return integrations
        
    async def validate_capability_preservation(self, inventory: Dict[str, Any]) -> Dict[str, Any]:
        """Validate that all capabilities are preserved after changes."""
        logger.info("Validating capability preservation...")
        
        validation_result = {
            "timestamp": datetime.now().isoformat(),
            "validation_passed": True,
            "missing_skills": [],
            "missing_capabilities": [],
            "missing_functions": [],
            "dependency_breaks": [],
            "summary": {}
        }
        
        # Re-scan current state
        current_inventory = await self.create_capability_inventory()
        
        # Compare skill counts
        original_skills = set(inventory["skills"].keys())
        current_skills = set(current_inventory["skills"].keys())
        
        missing_skills = original_skills - current_skills
        validation_result["missing_skills"] = list(missing_skills)
        
        # Compare capabilities
        original_capabilities = set(inventory["capabilities"].keys())
        current_capabilities = set(current_inventory["capabilities"].keys())
        
        missing_capabilities = original_capabilities - current_capabilities
        validation_result["missing_capabilities"] = list(missing_capabilities)
        
        # Check for validation pass/fail
        if missing_skills or missing_capabilities:
            validation_result["validation_passed"] = False
            logger.error(f"Capability preservation validation failed: "
                        f"{len(missing_skills)} skills, {len(missing_capabilities)} capabilities missing")
        else:
            logger.info("Capability preservation validation passed")
            
        # Create summary
        validation_result["summary"] = {
            "original_skills": len(original_skills),
            "current_skills": len(current_skills),
            "original_capabilities": len(original_capabilities),
            "current_capabilities": len(current_capabilities),
            "skills_preserved": len(original_skills - missing_skills),
            "capabilities_preserved": len(original_capabilities - missing_capabilities)
        }
        
        return validation_result

# Global instance
capability_preserver = None

async def initialize_capability_preserver(repo_root: Path) -> CapabilityPreserver:
    """Initialize the global capability preserver."""
    global capability_preserver
    capability_preserver = CapabilityPreserver(repo_root)
    return capability_preserver

async def create_capability_inventory() -> Dict[str, Any]:
    """Create complete capability inventory."""
    if not capability_preserver:
        raise RuntimeError("Capability preserver not initialized")
    return await capability_preserver.create_capability_inventory()

async def validate_capability_preservation(original_inventory: Dict[str, Any]) -> Dict[str, Any]:
    """Validate that capabilities are preserved after refactoring."""
    if not capability_preserver:
        raise RuntimeError("Capability preserver not initialized")
    return await capability_preserver.validate_capability_preservation(original_inventory)

if __name__ == "__main__":
    async def main():
        repo_root = Path(__file__).resolve().parents[2]
        await initialize_capability_preserver(repo_root)
        inventory = await create_capability_inventory()
        print(json.dumps(inventory, indent=2))
"