<div align="center">

# xyz-local — Fully Local AI Coding Agent

**v2.0.0** — *An open source AI coding agent for the terminal, powered by Ollama*

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat&logo=python&logoColor=white)](https://python.org)
[![Ollama](https://img.shields.io/badge/Ollama-Local-4B8BBE?style=flat&logo=ollama&logoColor=white)](https://ollama.com)
[![Rich](https://img.shields.io/badge/Rich-13.7+-FC6D26?style=flat&logo=python&logoColor=white)](https://rich.readthedocs.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://img.shields.io/badge/CI-GitHub%20Actions-blue)](.github/workflows/ci.yml)

**Created by [Kumar Satyam](mailto:kumarsatyam3135@gmail.com)**

A fully local, privacy-first AI coding agent that runs 100% on your machine using Ollama. No cloud APIs, no data leaves your laptop.

</div>

---

## Features

- **Pure local inference** via Ollama — no cloud, no API keys, no costs
- **Full agentic tool loop** with 10 tools: `list_directory`, `read_file`, `write_file`, `edit_file`, `grep_files`, `find_files`, `create_directory`, `execute_shell`, `get_cwd`
- **Real-time streaming** — tokens appear as they're generated
- **Smart safety system** — three-tier permission model (AUTO / ASK / DENY) with custom patterns, malicious pip detection, and dangerous path protection
- **In-session model switching** — type `/model` to pick any installed Ollama model without restarting
- **Session memory** with undo for file writes, auto-naming, and resume support
- **Rich terminal UI** with streaming, panels, tool call previews, and colored output
- **Graceful model support** — detects when a model doesn't support tool calling and shows helpful fallback parsing
- **Non-interactive mode** — `xyz-local run <prompt>` for scripting and automation
- **Docker support** — ready-to-use container image

## Installation

### Prerequisites

1. Python 3.10+
2. [Ollama](https://ollama.com) installed and running (`ollama serve`)
3. At least one coding-capable model pulled:

```bash
ollama pull qwen2.5-coder:latest     # 4.7 GB — recommended
# or
ollama pull gemma3:4b                # 3.3 GB — fastest
```

### Install

```bash
git clone https://github.com/krsatyam36/xyz-local.git
cd xyz-local
python3 -m venv .venv
source .venv/bin/activate          # On Windows: .venv\Scripts\activate
pip install -e .
```

## Quick Start

```bash
# Activate your virtual environment
source .venv/bin/activate

# Start an interactive session
xyz-local chat

# Or specify a model and trust mode
xyz-local chat -m qwen2.5-coder:latest --trust

# Single-prompt mode (non-interactive)
xyz-local run "List all Python files in the project"
```

### Example Session

```
> Create a file called hello.py that prints "Hello from xyz-local"

⚙ write_file hello.py
  ✓ File written successfully.

> Run it

⚙ execute_shell `python3 hello.py`
  exit=0
  Hello from xyz-local
```

## CLI Commands

| Command | Description | Key Options |
|---------|-------------|-------------|
| `chat` | Start an interactive coding session | `--model/-m`, `--session/-s`, `--trust`, `--verbose/-v`, `--dir/-d` |
| `run` | Process a single prompt and exit | `--model/-m`, `--trust` |
| `models` | List available Ollama models | — |
| `sessions` | List or clean up previous sessions | `--cleanup/-c`, `--force/-f` |
| `doctor` | Diagnose setup and connectivity | — |
| `--version` | Show version | — |

## Slash Commands (inside chat)

| Command | Description |
|---------|-------------|
| `/help` | Show all available commands |
| `/model` | Switch model mid-session (lists all installed models) |
| `/undo` | Revert the last file change |
| `/memory` | Show session state info |
| `/stats` | Show session statistics (duration, messages, tool calls) |
| `/clear` | Reset conversation context |
| `/retry` | Re-process the last input |
| `/save` | Force-save session to disk |
| `/temp` | View or set temperature (`/temp 0.3`) |
| `/inspect` | Show raw JSON of last tool result |
| `/trust` | Toggle trust mode |
| `/exit` | End the session |

## The Tools

| Tool | Description |
|------|-------------|
| `list_directory` | List files/dirs with icons, sizes, permissions, and modified times |
| `read_file` | Read file with offset/limit support, binary detection |
| `write_file` | Create or overwrite files (with automatic `.bak` backup on overwrite) |
| `edit_file` | Precise string replacement (preferred for modifications, creates `.bak`) |
| `grep_files` | Regex content search with `.gitignore` awareness, context lines |
| `find_files` | Find files by glob pattern (e.g. `*.py`, `test_*.py`) |
| `create_directory` | Create directories (`mkdir -p` equivalent) |
| `execute_shell` | Run shell commands with safety tiers |
| `get_cwd` | Return current working directory |

## Safety System

Commands are classified into three tiers:

| Tier | Behavior | Examples |
|------|----------|---------|
| **AUTO** | Runs without prompt | `ls`, `pwd`, `git status`, `pytest`, `pip list`, `ollama list`, `cat`, `grep` |
| **ASK** | Requires confirmation | `pip install`, `git commit`, `rm`, `mv`, `docker run`, `curl` |
| **DENY** | Hard blocked | `rm -rf /`, `sudo rm`, fork bombs, `curl \| bash`, known malicious pip packages |

Custom approval patterns can be added via `~/.xyz-local/config.json`:

```json
{
    "auto_approve_prefixes": ["docker ps", "my-custom-tool"],
    "deny_patterns": ["dangerous-command"]
}
```

## Configuration

Settings are loaded from `~/.xyz-local/config.json`, then environment variables, then defaults:

```json
{
    "default_model": "qwen2.5-coder:latest",
    "temperature": 0.1,
    "ollama_timeout": 300,
    "num_ctx": 8192,
    "ollama_base_url": "http://localhost:11434"
}
```

Environment variable overrides:

| Variable | Overrides |
|----------|-----------|
| `XYZ_LOCAL_DEFAULT_MODEL` | Default model name |
| `OLLAMA_BASE_URL` | Ollama server URL |
| `XYZ_LOCAL_MAX_TURNS` | Max agent reasoning steps |
| `XYZ_LOCAL_TEMPERATURE` | Model temperature |
| `XYZ_LOCAL_TIMEOUT` | Ollama API timeout (seconds) |

## Architecture

```
User (terminal)
   |
   v
Agent.run_interactive()   [agent.py]
   |
   v
Agent.process_turn()      [agent.py]
   |  - System prompt with tool list
   |  - Streaming async chat loop
   |  - Multi-turn tool execution
   v
OllamaClient.chat()       [ollama_client.py]
   |  - Streaming API via httpx
   |  - Tool call parsing + fallback
   v
Tool execution            [tools.py + safety.py]
   |  - Permission classification
   |  - Dangerous path checks
   v
SessionMemory             [memory.py]
   |  - Message persistence
   |  - File undo history
   v
Response back to user
```

### Core Modules

- **agent.py** — The heart. System prompt, streaming loop, tool orchestration, slash commands, caching, context warnings.
- **ollama_client.py** — Async HTTP client with retry logic, streaming, tool call fallback parsing, health checks.
- **tools.py** — All 10 tool implementations with `.gitignore`-aware search, human-readable sizes, binary detection, backup creation.
- **safety.py** — Three-tier permission system with custom patterns, malicious package detection, dangerous path protection.
- **memory.py** — Session persistence as JSON, file undo stack, auto-naming.
- **config.py** — Configuration loading from JSON file + env vars + defaults.
- **main.py** — Typer CLI with 5 commands and global `--version`.

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest -v

# Lint and type check
ruff check src/
mypy src/

# Install pre-commit hooks
pre-commit install
```

## Docker

```bash
docker build -t xyz-local .
docker run --rm -it --network host xyz-local chat
```

## Recommended Models

| Model | Size | Speed | Best For |
|-------|------|-------|----------|
| `qwen2.5-coder:latest` | 4.7 GB | Good | Daily driver (recommended) |
| `gemma3:4b` | 3.3 GB | Fastest | Quick tasks |
| `qwen2.5:7b` | 4.7 GB | Good | General purpose |
| `qwen2.5-coder:14b` | 9.0 GB | Slow | Complex tasks |

## Troubleshooting

**"This model doesn't support tool calling"**
→ The model doesn't support structured tool calls. Switch to a Qwen2.5-Coder model with `/model` or `--model`.

**Ollama is unreachable**
→ Run `ollama serve` in another terminal. Check `xyz-local doctor` for diagnostics.

**Context getting too large**
→ Use `/clear` to reset the conversation when responses slow down.

## License

MIT License — see [LICENSE](LICENSE).

---

*Privacy-first, fully local AI coding for your terminal.*
