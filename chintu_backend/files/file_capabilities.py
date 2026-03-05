"""
File capability handlers for Chintu AI Assistant.
Provides voice commands for reading files, listing directories, and clipboard.
"""

import re
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional
import os
import shutil
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel, Field

from ..core.capabilities import Capability, CapabilityType, ActionResult

logger = logging.getLogger(__name__)

# ============================================================================
# SCHEMAS
# ============================================================================

class ReadFileSchema(BaseModel):
    filename: str = Field(..., description="Name or path of the file to read.")

class ListFilesSchema(BaseModel):
    directory: Optional[str] = Field(None, description="The directory to list (e.g. 'Downloads', 'Desktop').")

class FileInfoSchema(BaseModel):
    filename: str = Field(..., description="Name of the file to check.")

class FileManagementSchema(BaseModel):
    operation: str = Field(
        ...,
        description=(
            "Operation to perform: 'create_folder', 'quarantine_path', 'quarantine_dir_contents', "
            "'purge_verification_folder'."
        ),
    )
    path: str = Field(..., description="Target file or folder path.")

class WriteFileSchema(BaseModel):
    path: str = Field(..., description="Path of the file to write (must be inside the current workspace).")
    content: str = Field(..., description="File contents to write.")

class ClipboardReadSchema(BaseModel):
    pass

class ClipboardCopySchema(BaseModel):
    pass

class OrganizeDownloadsSchema(BaseModel):
    """Organize a directory (defaults to Downloads) into subfolders by file type."""

    directory: Optional[str] = Field(
        None,
        description="Optional directory to organize (default: Downloads).",
    )

class FileHunterSchema(BaseModel):
    """Find a file by fuzzy name/content and (optionally) open it."""

    query: str = Field(..., description="What you're looking for (keywords).")
    days_back: int = Field(14, ge=1, le=3650, description="How far back to search by modified date.")
    extension: Optional[str] = Field(None, description="Optional extension filter like '.pdf' or 'pdf'.")
    open_top: bool = Field(True, description="Open the best match when confidence is high.")


class RepoSearchSchema(BaseModel):
    """Search the current workspace/repo for a string using ripgrep."""

    query: str = Field(..., description="String or regex to search for.")
    first_only: bool = Field(True, description="Return only the first match path.")


class DependencySummarySchema(BaseModel):
    """Summarize project dependency manifests into major component bullets."""

    path: Optional[str] = Field(
        None,
        description="Optional dependency manifest path (requirements.txt, pyproject.toml, package.json).",
    )
    bullets: int = Field(5, ge=3, le=8, description="Number of summary bullets.")


def read_file(path: str) -> str:
    """Wrapper for file reads to allow tests to patch this module."""
    from .file_handler import read_file as _read_file
    return _read_file(path)


def _get_workspace_root(context: Dict[str, Any]) -> Optional[Path]:
    workspace = context.get("workspace_dir") or context.get("_agent_workspace")
    if not workspace:
        return None
    try:
        return Path(str(workspace)).expanduser().resolve()
    except Exception:
        return None


def _resolve_in_workspace(path_str: str, workspace_root: Optional[Path]) -> Optional[Path]:
    try:
        candidate = Path(path_str).expanduser()
        if workspace_root and not candidate.is_absolute():
            candidate = workspace_root / candidate
        candidate = candidate.resolve()
        if workspace_root:
            try:
                candidate.relative_to(workspace_root)
            except Exception:
                return None
        return candidate
    except Exception:
        return None


def handle_read_file(text: str, context: Dict[str, Any]) -> ActionResult:
    """Handle file reading requests."""
    
    filename = None
    validated = context.get("_validated_params")
    if validated and isinstance(validated, ReadFileSchema):
        filename = validated.filename
        
    if not filename:
        # Extract filename from command (Legacy)
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

    workspace_root = _get_workspace_root(context)
    if workspace_root:
        resolved = _resolve_in_workspace(filename, workspace_root)
        if not resolved:
            return ActionResult.fail(
                "That file is outside the current agent workspace.",
                "read_file",
            )
        filename = str(resolved)
    
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


def handle_write_file(text: str, context: Dict[str, Any]) -> ActionResult:
    """Write a file inside the current workspace (safe, workspace-only)."""
    path_str = None
    content = None

    validated = context.get("_validated_params")
    if validated and isinstance(validated, WriteFileSchema):
        path_str = validated.path
        content = validated.content

    # Minimal legacy parsing. For reliable behavior, callers should pass parameters via schema.
    if not path_str:
        match = re.search(
            r"(?:write file|write to file|save to file|create file at)\s+(.+)$",
            (text or "").strip(),
            re.IGNORECASE,
        )
        if match:
            path_str = match.group(1).strip().strip("\"'")

    if content is None:
        return ActionResult.fail(
            "What content should I write? Provide 'content' explicitly.",
            "write_file",
        )

    if not path_str:
        return ActionResult.fail("Which file path should I write to?", "write_file")

    workspace_root = _get_workspace_root(context) or Path.cwd().resolve()
    resolved = _resolve_in_workspace(path_str, workspace_root)
    if not resolved:
        return ActionResult.fail("That path is outside the current workspace.", "write_file")

    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(str(content), encoding="utf-8", errors="ignore")
    except Exception as exc:
        return ActionResult.fail(f"Failed to write file: {exc}", "write_file")

    return ActionResult.ok(
        f"Wrote file: {resolved}",
        {"path": str(resolved), "bytes": len(str(content))},
        "write_file",
    )


