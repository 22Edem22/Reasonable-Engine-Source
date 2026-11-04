"""Durable per-project chat history with multiple AI conversations.

Every project keeps a small, human-readable JSON file::

    <project>/.reasonable/chat.json
    {
      "version": 2,
      "active": "chat_ab12...",
      "chats": [
        {"id": "chat_ab12...", "title": "Add a menu", "created": "...",
         "updated": "...", "messages": [{"ts": "...", "role": "user",
         "text": "...", "hidden": false}]}
      ]
    }

Older projects stored a plain list in the same file; they are migrated in
memory on read and rewritten in the new format on the next write. Hidden
messages (for example the internal "Improve project" prompt) stay in the
conversation context but are never rendered in the chat panel.
"""

from __future__ import annotations

import threading
import uuid
from pathlib import Path
from typing import Any

from .paths import atomic_write_json, now_iso, read_json

FILE_NAME = "chat.json"
FORMAT_VERSION = 2
_LOCK = threading.RLock()
_MAX_MESSAGES = 400
_MAX_TEXT = 8000
_TITLE_LIMIT = 64
_DEFAULT_CHAT_ID = "default"


def chat_path(project_dir: Path) -> Path:
    return Path(project_dir) / ".reasonable" / FILE_NAME


def _new_chat_id() -> str:
    return f"chat_{uuid.uuid4().hex[:12]}"


def _clean_title(text: Any) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= _TITLE_LIMIT:
        return value
    return value[: _TITLE_LIMIT - 1].rstrip() + "…"


# Roles the chat panel can render. ``system`` marks status notices (the run
# finished, the snapshot failed) and ``error`` keeps a failed answer visible
# after the project is reopened instead of turning it into a fake user message.
ROLES = frozenset({"user", "assistant", "system", "error"})


def _normalise_role(role: Any) -> str:
    value = str(role or "").strip().lower()
    return value if value in ROLES else "user"


