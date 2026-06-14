"""Configuration for xyz-local (local Ollama edition)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    # Recommended fast daily driver (4.7 GB) - best balance on 4GB GPU machines
    default_model: str = "qwen2.5-coder:latest"
    # Heavier but smarter model (use when you want maximum quality)
    big_model: str = "qwen2.5-coder:14b-instruct"
    ollama_base_url: str = "http://localhost:11434"
    sessions_dir: Path = Path.home() / ".xyz-local" / "sessions"
    max_turns: int = 15   # slightly higher for local models that need more steps

    def __post_init__(self):
        self.sessions_dir.mkdir(parents=True, exist_ok=True)


def get_config() -> Config:
    """Load config, allowing simple env overrides."""
    cfg = Config()

    if model := os.getenv("XYZ_LOCAL_DEFAULT_MODEL"):
        cfg.default_model = model
    if base := os.getenv("OLLAMA_BASE_URL"):
        cfg.ollama_base_url = base.rstrip("/")
    if turns := os.getenv("XYZ_LOCAL_MAX_TURNS"):
        cfg.max_turns = int(turns)

    return cfg