def handle_list_files(text: str, context: Dict[str, Any]) -> ActionResult:
    """Handle directory listing requests."""
    from .file_handler import list_directory
    
    path = None
    query_text = (text or "").strip().lower()
    validated = context.get("_validated_params")
    if validated and isinstance(validated, ListFilesSchema):
        path = validated.directory
    
    if not path:
        # Extract directory path (Legacy)
        query = query_text
        if "current working directory" in query or query in {"pwd", "print working directory"}:
            path = "current directory"
        elif "working directory" in query:
            path = "current directory"
        prefixes = [
            "can you list files in my ", "can you list files in ", 
            "list files in my ", "list files in ", "list files on my ", "list files on ",
            "show files in my ", "show files in ", "show files on my ", "show files on ",
            "what files are in my ", "what files are in ", 
            "what files are on my ", "what files are on ",
            "what's in my ", "what's in ",
            "what is in my ", "what is in ", 
            "show me my ", "show me ", "show my ", 
            "list my ", "list ", 
            "files in my ", "files in ", "files on my ", "files on "
        ]
        
        if not path:
            path = query
            for prefix in prefixes:
                if query.startswith(prefix):
                    path = query[len(prefix):].strip()
                    break
                
        # Clean up common references - strip punctuation and trailing words
        path = path.rstrip("?.!,").strip()
        # Preserve "this folder"/"current folder" phrases before stripping trailing words
        if path in {"this folder", "current folder", "this directory", "current directory"}:
            pass
        else:
            path = re.sub(r"\s*(folder|directory|for that|for me|please)[\.\?\!]?$", "", path, flags=re.IGNORECASE).strip()
            path = path.rstrip("?.!,").strip()  # Strip again after removing trailing words
            # Normalize leading article forms like "the current" or "the desktop".
            if path.lower().startswith("the "):
                path = path[4:].strip()
    
    # Map common names to actual paths (handle singular/plural variants)
    home = Path.home()
    path_map = {
        "desktop": str(home / "Desktop"),
        "my desktop": str(home / "Desktop"),
        "the desktop": str(home / "Desktop"),
        "this folder": str(_get_workspace_root(context) or Path.cwd()),
        "current folder": str(_get_workspace_root(context) or Path.cwd()),
        "current directory": str(_get_workspace_root(context) or Path.cwd()),
        "this directory": str(_get_workspace_root(context) or Path.cwd()),
        "this": str(_get_workspace_root(context) or Path.cwd()),
        "current": str(_get_workspace_root(context) or Path.cwd()),
        "the current": str(_get_workspace_root(context) or Path.cwd()),
        "documents": str(home / "Documents"),
        "document": str(home / "Documents"),
        "my documents": str(home / "Documents"),
        "my document": str(home / "Documents"),
        "the documents": str(home / "Documents"),
        "the document": str(home / "Documents"),
        "docs": str(home / "Documents"),
        "my docs": str(home / "Documents"),
        "downloads": str(home / "Downloads"),
        "download": str(home / "Downloads"),
        "my downloads": str(home / "Downloads"),
        "my download": str(home / "Downloads"),
        "the downloads": str(home / "Downloads"),
        "home": str(home),
        "my home": str(home),
        "pictures": str(home / "Pictures"),
        "my pictures": str(home / "Pictures"),
        "the pictures": str(home / "Pictures"),
        "videos": str(home / "Videos"),
        "my videos": str(home / "Videos"),
        "the videos": str(home / "Videos"),
        "music": str(home / "Music"),
        "my music": str(home / "Music"),
        "the music": str(home / "Music"),
    }
    
    path = path_map.get(path.lower(), path)
    
    if not path:
        path = str(home / "Desktop")  # Default to Desktop

    workspace_root = _get_workspace_root(context)
    if workspace_root:
        resolved = _resolve_in_workspace(path, workspace_root)
        if not resolved:
            return ActionResult.fail(
                "That directory is outside the current agent workspace.",
                "list_files",
            )
        path = str(resolved)

    if (
        "current working directory" in query_text
        or query_text in {"pwd", "print working directory", "print the current working directory"}
    ):
        return ActionResult.ok(
            f"Current working directory: {path}",
            {"path": path},
            "list_files",
        )
    
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
    """Read the current clipboard contents."""
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
    """Copy text to clipboard."""
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
    """Get information about a file."""
    from .file_handler import get_file_handler
    
    filename = None
    validated = context.get("_validated_params")
    if validated and isinstance(validated, FileInfoSchema):
        filename = validated.filename

    if not filename:
        # Extract filename (Legacy)
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

    workspace_root = _get_workspace_root(context)
    if workspace_root:
        resolved = _resolve_in_workspace(filename, workspace_root)
        if not resolved:
            return ActionResult.fail(
                "That file is outside the current agent workspace.",
                "file_info",
            )
        filename = str(resolved)
    
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


