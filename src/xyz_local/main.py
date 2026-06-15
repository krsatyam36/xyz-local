"""CLI entry point for xyz-local (local Ollama AI coding agent)."""

from __future__ import annotations

import sys
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from xyz_local import __version__
from xyz_local.config import get_config
from xyz_local.agent import Agent
from xyz_local.ollama_client import OllamaClient

app = typer.Typer(
    name="xyz-local",
    help="xyz-local — Fully local AI coding agent powered by Ollama (local-only edition of XYZ)",
    add_completion=False,
    no_args_is_help=True,
)
console = Console()


@app.callback()
def _main_callback(
    version: bool = typer.Option(False, "--version", help="Show version and exit"),
):
    if version:
        console.print(f"xyz-local v{__version__}")
        raise typer.Exit()


@app.command()
def chat(
    model: Optional[str] = typer.Option(
        None, "--model", "-m", help="Model to use (e.g. qwen2.5-coder:latest or gemma3:4b)"
    ),
    session: Optional[str] = typer.Option(
        None, "--session", "-s", help="Resume a previous session ID"
    ),
    trust: bool = typer.Option(
        False, "--trust", help="Start in trust mode (fewer confirmations — use carefully)"
    ),
):
    """Start an interactive coding session with a local Ollama model."""
    cfg = get_config()
    chosen_model = model or cfg.default_model

    console.print(Panel.fit(
        f"[bold cyan]xyz-local[/bold cyan] — Local AI Coding Agent (Ollama)\n"
        f"Model: [green]{chosen_model}[/green]\n"
        f"Trust mode: {'[yellow]ON[/yellow]' if trust else '[dim]OFF[/dim]'}",
        title="Starting Session",
        border_style="cyan"
    ))

    try:
        client = OllamaClient(base_url=cfg.ollama_base_url, model=chosen_model, timeout=cfg.ollama_timeout)
        agent = Agent(
            client=client,
            config=cfg,
            trust_mode=trust,
            resume_session=session,
        )
        agent.run_interactive()
    except KeyboardInterrupt:
        console.print("\n[yellow]Session ended by user.[/yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"[red]Fatal error:[/red] {e}")
        raise


@app.command()
def models():
    """List available local Ollama models (useful ones for coding highlighted)."""
    cfg = get_config()
    client = OllamaClient(base_url=cfg.ollama_base_url)

    try:
        models = client.list_models()
    except Exception as e:
        console.print(f"[red]Could not reach Ollama:[/red] {e}")
        raise typer.Exit(1)

    table = Table(title="Local Ollama Models", show_lines=False)
    table.add_column("Name", style="cyan")
    table.add_column("Size", justify="right")
    table.add_column("Recommended", style="green")

    coding_hints = ("coder", "deepseek", "codestral", "qwen", "command-r", "phi", "gemma")

    for m in models:
        name = m.get("name", "")
        size = m.get("size", "unknown")
        is_coding = any(h in name.lower() for h in coding_hints)
        rec = "✓ coding/agent" if is_coding else ""
        table.add_row(name, str(size), rec)

    console.print(table)
    console.print("\n[dim]Tip: Use --model <name> when starting chat[/dim]")
    console.print("[dim]Best for xyz-local: qwen2.5-coder:latest (4.7GB) or gemma3:4b (3.3GB)[/dim]")


@app.command()
def sessions(
    cleanup: bool = typer.Option(False, "--cleanup", "-c", help="Remove all session files"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation for cleanup"),
):
    """List or clean up previous sessions."""
    cfg = get_config()
    sessions_dir = cfg.sessions_dir
    if not sessions_dir.exists():
        console.print("[dim]No sessions yet.[/dim]")
        return

    if cleanup:
        session_files = list(sessions_dir.glob("*.json"))
        if not session_files:
            console.print("[dim]No sessions to clean.[/dim]")
            return
        if not force:
            from rich.prompt import Confirm
            if not Confirm.ask(f"Remove {len(session_files)} session file(s)?"):
                return
        for f in session_files:
            f.unlink()
        console.print(f"[green]Removed {len(session_files)} session file(s).[/green]")
        return

    table = Table(title="Previous Sessions")
    table.add_column("ID", style="cyan")
    table.add_column("Started")
    table.add_column("Model")

    for f in sorted(sessions_dir.glob("*.json")):
        import json
        meta = json.loads(f.read_text(encoding="utf-8"))
        table.add_row(
            f.stem,
            meta.get("created", "Unknown")[:19],
            meta.get("model", ""),
        )

    console.print(table)


@app.command()
def doctor():
    """Diagnose your setup (Ollama connectivity, recommended models, etc.)."""
    cfg = get_config()
    console.print("[bold]xyz-local doctor[/bold]\n")

    async def _run():
        client = OllamaClient(base_url=cfg.ollama_base_url)
        try:
            models = await client.list_models()
            await client.close()
            return models
        except Exception as e:
            await client.close()
            raise e

    import asyncio
    try:
        models = asyncio.run(_run())
        console.print(f"[green]✓[/green] Ollama reachable at {cfg.ollama_base_url}")
        console.print(f"  Found {len(models)} models.")
    except Exception as e:
        console.print(f"[red]✗[/red] Cannot reach Ollama: {e}")
        console.print("  Make sure `ollama serve` is running.")
        return

    good_models = [m for m in models if any(x in m.get("name", "").lower() for x in ["coder", "gemma3"])]
    if good_models:
        console.print(f"[green]✓[/green] Found {len(good_models)} coding-oriented model(s).")
    else:
        console.print("[yellow]![/yellow] No obvious coding models found. Consider `ollama pull qwen2.5-coder:latest`")

    console.print("\n[dim]Recommended for your hardware:[/dim]")
    console.print("  xyz-local chat -m qwen2.5-coder:latest --trust   (4.7 GB)")
    console.print("  xyz-local chat -m gemma3:4b --trust              (3.3 GB - fastest)")