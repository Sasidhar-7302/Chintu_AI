"""
Rollback Manager for Safe Chintu AI Refactoring

This module ensures zero-downtime refactoring by creating comprehensive
backups and rollback mechanisms before any code changes.
"""

import asyncio
import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger(__name__)

class RollbackManager:
    """Manages backups and rollbacks for safe refactoring."""
    
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.backup_dir = repo_root / "scripts/safety/backups"
        self.metadata_file = self.backup_dir / "backup_metadata.json"
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        
    async def create_comprehensive_backup(self) -> Dict[str, Any]:
        """Create complete backup of current working state."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_id = f"refactor_backup_{timestamp}"
        backup_path = self.backup_dir / backup_id
        
        logger.info(f"Creating comprehensive backup: {backup_id}")
        
        backup_metadata = {
            "backup_id": backup_id,
            "timestamp": timestamp,
            "created_at": datetime.now().isoformat(),
            "files_backed_up": [],
            "capabilities_status": {},
            "test_results": {},
            "configuration_snapshot": {}
        }
        
        # Backup critical directories
        critical_dirs = [
            "chintu_backend",
            "chintu_ui", 
            "skills",
            "tests",
            "scripts",
            "requirements.txt",
            "README.md"
        ]
        
        for dir_name in critical_dirs:
            source_path = self.repo_root / dir_name
            if source_path.exists():
                dest_path = backup_path / dir_name
                shutil.copytree(source_path, dest_path, dirs_exist_ok=True)
                backup_metadata["files_backed_up"].append(dir_name)
                logger.info(f"Backed up {dir_name}")
        
        # Capture current capability status
        backup_metadata["capabilities_status"] = await self._capture_capabilities_status()
        
        # Capture current test results
        backup_metadata["test_results"] = await self._capture_test_results()
        
        # Save configuration snapshot
        backup_metadata["configuration_snapshot"] = await self._capture_configuration()
        
        # Save metadata
        with open(self.metadata_file, 'w') as f:
            json.dump(backup_metadata, f, indent=2)
            
        logger.info(f"Backup created successfully: {backup_id}")
        return backup_metadata
        
    async def _capture_capabilities_status(self) -> Dict[str, Any]:
        """Capture current capabilities status."""
        capabilities_status = {
            "skill_count": 0,
            "capability_count": 0,
            "working_skills": [],
            "broken_skills": [],
            "dependency_status": {}
        }
        
        # Check skills directory
        skills_dir = self.repo_root / "skills"
        if skills_dir.exists():
            capabilities_status["skill_count"] = len(list(skills_dir.glob("*")))
            for skill_dir in skills_dir.iterdir():
                if skill_dir.is_dir():
                    skill_file = skill_dir / f"{skill_dir.name}.py"
                    if skill_file.exists():
                        capabilities_status["working_skills"].append(skill_dir.name)
                    else:
                        capabilities_status["broken_skills"].append(skill_dir.name)
        
        # Check backend capabilities
        backend_capabilities_dir = self.repo_root / "chintu_backend" / "capabilities"
        if backend_capabilities_dir.exists():
            capabilities_status["capability_count"] = len(list(backend_capabilities_dir.glob("*.py")))
            
        return capabilities_status
        
    async def _capture_test_results(self) -> Dict[str, Any]:
        """Capture current test status."""
        import subprocess
        
        test_results = {
            "last_test_run": None,
            "test_summary": {},
            "failed_tests": [],
            "test_coverage": None
        }
        
        try:
            # Run a quick test to verify current state
            result = await asyncio.create_subprocess_exec(
                "python", "-m", "pytest", "--tb=short", "-q",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await result.communicate()
            
            test_results["last_test_run"] = datetime.now().isoformat()
            test_results["test_exit_code"] = result.returncode
            test_results["test_output"] = stdout.decode()
            test_results["test_error"] = stderr.decode()
            
        except Exception as e:
            test_results["test_error"] = str(e)
            
        return test_results
        
    async def _capture_configuration(self) -> Dict[str, Any]:
        """Capture current configuration state."""
        config_snapshot = {
            "environment_vars": dict(__import__('os').environ),
            "python_version": __import__('sys').version,
            "installed_packages": {},
            "git_status": {},
            "disk_usage": {}
        }
        
        # Check pip packages
        try:
            result = await asyncio.create_subprocess_exec(
                "pip", "list", "--format=json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await result.communicate()
            if result.returncode == 0:
                import json
                packages = json.loads(stdout.decode())
                config_snapshot["installed_packages"] = {
                    pkg["name"]: pkg["version"] for pkg in packages
                }
        except:
            pass
            
        # Check git status
        try:
            result = await asyncio.create_subprocess_exec(
                "git", "status", "--porcelain",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await result.communicate()
            if result.returncode == 0:
                config_snapshot["git_status"] = {
                    "modified_files": stdout.decode().split('\n') if stdout else [],
                    "has_changes": len(stdout.decode().strip()) > 0
                }
        except:
            pass
            
        return config_snapshot
        
    async def validate_backup(self, backup_metadata: Dict[str, Any]) -> bool:
        """Validate that backup was created successfully."""
        try:
            backup_id = backup_metadata["backup_id"]
            backup_path = self.backup_dir / backup_id
            
            # Check backup directory exists
            if not backup_path.exists():
                return False
                
            # Check critical files exist
            critical_files = ["chintu_backend", "skills", "requirements.txt"]
            for file_name in critical_files:
                if not (backup_path / file_name).exists():
                    logger.error(f"Missing backup file: {file_name}")
                    return False
                    
            # Validate capabilities are intact
            if backup_metadata["capabilities_status"]["skill_count"] == 0:
                logger.error("No skills found in backup")
                return False
                
            logger.info(f"Backup validation successful: {backup_id}")
            return True
            
        except Exception as e:
            logger.error(f"Backup validation failed: {e}")
            return False
            
    async def create_skill_backup(self) -> Dict[str, Any]:
        """Create specific backup of skills to ensure no skill loss."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        skill_backup_id = f"skills_backup_{timestamp}"
        skill_backup_dir = self.backup_dir / skill_backup_id / "skills"
        
        skill_backup_metadata = {
            "backup_id": skill_backup_id,
            "timestamp": timestamp,
            "skills_backed_up": [],
            "skill_details": {},
            "dependencies": {}
        }
        
        # Create skills directory
        skill_backup_dir.mkdir(parents=True, exist_ok=True)
        
        # Backup each skill individually
        skills_dir = self.repo_root / "skills"
        if skills_dir.exists():
            for skill_dir in skills_dir.iterdir():
                if skill_dir.is_dir():
                    skill_name = skill_dir.name
                    dest_skill_dir = skill_backup_dir / skill_name
                    
                    # Copy entire skill directory
                    shutil.copytree(skill_dir, dest_skill_dir, dirs_exist_ok=True)
                    
                    # Record skill details
                    skill_backup_metadata["skills_backed_up"].append(skill_name)
                    skill_backup_metadata["skill_details"][skill_name] = {
                        "files": [f.name for f in skill_dir.rglob("*") if f.is_file()],
                        "has_executable": (skill_dir / f"{skill_name}.py").exists(),
                        "has_documentation": (skill_dir / "SKILL.md").exists(),
                        "has_requirements": (skill_dir / "requirements.txt").exists()
                    }
                    
                    logger.info(f"Backed up skill: {skill_name}")
        
        # Save skill-specific metadata
        skill_metadata_file = self.backup_dir / skill_backup_id / "skills_metadata.json"
        skill_metadata_file.parent.mkdir(parents=True, exist_ok=True)
        with open(skill_metadata_file, 'w') as f:
            json.dump(skill_backup_metadata, f, indent=2)
            
        logger.info(f"Skills backup created: {skill_backup_id}")
        return skill_backup_metadata

