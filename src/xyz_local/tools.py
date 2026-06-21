"""Core tools for xyz-local with safe path handling and helpful errors."""

from __future__ import annotations

import os
import stat
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from xyz_local.safety import is_dangerous_write_path


def _human_size(bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if bytes < 1024:
            return f"{bytes:.1f}{unit}" if unit != "B" else f"{bytes}B"
        bytes /= 1024
    return f"{bytes:.1f}PB"


def normalize_path(path: str) -> Path:
    """Safely expand ~ and resolve the path relative to the current working directory."""
    expanded = os.path.expanduser(path)
    p = Path(expanded)
    if not p.is_absolute():
        p = Path.cwd() / p
    return p.resolve()


def list_directory(path: str = ".", sort_by: str = "name", sort_desc: bool = False) -> dict[str, Any]:
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
        raw_entries = list(p.iterdir())
        if sort_by == "name":
            raw_entries.sort(key=lambda e: e.name, reverse=sort_desc)
        elif sort_by == "size":
            raw_entries.sort(key=lambda e: e.stat().st_size if e.is_file() else 0, reverse=not sort_desc)
        elif sort_by == "modified":
            raw_entries.sort(key=lambda e: e.stat().st_mtime, reverse=not sort_desc)
        elif sort_by == "type":
            raw_entries.sort(key=lambda e: (0 if e.is_dir() else 1, e.name), reverse=sort_desc)
        for entry in raw_entries:
            is_dir = entry.is_dir()
            icon = "📁" if is_dir else type_icons.get(entry.suffix.lower(), "📄")
            fstat = entry.stat()
            raw_size = fstat.st_size if entry.is_file() else None
            mode_str = stat.filemode(fstat.st_mode)
            modified = datetime.fromtimestamp(fstat.st_mtime).isoformat()[:19]
            entries.append({
                "name": entry.name,
                "type": "dir" if is_dir else "file",
                "size": raw_size,
                "size_human": _human_size(raw_size) if raw_size is not None else None,
                "mode": mode_str,
                "modified": modified,
                "icon": icon,
            })
    except PermissionError:
        return {"error": f"Permission denied: {path}"}

    total_files = sum(1 for e in entries if e["type"] == "file")
    total_dirs = sum(1 for e in entries if e["type"] == "dir")
    return {
        "path": str(p),
        "entries": entries[:100],
        "summary": {"total": len(entries), "files": total_files, "dirs": total_dirs, "shown": min(len(entries), 100)},
    }


def read_file(path: str, offset: int = 1, limit: int = 200) -> dict[str, Any]:
    p = normalize_path(path)
    if not p.exists():
        return {"error": f"File not found: {path}"}
    if not p.is_file():
        return {"error": f"Not a file: {path}"}

    try:
        raw = p.read_bytes()
        null_bytes = raw.count(b"\x00")
        is_binary = null_bytes > 0 and null_bytes > len(raw) * 0.01
        if is_binary:
            ext = p.suffix.lower()
            mime_hint = {
                ".png": "PNG image", ".jpg": "JPEG image", ".jpeg": "JPEG image",
                ".gif": "GIF image", ".pdf": "PDF document", ".zip": "ZIP archive",
                ".tar": "TAR archive", ".gz": "GZip archive", ".mp3": "MP3 audio",
                ".mp4": "MP4 video", ".so": "Shared object", ".dll": "DLL library",
                ".pyc": "Compiled Python", ".whl": "Python wheel",
            }
            hint = mime_hint.get(ext, "binary")
            return {"error": f"File appears to be a {hint} file ({null_bytes} null bytes detected). Use a shell command to inspect it.", "path": str(p), "binary": True}
        text = p.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines(keepends=True)
        start = max(0, offset - 1)
        end = start + limit
        selected = lines[start:end]
        if start >= len(lines):
            return {"error": f"Offset {offset} is beyond file length ({len(lines)} lines)", "total_lines": len(lines)}
        return {
            "path": str(p),
            "offset": offset,
            "limit": limit,
            "total_lines": len(lines),
            "lines_returned": len(selected),
            "content": "".join(selected),
        }
    except Exception as e:
        return {"error": str(e)}


def _load_gitignore(root: Path) -> list[str]:
    gitignore_patterns = []
    gitignore_path = root / ".gitignore"
    if gitignore_path.exists():
        for line in gitignore_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                gitignore_patterns.append(line)
    return gitignore_patterns


def _is_ignored(path: Path, root: Path, gitignore_patterns: list[str]) -> bool:
    import fnmatch
    try:
        rel = str(path.relative_to(root))
    except ValueError:
        return False
    for pattern in gitignore_patterns:
        if pattern.startswith("/"):
            if fnmatch.fnmatch(rel, pattern.lstrip("/")):
                return True
        else:
            if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(rel, f"**/{pattern}"):
                return True
    return False


def grep_files(pattern: str, path: str = ".", include: str = "", ignore_case: bool = False, max_count: int = 50, context: int = 0) -> dict[str, Any]:
    import fnmatch
    import re

    root = normalize_path(path)
    if not root.exists():
        return {"error": f"Path does not exist: {path}"}

    flags = re.IGNORECASE if ignore_case else 0
    regex = re.compile(pattern, flags)
    matches: list[dict[str, Any]] = []
    gitignore_patterns = _load_gitignore(root)

    try:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__", "node_modules", ".venv", "venv"}]
            if gitignore_patterns:
                dirnames[:] = [d for d in dirnames if not _is_ignored(Path(dirpath) / d, root, gitignore_patterns)]
            for fname in filenames:
                if include and not fnmatch.fnmatch(fname, include):
                    continue
                fpath = Path(dirpath) / fname
                if gitignore_patterns and _is_ignored(fpath, root, gitignore_patterns):
                    continue
                try:
                    text = fpath.read_text(encoding="utf-8", errors="ignore")
                    all_lines = text.splitlines()
                    for i, line in enumerate(all_lines, 1):
                        if regex.search(line):
                            entry: dict[str, Any] = {
                                "file": str(fpath.relative_to(root)),
                                "line": i,
                                "text": line.strip()[:200],
                            }
                            if context > 0:
                                start = max(0, i - 1 - context)
                                end = min(len(all_lines), i + context)
                                entry["context"] = "\n".join(
                                    f"{j+1}:{all_lines[j]}" for j in range(start, end)
                                )
                            matches.append(entry)
                            if len(matches) >= max_count:
                                return {"matches": matches, "truncated": True, "max_count": max_count}
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

        backup_path = p.with_suffix(p.suffix + ".bak")
        backup_path.write_text(original, encoding="utf-8")

        new_content = original.replace(old_string, new_string, 1)
        p.write_text(new_content, encoding="utf-8")

        return {
            "success": True,
            "path": str(p),
            "backup_path": str(backup_path),
            "message": "File edited successfully. Backup saved.",
            "old_length": len(original),
            "new_length": len(new_content),
        }
    except Exception as e:
        return {"error": str(e)}


def write_file(path: str, content: str, force: bool = False) -> dict[str, Any]:
    p = normalize_path(path)

    if is_dangerous_write_path(str(p)):
        return {"error": f"Refusing to write to dangerous path: {path}"}

    existed = p.exists()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        if existed:
            backup_path = p.with_suffix(p.suffix + ".bak")
            backup_path.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
        p.write_text(content, encoding="utf-8")
        return {
            "success": True,
            "path": str(p),
            "existed_before": existed,
            "overwritten": existed,
            "message": "File written successfully." if not existed else "File overwritten successfully (backup saved).",
            "bytes_written": len(content),
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


def create_directory(path: str) -> dict[str, Any]:
    p = normalize_path(path)
    if is_dangerous_write_path(str(p)):
        return {"error": f"Refusing to create directory at dangerous path: {path}"}
    try:
        existed = p.exists()
        p.mkdir(parents=True, exist_ok=True)
        return {
            "success": True,
            "path": str(p),
            "message": f"Directory already existed: {p}" if existed else f"Created directory: {p}",
        }
    except Exception as e:
        return {"error": str(e)}


def find_files(pattern: str, path: str = ".", include_dirs: bool = False) -> dict[str, Any]:
    import fnmatch
    root = normalize_path(path)
    if not root.exists():
        return {"error": f"Path does not exist: {path}"}

    gitignore_patterns = _load_gitignore(root)
    matches: list[str] = []

    try:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                d for d in dirnames
                if d not in {".git", "__pycache__", "node_modules", ".venv", "venv"}
                and not (gitignore_patterns and _is_ignored(Path(dirpath) / d, root, gitignore_patterns))
            ]
            if include_dirs:
                for d in dirnames:
                    if fnmatch.fnmatch(d, pattern):
                        rel = str((Path(dirpath) / d).relative_to(root))
                        matches.append(rel)
            for fname in filenames:
                if fnmatch.fnmatch(fname, pattern):
                    rel = str((Path(dirpath) / fname).relative_to(root))
                    matches.append(rel)
                    if len(matches) >= 200:
                        return {"matches": matches, "truncated": True}
    except Exception as e:
        return {"error": str(e)}

    return {"matches": sorted(matches), "count": len(matches)}


# ─────────────────────────────────────────────── File operations ──

def _backup(p: Path) -> Optional[str]:
    """Create a .bak copy of an existing file. Returns the backup path or None."""
    if p.exists() and p.is_file():
        backup = p.with_suffix(p.suffix + ".bak")
        backup.write_bytes(p.read_bytes())
        return str(backup)
    return None


def delete_file(path: str) -> dict[str, Any]:
    p = normalize_path(path)
    if is_dangerous_write_path(str(p)):
        return {"error": f"Refusing to delete dangerous path: {path}"}
    if not p.exists():
        return {"error": f"File not found: {path}"}
    if p.is_dir():
        return {"error": f"Path is a directory (use a shell command to remove dirs): {path}"}
    try:
        backup = _backup(p)
        p.unlink()
        return {"success": True, "path": str(p), "backup_path": backup, "message": f"Deleted {p} (backup saved)."}
    except Exception as e:
        return {"error": str(e)}


def move_file(src: str, dest: str) -> dict[str, Any]:
    s = normalize_path(src)
    d = normalize_path(dest)
    if is_dangerous_write_path(str(s)) or is_dangerous_write_path(str(d)):
        return {"error": "Refusing to move to/from a dangerous path."}
    if not s.exists():
        return {"error": f"Source not found: {src}"}
    try:
        d.parent.mkdir(parents=True, exist_ok=True)
        backup = _backup(d) if d.exists() else None
        import shutil
        shutil.move(str(s), str(d))
        return {"success": True, "src": str(s), "dest": str(d), "backup_path": backup, "message": f"Moved to {d}."}
    except Exception as e:
        return {"error": str(e)}


def copy_file(src: str, dest: str) -> dict[str, Any]:
    s = normalize_path(src)
    d = normalize_path(dest)
    if is_dangerous_write_path(str(d)):
        return {"error": f"Refusing to copy to dangerous path: {dest}"}
    if not s.exists():
        return {"error": f"Source not found: {src}"}
    try:
        d.parent.mkdir(parents=True, exist_ok=True)
        backup = _backup(d) if d.exists() else None
        import shutil
        if s.is_dir():
            shutil.copytree(str(s), str(d), dirs_exist_ok=True)
        else:
            shutil.copy2(str(s), str(d))
        return {"success": True, "src": str(s), "dest": str(d), "backup_path": backup, "message": f"Copied to {d}."}
    except Exception as e:
        return {"error": str(e)}


def multi_edit(path: str, edits: list[dict[str, str]]) -> dict[str, Any]:
    """Apply several exact old_string→new_string edits to one file atomically."""
    p = normalize_path(path)
    if is_dangerous_write_path(str(p)):
        return {"error": f"Refusing to edit dangerous path: {path}"}
    if not p.exists():
        return {"error": f"File does not exist: {path}. Use write_file for new files."}
    if not isinstance(edits, list) or not edits:
        return {"error": "edits must be a non-empty list of {old_string, new_string} objects."}
    try:
        original = p.read_text(encoding="utf-8")
        content = original
        for i, e in enumerate(edits):
            old = e.get("old_string", "")
            new = e.get("new_string", "")
            if not old:
                return {"error": f"Edit {i}: old_string is empty."}
            count = content.count(old)
            if count == 0:
                return {"error": f"Edit {i}: old_string not found (after prior edits). Make it more specific."}
            if count > 1:
                return {"error": f"Edit {i}: old_string appears {count} times. Add more context to make it unique."}
            content = content.replace(old, new, 1)
        backup = _backup(p)
        p.write_text(content, encoding="utf-8")
        return {
            "success": True, "path": str(p), "backup_path": backup,
            "edits_applied": len(edits), "message": f"Applied {len(edits)} edits.",
        }
    except Exception as e:
        return {"error": str(e)}


def directory_tree(path: str = ".", max_depth: int = 3) -> dict[str, Any]:
    root = normalize_path(path)
    if not root.exists():
        return {"error": f"Path does not exist: {path}"}
    if not root.is_dir():
        return {"error": f"Not a directory: {path}"}

    skip = {".git", "__pycache__", "node_modules", ".venv", "venv", ".pytest_cache", ".mypy_cache"}
    gitignore = _load_gitignore(root)
    lines: list[str] = [root.name + "/"]
    truncated = False

    def walk(d: Path, prefix: str, depth: int):
        nonlocal truncated
        if depth > max_depth:
            return
        try:
            entries = sorted(d.iterdir(), key=lambda e: (e.is_file(), e.name))
        except PermissionError:
            return
        entries = [
            e for e in entries
            if e.name not in skip and not (gitignore and _is_ignored(e, root, gitignore))
        ]
        for idx, e in enumerate(entries):
            if len(lines) >= 400:
                truncated = True
                return
            last = idx == len(entries) - 1
            connector = "└── " if last else "├── "
            lines.append(f"{prefix}{connector}{e.name}{'/' if e.is_dir() else ''}")
            if e.is_dir():
                walk(e, prefix + ("    " if last else "│   "), depth + 1)

    walk(root, "", 1)
    return {"path": str(root), "tree": "\n".join(lines), "truncated": truncated}


def file_info(path: str) -> dict[str, Any]:
    p = normalize_path(path)
    if not p.exists():
        return {"error": f"Path not found: {path}"}
    try:
        st = p.stat()
        info: dict[str, Any] = {
            "path": str(p),
            "type": "dir" if p.is_dir() else "file",
            "size": st.st_size,
            "size_human": _human_size(st.st_size),
            "mode": stat.filemode(st.st_mode),
            "modified": datetime.fromtimestamp(st.st_mtime).isoformat()[:19],
        }
        if p.is_file():
            try:
                raw = p.read_bytes()
                if b"\x00" not in raw[:1024]:
                    info["lines"] = raw.count(b"\n") + (0 if raw.endswith(b"\n") or not raw else 1)
            except Exception:
                pass
        return info
    except Exception as e:
        return {"error": str(e)}


# ──────────────────────────────────────────── Code intelligence ──

def _run(argv: list[str], timeout: int = 120) -> dict[str, Any]:
    """Run a fixed-binary command (shell=False) and capture output."""
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=os.getcwd())
        return {
            "exit_code": r.returncode,
            "stdout": (r.stdout or "")[-6000:],
            "stderr": (r.stderr or "")[-3000:],
        }
    except FileNotFoundError:
        return {"error": f"Command not found: {argv[0]}. Is it installed?"}
    except subprocess.TimeoutExpired:
        return {"error": f"Command timed out after {timeout}s: {' '.join(argv)}"}
    except Exception as e:
        return {"error": str(e)}


