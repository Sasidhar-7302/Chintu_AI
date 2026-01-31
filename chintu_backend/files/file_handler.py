"""
File Handler for Chintu AI Assistant.
Provides local file reading, listing, and info capabilities.
Supports: .txt, .md, .py, .json, .csv, .pdf, .docx
"""

import os
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

# Maximum file size to read (5MB)
MAX_FILE_SIZE = 5 * 1024 * 1024

# Supported text extensions
TEXT_EXTENSIONS = {'.txt', '.md', '.py', '.js', '.json', '.csv', '.xml', '.html', '.css', '.yaml', '.yml', '.log', '.ini', '.cfg'}


@dataclass
class FileInfo:
    """Information about a file."""
    path: str
    name: str
    extension: str
    size_bytes: int
    size_human: str
    modified: datetime
    is_dir: bool
    readable: bool


class FileHandler:
    """
    Handles local file operations for Chintu.
    Safely reads files with size limits and format support.
    """
    
    def __init__(self, allowed_dirs: Optional[List[str]] = None):
        """
        Initialize file handler.
        
        Args:
            allowed_dirs: List of allowed directories (None = allow common dirs)
        """
        self.allowed_dirs = allowed_dirs or self._get_default_allowed_dirs()
        self._pdf_available = self._check_pdf_support()
        self._docx_available = self._check_docx_support()
    
    def _get_default_allowed_dirs(self) -> List[str]:
        """Get default allowed directories."""
        home = Path.home()
        return [
            str(home / "Desktop"),
            str(home / "Documents"),
            str(home / "Downloads"),
            str(home),
        ]
    
    def _check_pdf_support(self) -> bool:
        """Check if PDF reading is available."""
        try:
            import PyPDF2
            return True
        except ImportError:
            try:
                import pdfplumber
                return True
            except ImportError:
                logger.warning("PDF support not available. Install: pip install PyPDF2 or pdfplumber")
                return False
    
    def _check_docx_support(self) -> bool:
        """Check if DOCX reading is available."""
        try:
            import docx
            return True
        except ImportError:
            logger.warning("DOCX support not available. Install: pip install python-docx")
            return False
    
    def _is_path_allowed(self, path: Path) -> bool:
        """Check if path is in allowed directories."""
        path_str = str(path.resolve())
        return any(path_str.startswith(d) for d in self.allowed_dirs)
    
    def _human_size(self, size_bytes: int) -> str:
        """Convert bytes to human readable size."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"
    
    def get_file_info(self, path: str) -> Optional[FileInfo]:
        """Get information about a file."""
        try:
            p = Path(path).expanduser().resolve()
            if not p.exists():
                return None
            
            stat = p.stat()
            return FileInfo(
                path=str(p),
                name=p.name,
                extension=p.suffix.lower(),
                size_bytes=stat.st_size,
                size_human=self._human_size(stat.st_size),
                modified=datetime.fromtimestamp(stat.st_mtime),
                is_dir=p.is_dir(),
                readable=os.access(p, os.R_OK)
            )
        except Exception as e:
            logger.error(f"Failed to get file info: {e}")
            return None
    
    def find_file(self, filename: str, search_dirs: Optional[List[str]] = None) -> Optional[str]:
        """
        Find a file by name in common directories.
        
        Args:
            filename: Name of file to find
            search_dirs: Directories to search (default: Desktop, Documents, Downloads)
            
        Returns:
            Full path if found, None otherwise
        """
        dirs = search_dirs or self.allowed_dirs
        
        for dir_path in dirs:
            try:
                dir_p = Path(dir_path)
                if not dir_p.exists():
                    continue
                
                # Direct match
                file_path = dir_p / filename
                if file_path.exists():
                    return str(file_path)
                
                # Case-insensitive search
                for f in dir_p.iterdir():
                    if f.name.lower() == filename.lower():
                        return str(f)
                        
            except Exception as e:
                logger.debug(f"Error searching {dir_path}: {e}")
                continue
        
        return None
    
    def read_text_file(self, path: Path) -> str:
        """Read a plain text file."""
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                return f.read()
        except UnicodeDecodeError:
            with open(path, 'r', encoding='latin-1') as f:
                return f.read()
    
    def read_pdf_file(self, path: Path) -> str:
        """Read a PDF file."""
        if not self._pdf_available:
            return "[PDF reading not available. Install: pip install PyPDF2]"
        
        try:
            # Try PyPDF2 first
            try:
                import PyPDF2
                text_parts = []
                with open(path, 'rb') as f:
                    reader = PyPDF2.PdfReader(f)
                    for page in reader.pages[:20]:  # Limit to first 20 pages
                        text_parts.append(page.extract_text() or "")
                return "\n\n".join(text_parts)
            except Exception:
                pass
            
            # Try pdfplumber
            import pdfplumber
            text_parts = []
            with pdfplumber.open(path) as pdf:
                for page in pdf.pages[:20]:
                    text_parts.append(page.extract_text() or "")
            return "\n\n".join(text_parts)
            
        except Exception as e:
            return f"[Failed to read PDF: {e}]"
    
    def read_docx_file(self, path: Path) -> str:
        """Read a DOCX file."""
        if not self._docx_available:
            return "[DOCX reading not available. Install: pip install python-docx]"
        
        try:
            import docx
            doc = docx.Document(path)
            paragraphs = [p.text for p in doc.paragraphs]
            return "\n\n".join(paragraphs)
        except Exception as e:
            return f"[Failed to read DOCX: {e}]"
    
    def read_file(self, path: str, max_chars: int = 10000) -> str:
        """
        Read a file and return its contents.
        
        Args:
            path: File path (absolute or relative to common dirs)
            max_chars: Maximum characters to return
            
        Returns:
            File contents or error message
        """
        # Find the file if not absolute
        p = Path(path).expanduser()
        if not p.is_absolute():
            found = self.find_file(path)
            if found:
                p = Path(found)
            else:
                return f"File not found: '{path}'. Try providing the full path or place the file in Desktop/Documents/Downloads."
        
        p = p.resolve()
        
        # Check existence
        if not p.exists():
            return f"File not found: '{path}'"
        
        if p.is_dir():
            return f"'{path}' is a directory, not a file. Use 'list files in {path}' to see its contents."
        
        # Check size
        info = self.get_file_info(str(p))
        if info and info.size_bytes > MAX_FILE_SIZE:
            return f"File is too large ({info.size_human}). Maximum size is 5MB."
        
        # Check permissions
        if not os.access(p, os.R_OK):
            return f"Cannot read file: permission denied."
        
        ext = p.suffix.lower()
        
        try:
            # Route to appropriate reader
            if ext == '.pdf':
                content = self.read_pdf_file(p)
            elif ext in {'.docx', '.doc'}:
                content = self.read_docx_file(p)
            elif ext in TEXT_EXTENSIONS or self._is_likely_text(p):
                content = self.read_text_file(p)
            else:
                return f"Unsupported file type: {ext}. Supported: txt, md, py, json, csv, pdf, docx"
            
            # Truncate if too long
            if len(content) > max_chars:
                content = content[:max_chars] + f"\n\n... [Truncated - showing first {max_chars} characters of {len(content)} total]"
            
            return content
            
        except Exception as e:
            logger.error(f"Failed to read file {path}: {e}")
            return f"Failed to read file: {e}"
    
    def _is_likely_text(self, path: Path) -> bool:
        """Check if a file is likely a text file."""
        try:
            with open(path, 'rb') as f:
                chunk = f.read(1024)
            # Check for null bytes (binary indicator)
            return b'\x00' not in chunk
        except:
            return False
    
    def list_directory(self, path: str, max_items: int = 30) -> str:
        """
        List contents of a directory.
        
        Args:
            path: Directory path
            max_items: Maximum items to list
            
        Returns:
            Formatted directory listing
        """
        p = Path(path).expanduser().resolve()
        
        if not p.exists():
            return f"Directory not found: '{path}'"
        
        if not p.is_dir():
            return f"'{path}' is a file, not a directory."
        
        try:
            items = list(p.iterdir())
            items.sort(key=lambda x: (not x.is_dir(), x.name.lower()))
            
            lines = [f"**Contents of {p.name}/** ({len(items)} items)\n"]
            
            for item in items[:max_items]:
                info = self.get_file_info(str(item))
                if info:
                    if info.is_dir:
                        lines.append(f"📁 {info.name}/")
                    else:
                        lines.append(f"📄 {info.name} ({info.size_human})")
            
            if len(items) > max_items:
                lines.append(f"\n... and {len(items) - max_items} more items")
            
            return "\n".join(lines)
            
        except PermissionError:
            return f"Cannot access directory: permission denied."
        except Exception as e:
            return f"Failed to list directory: {e}"


# Global instance
_file_handler: Optional[FileHandler] = None


def get_file_handler() -> FileHandler:
    """Get the global file handler instance."""
    global _file_handler
    if _file_handler is None:
        _file_handler = FileHandler()
    return _file_handler


def read_file(path: str, max_chars: int = 10000) -> str:
    """Convenience function to read a file."""
    return get_file_handler().read_file(path, max_chars)


def list_directory(path: str) -> str:
    """Convenience function to list a directory."""
    return get_file_handler().list_directory(path)


def get_file_info(path: str) -> Optional[FileInfo]:
    """Convenience function to get file info."""
    return get_file_handler().get_file_info(path)
