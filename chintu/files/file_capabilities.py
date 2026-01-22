"""
File capability handlers for Chintu AI Assistant.
Provides voice commands for reading files, listing directories, and clipboard.
"""

import re
import logging
from pathlib import Path
from typing import Dict, Any

from ..core.capabilities import Capability, CapabilityType, ActionResult

logger = logging.getLogger(__name__)


def handle_read_file(text: str, context: Dict[str, Any]) -> ActionResult:
    """
    Handle file reading requests.
    
    Examples:
        "Read file report.txt"
        "Open document notes.pdf"
        "Show me the contents of my resume.docx"
    """
    from .file_handler import read_file, get_file_handler
    
    # Extract filename from command
    query = text.strip()
    prefixes = [
        "read file ", "read the file ", "open file ", "open the file ",
        "show file ", "show the file ", "read ", "open document ",
        "show me the contents of ", "show contents of ", "what's in ",
        "what is in ", "display file ", "display ", "view file ", "view "
    ]
    
    filename = query
    for prefix in prefixes:
        if query.lower().startswith(prefix):
            filename = query[len(prefix):].strip()
            break
    
    # Clean up filename
    filename = filename.strip('"\'')
    
    if not filename:
        return ActionResult.fail(
            "Which file would you like me to read?",
            "read_file"
        )
    
    try:
        content = read_file(filename)
        
        # Check if it's an error message
        if content.startswith("File not found") or content.startswith("Cannot"):
            return ActionResult.fail(content, "read_file")
        
        # Format response
        response = f"**Contents of {Path(filename).name}:**\n\n{content}"
        
        return ActionResult.ok(
            response,
            {"filename": filename},
            "read_file"
        )
        
    except Exception as e:
        logger.error(f"Failed to read file: {e}")
        return ActionResult.fail(
            f"Failed to read file: {e}",
            "read_file"
        )


def handle_list_files(text: str, context: Dict[str, Any]) -> ActionResult:
    """
    Handle directory listing requests.
    
    Examples:
        "List files in Downloads"
        "What files are on my Desktop?"
        "Show me my Documents folder"
    """
    from .file_handler import list_directory
    
    # Extract directory path
    query = text.lower().strip()
    prefixes = [
        "list files in ", "list files on ", "show files in ", "show files on ",
        "what files are in ", "what files are on ", "what's in ",
        "what is in ", "show me ", "show my ", "list ", "files in ", "files on "
    ]
    
    path = query
    for prefix in prefixes:
        if query.startswith(prefix):
            path = query[len(prefix):].strip()
            break
    
    # Clean up common references
    path = path.rstrip("?").strip()
    path = re.sub(r"\s*(folder|directory)$", "", path, flags=re.IGNORECASE).strip()
    
    # Map common names to actual paths
    home = Path.home()
    path_map = {
        "desktop": str(home / "Desktop"),
        "my desktop": str(home / "Desktop"),
        "documents": str(home / "Documents"),
        "my documents": str(home / "Documents"),
        "downloads": str(home / "Downloads"),
        "my downloads": str(home / "Downloads"),
        "home": str(home),
        "my home": str(home),
    }
    
    path = path_map.get(path.lower(), path)
    
    if not path:
        path = str(home / "Desktop")  # Default to Desktop
    
    try:
        result = list_directory(path)
        
        if result.startswith("Directory not found") or result.startswith("Cannot"):
            return ActionResult.fail(result, "list_files")
        
        return ActionResult.ok(
            result,
            {"path": path},
            "list_files"
        )
        
    except Exception as e:
        logger.error(f"Failed to list directory: {e}")
        return ActionResult.fail(
            f"Failed to list directory: {e}",
            "list_files"
        )


def handle_clipboard_read(text: str, context: Dict[str, Any]) -> ActionResult:
    """
    Read the current clipboard contents.
    
    Examples:
        "What's in my clipboard?"
        "Show clipboard"
        "Paste that"
    """
    try:
        import pyperclip
        content = pyperclip.paste()
        
        if not content:
            return ActionResult.ok(
                "Your clipboard is empty.",
                {"content": None},
                "clipboard"
            )
        
        # Truncate if too long
        if len(content) > 2000:
            content = content[:2000] + f"\n\n... [Truncated - {len(content)} total characters]"
        
        return ActionResult.ok(
            f"**Clipboard contents:**\n\n{content}",
            {"content": content[:500]},
            "clipboard"
        )
        
    except ImportError:
        return ActionResult.fail(
            "Clipboard access not available. Install: pip install pyperclip",
            "clipboard"
        )
    except Exception as e:
        logger.error(f"Failed to read clipboard: {e}")
        return ActionResult.fail(
            f"Failed to read clipboard: {e}",
            "clipboard"
        )