def handle_file_management(text: str, context: Dict[str, Any]) -> ActionResult:
    """
    Handle file management operations (create/delete) with SAFETY confirmations.
    """
    def _normalize_named_user_dir(raw: str) -> Optional[Path]:
        t = (raw or "").strip().lower()
        if not t:
            return None
        aliases = {
            "downloads": Path.home() / "Downloads",
            "downloads folder": Path.home() / "Downloads",
            "my downloads": Path.home() / "Downloads",
            "my downloads folder": Path.home() / "Downloads",
            "desktop": Path.home() / "Desktop",
            "desktop folder": Path.home() / "Desktop",
            "my desktop": Path.home() / "Desktop",
            "documents": Path.home() / "Documents",
            "documents folder": Path.home() / "Documents",
            "my documents": Path.home() / "Documents",
        }
        return aliases.get(t)

    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except Exception:
            return False

    def _allowed_manage_path(path: Path, workspace_root: Optional[Path]) -> bool:
        # Strict allowlist: user folders + current workspace only.
        roots = [
            Path.home() / "Downloads",
            Path.home() / "Desktop",
            Path.home() / "Documents",
        ]
        if workspace_root:
            roots.append(workspace_root)
        target = path.resolve()
        for root in roots:
            try:
                if _is_within(target, root):
                    return True
            except Exception:
                continue
        return False

    def _quarantine_root() -> Path:
        root = Path.home() / ".chintu" / "verify_delete"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _unique_dest(dest: Path) -> Path:
        if not dest.exists():
            return dest
        stem = dest.stem
        suffix = dest.suffix
        parent = dest.parent
        for i in range(1, 1000):
            candidate = parent / f"{stem}_{i}{suffix}"
            if not candidate.exists():
                return candidate
        return parent / f"{stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{suffix}"

    # Use schema params for operation and path
    operation = None
    path_str = None
    
    validated = context.get("_validated_params")
    if validated and isinstance(validated, FileManagementSchema):
        operation = validated.operation
        path_str = validated.path
    
    # Check for legacy parsing if no schema
    if not path_str:
        text_lower = text.lower()
        if any(w in text_lower for w in ["purge", "empty"]) and any(w in text_lower for w in ["verify_delete", "verification folder", "verify folder"]):
            # Purge the verification folder root (safe, scoped).
            operation = "purge_verification_folder"
            path_str = str(_quarantine_root())
        elif any(w in text_lower for w in ["delete", "remove", "erase", "destroy"]):
            if "download" in text_lower and any(w in text_lower for w in ["everything", "all", "all files", "all items"]):
                operation = "quarantine_dir_contents"
                path_str = str(Path.home() / "Downloads")
                # Skip generic prefix parsing; we've resolved the target directory.
            else:
                # "delete file temp.txt"
                for prefix in [
                    "delete file ",
                    "remove file ",
                    "delete folder ",
                    "remove folder ",
                    "delete directory ",
                    "remove directory ",
                    "delete ",
                    "remove ",
                ]:
                    if prefix in text_lower:
                        path_str = text[text_lower.find(prefix) + len(prefix):].strip()
                        operation = "quarantine_path"
                        break
        elif any(w in text_lower for w in ["create folder", "make folder", "new folder", "mkdir"]):
            # "create folder test" or "create a new folder called X"
            match = re.search(r"(?:create|make|new)\s+(?:a\s+)?folder(?:\s+called)?\s+(.+)", text, re.IGNORECASE)
            if match:
                path_str = match.group(1).strip()
                operation = "create_folder"
            else:
                for prefix in ["create folder ", "make folder ", "new folder ", "mkdir "]:
                    if prefix in text_lower:
                        path_str = text[text_lower.find(prefix) + len(prefix):].strip()
                        operation = "create_folder"
                        break

    path_str = path_str.strip('."\'') if path_str else ""
    if path_str.lower().startswith("called "):
        path_str = path_str[7:].strip()
    if not path_str:
        return ActionResult.fail("Please specify which file or folder to manage.", "file_management")
        
    workspace_root = _get_workspace_root(context)
    # Map common user folders (Downloads/Desktop/Documents) even when workspace scoping is enabled.
    mapped_user_dir = _normalize_named_user_dir(path_str)
    if mapped_user_dir is not None:
        path = mapped_user_dir
    else:
        resolved_path = _resolve_in_workspace(path_str, workspace_root)
        if resolved_path is not None:
            path = resolved_path
        else:
            # Allow absolute paths only when they live in supported user folders.
            try:
                candidate = Path(path_str).expanduser().resolve()
            except Exception:
                candidate = None
            if candidate is None or not _allowed_manage_path(candidate, workspace_root):
                return ActionResult.fail(
                    "That path is outside the current agent workspace (or a supported user folder like Downloads/Desktop/Documents).",
                    "file_management",
                )
            path = candidate
    
    # SAFETY: No permanent deletion. All "delete" intents become quarantine moves.
    op_low = str(operation or "").lower().strip()
    is_quarantine = op_low in {"quarantine_path", "quarantine_dir_contents"} or ("delete" in op_low)
    is_purge_verify = operation == "purge_verification_folder"
    is_create = operation == "create_folder" or (not operation and any(w in text.lower() for w in ["create", "make"]))

    if is_purge_verify:
        verify_root = _quarantine_root().resolve()
        try:
            target = Path(path_str).expanduser().resolve()
        except Exception:
            target = verify_root
        if target != verify_root and not _is_within(target, verify_root):
            return ActionResult.fail("I can only purge folders inside the verification root.", "file_management")
        if not target.exists():
            return ActionResult.ok("Verification folder is already empty.", {"path": str(target)}, "file_management")

        def do_purge() -> ActionResult:
            try:
                shutil.rmtree(target)
                return ActionResult.ok(
                    f"Purged verification folder: {target.name}",
                    {"path": str(target), "op": "purge_verification_folder"},
                    "file_management",
                )
            except Exception as exc:
                return ActionResult.fail(f"Failed to purge verification folder: {exc}", "file_management")

        return ActionResult.confirm(
            f"This will permanently delete the verification folder '{target.name}'. Confirm?",
            do_purge,
            "file_management",
        )

    if is_quarantine:
        if not path.exists():
            return ActionResult.fail(f"I can't find '{path.name}' to move it to verification.", "file_management")
        if not _allowed_manage_path(path, workspace_root):
            return ActionResult.fail(
                "I can only move items from Downloads/Desktop/Documents or the current workspace into verification.",
                "file_management",
            )

        verify_root = _quarantine_root()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        batch_dir = verify_root / f"verify_{stamp}"
        batch_dir.mkdir(parents=True, exist_ok=True)

        def do_quarantine() -> ActionResult:
            moved: list[str] = []
            try:
                if operation == "quarantine_dir_contents" and path.is_dir():
                    for child in list(path.iterdir()):
                        # Skip the verification root if it's ever nested (defensive).
                        try:
                            if _is_within(child, verify_root):
                                continue
                        except Exception:
                            pass
                        dest = _unique_dest(batch_dir / child.name)
                        shutil.move(str(child), str(dest))
                        moved.append(str(dest))
                    return ActionResult.ok(
                        f"Moved {len(moved)} item(s) from '{path.name}' into verification folder: {batch_dir}",
                        {"op": "quarantine_dir_contents", "source": str(path), "dest": str(batch_dir), "moved": moved[:50]},
                        "file_management",
                    )

                dest = _unique_dest(batch_dir / path.name)
                shutil.move(str(path), str(dest))
                moved.append(str(dest))
                return ActionResult.ok(
                    f"Moved '{path.name}' into verification folder: {dest}",
                    {"op": "quarantine_path", "source": str(path), "dest": str(dest)},
                    "file_management",
                )
            except Exception as exc:
                return ActionResult.fail(f"Failed to move into verification folder: {exc}", "file_management")

        return ActionResult.confirm(
            f"I don't permanently delete files. I can move '{path.name}' into a verification folder instead (so you can review/recover). Confirm?",
            do_quarantine,
            "file_management",
        )
        
    # Check for CREATE DIRECTORY
    if is_create:
         try:
             path.mkdir(parents=True, exist_ok=True)
             return ActionResult.ok(f"Created folder: {path.name}", {"path": str(path), "op": "create_dir"}, "file_management")
         except Exception as e:
             return ActionResult.fail(f"Could not create folder: {e}", "file_management")

    return ActionResult.fail("I can create folders, move items into verification (instead of deleting), or purge the verification folder.", "file_management")


