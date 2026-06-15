"""Safety and permission system for xyz-local."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class PermissionTier(str, Enum):
    AUTO = "auto"
    ASK = "ask"
    DENY = "deny"


@dataclass
class PermissionResult:
    tier: PermissionTier
    reason: str
    command: str


AUTO_APPROVE_PREFIXES = (
    "ls", "pwd", "cd ", "cat ", "head ", "tail ", "less ", "wc ",
    "grep ", "rg ", "find ", "which ", "echo ", "date ", "whoami ",
    "git status", "git log", "git diff", "git branch", "git show ",
    "git stash", "git fetch", "git pull", "git remote",
    "python -m pytest", "pytest ", "python -c ", "python -m pyright",
    "ruff check", "ruff format --check", "mypy ", "black --check",
    "npm run test", "npm test", "npm run ",
    "mkdir ", "touch ", "cp ", "sort ", "uniq ", "comm ", "diff ",
    "pip list", "pip freeze", "pip show",
    "ollama list", "ollama ps", "ollama show",
    "nvidia-smi", "free ", "df ", "du ", "uptime", "uname ",
)

ASK_PREFIXES = (
    "pip install", "uv pip install", "npm install", "yarn add",
    "git add", "git commit", "git push", "git checkout -b",
    "docker build", "docker run", "docker compose up",
    "rm ", "mv ",
    "chmod ", "chown ",
    "curl ", "wget ", "apt ", "brew ",
)

DENY_PATTERNS = [
    r"rm\s+-rf\s+/", r"rm\s+-rf\s+~",
    r":\(\)\{.*\}", r"sudo\s+rm", r"shutdown", r"reboot", r"mkfs", r"dd\s+if=",
    r"curl\s+.*\|\s*(bash|sh)", r"wget\s+.*\|\s*(bash|sh)",
    r"eval\s+\$\(", r"exec\s+.*<",
]

KNOWN_MALICIOUS_PIP = {
    "pytort", "pyshater", "pycrypt", "cryptominer",
    "requests",  # typo of requests
    "pwdpy", "keylogger",
}


def is_suspicious_pip_install(command: str) -> Optional[str]:
    if not command.startswith("pip install"):
        return None
    parts = command.split()
    for part in parts[2:]:
        part = part.strip("\"'")
        pkg = part.split("==")[0].split(">")[0].split("<")[0].split("~")[0].split("!")[0]
        pkg_lower = pkg.lower().replace("-", "").replace("_", "")
        for mal in KNOWN_MALICIOUS_PIP:
            if mal in pkg_lower or pkg_lower in mal:
                return f"Package '{part}' matches known malicious pattern '{mal}'"
    return None


def classify_command(command: str, trust_mode: bool = False) -> PermissionResult:
    cmd = command.strip().lower()

    for pattern in DENY_PATTERNS:
        if re.search(pattern, cmd, re.IGNORECASE):
            return PermissionResult(
                tier=PermissionTier.DENY,
                reason="Command matches dangerous pattern",
                command=command,
            )

    pip_warning = is_suspicious_pip_install(cmd)
    if pip_warning:
        return PermissionResult(
            tier=PermissionTier.DENY,
            reason=pip_warning,
            command=command,
        )

    if trust_mode:
        return PermissionResult(
            tier=PermissionTier.AUTO,
            reason="Trust mode enabled",
            command=command,
        )

    for prefix in AUTO_APPROVE_PREFIXES:
        if cmd.startswith(prefix) or f"&& {prefix.strip()}" in cmd or f"; {prefix.strip()}" in cmd:
            return PermissionResult(
                tier=PermissionTier.AUTO,
                reason=f"Safe operation ({prefix.strip()})",
                command=command,
            )

    for prefix in ASK_PREFIXES:
        if cmd.startswith(prefix) or f"&& {prefix.strip()}" in cmd:
            return PermissionResult(
                tier=PermissionTier.ASK,
                reason=f"Modifying command: {prefix.strip()}",
                command=command,
            )

    return PermissionResult(
        tier=PermissionTier.ASK,
        reason="Unknown / potentially impactful command",
        command=command,
    )


def is_dangerous_write_path(path: str) -> bool:
    dangerous = {"/", "/etc", "/usr", "/boot", "/sys", "/proc", "~/.ssh", "~/.gnupg"}
    p = path.strip()
    for d in dangerous:
        if p == d or p.startswith(d + "/"):
            return True
    return False