def run_tests(path: str = ".", extra_args: str = "") -> dict[str, Any]:
    import shlex
    argv = ["pytest", path] + (shlex.split(extra_args) if extra_args else [])
    res = _run(argv, timeout=300)
    if "error" in res:
        return res
    out = (res.get("stdout", "") + "\n" + res.get("stderr", "")).strip()
    summary = ""
    for line in reversed(out.splitlines()):
        if "passed" in line or "failed" in line or "error" in line:
            summary = line.strip("= ")
            break
    return {"exit_code": res["exit_code"], "passed": res["exit_code"] == 0, "summary": summary, "output": out[-4000:]}


def lint_code(path: str = ".") -> dict[str, Any]:
    res = _run(["ruff", "check", path])
    if "error" in res:
        return res
    out = (res.get("stdout", "") or res.get("stderr", "")).strip()
    return {"exit_code": res["exit_code"], "clean": res["exit_code"] == 0, "output": out[:5000] or "No issues found."}


def format_code(path: str = ".") -> dict[str, Any]:
    res = _run(["ruff", "format", path])
    if "error" in res:
        return res
    out = (res.get("stdout", "") or res.get("stderr", "")).strip()
    return {"success": res["exit_code"] == 0, "exit_code": res["exit_code"], "message": out or "Formatted."}


