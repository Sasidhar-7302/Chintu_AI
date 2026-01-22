"""
Files module for Chintu AI Assistant.
Provides local file reading and manipulation capabilities.
"""

from .file_handler import FileHandler, read_file, list_directory, get_file_info
from .file_capabilities import register_file_capabilities

__all__ = [
    "FileHandler",
    "read_file",
    "list_directory",
    "get_file_info",
    "register_file_capabilities",
]
