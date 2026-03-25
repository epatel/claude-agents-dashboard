"""File browser endpoints for browsing the target project's files."""

import asyncio
import base64
import fnmatch
import mimetypes
import os
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
)

file_router = APIRouter(prefix="/api/files", tags=["files"])


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


def is_secret_file(filename: str) -> bool:
    """Check if a filename matches secret file patterns."""
    for pattern in FILE_BROWSER_SECRET_PATTERNS:
        if fnmatch.fnmatch(filename, pattern):
            return True
    return False


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

def scan_directory(dir_path: Path, project_root: Path, depth: int) -> list[dict]:
    """Scan a directory and return a tree structure."""
    entries = []
    try:
        with os.scandir(dir_path) as scanner:
            for entry in scanner:
                if is_excluded_entry(entry.name, entry.is_dir(follow_symlinks=False)):
                    continue
                try:
                    resolved = Path(entry.path).resolve()
                    if not resolved.is_relative_to(project_root.resolve()):
                        continue
                except (OSError, ValueError):
                    continue

                rel_path = str(resolved.relative_to(project_root.resolve()))
                node = {
                    "name": entry.name,
                    "path": rel_path,
                    "type": "dir" if entry.is_dir(follow_symlinks=True) else "file",
                }

                if entry.is_dir(follow_symlinks=True):
                    if depth > 1:
                        node["children"] = scan_directory(resolved, project_root, depth - 1)
                    else:
                        node["children"] = None
                entries.append(node)
    except PermissionError:
        pass

    entries.sort(key=lambda e: (0 if e["type"] == "dir" else 1, e["name"].lower()))
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

    tree = await asyncio.to_thread(scan_directory, scan_path, project_root, FILE_BROWSER_TREE_DEPTH)
    return {"root": str(project_root), "tree": tree}
