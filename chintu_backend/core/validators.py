"""Input Validator and Prerequisite Checker.

Validates user inputs, checks prerequisites before actions,
and provides helpful guidance when things are missing.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from chintu_backend.core.config import get_config

logger = logging.getLogger(__name__)


class PrereqStatus(str, Enum):
    """Status of a prerequisite check."""
    OK = "ok"
    MISSING = "missing"
    OUTDATED = "outdated"
    ERROR = "error"
    NOT_CONFIGURED = "not_configured"


@dataclass
class PrereqResult:
    """Result of a prerequisite check."""
    name: str
    status: PrereqStatus
    message: str
    fix_instructions: Optional[str] = None
    auto_fixable: bool = False
    fix_command: Optional[str] = None


@dataclass
class ValidationResult:
    """Result of input validation."""
    valid: bool
    value: Any = None
    message: str = ""
    suggestions: List[str] = None
    
    def __post_init__(self):
        if self.suggestions is None:
            self.suggestions = []


class InputValidator:
    """Validates various types of user input with helpful feedback."""
    
    @staticmethod
    def validate_file_path(
        path: str, 
        must_exist: bool = True,
        allowed_extensions: Optional[List[str]] = None,
        allow_directory: bool = False,
    ) -> ValidationResult:
        """Validate a file path.
        
        Args:
            path: Path to validate
            must_exist: Whether file must exist
            allowed_extensions: Allowed file extensions (e.g., [".py", ".txt"])
            allow_directory: Whether directories are allowed
        """
        if not path or not path.strip():
            return ValidationResult(False, message="Path cannot be empty")
        
        # Clean path
        clean_path = path.strip().strip('"').strip("'")
        clean_path = os.path.expanduser(clean_path)
        clean_path = os.path.expandvars(clean_path)
        
        p = Path(clean_path)
        
        # Check existence
        if must_exist and not p.exists():
            suggestions = []
            # Try to find similar files
            if p.parent.exists():
                similar = list(p.parent.glob(f"*{p.suffix}"))[:3]
                suggestions = [str(s) for s in similar]
            return ValidationResult(
                False, 
                message=f"Path does not exist: {clean_path}",
                suggestions=suggestions
            )
        
        # Check if directory
        if p.exists() and p.is_dir() and not allow_directory:
            return ValidationResult(
                False,
                message="Expected a file, but got a directory"
            )
        
        # Check extension
        if allowed_extensions and p.suffix.lower() not in [e.lower() for e in allowed_extensions]:
            return ValidationResult(
                False,
                message=f"File must have one of these extensions: {', '.join(allowed_extensions)}",
                suggestions=[f"Try a {allowed_extensions[0]} file"]
            )
        
        return ValidationResult(True, value=str(p.resolve()))

    @staticmethod
    def validate_url(url: str) -> ValidationResult:
        """Validate a URL."""
        if not url or not url.strip():
            return ValidationResult(False, message="URL cannot be empty")
        
        url = url.strip()
        
        # Basic URL pattern
        url_pattern = r'^(https?://)?[\w\-]+(\.[\w\-]+)+[^\s]*$'
        
        if not re.match(url_pattern, url, re.IGNORECASE):
            return ValidationResult(
                False, 
                message="That doesn't look like a valid URL",
                suggestions=["Try starting with https://"]
            )
        
        # Add https if missing
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        return ValidationResult(True, value=url)

    @staticmethod
    def validate_email(email: str) -> ValidationResult:
        """Validate an email address."""
        if not email or not email.strip():
            return ValidationResult(False, message="Email cannot be empty")
        
        email = email.strip().lower()
        
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        
        if not re.match(email_pattern, email):
            return ValidationResult(
                False,
                message="That doesn't look like a valid email address",
                suggestions=["Email should be like: name@example.com"]
            )
        
        return ValidationResult(True, value=email)

    @staticmethod
    def validate_number(
        value: str,
        min_value: Optional[float] = None,
        max_value: Optional[float] = None,
        allow_float: bool = True,
    ) -> ValidationResult:
        """Validate a numeric input."""
        if not value or not str(value).strip():
            return ValidationResult(False, message="Please provide a number")
        
        try:
            if allow_float:
                num = float(str(value).strip())
            else:
                num = int(str(value).strip())
        except ValueError:
            return ValidationResult(
                False,
                message="That's not a valid number",
                suggestions=["Enter a number like 42 or 3.14"]
            )
        
        if min_value is not None and num < min_value:
            return ValidationResult(
                False,
                message=f"Number must be at least {min_value}"
            )
        
        if max_value is not None and num > max_value:
            return ValidationResult(
                False,
                message=f"Number must be at most {max_value}"
            )
        
        return ValidationResult(True, value=num)

    @staticmethod
    def validate_choice(
        value: str,
        choices: List[str],
        case_sensitive: bool = False,
    ) -> ValidationResult:
        """Validate a choice from a list of options."""
        if not value or not value.strip():
            return ValidationResult(
                False,
                message="Please choose an option",
                suggestions=choices[:5]
            )
        
        value = value.strip()
        
        # Check for numeric choice
        try:
            idx = int(value) - 1
            if 0 <= idx < len(choices):
                return ValidationResult(True, value=choices[idx])
        except ValueError:
            pass
        
        # Check for text match
        for choice in choices:
            if case_sensitive:
                if value == choice:
                    return ValidationResult(True, value=choice)
            else:
                if value.lower() == choice.lower():
                    return ValidationResult(True, value=choice)
        
        # Check for partial match
        partial_matches = [c for c in choices if value.lower() in c.lower()]
        if len(partial_matches) == 1:
            return ValidationResult(True, value=partial_matches[0])
        
        return ValidationResult(
            False,
            message=f"'{value}' is not a valid option",
            suggestions=choices[:5]
        )

    @staticmethod
    def validate_json(value: str) -> ValidationResult:
        """Validate JSON input."""
        import json
        
        if not value or not value.strip():
            return ValidationResult(False, message="Please provide JSON data")
        
        try:
            parsed = json.loads(value.strip())
            return ValidationResult(True, value=parsed)
        except json.JSONDecodeError as exc:
            return ValidationResult(
                False,
                message=f"Invalid JSON: {exc.msg}",
                suggestions=["Make sure to use double quotes for strings"]
            )


class PrerequisiteChecker:
    """Checks prerequisites before performing actions."""
    
    def __init__(self):
        self.config = get_config()
        self._cache: Dict[str, PrereqResult] = {}
        self._cache_time: float = 0
    
    def check_all(self) -> List[PrereqResult]:
        """Check all common prerequisites."""
        results = [
            self.check_python(),
            self.check_pip_packages(),
            self.check_ollama(),
            self.check_docker(),
            self.check_audio(),
            self.check_disk_space(),
            self.check_internet(),
        ]
        return results
    
    def check_python(self) -> PrereqResult:
        """Check Python version."""
        import sys
        version = sys.version_info
        
        if version.major < 3 or (version.major == 3 and version.minor < 10):
            return PrereqResult(
                name="Python",
                status=PrereqStatus.OUTDATED,
                message=f"Python {version.major}.{version.minor} found, need 3.10+",
                fix_instructions="Install Python 3.10 or newer from python.org",
            )
        
        return PrereqResult(
            name="Python",
            status=PrereqStatus.OK,
            message=f"Python {version.major}.{version.minor}.{version.micro}",
        )
    
    def check_pip_packages(self) -> PrereqResult:
        """Check critical pip packages."""
        missing = []
        
        critical_packages = [
            "pydantic",
            "aiohttp",
            "sounddevice",
            "pyautogui",
        ]
        
        for pkg in critical_packages:
            try:
                __import__(pkg)
            except ImportError:
                missing.append(pkg)
        
        if missing:
            return PrereqResult(
                name="Dependencies",
                status=PrereqStatus.MISSING,
                message=f"Missing packages: {', '.join(missing)}",
                fix_instructions=f"pip install {' '.join(missing)}",
                auto_fixable=True,
                fix_command=f"pip install {' '.join(missing)}",
            )
        
        return PrereqResult(
            name="Dependencies",
            status=PrereqStatus.OK,
            message="All critical packages installed",
        )
    
    def check_ollama(self) -> PrereqResult:
        """Check if Ollama is available."""
        try:
            import requests
            response = requests.get("http://localhost:11434/api/tags", timeout=2)
            if response.status_code == 200:
                models = response.json().get("models", [])
                return PrereqResult(
                    name="Ollama",
                    status=PrereqStatus.OK,
                    message=f"Ollama running with {len(models)} models",
                )
        except Exception:
            pass
        
        return PrereqResult(
            name="Ollama",
            status=PrereqStatus.MISSING,
            message="Ollama not running",
            fix_instructions="Start Ollama with: ollama serve",
            auto_fixable=True,
            fix_command="ollama serve",
        )
    
    def check_docker(self) -> PrereqResult:
        """Check if Docker is available."""
        if not shutil.which("docker"):
            return PrereqResult(
                name="Docker",
                status=PrereqStatus.MISSING,
                message="Docker not installed",
                fix_instructions="Install Docker Desktop from docker.com",
            )
        
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0:
                return PrereqResult(
                    name="Docker",
                    status=PrereqStatus.OK,
                    message="Docker is running",
                )
            else:
                return PrereqResult(
                    name="Docker",
                    status=PrereqStatus.ERROR,
                    message="Docker installed but not running",
                    fix_instructions="Start Docker Desktop",
                )
        except Exception:
            return PrereqResult(
                name="Docker",
                status=PrereqStatus.ERROR,
                message="Docker check failed",
            )
    
    def check_audio(self) -> PrereqResult:
        """Check audio device availability."""
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            input_devices = [d for d in devices if d.get("max_input_channels", 0) > 0]
            output_devices = [d for d in devices if d.get("max_output_channels", 0) > 0]
            
            if not input_devices:
                return PrereqResult(
                    name="Audio",
                    status=PrereqStatus.MISSING,
                    message="No microphone detected",
                    fix_instructions="Connect a microphone",
                )
            
            if not output_devices:
                return PrereqResult(
                    name="Audio",
                    status=PrereqStatus.MISSING,
                    message="No speakers detected",
                    fix_instructions="Connect speakers or headphones",
                )
            
            return PrereqResult(
                name="Audio",
                status=PrereqStatus.OK,
                message=f"{len(input_devices)} mics, {len(output_devices)} outputs",
            )
        except Exception as exc:
            return PrereqResult(
                name="Audio",
                status=PrereqStatus.ERROR,
                message=f"Audio check failed: {exc}",
            )
    
    def check_disk_space(self, min_gb: float = 5.0) -> PrereqResult:
        """Check available disk space."""
        try:
            import shutil
            total, used, free = shutil.disk_usage(self.config.data_dir)
            free_gb = free / (1024 ** 3)
            
            if free_gb < min_gb:
                return PrereqResult(
                    name="Disk Space",
                    status=PrereqStatus.ERROR,
                    message=f"Only {free_gb:.1f}GB free, need {min_gb}GB",
                    fix_instructions="Free up disk space",
                )
            
            return PrereqResult(
                name="Disk Space",
                status=PrereqStatus.OK,
                message=f"{free_gb:.1f}GB available",
            )
        except Exception as exc:
            return PrereqResult(
                name="Disk Space",
                status=PrereqStatus.ERROR,
                message=f"Check failed: {exc}",
            )
    
    def check_internet(self) -> PrereqResult:
        """Check internet connectivity."""
        try:
            import socket
            socket.create_connection(("8.8.8.8", 53), timeout=3)
            return PrereqResult(
                name="Internet",
                status=PrereqStatus.OK,
                message="Connected",
            )
        except Exception:
            return PrereqResult(
                name="Internet",
                status=PrereqStatus.ERROR,
                message="No internet connection",
                fix_instructions="Check your network connection",
            )
    
    def check_for_action(self, action: str) -> Tuple[bool, List[PrereqResult]]:
        """Check prerequisites for a specific action.
        
        Args:
            action: Action name (e.g., "browser", "sandbox", "voice")
            
        Returns:
            Tuple of (all_ok, list_of_issues)
        """
        action_prereqs = {
            "browser": [self.check_pip_packages],
            "sandbox": [self.check_docker],
            "voice": [self.check_audio, self.check_pip_packages],
            "llm": [self.check_ollama],
            "vision": [self.check_ollama],
            "file": [self.check_disk_space],
        }
        
        checks = action_prereqs.get(action, [])
        results = [check() for check in checks]
        issues = [r for r in results if r.status != PrereqStatus.OK]
        
        return len(issues) == 0, issues
    
    def get_summary(self) -> str:
        """Get a formatted summary of all prerequisite checks."""
        results = self.check_all()
        
        lines = ["System Status:"]
        for r in results:
            icon = "✅" if r.status == PrereqStatus.OK else "❌"
            lines.append(f"  {icon} {r.name}: {r.message}")
            if r.fix_instructions and r.status != PrereqStatus.OK:
                lines.append(f"      Fix: {r.fix_instructions}")
        
        return "\n".join(lines)


# Singleton instances
_validator: Optional[InputValidator] = None
_prereq_checker: Optional[PrerequisiteChecker] = None


def get_input_validator() -> InputValidator:
    """Get the global Input Validator."""
    global _validator
    if _validator is None:
        _validator = InputValidator()
    return _validator


def get_prerequisite_checker() -> PrerequisiteChecker:
    """Get the global Prerequisite Checker."""
    global _prereq_checker
    if _prereq_checker is None:
        _prereq_checker = PrerequisiteChecker()
    return _prereq_checker
