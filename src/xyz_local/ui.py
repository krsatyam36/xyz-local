"""UI sink abstraction so the agent loop is decoupled from how output is shown.

The agent calls these (async) hooks during a turn. Two implementations exist:

- ``ConsoleUI``  — plain streaming to the terminal (used by ``xyz-local run`` and
  the ``--plain`` REPL).
- ``TextualUI``  — drives the full-screen Textual app (see ``tui.py``).
"""

from __future__ import annotations

import sys
from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm


def tool_preview(name: str, args: dict[str, Any]) -> str:
    """Compact one-line description of a tool call's arguments."""
    if name == "read_file":
        path = args.get("path", "")
        offset = args.get("offset", 1)
        return f"{path}:{offset}" if offset and offset != 1 else f"{path}"
    if name in ("write_file", "create_directory"):
        return str(args.get("path", ""))
    if name == "edit_file":
        old = str(args.get("old_string", ""))[:40].replace("\n", "↵")
        return f"{args.get('path', '')}  [{old}…]"
    if name == "execute_shell":
        return str(args.get("command", ""))[:80]
    if name == "grep_files":
        return f"/{args.get('pattern', '')}/ in {args.get('path', '.')}"
    if name in ("list_directory", "find_files", "directory_tree"):
        return str(args.get("path", args.get("pattern", ".")))
    if name in ("delete_file", "file_info", "python_check", "extract_symbols"):
        return str(args.get("path", ""))
    if name in ("move_file", "copy_file"):
        return f"{args.get('src', '')} → {args.get('dest', '')}"
    if name == "multi_edit":
        return f"{args.get('path', '')} ({len(args.get('edits', []))} edits)"
    if name in ("run_tests", "lint_code", "format_code"):
        return str(args.get("path", "."))
    if name == "git_diff":
        return "staged" if args.get("staged") else str(args.get("path", ""))
    if name == "git_branch":
        return f"{args.get('action', 'list')} {args.get('name', '')}".strip()
    if name == "git_commit":
        return str(args.get("message", ""))[:60]
    if name == "web_fetch":
        return str(args.get("url", ""))[:70]
    if name == "todo_write":
        return f"{len(args.get('todos', []))} tasks"
    if name == "which_command":
        return str(args.get("name", ""))
    return ""


# Friendly verbs for tool calls (opencode-style "→ Read file").
TOOL_VERBS = {
    "read_file": "Read",
    "write_file": "Write",
    "edit_file": "Edit",
    "create_directory": "Create dir",
    "list_directory": "List",
    "grep_files": "Grep",
    "find_files": "Find",
    "execute_shell": "Run",
    "get_cwd": "Cwd",
    # File operations
    "delete_file": "Delete",
    "move_file": "Move",
    "copy_file": "Copy",
    "multi_edit": "Multi-edit",
    "directory_tree": "Tree",
    "file_info": "Stat",
    # Code intelligence
    "run_tests": "Test",
    "lint_code": "Lint",
    "format_code": "Format",
    "python_check": "Check",
    "extract_symbols": "Symbols",
    # Git
    "git_status": "Git status",
    "git_diff": "Git diff",
    "git_log": "Git log",
    "git_branch": "Git branch",
    "git_commit": "Git commit",
    # Web / productivity
    "web_fetch": "Fetch",
    "todo_write": "Todo",
    "system_info": "System",
    "which_command": "Which",
}


class AgentUI:
    """Base UI sink. All hooks are async so interactive backends can await modals."""

    async def thinking(self, ms: int) -> None:
        """Model finished 'thinking' for this step (time to first output)."""

    async def stream_delta(self, text: str) -> None:
        """A chunk of streamed assistant prose."""

    async def stream_end(self) -> None:
        """The current streamed message is complete."""

    async def tool_call(self, name: str, args: dict[str, Any]) -> None:
        """The agent is about to run a tool."""

    async def tool_result(self, name: str, result: dict[str, Any]) -> None:
        """A tool finished; ``result`` is its return dict."""

    async def assistant_message(self, text: str) -> None:
        """A complete (non-streamed) assistant message."""

    async def notice(self, text: str, style: str = "dim") -> None:
        """An out-of-band status line."""

    async def confirm(self, command: str, reason: str, description: str) -> bool:
        """Ask the user to approve a shell command. Return True to allow."""
        return False


class ConsoleUI(AgentUI):
    """Plain streaming console output."""

    def __init__(self, console: Console | None = None, render_markdown: bool = True):
        self.console = console or Console()
        self.render_markdown = render_markdown
        self._streamed = ""

    async def thinking(self, ms: int) -> None:
        self.console.print(f"[dim]+ Thought: {ms}ms[/dim]")

    async def stream_delta(self, text: str) -> None:
        sys.stdout.write(text)
        sys.stdout.flush()
        self._streamed += text

    async def stream_end(self) -> None:
        sys.stdout.write("\n")
        sys.stdout.flush()
        self._streamed = ""

    async def tool_call(self, name: str, args: dict[str, Any]) -> None:
        verb = TOOL_VERBS.get(name, name)
        self.console.print(f"[cyan]→[/cyan] [bold]{verb}[/bold] [dim]{tool_preview(name, args)}[/dim]")

    async def tool_result(self, name: str, result: dict[str, Any]) -> None:
        if "error" in result:
            self.console.print(f"  [red]✗[/red] {str(result['error'])[:300]}")
        elif name == "execute_shell":
            exit_code = result.get("exit_code", "?")
            output = result.get("stdout") or result.get("stderr") or ""
            if output:
                lines = output.strip().split("\n")
                for line in lines[:20]:
                    self.console.print(f"  [dim]{line}[/dim]")
                if len(lines) > 20:
                    self.console.print(f"  [dim]… {len(lines) - 20} more lines[/dim]")
            self.console.print(f"  [dim]exit={exit_code}[/dim]")
        elif name in ("write_file", "edit_file", "create_directory"):
            self.console.print(f"  [green]✓[/green] {result.get('message', 'done')}")

    async def assistant_message(self, text: str) -> None:
        if self.render_markdown:
            self.console.print(Markdown(text))
        else:
            self.console.print(text)

    async def notice(self, text: str, style: str = "dim") -> None:
        self.console.print(f"[{style}]{text}[/{style}]")

    async def confirm(self, command: str, reason: str, description: str) -> bool:
        self.console.print(Panel(
            f"[yellow]Command requires confirmation[/yellow]\n\n"
            f"Command: [bold]{command}[/bold]\n"
            f"Reason: {reason}\n"
            f"Agent says: {description}",
            title="Shell Command",
            border_style="yellow",
        ))
        return Confirm.ask("Allow this command?", default=False)