def python_check(path: str) -> dict[str, Any]:
    import ast
    p = normalize_path(path)
    if not p.exists():
        return {"error": f"File not found: {path}"}
    try:
        source = p.read_text(encoding="utf-8")
        ast.parse(source, filename=str(p))
        return {"path": str(p), "valid": True, "message": "No syntax errors."}
    except SyntaxError as e:
        return {"path": str(p), "valid": False, "error": f"{e.msg} at line {e.lineno}, col {e.offset}"}
    except Exception as e:
        return {"error": str(e)}


def extract_symbols(path: str) -> dict[str, Any]:
    import ast
    p = normalize_path(path)
    if not p.exists() or not p.is_file():
        return {"error": f"File not found: {path}"}
    try:
        source = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"error": str(e)}

    symbols: list[dict[str, Any]] = []
    if p.suffix == ".py":
        try:
            tree = ast.parse(source)
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.append({"type": "function", "name": node.name, "line": node.lineno})
                elif isinstance(node, ast.ClassDef):
                    symbols.append({"type": "class", "name": node.name, "line": node.lineno})
                    for sub in node.body:
                        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            symbols.append({"type": "method", "name": f"{node.name}.{sub.name}", "line": sub.lineno})
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    mod = getattr(node, "module", None) or ",".join(a.name for a in node.names)
                    symbols.append({"type": "import", "name": mod, "line": node.lineno})
        except SyntaxError as e:
            return {"error": f"Syntax error: {e.msg} at line {e.lineno}"}
    else:
        import re
        for i, line in enumerate(source.splitlines(), 1):
            m = re.match(r"\s*(?:export\s+)?(?:async\s+)?(function|class|def)\s+(\w+)", line)
            if m:
                symbols.append({"type": m.group(1), "name": m.group(2), "line": i})
    return {"path": str(p), "symbols": symbols, "count": len(symbols)}


