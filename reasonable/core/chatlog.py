"""Durable per-project chat history for the AI agents.

User conversations must survive editor restarts: the agent keeps its context
across sessions, and the chat panel restores previous messages on open.

Storage is deliberately boring and human-readable:

    <project>/.reasonable/chat.json   [{"ts": ..., "role": "user", "text": ...}, ...]
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from .paths import atomic_write_json, now_iso, read_json

FILE_NAME = "chat.json"
_LOCK = threading.RLock()
_MAX_MESSAGES = 400
_MAX_TEXT = 8000


def chat_path(project_dir: Path) -> Path:
    return Path(project_dir) / ".reasonable" / FILE_NAME


def _normalise_role(role: Any) -> str:
    value = str(role or "").strip().lower()
    return value if value in {"user", "assistant"} else "user"


def load_chat(project_dir: Path) -> list[dict[str, str]]:
    """All saved messages, oldest first."""
    data = read_json(chat_path(project_dir), None)
    if not isinstance(data, list):
        return []
    result: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        result.append({"ts": str(item.get("ts") or ""), "role": _normalise_role(item.get("role")), "text": text})
    return result


def append_message(project_dir: Path, role: str, text: str) -> dict[str, str]:
    """Append one message and persist immediately."""
    message = {"ts": now_iso(), "role": _normalise_role(role), "text": str(text or "").strip()[:_MAX_TEXT]}
    if not message["text"]:
        return message
    with _LOCK:
        path = chat_path(project_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        history = load_chat(project_dir)
        history.append(message)
        if len(history) > _MAX_MESSAGES:
            history = history[-_MAX_MESSAGES:]
        atomic_write_json(path, history)
    return message


def recent_messages(project_dir: Path, limit: int = 24) -> list[dict[str, str]]:
    """The last ``limit`` messages, oldest first (for agent context)."""
    history = load_chat(project_dir)
    return history[-max(0, limit):] if limit > 0 else []


def clear_chat(project_dir: Path) -> None:
    with _LOCK:
        path = chat_path(project_dir)
        try:
            path.unlink()
        except OSError:
            pass
