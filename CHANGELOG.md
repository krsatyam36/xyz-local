# Changelog

## v2.0.0 (2026-06-17) — Agentic Overhaul & Model Picker

This is the **v2.0.0** major release of **xyz-local**, the fully local AI coding agent. After 50+ UX improvement branches merged over the past week, this release delivers a fundamentally reworked agent loop, critical bug fixes, new tools, mid-session model switching, and a much more reliable experience on small local models.

### ✨ New Features

- **In-session model switching** — Type `/model` at any time to see a numbered list of all installed Ollama models (with sizes, current marked with ●), then pick by number or switch directly by name/prefix (`/model qwen2.5-coder:7b`). Works without restarting the session.
- **Two new agent tools:**
  - `create_directory` — `mkdir -p` equivalent for creating directory structures
  - `find_files` — Glob-based file search (`*.py`, `test_*.py`, `**/*.tsx`)
- **Non-interactive run mode** — `xyz-local run <prompt>` for scripting and CI pipelines; processes a single prompt and exits
- **Ollama connection retry** — Exponential backoff (1s → 2s → 4s) on transient failures, with configurable `max_retries` and helpful user-facing messages
- **Ollama num_ctx support** — Configurable context window size (`num_ctx`) via `~/.xyz-local/config.json`

### 🐛 Critical Bug Fixes

- **Event-loop reuse crash** — `httpx.AsyncClient` was created once in `__init__` but `asyncio.run()` spawns a new event loop every turn. The second `/model` or any multi-turn conversation would crash with "Event loop is closed". Fixed by recreating the client per loop as a lazy property.
- **`models` CLI command broken** — Called async `list_models()` without `await`, throwing a coroutine-was-never-awaited warning and returning garbage. Fixed by wrapping in `asyncio.run()`.
- **Entry point dead** — `pyproject.toml` entry point pointed to `cli` (didn't exist) instead of `main:app`. `xyz-local` command was completely broken after install. Fixed in `pyproject.toml`.
- **`requests` falsely blocked** — The legitimate `pip install requests` was blocked because `requests` was in the malicious typo-squat set. Removed it from the deny list and added real typo variants (`requesrs`, `reqests`, `python-requeests`).
- **`rm -rf` over-blocking** — `rm -rf /tmp/test` was denied because the regex matched any `/`-prefixed path. Tightened to only deny root-level `/`, `/home`, `/etc`, `/usr`, `/var`, `/bin`, `/sbin`, `/boot`, `/dev`, `/opt`, `/proc`, `/sys`.
- **Message duplication in tool history** — `messages = self.memory.get_messages() + messages[-len(tool_calls)*2:]` corrupted tool context by duplicating assistant/tool message pairs, making the model see stale tool results. Removed the duplication.
- **Stale response cache** — Identical user messages returned cached (stale) responses without re-executing tools. Removed entirely.
- **Aggressive greeting/meta guards** — The "hello"/"what can you do?" shortcut guards short-circuited the model even when the user wanted actual work done. Removed.

### 🚀 CLI & Slash Commands

New and improved commands:

| Command | Type | Description |
|---------|------|-------------|
| `/model` | Slash | Switch model mid-session with interactive picker |
| `/stats` | Slash | Show session statistics (duration, message count, tool calls) |
| `/clear` | Slash | Reset conversation context (start fresh) |
| `/retry` | Slash | Re-process the last user input |
| `/save` | Slash | Force-save the session to disk immediately |
| `/temp` | Slash | View or set temperature (`/temp 0.3` for precise control) |
| `/inspect` | Slash | Show raw JSON of the last tool result |
| `run` | CLI | Non-interactive single-prompt mode |
| `sessions --cleanup` | CLI | Clean up old session files |

### 🔧 Tool Improvements

- **All file operations** now automatically create `.bak` backups before overwriting
- **`list_directory`** now shows human-readable sizes, file permissions, and last-modified timestamps with colored icons
- **`read_file`** has automatic binary file detection (doesn't try to read images/PDFs as text)
- **`grep_files`** respects `.gitignore` and supports context lines
- **`execute_shell`** improved classification with broader AUTO patterns for safe inspection commands
- **`find_files`** (new) — fast glob-based file discovery, respects `.gitignore`

### 🧹 System Prompt Rewrite

The agent's system prompt was completely rewritten to encourage:
1. **Explore before editing** — Read files first, understand the codebase, then make targeted changes
2. **Prefer `edit_file` over `write_file`** — Precise string replacement is safer than full rewrites
3. **Show, don't just do** — Explain what you changed and why
4. **Use the right tool** — Choose the best tool for each task instead of reaching for shell commands

### ⚙️ Configuration

New `~/.xyz-local/config.json` fields:

```json
{
    "temperature": 0.1,
    "num_ctx": 8192,
    "ollama_timeout": 300,
    "max_retries": 3,
    "auto_approve_prefixes": ["docker ps", "my-custom-tool"],
    "deny_patterns": ["dangerous-command"]
}
```

Environment variable overrides added: `XYZ_LOCAL_TEMPERATURE`, `XYZ_LOCAL_TIMEOUT`, `XYZ_LOCAL_MAX_TURNS`.

### 📚 Documentation

- Complete README rewrite with 260+ lines covering all features, CLI commands, slash commands, all 10 tools, safety tiers, configuration, architecture, Docker, and troubleshooting
- New CHANGELOG.md history

### 🧪 Testing

- All 11 tests passing (2 pre-existing safety.py failures fixed)
- End-to-end agentic run verified: "create hello.py, run it, tell me the output" — clean output, no raw JSON, no duplication

### 🔮 What's Coming (Post-2.0)

- `--backend` switch for LM Studio / llama.cpp (OpenAI-compatible API)
- Textual TUI for richer terminal experience
- Plugin system for custom tools and custom approval rules
- Session export/import for sharing
- Configurable system prompt templates per-project

---

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
