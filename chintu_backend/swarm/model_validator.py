"""
Model Roster Validator for Chintu v5.1

Validates that required Ollama models are available at startup.
Can optionally pull missing models.

Required models for v5.1:
- qwen2.5:1.5b (Router, ~1.2GB)
- llama3.1:8b (Planner, ~4.8GB)  
- qwen2.5-coder:7b (Coder, ~4.5GB)
- phi3.5:mini (Researcher, ~2.4GB)
"""

import logging
import subprocess
import re
from dataclasses import dataclass
from typing import List, Optional, Dict, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class ModelStatus(Enum):
    """Status of a model in the roster."""
    AVAILABLE = "available"
    MISSING = "missing"
    PULLING = "pulling"
    ERROR = "error"


@dataclass
class ModelInfo:
    """Information about a model."""
    name: str
    role: str
    size_mb: int
    status: ModelStatus
    error: Optional[str] = None


@dataclass
class RosterValidation:
    """Result of roster validation."""
    all_available: bool
    models: List[ModelInfo]
    missing_count: int
    total_size_mb: int
    message: str


class ModelRosterValidator:
    """
    Validates and manages the model roster for the swarm system.
    """
    
    # v5.1 Required model roster
    REQUIRED_MODELS = {
        "qwen2.5:1.5b": {"role": "Router", "size_mb": 1200},
        "llama3.1:8b": {"role": "Planner", "size_mb": 4800},
        "qwen2.5-coder:7b": {"role": "Coder", "size_mb": 4500},
        "phi3.5:mini": {"role": "Researcher", "size_mb": 2400},
    }
    
    def __init__(self, ollama_host: str = "http://localhost:11434"):
        self.ollama_host = ollama_host
        self._available_models: List[str] = []
    
    def _get_installed_models(self) -> List[str]:
        """Get list of installed Ollama models."""
        try:
            result = subprocess.run(
                ["ollama", "list"],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                logger.warning(f"ollama list failed: {result.stderr}")
                return []
            
            # Parse output: NAME ID SIZE MODIFIED
            models = []
            for line in result.stdout.strip().split('\n')[1:]:  # Skip header
                if line.strip():
                    parts = line.split()
                    if parts:
                        models.append(parts[0])
            
            return models
        except FileNotFoundError:
            logger.error("Ollama CLI not found. Please install Ollama.")
            return []
        except Exception as e:
            logger.error(f"Failed to list models: {e}")
            return []
    
    def validate(self) -> RosterValidation:
        """
        Validate that all required models are available.
        
        Returns:
            RosterValidation with results
        """
        installed = self._get_installed_models()
        self._available_models = installed
        
        models: List[ModelInfo] = []
        missing_count = 0
        total_size = 0
        
        for model_name, info in self.REQUIRED_MODELS.items():
            # Check if model is installed (handle version variations)
            is_available = any(
                model_name in installed_model or installed_model.startswith(model_name.split(':')[0])
                for installed_model in installed
            )
            
            status = ModelStatus.AVAILABLE if is_available else ModelStatus.MISSING
            if not is_available:
                missing_count += 1
            else:
                total_size += info["size_mb"]
            
            models.append(ModelInfo(
                name=model_name,
                role=info["role"],
                size_mb=info["size_mb"],
                status=status
            ))
        
        all_available = missing_count == 0
        
        if all_available:
            message = f"All {len(models)} required models are available ({total_size}MB total)"
        else:
            missing_names = [m.name for m in models if m.status == ModelStatus.MISSING]
            message = f"{missing_count} model(s) missing: {', '.join(missing_names)}"
        
        return RosterValidation(
            all_available=all_available,
            models=models,
            missing_count=missing_count,
            total_size_mb=total_size,
            message=message
        )
    
    def pull_missing(self, models: Optional[List[str]] = None) -> Dict[str, Tuple[bool, str]]:
        """
        Pull missing models.
        
        Args:
            models: Specific models to pull, or None for all missing
            
        Returns:
            Dict mapping model name to (success, message)
        """
        results = {}
        validation = self.validate()
        
        to_pull = models or [m.name for m in validation.models if m.status == ModelStatus.MISSING]
        
        for model_name in to_pull:
            logger.info(f"Pulling model: {model_name}")
            try:
                result = subprocess.run(
                    ["ollama", "pull", model_name],
                    capture_output=True,
                    text=True,
                    timeout=600  # 10 minutes for large models
                )
                
                if result.returncode == 0:
                    results[model_name] = (True, f"Successfully pulled {model_name}")
                else:
                    results[model_name] = (False, f"Failed: {result.stderr}")
            except Exception as e:
                results[model_name] = (False, f"Error: {e}")
        
        return results
    
    def get_summary(self) -> str:
        """Get a human-readable summary of model roster status."""
        validation = self.validate()
        
        lines = [validation.message, ""]
        for model in validation.models:
            icon = "[OK]" if model.status == ModelStatus.AVAILABLE else "[X]"
            lines.append(f"  {icon} {model.name} ({model.role}, {model.size_mb}MB)")
        
        return "\n".join(lines)


# Global instance
_validator: Optional[ModelRosterValidator] = None


def get_model_validator() -> ModelRosterValidator:
    """Get or create the global model roster validator."""
    global _validator
    if _validator is None:
        _validator = ModelRosterValidator()
    return _validator