def _normalise_message(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    text = str(item.get("text") or "").strip()[:_MAX_TEXT]
    if not text:
        return None
    return {
        "ts": str(item.get("ts") or ""),
        "role": _normalise_role(item.get("role")),
        "text": text,
        "hidden": bool(item.get("hidden")),
    }


def _title_from_messages(messages: list[dict[str, Any]]) -> str:
    for message in messages:
        if message.get("role") == "user" and not message.get("hidden"):
            return _clean_title(message.get("text"))
    return ""


def _new_chat(
    *,
    chat_id: str | None = None,
    title: str = "",
    messages: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    now = now_iso()
    return {
        "id": chat_id or _new_chat_id(),
        "title": _clean_title(title) or _title_from_messages(messages or []),
        "created": now,
        "updated": now,
        "messages": list(messages or []),
    }


def _normalise_chat(item: Any, index: int) -> dict[str, Any]:
    data = item if isinstance(item, dict) else {}
    messages: list[dict[str, Any]] = []
    for raw in data.get("messages") or []:
        message = _normalise_message(raw)
        if message is not None:
            messages.append(message)
    chat_id = str(data.get("id") or f"chat_{index + 1}")
    return {
        "id": chat_id,
        "title": _clean_title(data.get("title")) or _title_from_messages(messages),
        "created": str(data.get("created") or now_iso()),
        "updated": str(data.get("updated") or now_iso()),
        "messages": messages[-_MAX_MESSAGES:],
    }


def _empty_store() -> dict[str, Any]:
    chat = _new_chat(chat_id=_DEFAULT_CHAT_ID)
    return {"version": FORMAT_VERSION, "active": chat["id"], "chats": [chat]}


def _read_store(project_dir: Path) -> dict[str, Any]:
    raw = read_json(chat_path(project_dir), None)
    if isinstance(raw, dict) and isinstance(raw.get("chats"), list):
        chats = [
            _normalise_chat(item, index)
            for index, item in enumerate(raw.get("chats") or [])
            if isinstance(item, dict)
        ]
        if not chats:
            return _empty_store()
        active = str(raw.get("active") or "")
        if active not in {chat["id"] for chat in chats}:
            active = chats[0]["id"]
        return {"version": FORMAT_VERSION, "active": active, "chats": chats}
    if isinstance(raw, list):
        # Legacy single-chat format. Migrate in memory; the next write stores
        # the new structure with the same file name.
        messages: list[dict[str, Any]] = []
        for item in raw:
            message = _normalise_message(item)
            if message is not None:
                messages.append(message)
        chat = _new_chat(chat_id=_DEFAULT_CHAT_ID, messages=messages)
        return {"version": FORMAT_VERSION, "active": chat["id"], "chats": [chat]}
    return _empty_store()


def _write_store(project_dir: Path, store: dict[str, Any]) -> None:
    path = chat_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, store)


def _find_chat(store: dict[str, Any], chat_id: str | None) -> dict[str, Any] | None:
    chats = store.get("chats") or []
    wanted = chat_id or store.get("active")
    if chat_id:
        for chat in chats:
            if chat.get("id") == wanted:
                return chat
        return None
    for chat in chats:
        if chat.get("id") == wanted:
            return chat
    return chats[0] if chats else None


def _summary(chat: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(chat.get("id") or ""),
        "title": str(chat.get("title") or ""),
        "created": str(chat.get("created") or ""),
        "updated": str(chat.get("updated") or ""),
        "message_count": len(chat.get("messages") or []),
    }


def active_chat_id(project_dir: Path) -> str:
    with _LOCK:
        return str(_read_store(project_dir).get("active") or _DEFAULT_CHAT_ID)


def list_chats(project_dir: Path) -> list[dict[str, Any]]:
    """Chat summaries, oldest first. At least one chat always exists."""
    with _LOCK:
        store = _read_store(project_dir)
        return [_summary(chat) for chat in store.get("chats") or []]


def create_chat(project_dir: Path, title: str = "", *, activate: bool = True) -> dict[str, Any]:
    """Create an empty conversation and optionally make it active."""
    with _LOCK:
        store = _read_store(project_dir)
        chat = _new_chat(title=title)
        store.setdefault("chats", []).append(chat)
        if activate:
            store["active"] = chat["id"]
        _write_store(project_dir, store)
        return _summary(chat)


def set_active_chat(project_dir: Path, chat_id: str) -> dict[str, Any]:
    with _LOCK:
        store = _read_store(project_dir)
        chat = _find_chat(store, chat_id)
        if chat is None:
            chat = (store.get("chats") or [None])[0]
        if chat is not None:
            store["active"] = chat["id"]
            _write_store(project_dir, store)
            return _summary(chat)
        return {}


def rename_chat(project_dir: Path, chat_id: str, title: str) -> None:
    with _LOCK:
        store = _read_store(project_dir)
        chat = _find_chat(store, chat_id)
        if chat is None:
            return
        chat["title"] = _clean_title(title)
        chat["updated"] = now_iso()
        _write_store(project_dir, store)


def delete_chat(project_dir: Path, chat_id: str) -> dict[str, Any]:
    """Remove a conversation. The last remaining chat is only cleared."""
    with _LOCK:
        store = _read_store(project_dir)
        chats = store.get("chats") or []
        index = next(
            (position for position, chat in enumerate(chats) if chat.get("id") == chat_id),
            -1,
        )
        if index < 0:
            return _summary(chats[0]) if chats else {}
        if len(chats) == 1:
            chats[0]["messages"] = []
            chats[0]["title"] = ""
            chats[0]["updated"] = now_iso()
            store["active"] = chats[0]["id"]
            _write_store(project_dir, store)
            return _summary(chats[0])
        removed = chats.pop(index)
        if store.get("active") == removed.get("id"):
            replacement = chats[min(index, len(chats) - 1)]
            store["active"] = replacement["id"]
        _write_store(project_dir, store)
        active = _find_chat(store, str(store.get("active") or ""))
        return _summary(active) if active is not None else {}


def load_chat(project_dir: Path, chat_id: str | None = None) -> list[dict[str, Any]]:
    """All saved messages of a conversation, oldest first."""
    with _LOCK:
        store = _read_store(project_dir)
        chat = _find_chat(store, chat_id)
        if chat is None:
            return []
        return [dict(message) for message in chat.get("messages") or []]


def append_message(
    project_dir: Path,
    role: str,
    text: str,
    *,
    chat_id: str | None = None,
    hidden: bool = False,
) -> dict[str, Any]:
    """Append one message to a conversation and persist immediately."""
    message = {
        "ts": now_iso(),
        "role": _normalise_role(role),
        "text": str(text or "").strip()[:_MAX_TEXT],
        "hidden": bool(hidden),
    }
    if not message["text"]:
        return message
    with _LOCK:
        store = _read_store(project_dir)
        chat = _find_chat(store, chat_id)
        if chat is None:
            chat = _new_chat()
            store.setdefault("chats", []).append(chat)
            store["active"] = chat["id"]
        messages = chat.setdefault("messages", [])
        # The UI and the agent may both want to record the same turn (for
        # example the final answer emitted twice by different layers). Keep
        # the history readable by dropping an identical consecutive repeat.
        if messages:
            last = messages[-1]
            if (
                str(last.get("role")) == message["role"]
                and str(last.get("text")) == message["text"]
                and bool(last.get("hidden")) == message["hidden"]
            ):
                return last
        messages.append(message)
        if len(chat["messages"]) > _MAX_MESSAGES:
            chat["messages"] = chat["messages"][-_MAX_MESSAGES:]
        chat["updated"] = message["ts"]
        if message["role"] == "user" and not hidden and not chat.get("title"):
            chat["title"] = _clean_title(message["text"])
        _write_store(project_dir, store)
    return message


def recent_messages(
    project_dir: Path,
    limit: int = 24,
    chat_id: str | None = None,
) -> list[dict[str, Any]]:
    """The last ``limit`` messages, oldest first (for agent context)."""
    history = load_chat(project_dir, chat_id)
    return history[-max(0, limit):] if limit > 0 else []


def clear_chat(project_dir: Path, chat_id: str | None = None) -> None:
    """Clear one conversation (the active one by default)."""
    with _LOCK:
        store = _read_store(project_dir)
        chat = _find_chat(store, chat_id)
        if chat is None:
            return
        chat["messages"] = []
        chat["title"] = ""
        chat["updated"] = now_iso()
        _write_store(project_dir, store)
