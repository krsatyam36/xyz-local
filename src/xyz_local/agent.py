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


SYSTEM_PROMPT = """You are xyz-local, a careful and highly competent local AI coding assistant running entirely on the user's machine via Ollama.

**HIGHEST PRIORITY RULE - GREETINGS AND SMALL TALK:**
If the user says something like "Hello", "Hi", "Hey", "Hello there", or any simple greeting or conversational opener, respond with a short, natural, friendly reply (e.g. "Hello! How can I help you today?"). 
DO NOT call get_cwd, list_directory, read_file, or ANY tool for greetings. Just answer directly.

**CURRENT PROJECT CONTEXT (VERY IMPORTANT):**
You are currently running *inside* the xyz-local project itself.
- The current working directory shown below **is** the root of the xyz-local project.
- When the user says "Read the xyz-local project", "explore the xyz-local project", "summarize the project", or similar, they mean **explore the current directory**.
- Always use path "." (or the current working directory) for the root of xyz-local. Never try to list a subdirectory literally called "xyz-local" unless the user is clearly asking for a nested folder.

**TOOL USE RULE:**
Only call tools when the user's request clearly requires action.
- For a simple standalone request like "write a code to add 2 numbers", "write a hello world", or any self-contained small script:
  - Immediately use write_file with a good filename (e.g. add_two_numbers.py) in the current working directory.
  - Put complete, working code with comments and example usage.
  - After the write_file succeeds, give a short confirmation like "Done, created add_two_numbers.py with the code." and stop. Do not list_directory, do not read any files.
- Only explore (list_directory, read_file, get_cwd) when the request is about the existing project, debugging existing code, or the user explicitly asks to look at files. Use "." for the project root.

When you must use a tool:
- Output the function call in the exact JSON format with no extra text, no ```json blocks, no explanations before or after it in that response.

**AFTER RECEIVING TOOL RESULTS:**
Analyze the result and either:
- Call the next needed tool (but avoid repeating the same exploration tools), or
- Give a short, direct final answer to the user.
Do not keep calling list_directory + read_file(README.md) in loops.

**OTHER RULES:**
- Be concise and action-oriented.
- Never narrate your tool use in text.
- For code tasks, put real complete code in write_file calls.

Available tools:
{tool_list}

Current working directory: {cwd}
"""


