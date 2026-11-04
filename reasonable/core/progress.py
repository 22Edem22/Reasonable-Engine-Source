"""Shared development progress written by both the built-in and external agents.

The files are deliberately simple and human-readable:

    progress/state.json   current snapshot for the editor
    progress/events.jsonl append-only activity stream

External agents can call ``re progress`` / ``re event`` from the project folder.
The editor watches these files, so progress is visible regardless of which agent
is writing the code.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Iterable

from .i18n import tr
from .paths import atomic_write_json, now_iso, read_json


PROGRESS_DIR = "progress"
STATE_NAME = "state.json"
EVENTS_NAME = "events.jsonl"
_LOCK = threading.RLock()
_MAX_EVENT_FILE_BYTES = 2_000_000
_MAX_EVENTS_RETURNED = 180


def progress_dir(project_dir: Path) -> Path:
    return Path(project_dir) / PROGRESS_DIR


def state_path(project_dir: Path) -> Path:
    return progress_dir(project_dir) / STATE_NAME


def events_path(project_dir: Path) -> Path:
    return progress_dir(project_dir) / EVENTS_NAME


def empty_state(mode: str = "builtin") -> dict[str, Any]:
    stamp = now_iso()
    return {
        "version": 1,
        "mode": mode,
        "status": "idle",
        "percent": 0,
        "stage": tr("Waiting", "Ожидание"),
        "message": "",
        "tasks": [],
        "started_at": stamp,
        "updated_at": stamp,
        "last_event_at": stamp,
        "last_event": "",
    }


def ensure_state(project_dir: Path, mode: str | None = None) -> dict[str, Any]:
    project_dir = Path(project_dir)
    state = read_json(state_path(project_dir), None)
    if not isinstance(state, dict):
        state = empty_state(mode or "builtin")
        atomic_write_json(state_path(project_dir), state)
    elif mode and state.get("mode") != mode:
        state["mode"] = mode
        atomic_write_json(state_path(project_dir), state)
    progress_dir(project_dir).mkdir(parents=True, exist_ok=True)
    events_path(project_dir).touch(exist_ok=True)
    return state


def read_state(project_dir: Path) -> dict[str, Any]:
    state = read_json(state_path(project_dir), None)
    if not isinstance(state, dict):
        return empty_state()
    return state


def derived_percent(state: dict[str, Any]) -> float:
    """Best-effort development percent for display.

    Agents do not always call ``re progress``, so the editor derives the
    percent from the task plan when the stored value is still at zero. An
    explicitly reported percent always wins. This keeps the overview, the
    agent tab and external-agent view consistent.
    """
    try:
        stored = float(state.get("percent") or 0)
    except (TypeError, ValueError):
        stored = 0.0
    if stored > 0:
        return max(0.0, min(100.0, stored))
    tasks = state.get("tasks") or []
    total = 0
    done = 0
    for task in tasks:
        if not isinstance(task, dict):
            continue
        total += 1
        if task.get("status") == "done":
            done += 1
        elif task.get("status") == "skipped":
            done += 1  # resolved tasks count toward completion
    if total:
        return round(100.0 * done / total, 1)
    return 0.0


def _auto_percent(state: dict[str, Any]) -> float:
    """Refresh the stored percent from tasks unless the agent reported one."""
    derived = derived_percent(state)
    try:
        stored = float(state.get("percent") or 0)
    except (TypeError, ValueError):
        stored = 0.0
    if stored < derived:
        state["percent"] = derived
    return float(state.get("percent", derived))


def _write_state(project_dir: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = now_iso()
    atomic_write_json(state_path(project_dir), state)


def _truncate_events_if_needed(path: Path) -> None:
    try:
        if path.stat().st_size <= _MAX_EVENT_FILE_BYTES:
            return
    except OSError:
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-1200:]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass


def record_event(
    project_dir: Path,
    event_type: str,
    message: str = "",
    data: dict | None = None,
    *,
    update_activity: bool = True,
) -> dict[str, Any]:
    project_dir = Path(project_dir)
    with _LOCK:
        ensure_state(project_dir)
        stamp = now_iso()
        event = {
            "ts": stamp,
            "type": event_type,
            "message": message,
            "data": data or {},
        }
        path = events_path(project_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        _truncate_events_if_needed(path)
        try:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        except OSError:
            pass
        state = read_state(project_dir)
        state["last_event"] = message or event_type
        if update_activity:
            state["last_event_at"] = stamp
        _write_state(project_dir, state)
        return event


def heartbeat(project_dir: Path, message: str = "") -> None:
    with _LOCK:
        ensure_state(project_dir)
        state = read_state(project_dir)
        state["last_event_at"] = now_iso()
        state["status"] = "running"
        state["message"] = message or tr("The agent is working", "Агент работает")
        _write_state(project_dir, state)


def set_status(
    project_dir: Path,
    status: str,
    message: str = "",
    *,
    event_type: str = "status",
) -> dict[str, Any]:
    with _LOCK:
        ensure_state(project_dir)
        state = read_state(project_dir)
        state["status"] = status
        if message:
            state["message"] = message
        state["last_event_at"] = now_iso()
        _write_state(project_dir, state)
        record_event(project_dir, event_type, message or status)
        return state


def set_progress(
    project_dir: Path,
    percent: float | int,
    stage: str | None = None,
    message: str | None = None,
    status: str = "running",
) -> dict[str, Any]:
    percent = max(0.0, min(100.0, float(percent)))
    with _LOCK:
        ensure_state(project_dir)
        state = read_state(project_dir)
        state["percent"] = round(percent, 1)
        state["status"] = status
        if stage:
            state["stage"] = stage
        if message is not None:
            state["message"] = message
        state["last_event_at"] = now_iso()
        _write_state(project_dir, state)
        record_event(
            project_dir,
            "progress",
            message or (f"{state.get('stage', '')} — {percent:.0f}%"),
            {"percent": state["percent"], "stage": state.get("stage", ""), "status": status},
        )
        return state


def set_plan(project_dir: Path, tasks: Iterable[str | dict]) -> dict[str, Any]:
    normalized: list[dict[str, Any]] = []
    for index, task in enumerate(tasks, start=1):
        if isinstance(task, str):
            normalized.append({"id": f"t{index}", "title": task, "status": "pending"})
        elif isinstance(task, dict):
            normalized.append(
                {
                    "id": str(task.get("id") or f"t{index}"),
                    "title": str(task.get("title") or task.get("name") or tr("Task {index}", "Задача {index}", index=index)),
                    "status": str(task.get("status") or "pending"),
                }
            )
    with _LOCK:
        ensure_state(project_dir)
        state = read_state(project_dir)
        state["tasks"] = normalized
        state["last_event_at"] = now_iso()
        _auto_percent(state)
        _write_state(project_dir, state)
        record_event(project_dir, "plan", tr("Work plan updated", "План работ обновлён"), {"tasks": normalized})
        return state


def update_task(project_dir: Path, task_ref: str | int, status: str) -> dict[str, Any]:
    if status not in {"pending", "in_progress", "done", "skipped"}:
        status = "pending"
    with _LOCK:
        ensure_state(project_dir)
        state = read_state(project_dir)
        tasks = state.get("tasks", [])
        found = None
        ref = str(task_ref).strip().lower()
        for index, task in enumerate(tasks):
            title = str(task.get("title", "")).lower()
            if (
                str(task.get("id", "")).lower() == ref
                or str(index + 1) == ref
                or title == ref
                or (title and (ref in title or title in ref))
            ):
                found = task
                break
        if found is None:
            raise ValueError(tr("Task not found: {task}", "Задача не найдена: {task}", task=task_ref))
        found["status"] = status
        state["last_event_at"] = now_iso()
        _auto_percent(state)
        _write_state(project_dir, state)
        record_event(
            project_dir,
            "task",
            tr("Task “{title}”: {status}", "Задача «{title}»: {status}", title=found.get("title"), status=status),
            {"id": found.get("id"), "status": status},
        )
        return state


def finish_progress(project_dir: Path, message: str = "") -> dict[str, Any]:
    message = message or tr("Project finished", "Проект готов")
    with _LOCK:
        ensure_state(project_dir)
        state = read_state(project_dir)
        state["percent"] = 100.0
        state["status"] = "done"
        state["stage"] = tr("Done", "Готово")
        state["message"] = message
        state["last_event_at"] = now_iso()
        for task in state.get("tasks", []):
            if task.get("status") in {"pending", "in_progress"}:
                task["status"] = "done"
        _write_state(project_dir, state)
        record_event(project_dir, "done", message, {"percent": 100})
        return state


def read_events(project_dir: Path, limit: int = _MAX_EVENTS_RETURNED) -> list[dict[str, Any]]:
    """Return the newest events without loading the whole journal.

    ``events.jsonl`` is append-only and the editor polls it on a timer, so the
    last N lines are read by seeking from the end instead of reading up to
    several megabytes on every tick.
    """
    path = events_path(project_dir)
    limit = max(1, int(limit))
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            pos = size
            data = b""
            chunk = 64 * 1024
            while pos > 0 and data.count(b"\n") < limit + 1 and len(data) < 8_000_000:
                step = min(chunk, pos)
                pos -= step
                handle.seek(pos)
                data = handle.read(step) + data
            lines = data.decode("utf-8", "replace").splitlines()
    except OSError:
        return []
    if pos > 0 and lines:
        # The first line may start mid-character after the seek.
        lines = lines[1:]
    events: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                events.append(value)
        except ValueError:
            continue
    return events


def walk_project_files(project_dir: Path, *, ignored: set[str] | None = None):
    """Yield project files while pruning ignored folders early."""
    project_dir = Path(project_dir)
    skip = set(ignored) if ignored is not None else {
        ".reasonable",
        "__pycache__",
        ".git",
        "progress",
        "dist",
        "build",
        ".venv",
        "venv",
        "_engine",
    }
    stack = [project_dir]
    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    if entry.name not in skip:
                        stack.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    yield Path(entry.path)
            except OSError:
                continue


def scan_recent_files(project_dir: Path, limit: int = 16) -> list[dict[str, Any]]:
    """Find recently modified project files, useful in external-agent mode."""
    project_dir = Path(project_dir)
    ignored_suffixes = {".pyc", ".tmp", ".log"}
    rows: list[dict[str, Any]] = []
    try:
        for path in walk_project_files(project_dir):
            if len(rows) > 900:
                break
            if path.suffix.lower() in ignored_suffixes:
                continue
            try:
                rel_parts = path.relative_to(project_dir).parts
                stat = path.stat()
            except (OSError, ValueError):
                continue
            rows.append(
                {
                    "path": "/".join(rel_parts),
                    "mtime": stat.st_mtime,
                    "size": stat.st_size,
                }
            )
    except OSError:
        return []
    rows.sort(key=lambda item: item["mtime"], reverse=True)
    return rows[:limit]


def activity_is_live(project_dir: Path, window_seconds: int = 300) -> bool:
    """Heuristic: is an external agent actively working?"""
    from datetime import datetime

    state = read_state(project_dir)
    try:
        last = datetime.fromisoformat(state.get("last_event_at", ""))
    except ValueError:
        last = None
    if last is not None:
        delta = (datetime.now(last.tzinfo) - last).total_seconds()
        if delta <= window_seconds:
            return True
    for row in scan_recent_files(project_dir, limit=1):
        from time import time

        if time() - float(row["mtime"]) <= window_seconds:
            return True
    return False
