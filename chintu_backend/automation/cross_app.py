"""
Cross-App Data Transfer for Chintu AI Assistant.
Moves data between applications using clipboard and file-based methods.
"""

import logging
import json
import csv
import io
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class DataFormat(Enum):
    """Supported data formats."""
    TEXT = "text"
    JSON = "json"
    CSV = "csv"
    TABLE = "table"
    HTML = "html"


@dataclass
class DataPackage:
    """A package of data being transferred."""
    content: str
    format: DataFormat
    source: str
    metadata: Dict[str, Any] = None
    
    def to_text(self) -> str:
        """Convert to plain text."""
        return self.content
    
    def to_json(self) -> str:
        """Convert to JSON."""
        if self.format == DataFormat.JSON:
            return self.content
        return json.dumps({"content": self.content, "source": self.source})
    
    def to_csv(self) -> str:
        """Convert to CSV if possible."""
        if self.format == DataFormat.CSV:
            return self.content
        if self.format == DataFormat.TABLE:
            return self._table_to_csv()
        return self.content
    
    def _table_to_csv(self) -> str:
        """Convert table format to CSV."""
        lines = self.content.strip().split('\n')
        output = io.StringIO()
        writer = csv.writer(output)
        for line in lines:
            cells = [c.strip() for c in line.split('|') if c.strip()]
            if cells:
                writer.writerow(cells)
        return output.getvalue()


class DataTransfer:
    """
    Handles data transfer between applications.
    Supports clipboard, file, and direct transfer methods.
    """
    
    def __init__(self):
        self._last_package: Optional[DataPackage] = None
        self._buffer: Dict[str, DataPackage] = {}
    
    def capture_clipboard(self) -> Optional[DataPackage]:
        """Capture data from clipboard."""
        try:
            import pyperclip
            content = pyperclip.paste()
            
            if not content:
                return None
            
            # Detect format
            format_type = self._detect_format(content)
            
            package = DataPackage(
                content=content,
                format=format_type,
                source="clipboard"
            )
            self._last_package = package
            
            return package
            
        except ImportError:
            logger.warning("pyperclip not available")
            return None
        except Exception as e:
            logger.error(f"Failed to capture clipboard: {e}")
            return None
    
    def _detect_format(self, content: str) -> DataFormat:
        """Detect the format of content."""
        content = content.strip()
        
        # Try JSON
        try:
            json.loads(content)
            return DataFormat.JSON
        except:
            pass
        
        # Check for table-like structure
        lines = content.split('\n')
        if len(lines) > 1:
            pipe_count = sum(1 for line in lines if '|' in line)
            if pipe_count > len(lines) / 2:
                return DataFormat.TABLE
            
            comma_count = sum(1 for line in lines if ',' in line)
            if comma_count > len(lines) / 2:
                return DataFormat.CSV
        
        # Check for HTML
        if '<' in content and '>' in content:
            return DataFormat.HTML
        
        return DataFormat.TEXT
    
    def to_clipboard(self, package: DataPackage, format_as: Optional[DataFormat] = None) -> bool:
        """
        Copy data to clipboard.
        
        Args:
            package: The data package to copy
            format_as: Optionally convert to a different format
            
        Returns:
            True if successful
        """
        try:
            import pyperclip
            
            if format_as == DataFormat.JSON:
                content = package.to_json()
            elif format_as == DataFormat.CSV:
                content = package.to_csv()
            else:
                content = package.to_text()
            
            pyperclip.copy(content)
            logger.info(f"Copied to clipboard: {len(content)} chars")
            return True
            
        except ImportError:
            logger.warning("pyperclip not available")
            return False
        except Exception as e:
            logger.error(f"Failed to copy to clipboard: {e}")
            return False
    
    def to_file(self, package: DataPackage, path: str, format_as: Optional[DataFormat] = None) -> bool:
        """
        Save data to a file.
        
        Args:
            package: The data package to save
            path: File path to save to
            format_as: Optionally convert to a different format
            
        Returns:
            True if successful
        """
        try:
            file_path = Path(path)
            
            # Create directory if needed
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Convert format if needed
            if format_as == DataFormat.JSON or file_path.suffix == '.json':
                content = package.to_json()
            elif format_as == DataFormat.CSV or file_path.suffix == '.csv':
                content = package.to_csv()
            else:
                content = package.to_text()
            
            file_path.write_text(content, encoding='utf-8')
            logger.info(f"Saved to file: {path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save to file: {e}")
            return False
    
    def from_file(self, path: str) -> Optional[DataPackage]:
        """
        Read data from a file.
        
        Args:
            path: File path to read from
            
        Returns:
            DataPackage if successful
        """
        try:
            file_path = Path(path)
            
            if not file_path.exists():
                logger.warning(f"File not found: {path}")
                return None
            
            content = file_path.read_text(encoding='utf-8')
            format_type = self._detect_format(content)
            
            # Use file extension as hint
            if file_path.suffix == '.json':
                format_type = DataFormat.JSON
            elif file_path.suffix == '.csv':
                format_type = DataFormat.CSV
            elif file_path.suffix == '.html':
                format_type = DataFormat.HTML
            
            return DataPackage(
                content=content,
                format=format_type,
                source=f"file:{path}"
            )
            
        except Exception as e:
            logger.error(f"Failed to read file: {e}")
            return None
    
    def from_browser(self) -> Optional[DataPackage]:
        """Capture data from browser page."""
        try:
            from ..browser.browser_controller import get_browser_controller
            
            controller = get_browser_controller()
            if not controller.is_open:
                return None
            
            content = controller.get_page_content(max_length=5000)
            page_info = controller.get_page_info()
            
            return DataPackage(
                content=content,
                format=DataFormat.TEXT,
                source=f"browser:{page_info.url}",
                metadata={"title": page_info.title, "url": page_info.url}
            )
            
        except Exception as e:
            logger.error(f"Failed to capture from browser: {e}")
            return None
    
    def store(self, name: str, package: DataPackage):
        """Store a data package in the buffer."""
        self._buffer[name] = package
        logger.info(f"Stored data package: {name}")
    
    def retrieve(self, name: str) -> Optional[DataPackage]:
        """Retrieve a data package from the buffer."""
        return self._buffer.get(name)
    
    def list_stored(self) -> List[str]:
        """List all stored data packages."""
        return list(self._buffer.keys())


# Global instance
_data_transfer: Optional[DataTransfer] = None


def get_data_transfer() -> DataTransfer:
    """Get the global data transfer instance."""
    global _data_transfer
    if _data_transfer is None:
        _data_transfer = DataTransfer()
    return _data_transfer
