"""File browser endpoints for browsing the target project's files."""

import asyncio
import base64
import fnmatch
import logging
import mimetypes
import os
import zipfile
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.config import (
    FILE_BROWSER_EXCLUDED_DIRS,
    FILE_BROWSER_EXCLUDED_FILES,
    FILE_BROWSER_SECRET_PATTERNS,
    FILE_BROWSER_LANGUAGE_MAP,
    FILE_BROWSER_TREE_DEPTH,
    FILE_BROWSER_MAX_TEXT_SIZE,
    FILE_BROWSER_MAX_IMAGE_SIZE,
    FILE_BROWSER_IMAGE_EXTENSIONS,
    FILE_BROWSER_IMAGE_MIME_TYPES,
    FILE_BROWSER_3D_EXTENSIONS,
    FILE_BROWSER_MAX_3D_SIZE,
    FILE_BROWSER_ARCHIVE_EXTENSIONS,
)

logger = logging.getLogger(__name__)

file_router = APIRouter(prefix="/api/files", tags=["files"])

# Cache for parsed .browserhidden patterns per project root
_browserhidden_cache: dict[str, tuple[float, list[str]]] = {}

BROWSERHIDDEN_FILENAME = ".browserhidden"


# --- .browserhidden support ---

def parse_browserhidden(file_path: Path) -> list[str]:
    """Parse a .browserhidden file and return a list of glob patterns.

    Format is similar to .gitignore:
    - One pattern per line
    - Lines starting with # are comments
    - Empty lines are ignored
    - Leading/trailing whitespace is stripped
    """
    patterns: list[str] = []
    try:
        text = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return patterns

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(line)
    return patterns


def load_browserhidden_patterns(project_root: Path) -> list[str]:
    """Load .browserhidden patterns for a project, with mtime-based caching."""
    config_path = project_root / BROWSERHIDDEN_FILENAME
    cache_key = str(project_root)

    try:
        mtime = config_path.stat().st_mtime
    except OSError:
        # File doesn't exist — clear cache and return empty
        _browserhidden_cache.pop(cache_key, None)
        return []

    cached = _browserhidden_cache.get(cache_key)
    if cached and cached[0] == mtime:
        return cached[1]

    patterns = parse_browserhidden(config_path)
    _browserhidden_cache[cache_key] = (mtime, patterns)
    if patterns:
        logger.debug("Loaded %d patterns from %s", len(patterns), config_path)
    return patterns


def matches_browserhidden(name: str, rel_path: str, patterns: list[str]) -> bool:
    """Check if a filename or relative path matches any .browserhidden pattern.

    Patterns can match:
    - By filename only: e.g. "credentials.yaml" matches any file with that name
    - By glob: e.g. "*.tokens" matches any file ending in .tokens
    - By path prefix: e.g. "config/secrets/*" matches files under that path
    """
    for pattern in patterns:
        # Match against filename
        if fnmatch.fnmatch(name, pattern):
            return True
        # Match against full relative path (for path-based patterns like "config/secrets/*")
        if "/" in pattern and fnmatch.fnmatch(rel_path, pattern):
            return True
    return False


# --- Helper functions ---

def validate_file_browser_path(rel_path: str, project_root: Path) -> Path:
    """Validate and resolve a relative file path within the project root."""
    if not rel_path:
        raise ValueError("Path cannot be empty")
    if "\x00" in rel_path:
        raise ValueError("Path contains null bytes")
    if any(ord(c) < 32 for c in rel_path):
        raise ValueError("Path contains control characters")
    if os.path.isabs(rel_path):
        raise ValueError("Absolute paths not allowed — use absolute path relative to project")
    if ".." in rel_path.split(os.sep) or ".." in rel_path.split("/"):
        raise ValueError("Path traversal not allowed — '..' segments rejected")

    resolved = (project_root / rel_path).resolve()
    project_resolved = project_root.resolve()
    if not resolved.is_relative_to(project_resolved):
        raise ValueError("Path escapes project directory (possible symlink attack)")
    return resolved


def is_secret_file(filename: str, rel_path: str = "", extra_patterns: list[str] | None = None) -> bool:
    """Check if a filename matches secret file patterns.

    Checks built-in patterns first, then any extra patterns from .browserhidden.
    """
    if any(fnmatch.fnmatch(filename, pattern) for pattern in FILE_BROWSER_SECRET_PATTERNS):
        return True
    if not extra_patterns:
        return False
    return matches_browserhidden(filename, rel_path or filename, extra_patterns)


