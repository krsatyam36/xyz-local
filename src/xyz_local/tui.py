"""Full-screen Textual TUI for xyz-local — opencode-style chat interface.

Layout:
    ┌───────────────────────────────┐
    │ conversation (scrollable)      │
    │ ...                            │
    ├───────────────────────────────┤
    │ > prompt input                 │
    ├───────────────────────────────┤
    │ Build · model · trust   tokens │  status bar
    └───────────────────────────────┘

``/model`` opens a floating, searchable model picker (``ModelSelectScreen``).
Shell commands that need approval raise a ``ConfirmScreen`` modal.
"""

from __future__ import annotations

from typing import Any, Optional

from rich.markdown import Markdown as RichMarkdown
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from xyz_local.agent import Agent
from xyz_local.config import Config
from xyz_local.ollama_client import OllamaClient
from xyz_local.ui import AgentUI, TOOL_VERBS, tool_preview


# ─────────────────────────────────────────────────────────── Modals ──


class ConfirmScreen(ModalScreen[bool]):
    """Yes/no approval for a shell command."""

    BINDINGS = [("escape", "deny", "Deny"), ("y", "allow", "Allow"), ("n", "deny", "Deny")]

    def __init__(self, command: str, reason: str, description: str):
        super().__init__()
        self.command = command
        self.reason = reason
        self.description = description

    def compose(self) -> ComposeResult:
        with Container(id="confirm-dialog"):
            yield Static("Run this command?", id="confirm-title")
            yield Static(Text(self.command, style="bold white"), id="confirm-cmd")
            yield Static(f"Reason: {self.reason}", classes="confirm-meta")
            if self.description:
                yield Static(f"Agent: {self.description}", classes="confirm-meta")
            yield Static("[bold]y[/bold] allow   ·   [bold]n[/bold] / esc deny", id="confirm-hint")

    def action_allow(self) -> None:
        self.dismiss(True)

    def action_deny(self) -> None:
        self.dismiss(False)


class ModelSelectScreen(ModalScreen[Optional[str]]):
    """Floating searchable model picker (opencode-style)."""

    BINDINGS = [
        ("escape", "cancel", "Close"),
        ("down", "cursor_down", "Down"),
        ("up", "cursor_up", "Up"),
    ]

    def __init__(self, models: list[dict[str, Any]], current: str):
        super().__init__()
        self.models = models
        self.current = current

    def compose(self) -> ComposeResult:
        with Container(id="model-dialog"):
            yield Static("Select model", id="model-title")
            yield Input(placeholder="Search…", id="model-search")
            yield OptionList(id="model-list")

    def on_mount(self) -> None:
        self._populate("")
        self.query_one("#model-search", Input).focus()

    def _populate(self, query: str) -> None:
        olist = self.query_one("#model-list", OptionList)
        olist.clear_options()
        q = query.lower().strip()
        for m in self.models:
            name = m.get("name", "")
            if q and q not in name.lower():
                continue
            size = _human(m.get("size", 0))
            marker = "● " if name == self.current else "  "
            label = Text.assemble(
                (marker, "green" if name == self.current else "dim"),
                (name, "bold"),
                ("  " + size, "dim"),
            )
            olist.add_option(Option(label, id=name))
        if olist.option_count:
            olist.highlighted = 0

    def on_input_changed(self, event: Input.Changed) -> None:
        self._populate(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        olist = self.query_one("#model-list", OptionList)
        if olist.option_count and olist.highlighted is not None:
            opt = olist.get_option_at_index(olist.highlighted)
            self.dismiss(opt.id)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def action_cursor_down(self) -> None:
        self.query_one("#model-list", OptionList).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one("#model-list", OptionList).action_cursor_up()

    def action_cancel(self) -> None:
        self.dismiss(None)


def _human(n: int) -> str:
    if not n:
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}PB"


# ──────────────────────────────────────────────────────── UI sink ──