# ─────────────────────────────────────────────────────────── Git ──

def _git(argv: list[str]) -> dict[str, Any]:
    return _run(["git"] + argv, timeout=60)


def git_status() -> dict[str, Any]:
    res = _git(["status", "--porcelain=v1", "-b"])
    if "error" in res:
        return res
    if res["exit_code"] != 0:
        return {"error": res.get("stderr", "git status failed").strip()}
    branch = ""
    changes = []
    for line in res["stdout"].splitlines():
        if line.startswith("##"):
            branch = line[3:].strip()
        elif line:
            changes.append({"status": line[:2].strip(), "file": line[3:]})
    return {"branch": branch, "changes": changes, "clean": not changes}


def git_diff(path: str = "", staged: bool = False) -> dict[str, Any]:
    argv = ["diff"] + (["--staged"] if staged else [])
    if path:
        argv += ["--", path]
    res = _git(argv)
    if "error" in res:
        return res
    return {"diff": res["stdout"][:8000] or "(no changes)", "truncated": len(res["stdout"]) > 8000}


def git_log(max_count: int = 10) -> dict[str, Any]:
    res = _git(["log", f"-{max_count}", "--pretty=format:%h%x1f%an%x1f%ad%x1f%s", "--date=short"])
    if "error" in res:
        return res
    if res["exit_code"] != 0:
        return {"error": res.get("stderr", "git log failed").strip()}
    commits = []
    for line in res["stdout"].splitlines():
        parts = line.split("\x1f")
        if len(parts) == 4:
            commits.append({"hash": parts[0], "author": parts[1], "date": parts[2], "subject": parts[3]})
    return {"commits": commits, "count": len(commits)}


