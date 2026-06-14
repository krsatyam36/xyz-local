<div align="center">

# XYZ — Open Source AI Coding Agent!

**v0.4.0** — *An open source AI coding agent for the terminal, inspired by OpenCode and Claude Code*

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat&logo=python&logoColor=white)](https://python.org)
[![NVIDIA NIM](https://img.shields.io/badge/NVIDIA_NIM-API-76B900?style=flat&logo=nvidia&logoColor=white)](https://build.nvidia.com)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Rich](https://img.shields.io/badge/Rich-13.7+-FC6D26?style=flat&logo=python&logoColor=white)](https://rich.readthedocs.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://img.shields.io/badge/CI-GitHub%20Actions-blue)](.github/workflows/ci.yml)

**Created by [Kumar Satyam](mailto:kumarsatyam3135@gmail.com)**

A powerful terminal-based AI coding agent with tool-calling, multi-agent architecture, session memory, streaming responses, and a local FastAPI gateway proxying to NVIDIA's NIM API.

</div>

---

# xyz-local — Local Ollama Edition

**A fully local, privacy-first version of the XYZ AI coding agent that runs 100% on your machine using Ollama.**

This is the **xyz-local** project: the complete local-only implementation that removes all external API dependencies (no NVIDIA NIM, no cloud). It uses **Ollama** for inference, works great with small efficient models (7B and even 4B), and includes many improvements for reliability, safety, and usability on consumer hardware.

## Why xyz-local?

The original XYZ project is powerful but relies on remote model providers. This fork (xyz-local) was created so you can have the same agentic coding experience completely offline, on your laptop, with the models you already have via `ollama list`.

**Key advantages of this local edition:**
- Zero API keys or cloud costs
- Works with the models you already downloaded (especially the fast 4.7GB and 3.3GB ones)
- Strong built-in safety and confirmation system
- Special guards for greetings and meta-questions so the agent doesn't waste time exploring when you just say "hi" or "what can you do?"
- Excellent path handling and preprocessing so phrases like "read the xyz-local project" are understood correctly even when the agent is running inside the project itself
- Graceful degradation when a model doesn't support tool calling (shows a helpful error instead of 400)
- Designed and tested on real consumer hardware (4GB laptop GPUs)

## Features

- **Pure local inference** via Ollama (no remote gateway required in this edition)
- Full tool-calling agent loop with reliable parsing (supports both native Ollama tools and common fallback formats used by Qwen/Gemma)
- 8 high-quality tools: `list_directory`, `read_file`, `write_file`, `edit_file`, `grep_files`, `execute_shell`, `get_cwd`
- Smart safety & permission system (auto-approve safe commands, ask for destructive ones, hard-deny dangerous patterns)
- Session memory with undo for file writes
- Clean Rich terminal UI with streaming responses
- Special client-side guards:
  - Instant replies for greetings (`hello`, `hi`, `hey`...)
  - Direct answers for capability questions (`what can you do?`, `help`)
- Intelligent preprocessing so the agent understands "read the xyz-local project" means "explore the current directory (.)"
- Excellent support for the fastest useful models:
  - `qwen2.5-coder:latest` (4.7 GB) — recommended daily driver
  - `gemma3:4b` / `gemma3:latest` (3.3 GB) — fastest option
- Detailed logging of tool usage without polluting the chat with raw JSON
- Works great with `--trust` mode for power users

## Installation

### Prerequisites

1. Python 3.10+
2. [Ollama](https://ollama.com) installed and running (`ollama serve`)
3. At least one small coding-capable model pulled:

```bash
ollama pull qwen2.5-coder:latest     # 4.7 GB - recommended
# or
ollama pull gemma3:4b                # 3.3 GB - fastest
```

### Install xyz-local

```bash
git clone https://github.com/krsatyam36/xyz-local.git
cd xyz-local
python -m venv .venv
source .venv/bin/activate          # On Windows: .venv\Scripts\activate
pip install -e .
```

Or if you just want to use it without cloning (once published):

```bash
pip install xyz-local
```

## Quick Start

```bash
# Activate your venv
source .venv/bin/activate

# Start with the fast recommended model
xyz-local chat -m qwen2.5-coder:latest --trust

# Or the even faster tiny model
xyz-local chat -m gemma3:4b --trust
```

Inside the session just talk naturally:

```
> Hello

> What can you do?

> Create a new file called hello.py that prints "Hello from xyz-local"

> Read the current project and tell me what the main files are

> Add a simple FastAPI health endpoint to the existing backend
```

Use `/help` inside the session for slash commands (`/undo`, `/trust`, `/memory`, etc.).

## Recommended Models (as of 2026)

| Model                        | Size  | Speed on 4GB GPU | Tool Calling | Best For                          |
|-----------------------------|-------|------------------|--------------|-----------------------------------|
| `qwen2.5-coder:latest`      | 4.7GB | Good             | Excellent    | **Daily driver** (recommended)   |
| `gemma3:4b`                 | 3.3GB | Fastest          | Good         | Maximum speed, simpler tasks     |
| `qwen2.5:7b`                | 4.7GB | Good             | Very good    | General purpose                  |
| `qwen2.5-coder:14b-instruct`| 9.0GB | Slow             | Best         | When you need maximum intelligence |

**Tip:** Start with `qwen2.5-coder:latest`. It gives the best balance for the agent loop (tool following, code editing, not over-exploring).

## Architecture Overview

```
User (terminal)
   |
   v
run_interactive()  [main.py]
   |
   +--> Greeting / Meta guard?  --> direct reply (no LLM)
   |
   v
Agent.process_turn()
   |
   +--> Preprocessing (xyz-local project name → ".")
   |
   v
OllamaClient.chat()   (with tools or graceful fallback)
   |
   +--> Tool execution (safety.py + tools.py)
   |
   v
Memory + undo tracking
   |
   v
Clean response back to user
```

### Core Components

- **agent.py** — The heart. Contains the strict system prompt, greeting/meta guards, input preprocessing, tool execution loop, and max-turns protection.
- **ollama_client.py** — Streaming + tool-call parsing. Special handling for models that return 400 when tools are sent.
- **tools.py** — All 8 tools + `normalize_path()` (proper ~ expansion) + helpful error messages.
- **safety.py** — Tiered permission system (AUTO / ASK / DENY) + dangerous path protection.
- **memory.py** — Session persistence + file undo stack.
- **config.py** — Defaults (you can change default_model here).
- **main.py** — Typer CLI + Rich UI loop.

## The Tools

| Tool             | Description                                                                 | When the agent uses it                     |
|------------------|-----------------------------------------------------------------------------|--------------------------------------------|
| `list_directory` | List files/folders (use "." for current project root)                       | Exploration, "what's in this project?"     |
| `read_file`      | Read file contents (supports offset + limit for large files)                | Before editing, understanding code         |
| `write_file`     | Create or overwrite a file                                                  | New files, full rewrites (use sparingly)   |
| `edit_file`      | Precise string replacement (preferred for modifications)                    | Almost all code changes                    |
| `grep_files`     | Regex search across the project                                             | Finding definitions, usages                |
| `execute_shell`  | Run any shell command (with safety tiers)                                   | Running tests, git, python, etc.           |
| `get_cwd`        | Returns the agent's current working directory                               | When the agent needs to confirm location   |

All file tools use safe `~` expansion and resolve relative to the real current working directory.

## Safety & Trust Mode

- **AUTO** (no prompt): `ls`, `cat`, `grep`, `git status`, `pytest`, `mkdir`, `touch`, simple reads.
- **ASK**: `pip install`, `git commit`, most destructive ops, `rm`, `mv`, etc.
- **DENY** (hard blocked): `rm -rf /`, `sudo`, fork bombs, `curl | bash`, etc.

Use `--trust` (or `/trust` inside session) to auto-approve more commands (use with care).

The agent will never run a truly dangerous command without explicit user confirmation (unless trust mode is on).

## Session Features

- Every file write is tracked.
- Type `/undo` to revert the last file change the agent made.
- Sessions are saved in `~/.xyz-local/sessions/`.
- You can resume with `xyz-local chat --session <id>`.

## Configuration

Edit `src/xyz_local/config.py` (or set env vars):

```python
default_model = "qwen2.5-coder:latest"   # fast 7B coder
big_model     = "qwen2.5-coder:14b-instruct"
```

You can also pass `--model` on the command line.

## Development & Packaging

```bash
# Install in editable mode (already done in quick start)
pip install -e .

# Run tests (if you add some)
python -m pytest

# The CLI entry point is defined in pyproject.toml
xyz-local --help
```

## Differences from the original XYZ

- No NVIDIA NIM / remote gateway — pure Ollama.
- Added client-side guards for greetings and capability questions.
- Added aggressive input rewriting so "read the xyz-local project" works correctly when the agent lives inside the project.
- Added 400 tool-support detection with helpful suggestions.
- Much stronger emphasis on "do not explore on trivial tasks".
- Designed and battle-tested with the smallest useful models (4.7 GB and 3.3 GB).
- Focused on making the agent feel fast and predictable on real laptops.

## Troubleshooting

**"400 Bad Request" with gemma3:4b or other small models**
→ This model does not support the structured tool calling format xyz-local uses. Switch to a Qwen2.5-Coder model.

**Agent keeps listing the wrong directory or saying path does not exist**
→ The model sometimes forgets it is inside the project. The preprocessing + prompt now handle most cases. You can be explicit: "List the current directory using path='.' "

**Agent goes into long exploration loops on simple requests**
→ Use a more specific prompt or the 14B model. The 7B is fast but has weaker long-horizon discipline.

**Double messages on hello / what can you do**
→ This was fixed in the latest version. Make sure you did `pip install -e . --quiet` after pulling updates.

**Ollama is slow**
→ On 4 GB VRAM the 7B models still offload many layers to CPU. This is expected. gemma3:4b will feel the snappiest.

## Contributing

Contributions are welcome! Especially:

- Better small-model prompt engineering
- Additional safety rules
- More robust tool parsing fallbacks
- Nice TUI improvements (the Textual experiment is still early)

## License

MIT License — see [LICENSE](LICENSE).

## Author

**Kumar Satyam**  
kumarsatyam3135@gmail.com  
https://github.com/krsatyam36

---

*This is the local Ollama edition of the XYZ vision. The goal is a fast, private, reliable coding agent that lives entirely on your machine and actually does what you ask — without random exploration or cloud round-trips.*