def _extract_quoted(text: str) -> str:
    match = re.search(r"['\"]([^'\"]{2,120})['\"]", text or "")
    return (match.group(1) if match else "").strip()


def _parse_days_back(text: str, default_days: int = 14) -> int:
    t = (text or "").lower()
    if "yesterday" in t:
        return 2
    if "last week" in t or "past week" in t:
        return 8
    if "last month" in t or "past month" in t:
        return 35
    m = re.search(r"last\s+(\d{1,3})\s+(day|days|week|weeks|month|months)", t)
    if not m:
        return int(default_days)
    n = int(m.group(1))
    unit = m.group(2)
    if "week" in unit:
        return min(3650, n * 7 + 1)
    if "month" in unit:
        return min(3650, n * 30 + 1)
    return min(3650, n + 1)


def _parse_extension(text: str) -> str:
    t = (text or "").lower()
    for ext in (".pdf", ".docx", ".doc", ".txt", ".md"):
        if ext[1:] in t or ext in t:
            return ext
    return ""


def _tokenize(query: str) -> list[str]:
    raw = re.sub(r"[^a-zA-Z0-9]+", " ", query or "").strip().lower()
    tokens = [t for t in raw.split() if len(t) >= 3]
    # de-dupe while preserving order
    seen = set()
    out = []
    for t in tokens:
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out[:10]


def _walk_files(base: Path, *, max_depth: int = 5) -> list[Path]:
    base = Path(base).expanduser()
    if not base.exists() or not base.is_dir():
        return []
    out: list[Path] = []
    base_depth = len(base.parts)
    for root, dirs, files in os.walk(base, topdown=True):
        try:
            depth = len(Path(root).parts) - base_depth
        except Exception:
            depth = 0
        if depth > max_depth:
            dirs[:] = []
            continue
        # skip noisy folders
        dirs[:] = [
            d
            for d in dirs
            if not d.startswith(".")
            and d.lower() not in {"node_modules", "__pycache__", ".git", ".venv", "venv"}
        ]
        for f in files:
            if not f or f.startswith("~$"):
                continue
            out.append(Path(root) / f)
        if len(out) > 12000:
            break
    return out


def handle_file_hunter(text: str, context: Dict[str, Any]) -> ActionResult:
    """Find a file by keywords/timeframe and optionally open the best match."""
    from .file_handler import get_file_handler

    query = ""
    days_back = _parse_days_back(text, default_days=14)
    ext = _parse_extension(text)
    open_top = "open" in (text or "").lower()

    validated = context.get("_validated_params")
    if validated and isinstance(validated, FileHunterSchema):
        query = validated.query
        days_back = int(validated.days_back or days_back)
        ext = (validated.extension or ext or "").strip()
        if ext and not ext.startswith("."):
            ext = "." + ext
        open_top = bool(validated.open_top)

    if not query:
        quoted = _extract_quoted(text)
        if quoted:
            query = quoted
        else:
            # best-effort: take words after "about"
            m = re.search(r"\babout\s+(.+)$", text or "", flags=re.IGNORECASE)
            query = (m.group(1) if m else (text or "")).strip()

    query = (query or "").strip().strip("?.!,\"'")
    if not query or len(query) < 2:
        return ActionResult.fail("What file/topic should I search for? Example: \"Find the PDF about 'Distributed Computing' from last week\".", "file_hunter")

    tokens = _tokenize(query)
    if not tokens and len(query) >= 3:
        tokens = [query.lower()[:24]]

    home = Path.home()
    bases = [home / "Desktop", home / "Documents", home / "Downloads"]

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max(1, int(days_back)))

    handler = get_file_handler()

    candidates: list[dict[str, Any]] = []
    for base in bases:
        for path in _walk_files(base, max_depth=5):
            try:
                if ext and path.suffix.lower() != ext.lower():
                    continue
                stat = path.stat()
                mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
                if mtime < cutoff:
                    continue
                if stat.st_size > 150 * 1024 * 1024:
                    continue
                name_lower = path.name.lower()
                name_score = sum(1 for t in tokens if t in name_lower)
                if tokens and name_score == 0:
                    # Keep a small tail of recent docs even if name doesn't match.
                    continue
                candidates.append(
                    {
                        "path": str(path),
                        "name": path.name,
                        "ext": path.suffix.lower(),
                        "mtime": mtime.isoformat(),
                        "mtime_ts": stat.st_mtime,
                        "size": stat.st_size,
                        "name_score": int(name_score),
                        "content_score": 0.0,
                    }
                )
            except Exception:
                continue

    if not candidates:
        return ActionResult.ok(
            f"I couldn't find anything matching '{query}' in Desktop/Documents/Downloads within the last {days_back} days.",
            {"query": query, "days_back": days_back, "matches": []},
            "file_hunter",
        )

    # Sort by name score then recency.
    candidates.sort(key=lambda c: (int(c.get("name_score") or 0), float(c.get("mtime_ts") or 0.0)), reverse=True)
    top = candidates[:30]

    # Deepen with content match on a smaller subset.
    if tokens:
        probe = top[:12]
        for item in probe:
            try:
                content = ""
                p = Path(item["path"])
                # Read a small portion for matching.
                if p.suffix.lower() == ".pdf":
                    content = handler.read_pdf_file(p)[:6000]
                elif p.suffix.lower() in {".docx", ".doc"}:
                    content = handler.read_docx_file(p)[:8000]
                elif p.suffix.lower() in {".txt", ".md", ".log"}:
                    content = handler.read_text_file(p)[:8000]
                else:
                    content = ""
                content_lower = (content or "").lower()
                if not content_lower:
                    continue
                hits = sum(1 for t in tokens if t in content_lower)
                item["content_score"] = float(hits) / float(max(1, len(tokens)))
            except Exception:
                continue

        top.sort(
            key=lambda c: (
                float(c.get("content_score") or 0.0),
                int(c.get("name_score") or 0),
                float(c.get("mtime_ts") or 0.0),
            ),
            reverse=True,
        )

    best = top[0]
    best_path = str(best.get("path") or "")
    best_conf = float(best.get("content_score") or 0.0)
    best_name_score = int(best.get("name_score") or 0)

    # Persist a small report as run evidence (best-effort).
    report_path = None
    run_id = context.get("_run_id") if isinstance(context, dict) else None
    try:
        if run_id:
            from chintu_backend.core.run_manager import get_run_manager

            rm = get_run_manager()
            lines = [
                "# File Hunter Report",
                "",
                f"- Query: {query}",
                f"- Days back: {days_back}",
                f"- Extension: {ext or '(any)'}",
                f"- Candidates scanned: {len(candidates)}",
                "",
                "## Top Matches",
            ]
            for i, item in enumerate(top[:8], start=1):
                lines.append(
                    f"{i}. {item.get('name')} | score(name={item.get('name_score')}, content={item.get('content_score')}) | {item.get('mtime')}"
                )
                lines.append(f"   - {item.get('path')}")
            report_path = rm.write_artifact(str(run_id), "file_hunter_report.md", "\n".join(lines) + "\n")
    except Exception:
        report_path = None

    # Auto-open only when user asked and confidence is good.
    opened = False
    if open_top:
        try:
            confident = (best_conf >= 0.8) or (best_name_score >= max(2, len(tokens)))
            if confident and best_path:
                os.startfile(best_path)  # noqa: S606 - intended Windows open
                opened = True
        except Exception:
            opened = False

    preview_lines = [f"Top match: {best.get('name')}"]
    preview_lines.append(f"- Path: {best_path}")
    preview_lines.append(f"- Modified: {best.get('mtime')}")
    if tokens:
        preview_lines.append(f"- Confidence: name={best_name_score}, content={best_conf:.2f}")
    if opened:
        preview_lines.append("- Action: opened")
    else:
        preview_lines.append("- Action: not opened (low confidence or open not requested)")

    preview_lines.append("")
    preview_lines.append("Other candidates:")
    for i, item in enumerate(top[1:6], start=2):
        preview_lines.append(
            f"- {i}. {item.get('name')} (name={item.get('name_score')}, content={item.get('content_score')})"
        )

    data = {"best_path": best_path, "opened": opened, "query": query, "days_back": days_back, "top": top[:10]}
    if report_path:
        data["report_path"] = report_path
    return ActionResult.ok("\n".join(preview_lines).strip(), data, "file_hunter")