def detect_language(filename: str) -> str | None:
    """Map a filename to a Prism.js language identifier."""
    ext = Path(filename).suffix.lower()
    return FILE_BROWSER_LANGUAGE_MAP.get(ext)


def is_excluded_entry(name: str, is_dir: bool) -> bool:
    """Check if a directory or file entry should be excluded from the tree."""
    if is_dir:
        return name in FILE_BROWSER_EXCLUDED_DIRS
    return name in FILE_BROWSER_EXCLUDED_FILES


# --- Directory scanning ---

def scan_directory(
    dir_path: Path,
    project_root: Path,
    depth: int,
    browserhidden_patterns: list[str] | None = None,
) -> list[dict]:
    """Scan a directory and return a tree structure."""
    project_resolved = project_root.resolve()

    def node_for(entry) -> dict | None:
        """Tree node for a non-symlink entry, or None if it is hidden or outside the project."""
        is_dir = entry.is_dir(follow_symlinks=False)
        if is_excluded_entry(entry.name, is_dir):
            return None
        resolved = _resolved_in_project(entry, project_resolved)
        if resolved is None:
            return None
        rel_path = str(resolved.relative_to(project_resolved))
        # Check .browserhidden patterns (applies to both files and dirs)
        if browserhidden_patterns and matches_browserhidden(entry.name, rel_path, browserhidden_patterns):
            return None
        node = {"name": entry.name, "path": rel_path, "type": "dir" if is_dir else "file"}
        if is_dir:
            node["children"] = (
                scan_directory(resolved, project_root, depth - 1, browserhidden_patterns)
                if depth > 1 else None
            )
        return node

    entries = []
    try:
        with os.scandir(dir_path) as scanner:
            for entry in scanner:
                # Symlinks are listed (as a visual indicator) but never followed,
                # so the browser can't navigate outside the project directory.
                node = _symlink_node(entry, project_resolved) if entry.is_symlink() else node_for(entry)
                if node is not None:
                    entries.append(node)
    except PermissionError:
        pass

    entries.sort(key=lambda e: (0 if e["type"] == "dir" else 1, e["name"].lower()))
    return entries


def _symlink_node(entry, project_resolved: Path) -> dict:
    """Tree node for a symlink: shown with its target, never followed."""
    try:
        target = os.readlink(entry.path)
    except OSError:
        target = "unknown"
    return {
        "name": entry.name,
        "path": str(Path(entry.path).relative_to(project_resolved)),
        "type": "symlink",
        "symlink_target": target,
    }


def _resolved_in_project(entry, project_resolved: Path) -> Path | None:
    """The entry's resolved path if it stays inside the project, else None."""
    try:
        resolved = Path(entry.path).resolve()
        return resolved if resolved.is_relative_to(project_resolved) else None
    except (OSError, ValueError):
        return None


# --- File content reading ---

def read_file_content(
    file_path: Path, rel_path: str, browserhidden_patterns: list[str] | None = None,
) -> dict:
    """Read file content and return metadata."""
    filename = file_path.name
    size = file_path.stat().st_size

    if is_secret_file(filename, rel_path, browserhidden_patterns):
        return {
            "path": rel_path, "content": None, "size": size,
            "language": None, "binary": False, "hidden": True,
            "reason": "Hidden for security",
        }

    ext = file_path.suffix.lower()
    if ext in FILE_BROWSER_3D_EXTENSIONS:
        return _read_3d_model(file_path, rel_path, size, ext)
    if ext in FILE_BROWSER_ARCHIVE_EXTENSIONS:
        return _read_archive(file_path, rel_path, size)
    if ext in FILE_BROWSER_IMAGE_EXTENSIONS:
        return _read_image(file_path, rel_path, size, ext)
    return _read_text(file_path, rel_path, size)


def _read_3d_model(file_path: Path, rel_path: str, size: int, ext: str) -> dict:
    """3D model file: base64 data for client-side rendering (none when too large)."""
    content = None
    if size <= FILE_BROWSER_MAX_3D_SIZE:
        content = base64.b64encode(file_path.read_bytes()).decode("ascii")
    return {
        "path": rel_path, "content": content, "size": size,
        "language": None, "binary": True, "viewer": "3d",
        "model_format": ext.lstrip("."),
    }