class TextualUI(AgentUI):
    """Agent output sink that mounts/updates widgets in the Textual app."""

    def __init__(self, app: "XYZApp"):
        self.app = app
        self._stream_widget: Optional[Static] = None
        self._stream_buffer = ""

    async def thinking(self, ms: int) -> None:
        await self.app.add_line(f"+ Thought: {ms}ms", "thought")

    async def stream_delta(self, text: str) -> None:
        if self._stream_widget is None:
            self._stream_widget = Static("", classes="assistant")
            await self.app.conversation.mount(self._stream_widget)
            self._stream_buffer = ""
        self._stream_buffer += text
        self._stream_widget.update(self._stream_buffer)
        self.app.scroll_down()

    async def stream_end(self) -> None:
        if self._stream_widget is not None and self._stream_buffer.strip():
            self._stream_widget.update(RichMarkdown(self._stream_buffer))
        self._stream_widget = None
        self._stream_buffer = ""
        self.app.scroll_down()

    async def tool_call(self, name: str, args: dict[str, Any]) -> None:
        verb = TOOL_VERBS.get(name, name)
        line = Text.assemble(("→ ", "cyan"), (verb + " ", "bold"), (tool_preview(name, args), "dim"))
        await self.app.add_widget(Static(line, classes="tool-line"))

    async def tool_result(self, name: str, result: dict[str, Any]) -> None:
        if "error" in result:
            await self.app.add_line(f"  ✗ {str(result['error'])[:200]}", "tool-error")
        elif name == "execute_shell":
            output = (result.get("stdout") or result.get("stderr") or "").strip()
            if output:
                lines = output.split("\n")
                shown = "\n".join(lines[:15])
                if len(lines) > 15:
                    shown += f"\n  … {len(lines) - 15} more lines"
                await self.app.add_widget(Static(Text(shown, style="grey70"), classes="tool-output"))

    async def assistant_message(self, text: str) -> None:
        await self.app.add_widget(Static(RichMarkdown(text), classes="assistant"))

    async def notice(self, text: str, style: str = "dim") -> None:
        await self.app.add_line(text, "notice")

    async def confirm(self, command: str, reason: str, description: str) -> bool:
        return bool(await self.app.push_screen_wait(ConfirmScreen(command, reason, description)))


# ────────────────────────────────────────────────────────── App ──