def _extract_repo_search_query(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    quoted = _extract_quoted(raw)
    if quoted:
        return quoted
    patterns = [
        r"search this repo for\s+(.+)$",
        r"search this project for\s+(.+)$",
        r"find in repo\s+(.+)$",
        r"find in project\s+(.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip().strip("\"'")
    return raw


_REPO_SEARCH_EXCLUDE_GLOBS = (
    "!.git/*",
    "!node_modules/*",
    "!venv/*",
    "!.venv/*",
    "!generated_reports/*",
    "!.GCC/*",
    "!logs/*",
    "!.tmp/*",
    "!data/*",
)
_REPO_SEARCH_PREFERRED_DIR_WEIGHTS = {
    "chintu_backend/": 100,
    "skills/": 90,
    "scripts/": 80,
    "tests/": 45,
    "docs/": 35,
}
_REPO_SEARCH_DEPRIORITIZED_DIRS = (
    "generated_reports/",
    ".gcc/",
    "logs/",
    ".tmp/",
    "data/",
)


def _repo_match_score(line: str) -> tuple[int, int]:
    path, _line_no, _content = _parse_rg_line(str(line or ""))
    path = str(path or "").replace("\\", "/").lower().strip()
    score = 0
    if any(path.endswith(ext) for ext in (".py", ".md", ".yaml", ".yml", ".toml", ".ini")):
        score += 30
    if any(path.endswith(ext) for ext in (".json", ".txt", ".log")):
        score -= 10
    for preferred, weight in _REPO_SEARCH_PREFERRED_DIR_WEIGHTS.items():
        if f"/{preferred}" in f"/{path}":
            score += int(weight)
            break
    for deprioritized in _REPO_SEARCH_DEPRIORITIZED_DIRS:
        if f"/{deprioritized}" in f"/{path}":
            score -= 80
            break
    # Shorter paths are usually source files, not deep artifacts.
    return score, -len(path)


def _parse_rg_line(line: str) -> tuple[str, str, str]:
    raw = str(line or "").strip()
    if not raw:
        return "", "", ""
    # Windows absolute path: C:\path\to\file.py:123:match text
    win = re.match(r"^([A-Za-z]:[\\/].*?):(\d+):(.*)$", raw)
    if win:
        return win.group(1), win.group(2), win.group(3)
    # Generic path: path/to/file.py:123:match text
    unix = re.match(r"^([^:]+):(\d+):(.*)$", raw)
    if unix:
        return unix.group(1), unix.group(2), unix.group(3)
    return raw, "", ""


def handle_repo_search(text: str, context: Dict[str, Any]) -> ActionResult:
    """Search local repository/workspace files; never falls back to web results."""
    validated = context.get("_validated_params")
    query = ""
    first_only = True
    if validated and isinstance(validated, RepoSearchSchema):
        query = str(validated.query or "").strip()
        first_only = bool(validated.first_only)
    if not query:
        query = _extract_repo_search_query(text)
    query = (query or "").strip().strip("\"'")
    if not query:
        return ActionResult.fail("What should I search for in this repo?", "repo_search")

    workspace_root = _get_workspace_root(context) or Path.cwd().resolve()
    try:
        root = Path(workspace_root).resolve()
    except Exception:
        root = Path.cwd().resolve()

    if not root.exists():
        return ActionResult.fail(f"Workspace not found: {root}", "repo_search")

    limit = 1 if first_only else 8
    cmd = [
        "rg",
        "-n",
        "--hidden",
        query,
        str(root),
    ]
    for glob in _REPO_SEARCH_EXCLUDE_GLOBS:
        cmd.insert(4, glob)
        cmd.insert(4, "--glob")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20, check=False)
    except FileNotFoundError:
        return ActionResult.fail("ripgrep (rg) is not installed.", "repo_search")
    except Exception as exc:
        return ActionResult.fail(f"Repo search failed: {exc}", "repo_search")

    if proc.returncode not in (0, 1):
        err = (proc.stderr or proc.stdout or "unknown error").strip()
        return ActionResult.fail(f"Repo search failed: {err}", "repo_search")

    lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
    if not lines:
        return ActionResult.ok(
            f"No matches for '{query}' in {root}.",
            {"query": query, "matches": []},
            "repo_search",
        )

    ordered_lines = sorted(lines, key=_repo_match_score, reverse=True)
    matches = ordered_lines[:limit]
    rendered = []
    for ln in matches:
        path_part, line_part, _content = _parse_rg_line(ln)
        if path_part and line_part:
            rendered.append(f"- {path_part}:{line_part}")
        else:
            rendered.append(f"- {ln}")
    message = (
        f"First match for '{query}':\n{rendered[0]}"
        if first_only
        else f"Top matches for '{query}':\n" + "\n".join(rendered)
    )
    return ActionResult.ok(
        message,
        {"query": query, "matches": matches, "workspace": str(root)},
        "repo_search",
    )