class Agent:
    def __init__(
        self,
        client: OllamaClient,
        config: Config,
        trust_mode: bool = False,
        resume_session: Optional[str] = None,
    ):
        self.client = client
        self.config = config
        self.trust_mode = trust_mode
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
        tool_list = "\n".join(
            f"- {t['function']['name']}: {t['function']['description']}"
            for t in TOOL_DEFINITIONS
        )
        cwd = str(Path.cwd())
        return SYSTEM_PROMPT.format(tool_list=tool_list, cwd=cwd)

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

    async def process_turn(self, user_input: str) -> str:
        """Process one user message and return final assistant text."""
        # Greeting guard
        greeting_phrases = {"hello", "hi", "hey", "hello there", "hi there", "hey there", 
                            "good morning", "good afternoon", "good evening"}
        cleaned_input = user_input.strip().lower().rstrip("!?., ")
        if cleaned_input in greeting_phrases or (len(cleaned_input) < 30 and any(g in cleaned_input for g in greeting_phrases)):
            greeting_reply = "Hello! How can I help you with your code or project today?"
            console.print(greeting_reply)
            self.memory.add_message("user", user_input)
            self.memory.add_message("assistant", greeting_reply)
            self.memory.save(self.config.sessions_dir)
            return greeting_reply

        # Meta / capability guard
        meta_phrases = ["what can you do", "what do you do", "your capabilities", "how do you work", "what are you", "help", "commands", "features"]
        if any(p in cleaned_input for p in meta_phrases) or cleaned_input in {"what can you do?", "what can you do"}:
            meta_reply = (
                "I am a local AI coding agent. I can:\n"
                "- Read, edit, and create files in your project\n"
                "- Run shell commands and tests (with safety confirmations)\n"
                "- Explore code with grep and directory listing\n"
                "- Help you build features, fix bugs, refactor, write tests, etc.\n\n"
                "Just describe what you want to build or change. I work best with clear, specific requests."
            )
            console.print(meta_reply)
            self.memory.add_message("user", user_input)
            self.memory.add_message("assistant", meta_reply)
            self.memory.save(self.config.sessions_dir)
            return meta_reply

        # Preprocess "xyz-local project" references
        original_input = user_input
        lower_input = user_input.lower()
        if ("xyz-local" in lower_input and any(kw in lower_input for kw in ["project", "folder", "directory", "read", "explore", "summarize"])) or lower_input.startswith("read the "):
            user_input = user_input.replace("xyz-local", "current").replace("./xyz-local", ".").replace("the xyz-local project", "the current project (we are inside it)")
            if "list" not in lower_input and "read_file" not in lower_input and "read the" in lower_input:
                user_input = user_input.replace("read the ", "explore/summarize the content of ").strip() + ". Use path='.' for the project root."

        if not self.memory.messages:
            self.memory.add_message("system", self._get_system_prompt())

        self.memory.add_message("user", user_input)

        messages = self.memory.get_messages()
        turn = 0

        while turn < self.config.max_turns:
            turn += 1

            console.print("[dim]Thinking...[/dim]", end="")

            full_response = ""
            tool_calls = []

            async for event in self.client.chat(
                messages=messages,
                tools=TOOL_DEFINITIONS,
                temperature=self.config.temperature,
            ):
                if event["type"] == "token":
                    full_response += event.get("data", "")
                elif event["type"] == "tool_call":
                    tool_calls.append(event["data"])
                elif event["type"] == "done":
                    if event.get("tool_calls"):
                        tool_calls = event["tool_calls"]
                    break
                elif event["type"] == "error":
                    console.print("\r" + " " * 20 + "\r", end="")
                    err = event['data']
                    if err == "MODEL_DOES_NOT_SUPPORT_TOOLS":
                        console.print("[yellow]This model does not support tool calling well.[/yellow]")
                        console.print("xyz-local works best with Qwen2.5-Coder models.")
                        console.print("Try:  xyz-local chat -m qwen2.5-coder:latest --trust")
                        return "Model does not support tools. Please switch to a coder model (e.g. qwen2.5-coder:latest)."
                    console.print(f"[red]Error from model:[/red] {err}")
                    return f"Error: {err}"

            console.print("\r" + " " * 20 + "\r", end="")

            cleaned_response = _sanitize_assistant_text(full_response)

            if not tool_calls and full_response:
                from xyz_local.ollama_client import _parse_tool_call_fallback
                tool_calls = _parse_tool_call_fallback(full_response)

            if not tool_calls:
                if cleaned_response.strip():
                    console.print(cleaned_response)
                self.memory.add_message("assistant", cleaned_response or full_response)
                self.memory.save(self.config.sessions_dir)
                return cleaned_response or full_response

            cleaned_for_history = cleaned_response or full_response
            messages.append({"role": "assistant", "content": cleaned_for_history})

            for tc in tool_calls:
                name = tc.get("function", {}).get("name") or tc.get("name", "")
                args = tc.get("function", {}).get("arguments") or tc.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}

                if not name:
                    continue

                console.print(f"[cyan]→[/cyan] Using tool: [bold]{name}[/bold]")

                result = self._execute_tool(name, args)

                if name in ("edit_file", "write_file") and result.get("success"):
                    path = args.get("path")
                    if path and Path(path).exists():
                        pass

                tool_result_msg = {
                    "role": "tool",
                    "content": json.dumps(result, ensure_ascii=False),
                }
                messages.append(tool_result_msg)

                if "error" in result:
                    console.print(f"  [red]Tool error:[/red] {result['error']}")
                elif name == "execute_shell":
                    exit_code = result.get("exit_code")
                    stdout = (result.get("stdout") or "")[:300]
                    console.print(f"  exit={exit_code}  stdout preview:\n{stdout}")

            messages = self.memory.get_messages() + messages[-len(tool_calls)*2:]

        self.memory.add_message("assistant", "(max turns reached)")
        self.memory.save(self.config.sessions_dir)
        return "I reached the maximum number of reasoning steps. Please ask me to continue or simplify the request."

    def _remove_last_assistant_turn(self):
        """Remove the last assistant turn and associated tool calls from memory."""
        if len(self.memory.messages) < 2:
            return
        while self.memory.messages and self.memory.messages[-1].get("role") in ("assistant", "tool"):
            self.memory.messages.pop()

    def run_interactive(self):
        """Main interactive loop."""
        cwd = Path.cwd()
        already_printed_prefixes = (
            "Hello! How can I help you with your code",
            "I am a local AI coding agent. I can:",
        )
        console.print(f"[dim]Working directory: {cwd}[/dim]")
        console.print("[dim]Type your request. Use /help for commands, Ctrl+C to exit.[/dim]\n")

        while True:
            try:
                user_input = Prompt.ask("[bold cyan]>[/bold cyan]")
            except (EOFError, KeyboardInterrupt):
                break

            if not user_input.strip():
                continue

            if user_input.strip().startswith("/"):
                if user_input.strip() == "/retry" and self._last_user_input:
                    self._remove_last_assistant_turn()
                    import asyncio
                    response = asyncio.run(self.process_turn(self._last_user_input))
                    if response and response.strip() and not any(response.startswith(p) for p in already_printed_prefixes):
                        if not response.startswith("→ Using tool"):
                            console.print(response)
                    console.print()
                    continue
                if self._handle_slash_command(user_input.strip()):
                    continue
                else:
                    break

            self._last_user_input = user_input
            import asyncio
            response = asyncio.run(self.process_turn(user_input))

            if response and response.strip() and not any(response.startswith(p) for p in already_printed_prefixes):
                if not response.startswith("→ Using tool"):
                    console.print(response)

            console.print()

    def _handle_slash_command(self, cmd: str) -> bool:
        if cmd in {"/exit", "/quit"}:
            return False
        if cmd == "/help":
            console.print(
                "Available: /help, /undo, /memory, /clear, /stats, /retry, /model, /trust, /exit\n"
                "Most work happens by just chatting normally."
            )
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
        console.print(f"[yellow]Unknown command:[/yellow] {cmd}")
        return True