def handle_clipboard_copy(text: str, context: Dict[str, Any]) -> ActionResult:
    """
    Copy text to clipboard.
    
    Examples:
        "Copy the last response"
        "Copy that to clipboard"
    """
    try:
        import pyperclip
        from ..core.state import get_state_manager
        
        state = get_state_manager().state
        
        # Get the last response (raw version if available)
        content = getattr(state, 'last_response_raw', None) or state.last_response
        
        if not content:
            return ActionResult.fail(
                "There's nothing to copy - I haven't responded yet.",
                "clipboard"
            )
        
        pyperclip.copy(content)
        
        preview = content[:100] + "..." if len(content) > 100 else content
        
        return ActionResult.ok(
            f"Copied to clipboard! Preview: {preview}",
            {"copied": True, "length": len(content)},
            "clipboard"
        )
        
    except ImportError:
        return ActionResult.fail(
            "Clipboard access not available. Install: pip install pyperclip",
            "clipboard"
        )
    except Exception as e:
        logger.error(f"Failed to copy to clipboard: {e}")
        return ActionResult.fail(
            f"Failed to copy: {e}",
            "clipboard"
        )


def handle_file_info(text: str, context: Dict[str, Any]) -> ActionResult:
    """
    Get information about a file.
    
    Examples:
        "File info for report.pdf"
        "How big is my resume.docx?"
    """
    from .file_handler import get_file_handler
    
    # Extract filename
    query = text.lower().strip()
    prefixes = [
        "file info for ", "file info ", "info about ", "info for ",
        "how big is ", "size of ", "details about ", "details for "
    ]
    
    filename = query
    for prefix in prefixes:
        if query.startswith(prefix):
            filename = query[len(prefix):].strip()
            break
    
    filename = filename.strip('"\'?')
    
    if not filename:
        return ActionResult.fail(
            "Which file would you like info about?",
            "file_info"
        )
    
    handler = get_file_handler()
    
    # Try to find the file
    found = handler.find_file(filename)
    if not found:
        return ActionResult.fail(
            f"File not found: '{filename}'",
            "file_info"
        )
    
    info = handler.get_file_info(found)
    if not info:
        return ActionResult.fail(
            f"Could not get info for '{filename}'",
            "file_info"
        )
    
    response = f"""**File: {info.name}**
- Size: {info.size_human}
- Type: {info.extension or 'Unknown'}
- Last Modified: {info.modified.strftime('%Y-%m-%d %H:%M')}
- Path: {info.path}"""
    
    return ActionResult.ok(
        response,
        {"filename": info.name, "size": info.size_bytes},
        "file_info"
    )


def register_file_capabilities(registry) -> None:
    """Register all file-related capabilities."""
    
    # Read File
    registry.register(Capability(
        name="read_file",
        triggers=[
            "read file", "open file", "show file", "read the file",
            "show me the contents", "display file", "view file",
            "what's in the file", "open document"
        ],
        handler=handle_read_file,
        requires_confirmation=False,
        description="read local files (txt, pdf, docx)",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=[
            "Read file notes.txt",
            "Open document report.pdf",
            "Show me the contents of resume.docx"
        ]
    ))
    
    # List Files
    registry.register(Capability(
        name="list_files",
        triggers=[
            "list files", "show files", "what files", "files in",
            "files on", "show my desktop", "show my documents",
            "show my downloads", "what's on my desktop"
        ],
        handler=handle_list_files,
        requires_confirmation=False,
        description="list files in a directory",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=[
            "List files in Downloads",
            "What files are on my Desktop?",
            "Show my Documents folder"
        ]
    ))
    
    # Clipboard Read
    registry.register(Capability(
        name="clipboard_read",
        triggers=[
            "what's in my clipboard", "what is in my clipboard",
            "show clipboard", "clipboard contents", "paste that",
            "what did i copy", "read clipboard"
        ],
        handler=handle_clipboard_read,
        requires_confirmation=False,
        description="show clipboard contents",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=[
            "What's in my clipboard?",
            "Show clipboard"
        ]
    ))
    
    # Clipboard Copy
    registry.register(Capability(
        name="clipboard_copy",
        triggers=[
            "copy that", "copy the response", "copy the last response",
            "copy to clipboard", "copy it"
        ],
        handler=handle_clipboard_copy,
        requires_confirmation=False,
        description="copy last response to clipboard",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=[
            "Copy that",
            "Copy the last response"
        ]
    ))
    
    # File Info
    registry.register(Capability(
        name="file_info",
        triggers=[
            "file info", "info about", "how big is", "size of",
            "details about file"
        ],
        handler=handle_file_info,
        requires_confirmation=False,
        description="get file information",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=[
            "File info for report.pdf",
            "How big is my resume.docx?"
        ]
    ))
    
    logger.info("Registered file capabilities")