def _read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _parse_requirements_packages(path: Path) -> list[str]:
    packages: list[str] = []
    for raw in _read_text_file(path).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Remove inline comments and env markers.
        line = line.split("#", 1)[0].split(";", 1)[0].strip()
        if not line:
            continue
        name = re.split(r"[<>=!~\[]", line, maxsplit=1)[0].strip().lower()
        if name and name not in packages:
            packages.append(name)
    return packages


def _parse_package_json_packages(path: Path) -> list[str]:
    import json

    packages: list[str] = []
    try:
        payload = json.loads(_read_text_file(path) or "{}")
    except Exception:
        return packages
    for section in ("dependencies", "devDependencies", "optionalDependencies"):
        deps = payload.get(section)
        if not isinstance(deps, dict):
            continue
        for name in deps.keys():
            pkg = str(name or "").strip().lower()
            if pkg and pkg not in packages:
                packages.append(pkg)
    return packages


def _parse_pyproject_packages(path: Path) -> list[str]:
    text = _read_text_file(path)
    packages: list[str] = []
    # Best-effort parse for entries like: "fastapi>=0.111.0"
    for quoted in re.findall(r"['\"]([A-Za-z0-9_.-]+(?:\[[^'\"]+\])?[^'\"]*)['\"]", text):
        name = re.split(r"[<>=!~\[]", quoted, maxsplit=1)[0].strip().lower()
        if not name:
            continue
        # Ignore known non-dependency sections accidentally matched.
        if name in {"name", "version", "description", "authors", "readme", "requires-python"}:
            continue
        if name not in packages:
            packages.append(name)
    return packages


def _bucket_dependency_names(packages: list[str]) -> dict[str, list[str]]:
    buckets: dict[str, list[str]] = {
        "core": [],
        "ai": [],
        "automation": [],
        "data": [],
        "tooling": [],
    }
    for pkg in packages:
        low = pkg.lower()
        if any(k in low for k in ("llama", "langchain", "langgraph", "transformers", "openai", "anthropic", "google", "gemini", "ollama", "qwen")):
            buckets["ai"].append(pkg)
        elif any(k in low for k in ("playwright", "selenium", "pyautogui", "beautifulsoup", "requests", "scrapy")):
            buckets["automation"].append(pkg)
        elif any(k in low for k in ("chroma", "chromadb", "faiss", "sqlite", "pandas", "numpy", "scipy", "sqlalchemy")):
            buckets["data"].append(pkg)
        elif any(k in low for k in ("pytest", "ruff", "mypy", "black", "flake8", "pre-commit", "coverage", "tox")):
            buckets["tooling"].append(pkg)
        else:
            buckets["core"].append(pkg)
    return buckets


def _render_dependency_summary(manifest: Path, packages: list[str], bullets: int) -> str:
    buckets = _bucket_dependency_names(packages)

    def _sample(items: list[str], size: int = 5) -> str:
        return ", ".join(items[:size]) if items else "none detected"

    lines = [
        f"Dependency summary from `{manifest.name}`:",
        f"- Core/runtime components: {_sample(buckets['core'])}.",
        f"- AI/LLM stack: {_sample(buckets['ai'])}.",
        f"- Automation/browser stack: {_sample(buckets['automation'])}.",
        f"- Data/storage stack: {_sample(buckets['data'])}.",
        f"- Tooling/testing stack: {_sample(buckets['tooling'])}.",
    ]

    # Keep the requested number of bullets, preserving the title line.
    max_lines = max(2, int(bullets) + 1)
    return "\n".join(lines[:max_lines]).strip()


def _resolve_manifest_for_summary(text: str, context: Dict[str, Any], path_hint: Optional[str]) -> Optional[Path]:
    root = _get_workspace_root(context) or Path.cwd().resolve()
    if path_hint:
        resolved = _resolve_in_workspace(path_hint, root)
        if resolved and resolved.exists() and resolved.is_file():
            return resolved
    text_low = str(text or "").lower()
    candidates = []
    if "requirements.txt" in text_low:
        candidates.append(root / "requirements.txt")
    if "pyproject.toml" in text_low:
        candidates.append(root / "pyproject.toml")
    if "package.json" in text_low:
        candidates.append(root / "package.json")
    candidates.extend(
        [
            root / "requirements.txt",
            root / "pyproject.toml",
            root / "package.json",
        ]
    )
    seen = set()
    for cand in candidates:
        key = str(cand).lower()
        if key in seen:
            continue
        seen.add(key)
        if cand.exists() and cand.is_file():
            return cand
    return None