class XYZApp(App):
    CSS = """
    Screen { background: $background; }

    #conversation { height: 1fr; padding: 0 2; }

    .user-msg {
        border-left: thick $accent;
        background: $boost;
        padding: 0 2;
        margin: 1 0 0 0;
        color: $text;
    }
    .assistant { padding: 0 1; margin: 0 0 1 0; }
    .tool-line { color: $text-muted; padding: 0 1; }
    .tool-output { padding: 0 3; color: $text-muted; }
    .tool-error { color: $error; padding: 0 1; }
    .thought { color: $text-muted; text-style: italic; padding: 1 1 0 1; }
    .notice { color: $warning; padding: 0 1; }

    #prompt {
        height: 3;
        border: round $primary;
        margin: 0 1;
    }
    #status {
        height: 1;
        background: $panel;
        color: $text-muted;
        padding: 0 2;
    }
    #status .accent { color: $accent; }

    #model-dialog {
        align: center middle;
        width: 64; height: auto; max-height: 80%;
        background: $surface;
        border: round $primary;
        padding: 1 2;
    }
    #model-title { text-style: bold; padding-bottom: 1; }
    #model-search { margin-bottom: 1; }
    #model-list { height: auto; max-height: 16; }

    #confirm-dialog {
        align: center middle;
        width: 70; height: auto;
        background: $surface;
        border: round $warning;
        padding: 1 2;
    }
    #confirm-title { text-style: bold; color: $warning; padding-bottom: 1; }
    #confirm-cmd { padding-bottom: 1; }
    .confirm-meta { color: $text-muted; }
    #confirm-hint { padding-top: 1; color: $text-muted; }
    """

    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+l", "clear", "Clear"),
        ("ctrl+p", "open_model", "Model"),
    ]

    def __init__(self, client: OllamaClient, config: Config, trust_mode: bool, resume_session: Optional[str]):
        super().__init__()
        self.client = client
        self.config = config
        self.agent = Agent(
            client=client, config=config, trust_mode=trust_mode,
            resume_session=resume_session, ui=TextualUI(self),
        )
        self._busy = False

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="conversation")
        yield Input(placeholder="Type a message, or /help …", id="prompt")
        yield Static(id="status")

    def on_mount(self) -> None:
        self.title = "xyz-local"
        self.query_one("#prompt", Input).focus()
        self._update_status()
        self.call_later(self._greet)

    async def _greet(self) -> None:
        await self.add_line(f"xyz-local · {self.client.model} · {self._dir()}", "thought")
        await self.add_line("Type your request. /help for commands, /model to switch models.", "thought")

    # ---- widget helpers ----

    @property
    def conversation(self) -> VerticalScroll:
        return self.query_one("#conversation", VerticalScroll)

    async def add_widget(self, widget) -> None:
        await self.conversation.mount(widget)
        self.scroll_down()

    async def add_line(self, text: str, css_class: str) -> None:
        await self.add_widget(Static(text, classes=css_class))

    def scroll_down(self) -> None:
        self.conversation.scroll_end(animate=False)

    def _dir(self) -> str:
        from pathlib import Path
        return str(Path.cwd())

    def _update_status(self) -> None:
        msgs = self.agent.memory.messages
        chars = sum(len(str(m.get("content", ""))) for m in msgs)
        tokens = chars // 4
        ctx = self.config.num_ctx or 32768
        pct = min(100, int(tokens / ctx * 100)) if ctx else 0
        trust = "trust" if self.agent.trust_mode else "ask"
        tok_str = f"{tokens/1000:.1f}K" if tokens >= 1000 else str(tokens)
        status = Text.assemble(
            ("● ", "green" if not self._busy else "yellow"),
            (self.client.model, "bold"),
            (f"  ·  {trust}", "dim"),
            (f"   {tok_str} ({pct}%)", "dim"),
            ("    ^p model · ^l clear · ^c exit", "dim"),
        )
        self.query_one("#status", Static).update(status)

    # ---- input handling ----

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "prompt":
            return
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        if text.startswith("/"):
            await self._handle_slash(text)
            return
        if self._busy:
            await self.add_line("Still working on the previous request…", "notice")
            return
        await self.add_widget(Static(Text(text), classes="user-msg"))
        self._run_turn(text)

    @work(exclusive=True, group="agent")
    async def _run_turn(self, text: str) -> None:
        self._busy = True
        self._update_status()
        try:
            await self.agent.process_turn(text)
        except Exception as e:  # noqa: BLE001
            await self.add_line(f"Error: {e}", "tool-error")
        finally:
            self._busy = False
            self._update_status()

    async def _handle_slash(self, cmd: str) -> None:
        parts = cmd.split(maxsplit=1)
        name = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if name in ("/exit", "/quit"):
            self.exit()
        elif name == "/model":
            self._model_picker(arg)
        elif name == "/clear":
            self.action_clear()
        elif name == "/trust":
            self.agent.trust_mode = not self.agent.trust_mode
            await self.add_line(f"Trust mode: {'ON' if self.agent.trust_mode else 'OFF'}", "notice")
            self._update_status()
        elif name == "/save":
            self.agent.memory.save(self.config.sessions_dir)
            await self.add_line(f"Saved session {self.agent.memory.id}", "notice")
        elif name == "/undo":
            restored = self.agent.memory.undo_last_write()
            await self.add_line(f"Restored {restored}" if restored else "Nothing to undo.", "notice")
        elif name == "/stats":
            m = self.agent.memory
            tools = sum(1 for x in m.messages if x.get("role") == "tool")
            await self.add_line(
                f"id={m.id} · model={m.model} · messages={len(m.messages)} · tools={tools} · writes={len(m.file_history)}",
                "notice",
            )
        elif name == "/help":
            await self.add_widget(Static(RichMarkdown(_HELP), classes="assistant"))
        else:
            await self.add_line(f"Unknown command: {name}", "notice")

    # ---- actions ----

    def action_clear(self) -> None:
        self.agent.memory.messages.clear()
        self.conversation.remove_children()
        self._update_status()

    def action_open_model(self) -> None:
        self._model_picker("")

    @work(exclusive=True, group="model")
    async def _model_picker(self, prefilter: str = "") -> None:
        models = await self.client.list_models()
        if not models:
            await self.add_line("No models found (is Ollama running?)", "notice")
            return
        # Direct switch: "/model <name>"
        if prefilter:
            names = [m.get("name", "") for m in models]
            match = prefilter if prefilter in names else next((n for n in names if n.startswith(prefilter)), None)
            if match:
                self._switch(match)
                return
        chosen = await self.push_screen_wait(ModelSelectScreen(models, self.client.model))
        if chosen:
            self._switch(chosen)

    def _switch(self, name: str) -> None:
        if name == self.client.model:
            return
        self.client.model = name
        self.agent.memory.model = name
        self.run_worker(self.add_line(f"Model → {name}", "notice"))
        self._update_status()


_HELP = """\
**Commands**

- `/model [name]` — open the model picker (or switch directly)
- `/clear` — clear the conversation  (`ctrl+l`)
- `/trust` — toggle auto-approval of shell commands
- `/undo` — revert the last file write
- `/save` — save the session
- `/stats` — session statistics
- `/exit` — quit  (`ctrl+c`)

Just type normally to chat. The agent can read, write, and edit files, run shell
commands, and search the codebase.
"""


def run_tui(client: OllamaClient, config: Config, trust_mode: bool = False, resume_session: Optional[str] = None) -> None:
    XYZApp(client, config, trust_mode, resume_session).run()