def _read_archive(file_path: Path, rel_path: str, size: int) -> dict:
    """Archive file: its listed contents."""
    entries = _read_zip_contents(file_path)
    return {
        "path": rel_path, "content": None, "size": size,
        "language": None, "binary": True, "viewer": "archive",
        "archive_entries": entries,
    }


def _read_image(file_path: Path, rel_path: str, size: int, ext: str) -> dict:
    """Image file: a data URL (none when too large)."""
    mime_type = FILE_BROWSER_IMAGE_MIME_TYPES.get(ext, "application/octet-stream")
    content = None
    if size <= FILE_BROWSER_MAX_IMAGE_SIZE:
        b64 = base64.b64encode(file_path.read_bytes()).decode("ascii")
        content = f"data:{mime_type};base64,{b64}"
    return {
        "path": rel_path, "content": content, "size": size,
        "language": None, "binary": True, "mime_type": mime_type,
    }


def _read_text(file_path: Path, rel_path: str, size: int) -> dict:
    """Text file content (truncated when long), or binary metadata when not UTF-8."""
    filename = file_path.name
    try:
        raw = file_path.read_bytes()
        text = raw.decode("utf-8")
    except (UnicodeDecodeError, ValueError):
        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        return {
            "path": rel_path, "content": None, "size": size,
            "language": None, "binary": True, "mime_type": mime_type,
        }

    truncated = False
    if len(text) > FILE_BROWSER_MAX_TEXT_SIZE:
        text = text[:FILE_BROWSER_MAX_TEXT_SIZE]
        truncated = True

    return {
        "path": rel_path, "content": text, "size": size,
        "lines": text.count("\n") + (1 if text else 0),
        "language": detect_language(filename), "binary": False,
        "truncated": truncated,
    }


def _read_zip_contents(file_path: Path, max_entries: int = 500) -> list[dict]:
    """Read the listing of entries inside a ZIP file."""
    entries = []
    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            for i, info in enumerate(zf.infolist()):
                if i >= max_entries:
                    entries.append({
                        "name": f"... and {len(zf.infolist()) - max_entries} more entries",
                        "size": 0, "compressed_size": 0,
                        "is_dir": False, "truncated": True,
                    })
                    break
                entries.append({
                    "name": info.filename,
                    "size": info.file_size,
                    "compressed_size": info.compress_size,
                    "is_dir": info.is_dir(),
                    "date": f"{info.date_time[0]:04d}-{info.date_time[1]:02d}-{info.date_time[2]:02d} "
                            f"{info.date_time[3]:02d}:{info.date_time[4]:02d}",
                })
    except (zipfile.BadZipFile, OSError) as e:
        entries.append({"name": f"Error reading archive: {e}", "size": 0,
                        "compressed_size": 0, "is_dir": False, "error": True})
    return entries


# --- Endpoints ---

@file_router.get("/tree")
async def get_file_tree(request: Request, path: str = ""):
    """Return directory tree for the target project."""
    project_root = Path(request.app.state.target_project)

    if path:
        try:
            scan_path = validate_file_browser_path(path, project_root)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        if not scan_path.is_dir():
            return JSONResponse({"error": "Not a directory"}, status_code=400)
    else:
        scan_path = project_root

    patterns = load_browserhidden_patterns(project_root)
    tree = await asyncio.to_thread(
        scan_directory, scan_path, project_root, FILE_BROWSER_TREE_DEPTH, patterns or None,
    )
    return {"root": str(project_root), "tree": tree}


@file_router.get("/content")
async def get_file_content(request: Request, path: str):
    """Return the content of a file in the target project."""
    project_root = Path(request.app.state.target_project)

    try:
        file_path = validate_file_browser_path(path, project_root)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    if not file_path.exists():
        return JSONResponse({"error": f"File not found: {path}"}, status_code=404)

    # Block reading symlinks to prevent following links outside the project
    # Check the original (pre-resolved) path since validate_file_browser_path resolves symlinks
    original_path = project_root / path
    if original_path.is_symlink():
        return JSONResponse({"error": "Symlinks cannot be read for security reasons"}, status_code=403)

    if not file_path.is_file():
        return JSONResponse({"error": f"Not a file: {path}"}, status_code=400)

    patterns = load_browserhidden_patterns(project_root)
    result = await asyncio.to_thread(read_file_content, file_path, path, patterns or None)
    return result