def handle_dependency_summary(text: str, context: Dict[str, Any]) -> ActionResult:
    """Summarize dependency manifests into concise major-component bullets."""
    validated = context.get("_validated_params")
    bullets = 5
    path_hint = None
    if validated and isinstance(validated, DependencySummarySchema):
        bullets = int(validated.bullets)
        path_hint = validated.path

    manifest = _resolve_manifest_for_summary(text, context, path_hint)
    if not manifest:
        return ActionResult.fail(
            "I couldn't find a dependency manifest (requirements.txt, pyproject.toml, or package.json) in this workspace.",
            "dependency_summary",
        )

    packages: list[str]
    name = manifest.name.lower()
    if name == "requirements.txt":
        packages = _parse_requirements_packages(manifest)
    elif name == "package.json":
        packages = _parse_package_json_packages(manifest)
    elif name == "pyproject.toml":
        packages = _parse_pyproject_packages(manifest)
    else:
        packages = _parse_requirements_packages(manifest)

    if not packages:
        return ActionResult.fail(f"No dependency entries were detected in {manifest.name}.", "dependency_summary")

    response = _render_dependency_summary(manifest, packages, bullets=bullets)
    return ActionResult.ok(
        response,
        {"path": str(manifest), "package_count": len(packages), "packages": packages[:50]},
        "dependency_summary",
    )


_DOWNLOADS_SKIP_EXTS = {
    ".crdownload",  # Chrome in-progress
    ".part",        # Firefox in-progress
    ".tmp",
}