def git_branch(action: str = "list", name: str = "") -> dict[str, Any]:
    if action == "list":
        res = _git(["branch", "--all"])
        if "error" in res:
            return res
        branches = [b.strip("* ").strip() for b in res["stdout"].splitlines() if b.strip()]
        current = next((b[2:].strip() for b in res["stdout"].splitlines() if b.startswith("*")), "")
        return {"branches": branches, "current": current}
    if not name:
        return {"error": "A branch name is required for create/switch."}
    if action == "create":
        res = _git(["checkout", "-b", name])
    elif action == "switch":
        res = _git(["checkout", name])
    else:
        return {"error": f"Unknown action: {action}. Use list, create, or switch."}
    if "error" in res:
        return res
    if res["exit_code"] != 0:
        return {"error": (res.get("stderr") or res.get("stdout") or "git branch failed").strip()}
    return {"success": True, "message": f"{action} branch {name}."}


def git_commit(message: str) -> dict[str, Any]:
    """Commit currently-staged changes. Stage files first (git add via execute_shell)."""
    if not message.strip():
        return {"error": "A commit message is required."}
    res = _git(["commit", "-m", message])
    if "error" in res:
        return res
    out = (res.get("stdout") or "").strip()
    if res["exit_code"] != 0:
        return {"error": (res.get("stderr") or out or "git commit failed").strip(), "hint": "Did you stage changes? Use 'git add' first."}
    return {"success": True, "message": out[:500]}


