# Changelog

## v1.0.0 (2026-06-15) — First Stable Release

This is the first stable release of **xyz-local**, the fully local, privacy-first AI coding agent powered by Ollama. This release marks the transition from beta to stable, with a mature feature set, robust safety systems, and excellent support for small local models.

### ✨ Features

- **Pure local inference** via Ollama — no cloud APIs, no data leaves your machine
- **Full tool-calling agent loop** with 8 high-quality tools:
  - `list_directory`, `read_file`, `write_file`, `edit_file`, `grep_files`, `execute_shell`, `get_cwd`
- **Smart safety & permission system** with three tiers:
  - `AUTO` — safe commands run without prompt (ls, git status, pytest, etc.)
  - `ASK` — destructive commands require confirmation (rm, pip install, git commit, etc.)
  - `DENY` — dangerous patterns hard-blocked (rm -rf /, sudo, fork bombs, etc.)
- **Client-side intelligent guards**:
  - Instant replies for greetings (hello, hi, hey, etc.) — no wasted LLM calls
  - Direct answers for capability questions ("what can you do?", "help")
  - Project name preprocessing ("read the xyz-local project" → explore current dir)
- **Graceful model support**:
  - Detects when a model doesn't support tool calling and shows helpful error
  - Fallback parsing for models that return tool calls in `<tool_call>` or ```json blocks
- **Session memory** with undo support for file writes
- **Clean Rich terminal UI** with streaming responses, panels, and colored output

### 🚀 CLI Commands

- `xyz-local chat` — Start an interactive coding session
- `xyz-local models` — List available local Ollama models
- `xyz-local sessions` — List previous sessions
- `xyz-local doctor` — Diagnose setup and connectivity

### 🔧 Slash Commands (inside chat)

- `/help` — Show available commands
- `/undo` — Revert the last file change
- `/memory` — Show session state info
- `/trust` — Toggle trust mode on/off
- `/exit` — End the session

### 🎯 Recommended Models

| Model | Size | Best For |
|-------|------|----------|
| `qwen2.5-coder:latest` | 4.7 GB | Daily driver (recommended) |
| `gemma3:4b` | 3.3 GB | Maximum speed |
| `qwen2.5:7b` | 4.7 GB | General purpose |
| `qwen2.5-coder:14b-instruct` | 9.0 GB | Maximum intelligence |

### 🛡️ Safety

- Tiered permission system with automatic classification
- Dangerous path protection for file writes (`/etc`, `/usr`, `~/.ssh`, etc.)
- Trust mode for power users who want fewer interruptions
- All tool calls logged without polluting chat history with raw JSON

### 📦 Installation

```bash
pip install xyz-local
# or from source:
git clone https://github.com/krsatyam36/xyz-local.git
cd xyz-local
pip install -e .
```

### 🔮 What's Coming (Post-1.0)

- Textual TUI for a richer terminal experience
- Additional small-model prompt engineering improvements
- More robust tool parsing fallbacks
- Plugin system for custom tools
- Configurable system prompt templates
- Session export and sharing
