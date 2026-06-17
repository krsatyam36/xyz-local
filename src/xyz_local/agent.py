"""Core agent loop for xyz-local (local Ollama edition).

This version includes:
- Greeting guard (instant replies, no tools)
- Meta-question guard ("what can you do?")
- Project name preprocessing ("read the xyz-local project" → ".")
- Very strict system prompt against unnecessary exploration
- Graceful handling when models don't support tools
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from datetime import datetime

from xyz_local.config import Config
from xyz_local.memory import SessionMemory
from xyz_local.ollama_client import OllamaClient
from xyz_local.safety import classify_command, PermissionTier
from xyz_local.tools import TOOL_DEFINITIONS, TOOL_REGISTRY

console = Console()


def _sanitize_assistant_text(text: str) -> str:
    """Remove raw tool call JSON blocks from the model's text response."""
    import re
    if not text:
        return text
    text = re.sub(r'```(?:json)?\s*\n?\s*\{\s*"name"\s*:\s*".*?"[\s\S]*?\}\s*\n?```', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\n?\s*\{\s*"name"\s*:\s*".*?"[\s\S]*?"arguments"\s*:\s*\{[\s\S]*?\}\s*\}', '', text)
    text = re.sub(r'<tool_call>[\s\S]*?</tool_call>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return text


SYSTEM_PROMPT = """You are xyz-local, a powerful AI coding assistant running on the user's machine via Ollama.

You have tools to read files, write files, edit code, run shell commands, search codebases, and manage directories. Use them freely and chain them together to complete tasks fully.

**HOW TO WORK:**

For fixing bugs, adding features, or modifying code:
1. Use grep_files to locate the relevant code
2. Use read_file to read the files you need to understand
3. Use edit_file for precise targeted changes, or write_file for new files/full rewrites
4. Use execute_shell to run tests, linters, or the program to verify the change works
5. Fix any issues found and confirm the task is done

For writing new scripts or files:
1. Use write_file immediately with complete, working code

For exploring or understanding a codebase:
1. Use list_directory to see the structure
2. Use grep_files to find functions, classes, or patterns
3. Use read_file to read the relevant sections
4. Explain what you found

**TOOL RULES:**
- Always read_file before editing — never edit blind
- Use grep_files to find symbols before diving into files
- Use execute_shell freely: run tests, git status, install packages, build, etc.
- edit_file requires exact old_string — if unsure, read the file first
- Chain multiple tool calls to finish tasks completely — don't stop halfway
- After changing code, run the relevant test or command to confirm it works

**BEHAVIOR:**
- Be direct and action-oriented — do the task, don't describe what you'll do
- Don't ask for permission unless about to do something destructive
- Call tools without narrating — just call them and act on the results
- Keep working until the task is fully done

Current working directory: {cwd}
"""


class Agent:
    def __init__(
        self,
        client: OllamaClient,
        config: Config,
        trust_mode: bool = False,
        verbose: bool = False,
        resume_session: Optional[str] = None,
    ):
        self.client = client
        self.config = config
        self.trust_mode = trust_mode
        self.verbose = verbose
        self.memory = self._load_or_create_memory(resume_session)
        self.memory.model = client.model
        self._last_user_input: str = ""

    def _load_or_create_memory(self, session_id: Optional[str]) -> SessionMemory:
        if session_id:
            mem = SessionMemory.load(session_id, self.config.sessions_dir)
            if mem:
                console.print(f"[dim]Resumed session {session_id}[/dim]")
                return mem
        mem = SessionMemory(model=self.client.model)
        return mem

    def _get_system_prompt(self) -> str:
        return SYSTEM_PROMPT.format(cwd=str(Path.cwd()))

    def _execute_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name not in TOOL_REGISTRY:
            return {"error": f"Unknown tool: {name}"}

        func = TOOL_REGISTRY[name]

        if name == "execute_shell":
            cmd = args.get("command", "")
            desc = args.get("description", "")
            perm = classify_command(cmd, trust_mode=self.trust_mode)

            if perm.tier == PermissionTier.DENY:
                return {"error": f"Command denied by safety system: {perm.reason}", "command": cmd}

            if perm.tier == PermissionTier.ASK:
                console.print(Panel(
                    f"[yellow]Command requires confirmation[/yellow]\n\n"
                    f"Command: [bold]{cmd}[/bold]\n"
                    f"Reason: {perm.reason}\n"
                    f"Description from agent: {desc}",
                    title="Shell Command",
                    border_style="yellow",
                ))
                if not Confirm.ask("Allow this command?", default=False):
                    return {"error": "User denied execution", "command": cmd}

        if name in ("write_file", "edit_file"):
            path = args.get("path", "")
            if path and self._is_very_dangerous_path(path):
                return {"error": f"Refusing to modify dangerous path: {path}"}

        try:
            result = func(**args)
            return result
        except Exception as e:
            return {"error": f"Tool execution failed: {e}"}

    def _is_very_dangerous_path(self, path: str) -> bool:
        from xyz_local.safety import is_dangerous_write_path
        return is_dangerous_write_path(path)

    def _args_preview(self, name: str, args: dict) -> str:
        """Compact display of tool arguments for the console."""
        if name == "read_file":
            path = args.get("path", "")
            offset = args.get("offset", 1)
            suffix = f":{offset}" if offset != 1 else ""
            return f" {path}{suffix}"
        elif name in ("write_file", "create_directory"):
            return f" {args.get('path', '')}"
        elif name == "edit_file":
            path = args.get("path", "")
            old = args.get("old_string", "")[:40].replace("\n", "↵")
            return f" {path} [{old}…]"
        elif name == "execute_shell":
            cmd = args.get("command", "")[:70]
            return f" `{cmd}`"
        elif name == "grep_files":
            pat = args.get("pattern", "")
            path = args.get("path", ".")
            return f" /{pat}/ in {path}"
        elif name in ("list_directory", "find_files"):
            return f" {args.get('path', '.')}"
        return ""

    async def process_turn(self, user_input: str) -> str:
        """Process one user message, running the agentic tool loop until done."""
        import sys

        if not self.memory.messages:
            self.memory.add_message("system", self._get_system_prompt())

        self.memory.add_message("user", user_input)
        self.memory.auto_name()

        turn = 0

        while turn < self.config.max_turns:
            turn += 1

            total_chars = sum(len(str(m.get("content", ""))) for m in self.memory.messages)
            if total_chars > 30000:
                console.print(f"[yellow]Context ~{total_chars} chars — use /clear if responses slow down[/yellow]")

            if self.verbose:
                console.print(f"[dim]Turn {turn}/{self.config.max_turns} · {len(self.memory.messages)} messages[/dim]")

            full_response = ""
            native_tool_calls: list = []
            # Streaming state: None = undecided, True = streaming prose live,
            # False = suppressed (looks like an inline tool-call JSON blob).
            stream_live: Optional[bool] = None
            printed_anything = False

            extra_options = {}
            if self.config.num_ctx > 0:
                extra_options["num_ctx"] = self.config.num_ctx

            async for event in self.client.chat(
                messages=self.memory.messages,
                tools=TOOL_DEFINITIONS,
                temperature=self.config.temperature,
                extra_options=extra_options,
            ):
                if event["type"] == "token":
                    token = event.get("data", "")
                    full_response += token
                    # Decide once, on the first non-whitespace content, whether this
                    # is prose (stream it) or an inline tool call (hide the raw JSON).
                    if stream_live is None:
                        stripped = full_response.lstrip()
                        if stripped:
                            stream_live = not (
                                stripped[0] == "{"
                                or stripped.startswith("```")
                                or stripped.lower().startswith("<tool_call")
                            )
                            if stream_live:
                                sys.stdout.write(stripped)
                                sys.stdout.flush()
                                printed_anything = True
                    elif stream_live:
                        sys.stdout.write(token)
                        sys.stdout.flush()
                        printed_anything = True
                elif event["type"] == "tool_call":
                    native_tool_calls.append(event["data"])
                elif event["type"] == "done":
                    if event.get("tool_calls"):
                        native_tool_calls = event["tool_calls"]
                    break
                elif event["type"] == "error":
                    if printed_anything:
                        sys.stdout.write("\n")
                        sys.stdout.flush()
                    err = event["data"]
                    if err == "MODEL_DOES_NOT_SUPPORT_TOOLS":
                        msg = (
                            "This model doesn't support tool calling. "
                            "Try: xyz-local chat -m qwen2.5-coder:latest"
                        )
                        console.print(f"[red]{msg}[/red]")
                        return msg
                    console.print(f"[red]Error from model:[/red] {err}")
                    return f"Error: {err}"

            # Fallback: parse tool calls out of streamed text if API didn't return them natively
            if not native_tool_calls and full_response:
                from xyz_local.ollama_client import _parse_tool_call_fallback
                native_tool_calls = _parse_tool_call_fallback(full_response)

            clean_response = _sanitize_assistant_text(full_response)

            if not native_tool_calls:
                # Pure text response — done
                if printed_anything:
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                final = clean_response or full_response or ""
                if not final:
                    final = "No response from model. Please rephrase your request."
                    console.print(f"[yellow]{final}[/yellow]")
                elif not printed_anything:
                    console.print(final)
                self.memory.add_message("assistant", final)
                self.memory.save(self.config.sessions_dir)
                return final

            # Has tool calls — ensure newline after any streamed reasoning text
            if printed_anything:
                sys.stdout.write("\n")
                sys.stdout.flush()

            # Normalize tool calls to a consistent format
            normalized_tcs = []
            for tc in native_tool_calls:
                name = tc.get("function", {}).get("name") or tc.get("name", "")
                args = tc.get("function", {}).get("arguments") or tc.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                if name:
                    normalized_tcs.append({"function": {"name": name, "arguments": args}})

            # Store assistant message with tool_calls field so the model sees proper history
            self.memory.messages.append({
                "role": "assistant",
                "content": clean_response or "",
                "tool_calls": normalized_tcs,
            })

            # Execute each tool and append results
            for tc in normalized_tcs:
                name = tc["function"]["name"]
                args = tc["function"]["arguments"]

                console.print(f"[cyan]⚙[/cyan] [bold]{name}[/bold]{self._args_preview(name, args)}")

                result = self._execute_tool(name, args)

                self.memory.messages.append({
                    "role": "tool",
                    "content": json.dumps(result, ensure_ascii=False),
                })

                if "error" in result:
                    console.print(f"  [red]✗[/red] {result['error'][:300]}")
                elif name == "execute_shell":
                    exit_code = result.get("exit_code", "?")
                    stdout = result.get("stdout", "")
                    stderr = result.get("stderr", "")
                    output = stdout or stderr
                    if output:
                        lines = output.strip().split("\n")
                        preview = "\n".join(f"  {l}" for l in lines[:20])
                        console.print(f"  [dim]exit={exit_code}[/dim]\n{preview}")
                        if len(lines) > 20:
                            console.print(f"  [dim]... {len(lines) - 20} more lines[/dim]")
                    else:
                        console.print(f"  [dim]exit={exit_code}[/dim]")
                elif name in ("write_file", "edit_file", "create_directory"):
                    msg = result.get("message", "done")
                    console.print(f"  [green]✓[/green] {msg}")

        self.memory.add_message("assistant", "(max turns reached)")
        self.memory.save(self.config.sessions_dir)
        return "Reached maximum reasoning steps. Please ask me to continue or simplify the request."

    def _remove_last_assistant_turn(self):
        """Remove the last assistant turn and associated tool calls from memory."""
        if len(self.memory.messages) < 2:
            return
        while self.memory.messages and self.memory.messages[-1].get("role") in ("assistant", "tool"):
            self.memory.messages.pop()

    def run_interactive(self):
        """Main interactive loop."""
        console.print(f"[dim]Working directory: {Path.cwd()}[/dim]")
        console.print("[dim]Type your request. Use /help for commands, Ctrl+C to exit.[/dim]\n")

        while True:
            try:
                user_input = Prompt.ask("[bold cyan]>[/bold cyan]")
            except (EOFError, KeyboardInterrupt):
                break

            if not user_input.strip():
                continue

            while user_input.strip().endswith("\\"):
                try:
                    continuation = Prompt.ask("[dim]>[/dim]")
                    user_input = user_input.rstrip("\\") + "\n" + continuation
                except (EOFError, KeyboardInterrupt):
                    break

            if user_input.strip().startswith("/"):
                if user_input.strip() == "/retry" and self._last_user_input:
                    self._remove_last_assistant_turn()
                    import asyncio
                    asyncio.run(self.process_turn(self._last_user_input))
                    console.print()
                    continue
                if self._handle_slash_command(user_input.strip()):
                    continue
                else:
                    break

            self._last_user_input = user_input
            import asyncio
            asyncio.run(self.process_turn(user_input))
            self.memory.save(self.config.sessions_dir)
            console.print()

    def _handle_slash_command(self, cmd: str) -> bool:
        if cmd in {"/exit", "/quit"}:
            return False
        if cmd == "/help":
            console.print(
                "Commands:\n"
                "  /model [name]  List models and pick one (or switch directly by name)\n"
                "  /temp [value]  Show or set temperature (0.0-2.0)\n"
                "  /trust         Toggle trust mode (auto-approve shell commands)\n"
                "  /undo          Revert the last file write\n"
                "  /clear         Clear conversation context\n"
                "  /retry         Re-run your last request\n"
                "  /stats         Session statistics\n"
                "  /memory        Session ID and counts\n"
                "  /inspect       Show last tool result\n"
                "  /save          Force-save session\n"
                "  /exit          Quit\n\n"
                "Most work happens by just chatting normally."
            )
            return True
        if cmd == "/inspect":
            tool_msgs = [m for m in self.memory.messages if m.get("role") == "tool"]
            if not tool_msgs:
                console.print("[yellow]No tool calls to inspect.[/yellow]")
            else:
                last_tool = tool_msgs[-1]
                content = last_tool.get("content", "")
                try:
                    parsed = json.loads(content) if isinstance(content, str) else content
                    console.print(json.dumps(parsed, indent=2))
                except Exception:
                    console.print(content[:2000])
            return True
        if cmd == "/stats":
            tool_count = sum(1 for m in self.memory.messages if m.get("role") == "tool")
            elapsed = datetime.utcnow().isoformat()
            if self.memory.created:
                try:
                    start = datetime.fromisoformat(self.memory.created)
                    delta = datetime.utcnow() - start
                    elapsed = f"{delta.seconds // 3600}h {(delta.seconds // 60) % 60}m {delta.seconds % 60}s"
                except Exception:
                    pass
            console.print("[bold]Session Statistics[/bold]")
            console.print(f"  ID:         {self.memory.id}")
            console.print(f"  Model:      {self.memory.model or 'N/A'}")
            console.print(f"  Duration:   {elapsed}")
            console.print(f"  Messages:   {len(self.memory.messages)}")
            console.print(f"  Tool calls: {tool_count}")
            console.print(f"  File writes: {len(self.memory.file_history)}")
            console.print(f"  Trust mode: {'ON' if self.trust_mode else 'OFF'}")
            return True
        if cmd == "/save":
            self.memory.save(self.config.sessions_dir)
            console.print(f"[green]Session saved:[/green] {self.memory.id}")
            return True
        if cmd.startswith("/temp"):
            parts = cmd.split()
            if len(parts) == 2:
                try:
                    new_temp = float(parts[1])
                    if 0.0 <= new_temp <= 2.0:
                        self.config.temperature = new_temp
                        console.print(f"[green]Temperature set to {new_temp}[/green]")
                    else:
                        console.print("[yellow]Temperature must be between 0.0 and 2.0[/yellow]")
                except ValueError:
                    console.print(f"[yellow]Usage: /temp <value> (0.0-2.0)[/yellow]")
            else:
                console.print(f"[yellow]Current temperature: {self.config.temperature}[/yellow]")
            return True
        if cmd == "/clear":
            self.memory.messages.clear()
            console.print("[green]Conversation context cleared.[/green]")
            return True
        if cmd == "/undo":
            restored = self.memory.undo_last_write()
            if restored:
                console.print(f"[green]Restored previous version of[/green] {restored}")
            else:
                console.print("[yellow]Nothing to undo.[/yellow]")
            return True
        if cmd == "/memory":
            console.print(f"Session: {self.memory.id}")
            console.print(f"Messages so far: {len(self.memory.messages)}")
            console.print(f"File changes tracked: {len(self.memory.file_history)}")
            return True
        if cmd == "/trust":
            self.trust_mode = not self.trust_mode
            console.print(f"Trust mode: {'[green]ON[/green]' if self.trust_mode else '[red]OFF[/red]'}")
            return True
        if cmd == "/model" or cmd.startswith("/model "):
            self._handle_model_command(cmd)
            return True
        console.print(f"[yellow]Unknown command:[/yellow] {cmd}")
        return True

    def _handle_model_command(self, cmd: str):
        """Interactive model picker — lists installed Ollama models and switches to the chosen one."""
        import asyncio

        from xyz_local.tools import _human_size

        models = asyncio.run(self.client.list_models())
        if not models:
            console.print("[yellow]No models found (is Ollama running?).[/yellow]")
            return

        names = [m.get("name", "") for m in models if m.get("name")]

        # Direct switch: "/model <name>"
        parts = cmd.split(maxsplit=1)
        if len(parts) == 2:
            requested = parts[1].strip()
            match = requested if requested in names else next(
                (n for n in names if n.startswith(requested)), None
            )
            if match:
                self._switch_model(match)
            else:
                console.print(f"[yellow]No model matching '{requested}'. Type /model to list.[/yellow]")
            return

        # Interactive list
        console.print("\n[bold]Available models:[/bold]")
        for i, m in enumerate(models, 1):
            name = m.get("name", "?")
            size = _human_size(m.get("size", 0)) if m.get("size") else ""
            marker = "[green]●[/green]" if name == self.client.model else " "
            console.print(f"  {marker} [cyan]{i:>2}[/cyan]. {name}  [dim]{size}[/dim]")

        try:
            choice = Prompt.ask("\nSelect a model number (or Enter to cancel)", default="").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if not choice:
            return
        try:
            idx = int(choice)
            if 1 <= idx <= len(models):
                self._switch_model(models[idx - 1]["name"])
            else:
                console.print("[yellow]Number out of range.[/yellow]")
        except ValueError:
            console.print("[yellow]Please enter a valid number.[/yellow]")

    def _switch_model(self, name: str):
        if name == self.client.model:
            console.print(f"[dim]Already using {name}[/dim]")
            return
        old = self.client.model
        self.client.model = name
        self.memory.model = name
        console.print(f"[green]Switched model:[/green] {old} → [bold]{name}[/bold]")