# Global instance
rollback_manager = None

async def initialize_rollback_manager(repo_root: Path) -> RollbackManager:
    """Initialize the global rollback manager."""
    global rollback_manager
    rollback_manager = RollbackManager(repo_root)
    return rollback_manager

async def create_safety_backups() -> Dict[str, Any]:
    """Create all necessary safety backups before refactoring."""
    if not rollback_manager:
        raise RuntimeError("Rollback manager not initialized")
        
    logger.info("Creating comprehensive safety backups...")
    
    # Create main backup
    main_backup = await rollback_manager.create_comprehensive_backup()
    
    # Create skills-specific backup
    skills_backup = await rollback_manager.create_skill_backup()
    
    # Validate both backups
    main_valid = await rollback_manager.validate_backup(main_backup)
    skills_valid = await rollback_manager.validate_backup(skills_backup)
    
    if not main_valid or not skills_valid:
        raise RuntimeError("Backup validation failed - aborting refactoring")
        
    logger.info("All safety backups created and validated successfully")
    return {
        "main_backup": main_backup,
        "skills_backup": skills_backup,
        "validation_passed": True
    }

if __name__ == "__main__":
    async def main():
        repo_root = Path(__file__).resolve().parents[2]
        await initialize_rollback_manager(repo_root)
        result = await create_safety_backups()
        print(json.dumps(result, indent=2))