# ──────────────────────────────────────────── Web / productivity ──

_TODOS: list[dict[str, str]] = []


def web_fetch(url: str, max_chars: int = 8000) -> dict[str, Any]:
    import re
    import httpx
    if not url.startswith(("http://", "https://")):
        return {"error": "URL must start with http:// or https://"}
    try:
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": "xyz-local/1.0"})
            resp.raise_for_status()
            ctype = resp.headers.get("content-type", "")
            text = resp.text
            if "html" in ctype:
                text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", text, flags=re.DOTALL | re.IGNORECASE)
                text = re.sub(r"<[^>]+>", " ", text)
                text = re.sub(r"\s+", " ", text).strip()
            return {
                "url": str(resp.url), "status": resp.status_code, "content_type": ctype,
                "content": text[:max_chars], "truncated": len(text) > max_chars,
            }
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code} for {url}"}
    except Exception as e:
        return {"error": f"Fetch failed: {e}"}


def todo_write(todos: list[dict[str, str]]) -> dict[str, Any]:
    """Replace the session task list. Each todo is {content, status}; status in pending/in_progress/completed."""
    global _TODOS
    if not isinstance(todos, list):
        return {"error": "todos must be a list of {content, status} objects."}
    cleaned = []
    for t in todos:
        if isinstance(t, dict) and t.get("content"):
            cleaned.append({"content": str(t["content"]), "status": str(t.get("status", "pending"))})
    _TODOS = cleaned
    done = sum(1 for t in _TODOS if t["status"] == "completed")
    return {"todos": _TODOS, "total": len(_TODOS), "completed": done}


def system_info() -> dict[str, Any]:
    import platform
    info: dict[str, Any] = {
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "cwd": os.getcwd(),
    }
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal"):
                    info["mem_total"] = _human_size(int(line.split()[1]) * 1024)
                elif line.startswith("MemAvailable"):
                    info["mem_available"] = _human_size(int(line.split()[1]) * 1024)
                    break
    except Exception:
        pass
    gpu = _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"], timeout=10)
    if "error" not in gpu and gpu.get("exit_code") == 0 and gpu.get("stdout").strip():
        info["gpu"] = gpu["stdout"].strip()
    return info