def _downloads_category_for(path: Path) -> str:
    ext = path.suffix.lower()
    if not ext:
        return "Other"

    images = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".heic"}
    docs = {".pdf", ".doc", ".docx", ".txt", ".md", ".rtf", ".odt", ".csv", ".xls", ".xlsx", ".ppt", ".pptx"}
    installers = {".exe", ".msi", ".msix", ".appx", ".appxbundle"}
    archives = {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso"}
    audio = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac"}
    video = {".mp4", ".mov", ".mkv", ".avi", ".webm"}
    code = {".py", ".js", ".ts", ".tsx", ".json", ".yaml", ".yml", ".toml", ".ini", ".log", ".sql", ".ipynb"}
    shortcuts = {".lnk"}

    if ext in images:
        return "Images"
    if ext in docs:
        return "Documents"
    if ext in installers:
        return "Installers"
    if ext in archives:
        return "Archives"
    if ext in audio:
        return "Audio"
    if ext in video:
        return "Video"
    if ext in code:
        return "Code"
    if ext in shortcuts:
        return "Shortcuts"

    return "Other"


def _unique_destination(dest: Path) -> Path:
    if not dest.exists():
        return dest

    stem = dest.stem
    suffix = dest.suffix
    parent = dest.parent
    for i in range(1, 9999):
        candidate = parent / f"{stem} ({i}){suffix}"
        if not candidate.exists():
            return candidate
    return parent / f"{stem} (copy){suffix}"


def handle_organize_downloads(text: str, context: Dict[str, Any]) -> ActionResult:
    """Organize the Downloads folder by moving files into type-based subfolders.

    Safety:
    - Never deletes files.
    - Only moves within the target directory.
    - Always asks for confirmation with a preview plan.
    """

    directory = None
    validated = context.get("_validated_params")
    if validated and isinstance(validated, OrganizeDownloadsSchema):
        directory = validated.directory

    home = Path.home()
    downloads_dir = Path(directory).expanduser() if directory else (home / "Downloads")
    # Keep it deterministic and safe.
    try:
        downloads_dir = downloads_dir.resolve()
    except Exception:
        downloads_dir = home / "Downloads"

    if not downloads_dir.exists() or not downloads_dir.is_dir():
        return ActionResult.fail(f"Folder not found: {downloads_dir}", "organize_downloads")

    # Build the plan.
    files: list[Path] = []
    try:
        for item in downloads_dir.iterdir():
            if item.is_dir():
                continue
            if item.name.lower() in {"desktop.ini"}:
                continue
            if item.suffix.lower() in _DOWNLOADS_SKIP_EXTS:
                continue
            files.append(item)
    except Exception as exc:
        return ActionResult.fail(f"Failed to scan {downloads_dir}: {exc}", "organize_downloads")

    if not files:
        return ActionResult.ok(f"Nothing to organize in {downloads_dir}.", {"path": str(downloads_dir)}, "organize_downloads")

    plan: Dict[str, list[Dict[str, str]]] = {}
    for src in files:
        category = _downloads_category_for(src)
        dest_dir = downloads_dir / category
        dest_path = _unique_destination(dest_dir / src.name)
        plan.setdefault(category, []).append({"from": str(src), "to": str(dest_path)})

    # Preview summary.
    total_moves = sum(len(items) for items in plan.values())
    lines = [
        f"Plan: organize folder `{downloads_dir}` (no deletions)",
        f"- Files to move: {total_moves}",
        "",
        "Moves by category:",
    ]
    for category in sorted(plan.keys()):
        lines.append(f"- {category}: {len(plan[category])}")
    # Show a small sample (first 12 moves).
    lines.append("")
    lines.append("Sample moves:")
    shown = 0
    for category in sorted(plan.keys()):
        for item in plan[category]:
            if shown >= 12:
                break
            src_name = Path(item["from"]).name
            dest_rel = Path(item["to"]).relative_to(downloads_dir)
            lines.append(f"- {src_name} -> {dest_rel}")
            shown += 1
        if shown >= 12:
            break
    if total_moves > shown:
        lines.append(f"- ... and {total_moves - shown} more")

    if context.get("_plan_only"):
        return ActionResult.ok("\n".join(lines), {"path": str(downloads_dir), "moves": total_moves}, "organize_downloads")

    run_id = None
    try:
        if isinstance(context, dict):
            run_id = context.get("_run_id")
    except Exception:
        run_id = None

    def _apply_plan() -> ActionResult:
        moved = 0
        skipped = 0
        errors: list[str] = []
        for category, items in plan.items():
            dest_dir = downloads_dir / category
            try:
                dest_dir.mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                errors.append(f"{category}: failed to create folder ({exc})")
                continue

            for item in items:
                src = Path(item["from"])
                dest = Path(item["to"])
                try:
                    if not src.exists():
                        skipped += 1
                        continue
                    dest = _unique_destination(dest)
                    shutil.move(str(src), str(dest))
                    moved += 1
                except Exception as exc:
                    errors.append(f"{src.name}: {exc}")

        msg = f"Organized {downloads_dir}.\n- Moved: {moved}\n- Skipped: {skipped}"
        if errors:
            msg += f"\n- Errors: {len(errors)} (showing up to 5)\n"
            msg += "\n".join(f"  - {e}" for e in errors[:5])

        report_path = None
        try:
            if run_id:
                from datetime import datetime

                from chintu_backend.core.run_manager import get_run_manager

                rm = get_run_manager()
                now = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                sample_lines = []
                shown = 0
                for category in sorted(plan.keys()):
                    for item in plan[category]:
                        if shown >= 30:
                            break
                        try:
                            src_name = Path(item["from"]).name
                            dest_rel = Path(item["to"]).relative_to(downloads_dir)
                            sample_lines.append(f"- {src_name} -> {dest_rel}")
                        except Exception:
                            pass
                        shown += 1
                    if shown >= 30:
                        break
                report = "\n".join(
                    [
                        "# Downloads Organization Report",
                        "",
                        f"- Folder: {downloads_dir}",
                        f"- Moved: {moved}",
                        f"- Skipped: {skipped}",
                        f"- Errors: {len(errors)}",
                        "",
                        "## Sample Moves",
                        *(sample_lines or ["(no moves recorded)"]),
                        "",
                        "## Errors (first 20)",
                        *([f"- {e}" for e in errors[:20]] if errors else ["(none)"]),
                        "",
                    ]
                )
                report_path = rm.write_artifact(str(run_id), f"downloads_organize_{now}.md", report)
        except Exception:
            report_path = None

        data = {"path": str(downloads_dir), "moved": moved, "skipped": skipped, "errors": errors}
        if report_path:
            data["report_path"] = report_path
        return ActionResult.ok(msg.strip(), data, "organize_downloads")

    return ActionResult.confirm("\n".join(lines) + "\n\nProceed to move these files?", _apply_plan, "organize_downloads")


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
        ],
        schema=ReadFileSchema
    ))

    # Write File (workspace-only)
    registry.register(Capability(
        name="write_file",
        triggers=[
            "write file",
            "write to file",
            "save to file",
            "create file at",
        ],
        handler=handle_write_file,
        requires_confirmation=False,
        description="write a file inside the workspace",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=[
            "Write file notes.txt with content: hello",
            "Save to file output.md with content: ...",
        ],
        schema=WriteFileSchema,
    ))
    
    # List Files
    registry.register(Capability(
        name="list_files",
        triggers=[
            "list files", "show files", "what files", "files in",
            "files on", "show my desktop", "show my documents",
            "show my downloads", "what's on my desktop",
            "current working directory", "working directory",
            "print the current working directory", "pwd"
        ],
        handler=handle_list_files,
        requires_confirmation=False,
        description="list files in a directory",
        capability_type=CapabilityType.PRODUCTIVITY,
        examples=[
            "List files in Downloads",
            "What files are on my Desktop?",
            "Show my Documents folder"
        ],
        schema=ListFilesSchema
    ))

    registry.register(
        Capability(
            name="repo_search",
            triggers=[
                "search this repo for",
                "search this project for",
                "find in repo",
                "find in project",
            ],
            handler=handle_repo_search,
            requires_confirmation=False,
            description="search local repository/workspace text with ripgrep",
            capability_type=CapabilityType.PRODUCTIVITY,
            examples=[
                "Search this repo for phase9_governance_gate",
                "Find in project 'Calendar not connected'",
            ],
            schema=RepoSearchSchema,
        )
    )

    registry.register(
        Capability(
            name="dependency_summary",
            triggers=[
                "summarize what's in requirements.txt",
                "summarize requirements.txt",
                "summarize requirements",
                "dependency summary",
                "summarize dependencies",
            ],
            handler=handle_dependency_summary,
            requires_confirmation=False,
            description="summarize dependency manifests into major component bullets",
            capability_type=CapabilityType.PRODUCTIVITY,
            examples=[
                "Summarize what's in requirements.txt in 5 bullets",
                "Dependency summary for pyproject.toml",
            ],
            schema=DependencySummarySchema,
        )
    )
    
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
        ],
        schema=ClipboardReadSchema
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
        ],
        schema=ClipboardCopySchema
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
        ],
        schema=FileInfoSchema
    ))
    
    # Safe File Management
    registry.register(Capability(
        name="file_management",
        triggers=[
            "delete file", "remove file", "delete folder", "remove folder",
            "delete ", "remove ", "erase ",
            "create folder", "create a folder", "create new folder",
            "make directory", "new folder", "mkdir"
        ],
        handler=handle_file_management,
        requires_confirmation=False, # We handle confirmation internally for precision
        description="safe file operations (delete, mkdir)",
        capability_type=CapabilityType.SYSTEM,
        examples=["Delete file temp.txt", "Create folder Archives"],
        schema=FileManagementSchema
    ))

    registry.register(Capability(
        name="organize_downloads",
        triggers=[
            "clean up downloads",
            "cleanup downloads",
            "organize downloads",
            "tidy downloads",
            "my downloads folder is a mess",
            "clean my downloads folder",
        ],
        handler=handle_organize_downloads,
        requires_confirmation=False,  # Handler shows preview + confirmation
        description="organize the Downloads folder into subfolders (safe, no deletions)",
        capability_type=CapabilityType.SYSTEM,
        examples=[
            "My Downloads folder is a mess. Clean it up.",
            "Organize downloads",
        ],
        schema=OrganizeDownloadsSchema,
    ))

    registry.register(
        Capability(
            name="file_hunter",
            triggers=[
                "where did i save",
                "where did i put",
                "find that pdf",
                "find my pdf",
                "file hunter",
                "find it and open",
                "find the document",
            ],
            handler=handle_file_hunter,
            requires_confirmation=False,
            description="search for a file by keywords/timeframe and open the best match when confident",
            capability_type=CapabilityType.PRODUCTIVITY,
            examples=[
                "Where did I save that PDF about 'Distributed Computing' from last week? Find it and open it.",
                "Find my document about transformers from yesterday.",
            ],
            schema=FileHunterSchema,
        )
    )

    logger.info("Registered file capabilities")
