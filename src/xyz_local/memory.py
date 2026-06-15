"""Lightweight session memory + undo for file operations."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


@dataclass
class FileChange:
    path: str
    old_content: str
    timestamp: str


@dataclass
class SessionMemory:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    name: str = ""
    messages: list[dict[str, Any]] = field(default_factory=list)
    file_history: list[FileChange] = field(default_factory=list)
    model: str = ""

    def auto_name(self):
        if self.name or not self.messages:
            return
        first = self.messages[0].get("content", "")
        max_len = 50
        self.name = first.strip()[:max_len].replace("\n", " ")

    def add_message(self, role: str, content: str):
        self.messages.append({"role": role, "content": content})

    def track_file_write(self, path: str, old_content: str):
        self.file_history.append(FileChange(
            path=path,
            old_content=old_content,
            timestamp=datetime.utcnow().isoformat()
        ))

    def undo_last_write(self) -> Optional[str]:
        if not self.file_history:
            return None
        change = self.file_history.pop()
        try:
            Path(change.path).write_text(change.old_content, encoding="utf-8")
            return change.path
        except Exception:
            self.file_history.append(change)
            return None

    def get_messages(self) -> list[dict[str, Any]]:
        return self.messages

    def save(self, sessions_dir: Path):
        sessions_dir.mkdir(parents=True, exist_ok=True)
        path = sessions_dir / f"{self.id}.json"
        self.auto_name()
        data = asdict(self)
        data["file_history"] = [asdict(fc) for fc in self.file_history]
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, session_id: str, sessions_dir: Path) -> Optional["SessionMemory"]:
        path = sessions_dir / f"{session_id}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        mem = cls(
            id=data["id"],
            created=data["created"],
            messages=data.get("messages", []),
            model=data.get("model", ""),
        )
        for fc in data.get("file_history", []):
            mem.file_history.append(FileChange(**fc))
        return mem
