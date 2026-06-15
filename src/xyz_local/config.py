"""Configuration for xyz-local (local Ollama edition)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Config:
    # Recommended fast daily driver (4.7 GB) - best balance on 4GB GPU machines
    default_model: str = "qwen2.5-coder:latest"
    # Heavier but smarter model (use when you want maximum quality)
    big_model: str = "qwen2.5-coder:14b-instruct"
    ollama_base_url: str = "http://localhost:11434"
    sessions_dir: Path = Path.home() / ".xyz-local" / "sessions"
    max_turns: int = 15   # slightly higher for local models that need more steps
    temperature: float = 0.1  # low temperature for deterministic tool calling
    ollama_timeout: int = 300  # seconds for Ollama API calls

    def __post_init__(self):
        self.sessions_dir.mkdir(parents=True, exist_ok=True)


def _load_config_file() -> dict[str, Any]:
    config_path = Path.home() / ".xyz-local" / "config.json"
    if config_path.exists():
        try:
            return json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def get_config() -> Config:
    """Load config from file, then env overrides."""
    cfg = Config()
    file_cfg = _load_config_file()

    cfg.default_model = file_cfg.get("default_model", cfg.default_model)
    cfg.big_model = file_cfg.get("big_model", cfg.big_model)
    cfg.max_turns = int(file_cfg.get("max_turns", cfg.max_turns))
    cfg.temperature = float(file_cfg.get("temperature", cfg.temperature))
    cfg.ollama_timeout = int(file_cfg.get("ollama_timeout", cfg.ollama_timeout))
    if "ollama_base_url" in file_cfg:
        cfg.ollama_base_url = file_cfg["ollama_base_url"].rstrip("/")

    if model := os.getenv("XYZ_LOCAL_DEFAULT_MODEL"):
        cfg.default_model = model
    if base := os.getenv("OLLAMA_BASE_URL"):
        cfg.ollama_base_url = base.rstrip("/")
    if turns := os.getenv("XYZ_LOCAL_MAX_TURNS"):
        cfg.max_turns = int(turns)
    if temp := os.getenv("XYZ_LOCAL_TEMPERATURE"):
        try:
            cfg.temperature = float(temp)
        except ValueError:
            pass
    if timeout := os.getenv("XYZ_LOCAL_TIMEOUT"):
        try:
            cfg.ollama_timeout = int(timeout)
        except ValueError:
            pass

    return cfg