def which_command(name: str) -> dict[str, Any]:
    import shutil
    path = shutil.which(name)
    return {"name": name, "found": path is not None, "path": path}


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
                    "sort_by": {"type": "string", "description": "Sort field: name, size, modified, or type", "default": "name"},
                    "sort_desc": {"type": "boolean", "description": "Sort in descending order", "default": False},
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
                    "ignore_case": {"type": "boolean", "description": "Case-insensitive search", "default": False},
                    "max_count": {"type": "integer", "description": "Maximum matches to return", "default": 50},
                    "context": {"type": "integer", "description": "Number of context lines around each match", "default": 0},
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
            "description": "Create a new file or overwrite an existing one. Use force=true to overwrite existing files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to write"},
                    "content": {"type": "string", "description": "Full new content"},
                    "force": {"type": "boolean", "description": "Force overwrite if file exists", "default": False},
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
            "description": "Get the agent's current working directory.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_directory",
            "description": "Create a directory (and any missing parents). Safe to call if directory already exists.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path to create"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_files",
            "description": "Find files by filename pattern (glob). Use grep_files to search file contents instead.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern, e.g. '*.py', 'test_*.py', 'config.*'"},
                    "path": {"type": "string", "description": "Directory to search in", "default": "."},
                    "include_dirs": {"type": "boolean", "description": "Also match directory names", "default": False},
                },
                "required": ["pattern"],
            },
        },
    },
    # ── File operations ──
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "Delete a file (a .bak backup is saved first). Requires confirmation unless in trust mode.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "File to delete"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_file",
            "description": "Move or rename a file/directory. Backs up the destination if it exists.",
            "parameters": {
                "type": "object",
                "properties": {
                    "src": {"type": "string", "description": "Source path"},
                    "dest": {"type": "string", "description": "Destination path"},
                },
                "required": ["src", "dest"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "copy_file",
            "description": "Copy a file or directory. Backs up the destination if it exists.",
            "parameters": {
                "type": "object",
                "properties": {
                    "src": {"type": "string", "description": "Source path"},
                    "dest": {"type": "string", "description": "Destination path"},
                },
                "required": ["src", "dest"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "multi_edit",
            "description": "Apply several exact old_string→new_string edits to one file atomically (all or nothing).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File to edit"},
                    "edits": {
                        "type": "array",
                        "description": "List of edits, each with old_string and new_string",
                        "items": {
                            "type": "object",
                            "properties": {
                                "old_string": {"type": "string"},
                                "new_string": {"type": "string"},
                            },
                            "required": ["old_string", "new_string"],
                        },
                    },
                },
                "required": ["path", "edits"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "directory_tree",
            "description": "Show a directory as an indented tree (gitignore-aware). Good for understanding project structure.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Root directory", "default": "."},
                    "max_depth": {"type": "integer", "description": "Maximum depth to descend", "default": 3},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_info",
            "description": "Get metadata for a file or directory: size, type, permissions, modified time, line count.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Path to inspect"}},
                "required": ["path"],
            },
        },
    },
    # ── Code intelligence ──
    {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": "Run pytest and report whether tests passed, with a summary.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path or test target", "default": "."},
                    "extra_args": {"type": "string", "description": "Extra pytest args, e.g. '-k name -x'", "default": ""},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lint_code",
            "description": "Run ruff to lint Python code and report issues.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Path to lint", "default": "."}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "format_code",
            "description": "Run ruff format to auto-format Python code (modifies files). Requires confirmation.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Path to format", "default": "."}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "python_check",
            "description": "Check a Python file for syntax errors without running it.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Python file to check"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "extract_symbols",
            "description": "List the functions, classes, methods, and imports defined in a file, with line numbers.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "File to analyze"}},
                "required": ["path"],
            },
        },
    },
    # ── Git ──
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Show the git status: current branch and changed files.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "Show the git diff. Use staged=true for the staged diff; optionally limit to a path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Limit diff to this path", "default": ""},
                    "staged": {"type": "boolean", "description": "Show staged changes", "default": False},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_log",
            "description": "Show recent git commits (hash, author, date, subject).",
            "parameters": {
                "type": "object",
                "properties": {"max_count": {"type": "integer", "description": "Number of commits", "default": 10}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_branch",
            "description": "List branches, or create/switch a branch. Create/switch requires confirmation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "list, create, or switch", "default": "list"},
                    "name": {"type": "string", "description": "Branch name (for create/switch)", "default": ""},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_commit",
            "description": "Commit staged changes with a message. Stage files first via execute_shell 'git add'. Requires confirmation.",
            "parameters": {
                "type": "object",
                "properties": {"message": {"type": "string", "description": "Commit message"}},
                "required": ["message"],
            },
        },
    },
    # ── Web / productivity ──
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch the text content of a URL (HTML is stripped to text). Makes an outbound network request; requires confirmation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "http(s) URL to fetch"},
                    "max_chars": {"type": "integer", "description": "Max characters to return", "default": 8000},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "todo_write",
            "description": "Set the session task list to track multi-step work. Pass the full list each time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "description": "Tasks, each {content, status} where status is pending/in_progress/completed",
                        "items": {
                            "type": "object",
                            "properties": {
                                "content": {"type": "string"},
                                "status": {"type": "string"},
                            },
                            "required": ["content", "status"],
                        },
                    },
                },
                "required": ["todos"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "system_info",
            "description": "Report OS, Python version, CPU count, memory, and GPU (if available).",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "which_command",
            "description": "Locate an executable on PATH (like the 'which' command).",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "Executable name, e.g. 'python3', 'git'"}},
                "required": ["name"],
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
    "create_directory": create_directory,
    "find_files": find_files,
    # File operations
    "delete_file": delete_file,
    "move_file": move_file,
    "copy_file": copy_file,
    "multi_edit": multi_edit,
    "directory_tree": directory_tree,
    "file_info": file_info,
    # Code intelligence
    "run_tests": run_tests,
    "lint_code": lint_code,
    "format_code": format_code,
    "python_check": python_check,
    "extract_symbols": extract_symbols,
    # Git
    "git_status": git_status,
    "git_diff": git_diff,
    "git_log": git_log,
    "git_branch": git_branch,
    "git_commit": git_commit,
    # Web / productivity
    "web_fetch": web_fetch,
    "todo_write": todo_write,
    "system_info": system_info,
    "which_command": which_command,
}