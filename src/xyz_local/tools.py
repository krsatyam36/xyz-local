"""Core tools for xyz-local with safe path handling and helpful errors."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Optional


def _human_size(bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if bytes < 1024:
            return f"{bytes:.1f}{unit}" if unit != "B" else f"{bytes}B"
        bytes /= 1024
    return f"{bytes:.1f}PB"

from xyz_local.safety import classify_command, PermissionResult, PermissionTier, is_dangerous_write_path


def normalize_path(path: str) -> Path:
    """Safely expand ~ and resolve the path relative to the current working directory."""
    expanded = os.path.expanduser(path)
    p = Path(expanded)
    if not p.is_absolute():
        p = Path.cwd() / p
    return p.resolve()


def list_directory(path: str = ".") -> dict[str, Any]:
    p = normalize_path(path)
    if not p.exists():
        suggestion = ""
        if "xyz-local" in path.lower() or path == "./xyz-local":
            suggestion = " (You are already inside the xyz-local project. Try path='.' instead of './xyz-local')"
        return {"error": f"Path does not exist: {path}{suggestion}"}
    if not p.is_dir():
        return {"error": f"Not a directory: {path}"}

    entries = []
    type_icons = {
        ".py": "🐍", ".js": "📜", ".ts": "📘", ".jsx": "⚛️", ".tsx": "⚛️",
        ".json": "📋", ".yaml": "📋", ".yml": "📋", ".toml": "⚙️",
        ".md": "📝", ".rst": "📝", ".txt": "📄",
        ".html": "🌐", ".css": "🎨", ".scss": "🎨",
        ".sh": "💻", ".bash": "💻", ".zsh": "💻",
        ".pyc": "⚡", ".so": "🔧", ".dll": "🔧",
        ".gitignore": "🙈", ".dockerignore": "🐳",
        ".png": "🖼️", ".jpg": "🖼️", ".jpeg": "🖼️", ".svg": "🖼️",
        ".pdf": "📕", ".zip": "📦", ".tar": "📦", ".gz": "📦",
    }
    try:
        for entry in sorted(p.iterdir()):
            is_dir = entry.is_dir()
            icon = "📁" if is_dir else type_icons.get(entry.suffix.lower(), "📄")
            raw_size = entry.stat().st_size if entry.is_file() else None
            entries.append({
                "name": entry.name,
                "type": "dir" if is_dir else "file",
                "size": raw_size,
                "size_human": _human_size(raw_size) if raw_size is not None else None,
                "icon": icon,
            })
    except PermissionError:
        return {"error": f"Permission denied: {path}"}

    return {
        "path": str(p),
        "entries": entries[:100],
    }


def read_file(path: str, offset: int = 1, limit: int = 200) -> dict[str, Any]:
    p = normalize_path(path)
    if not p.exists():
        return {"error": f"File not found: {path}"}
    if not p.is_file():
        return {"error": f"Not a file: {path}"}

    try:
        text = p.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines(keepends=True)
        start = max(0, offset - 1)
        end = start + limit
        selected = lines[start:end]
        return {
            "path": str(p),
            "offset": offset,
            "limit": limit,
            "total_lines": len(lines),
            "content": "".join(selected),
        }
    except Exception as e:
        return {"error": str(e)}


def grep_files(pattern: str, path: str = ".", include: str = "") -> dict[str, Any]:
    import fnmatch
    import re

    root = normalize_path(path)
    if not root.exists():
        return {"error": f"Path does not exist: {path}"}

    regex = re.compile(pattern)
    matches: list[dict[str, Any]] = []

    try:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__", "node_modules", ".venv", "venv"}]
            for fname in filenames:
                if include and not fnmatch.fnmatch(fname, include):
                    continue
                fpath = Path(dirpath) / fname
                try:
                    text = fpath.read_text(encoding="utf-8", errors="ignore")
                    for i, line in enumerate(text.splitlines(), 1):
                        if regex.search(line):
                            matches.append({
                                "file": str(fpath.relative_to(root)),
                                "line": i,
                                "text": line.strip()[:200],
                            })
                            if len(matches) >= 50:
                                return {"matches": matches, "truncated": True}
                except Exception:
                    pass
    except Exception as e:
        return {"error": str(e)}

    return {"matches": matches, "count": len(matches)}


def edit_file(path: str, old_string: str, new_string: str) -> dict[str, Any]:
    p = normalize_path(path)
    if not p.exists():
        return {"error": f"File does not exist: {path}. Use write_file for new files."}

    if is_dangerous_write_path(str(p)):
        return {"error": f"Refusing to edit dangerous system path: {path}"}

    try:
        original = p.read_text(encoding="utf-8")
        if old_string not in original:
            return {
                "error": "old_string not found in file. Make sure it matches exactly (including whitespace).",
                "hint": "Read the file again with read_file and copy the exact text."
            }

        count = original.count(old_string)
        if count > 1:
            return {
                "error": f"old_string appears {count} times. Make the old_string more unique (include more context)."
            }

        new_content = original.replace(old_string, new_string, 1)
        p.write_text(new_content, encoding="utf-8")

        return {
            "success": True,
            "path": str(p),
            "message": "File edited successfully.",
            "old_length": len(original),
            "new_length": len(new_content),
        }
    except Exception as e:
        return {"error": str(e)}


def write_file(path: str, content: str) -> dict[str, Any]:
    p = normalize_path(path)

    if is_dangerous_write_path(str(p)):
        return {"error": f"Refusing to write to dangerous path: {path}"}

    existed = p.exists()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {
            "success": True,
            "path": str(p),
            "existed_before": existed,
            "message": "File written successfully.",
            "bytes_written": len(content),
            "hint": "Strongly recommended: call list_directory on the parent folder now to verify the current state of files before writing more."
        }
    except Exception as e:
        return {"error": str(e)}


def execute_shell(command: str, description: str = "", timeout: int = 60) -> dict[str, Any]:
    if not description:
        description = "No description provided by the agent."

    command = os.path.expanduser(command)

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=os.getcwd(),
        )
        return {
            "command": command,
            "description": description,
            "exit_code": result.returncode,
            "stdout": result.stdout[-4000:] if result.stdout else "",
            "stderr": result.stderr[-2000:] if result.stderr else "",
            "cwd": os.getcwd(),
        }
    except subprocess.TimeoutExpired:
        return {
            "command": command,
            "error": f"Command timed out after {timeout} seconds",
            "cwd": os.getcwd(),
        }
    except Exception as e:
        return {
            "command": command,
            "error": str(e),
            "cwd": os.getcwd(),
        }


def get_cwd() -> dict[str, Any]:
    """Return the agent's current working directory."""
    return {"cwd": os.getcwd()}


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List files and directories in a given path. Use '.' for the current project root.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path to list. Use '.' for current directory."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file. Always read before editing. Supports offset/limit.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file"},
                    "offset": {"type": "integer", "description": "Starting line number (1-indexed)", "default": 1},
                    "limit": {"type": "integer", "description": "Maximum number of lines to read", "default": 200},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep_files",
            "description": "Search for a pattern across files using Python regex.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern to search for"},
                    "path": {"type": "string", "description": "Directory to search in (default: current dir)", "default": "."},
                    "include": {"type": "string", "description": "Glob pattern to filter files, e.g. '*.py'", "default": ""},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Make a precise edit by replacing an exact old_string with new_string. Preferred for modifications.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File to edit"},
                    "old_string": {"type": "string", "description": "Exact text to replace (must match exactly)"},
                    "new_string": {"type": "string", "description": "Text to replace it with"},
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create a new file or completely overwrite an existing one. Use for brand new files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to write"},
                    "content": {"type": "string", "description": "Full new content"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_shell",
            "description": "Execute a shell command. Provide a clear description. The system will ask for confirmation on potentially dangerous commands.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The shell command to run"},
                    "description": {"type": "string", "description": "Clear explanation of what this command does and why"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 60},
                },
                "required": ["command", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_cwd",
            "description": "Get the agent's current working directory. Useful when the agent needs to confirm location.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]


TOOL_REGISTRY = {
    "list_directory": list_directory,
    "read_file": read_file,
    "grep_files": grep_files,
    "edit_file": edit_file,
    "write_file": write_file,
    "execute_shell": execute_shell,
    "get_cwd": get_cwd,
}