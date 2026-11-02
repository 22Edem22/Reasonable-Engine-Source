"""Project snapshots: safe versions the user can return to.

The built-in agent writes files straight into the project, so every agent run
starts with a snapshot. Snapshots live inside the project (``.reasonable`` is
already ignored by the project browser and by exports) and contain a plain copy
of the project files plus a small ``meta.json`` description.

The format is deliberately boring: users can open the folder, inspect a file,
or copy a snapshot somewhere else without any tooling.
"""

from __future__ import annotations

import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .i18n import t as _t, tr
from .paths import atomic_write_json, now_iso, read_json

HISTORY_DIR = ".reasonable/history"
META_NAME = "meta.json"
FILES_DIR = "files"
MAX_SNAPSHOTS = 20
MAX_FILES = 5000
MAX_FILE_BYTES = 8_000_000

# Folders that must never be copied into a snapshot or removed on restore.
IGNORED_DIRS = {
    ".reasonable",
    "_engine",
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "venv",
    "dist",
    "build",
    ".idea",
    ".vscode",
}
IGNORED_SUFFIXES = {".pyc", ".pyo", ".tmp", ".log"}

# Reason keys -> i18n translation keys (labels resolve through t()).
REASON_KEYS = {
    "agent": "history.agent_run",
    "manual": "history.manual",
    "before-restore": "history.before_restore",
    "before-run": "history.before_run",
}


def reason_label(reason: str) -> str:
    """Localized label for a snapshot reason key."""
    return _t(REASON_KEYS.get(reason, "history.snapshot"))


def project_root(project: Any) -> Path:
    if isinstance(project, (str, Path)):
        return Path(project)
    root = getattr(project, "root", project)
    return Path(root)


def history_root(project: Any) -> Path:
    return project_root(project) / HISTORY_DIR


def _new_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{uuid.uuid4().hex[:4]}"


def _copy_tree(source: Path, target: Path) -> tuple[int, int, list[str]]:
    """Copy project files, skipping caches, the vendored engine and history."""
    target.mkdir(parents=True, exist_ok=True)
    file_count = 0
    total_bytes = 0
    skipped: list[str] = []
    for current, directories, files in os.walk(source):
        current_path = Path(current)
        directories[:] = sorted(
            name for name in directories if name not in IGNORED_DIRS
        )
        for name in sorted(files):
            source_file = current_path / name
            relative = source_file.relative_to(source)
            if source_file.suffix.lower() in IGNORED_SUFFIXES:
                continue
            try:
                size = source_file.stat().st_size
            except OSError:
                continue
            if size > MAX_FILE_BYTES:
                skipped.append(str(relative).replace("\\", "/"))
                continue
            if file_count >= MAX_FILES:
                skipped.append("…")
                break
            destination = target / relative
            try:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_file, destination)
            except OSError:
                continue
            file_count += 1
            total_bytes += size
        if file_count >= MAX_FILES:
            break
    return file_count, total_bytes, skipped


def _snapshot_from_disk(project: Any, directory: Path) -> dict[str, Any]:
    meta = read_json(directory / META_NAME, {})
    if not isinstance(meta, dict):
        meta = {}
    meta.setdefault("id", directory.name)
    meta.setdefault("created_at", datetime.fromtimestamp(directory.stat().st_mtime).isoformat(timespec="seconds"))
    meta.setdefault("label", meta["id"])
    meta.setdefault("reason", "manual")
    meta.setdefault("file_count", 0)
    meta.setdefault("bytes", 0)
    meta.setdefault("changed_files", [])
    meta.setdefault("skipped", [])
    try:
        meta["path"] = str(directory)
    except OSError:
        meta["path"] = ""
    return meta


def create_snapshot(
    project: Any,
    *,
    label: str = "",
    reason: str = "manual",
    record: bool = True,
) -> dict[str, Any]:
    """Create a full snapshot and return its metadata."""
    root = project_root(project).resolve()
    if not root.is_dir():
        raise ValueError(tr("Project folder not found: {root}", "Папка проекта не найдена: {root}", root=root))
    target_root = history_root(root)
    target_root.mkdir(parents=True, exist_ok=True)
    snapshot_id = _new_id()
    directory = target_root / snapshot_id
    files_dir = directory / FILES_DIR
    file_count, total_bytes, skipped = _copy_tree(root, files_dir)
    meta = {
        "id": snapshot_id,
        "label": (label or reason_label(reason))[:120],
        "reason": reason,
        "created_at": now_iso(),
        "file_count": file_count,
        "bytes": total_bytes,
        "changed_files": [],
        "skipped": skipped,
        "source": "editor",
    }
    directory.mkdir(parents=True, exist_ok=True)
    atomic_write_json(directory / META_NAME, meta)
    _prune(root)
    if record:
        try:
            from .progress import record_event

            record_event(root, "history", tr("Project snapshot: {label}", "Снимок проекта: {label}", label=meta["label"]), {"snapshot": snapshot_id})
        except Exception:
            pass
    meta["path"] = str(directory)
    return meta


def list_snapshots(project: Any) -> list[dict[str, Any]]:
    """Newest snapshots first. Broken metadata is tolerated."""
    root = history_root(project)
    if not root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for directory in root.iterdir():
        if not directory.is_dir():
            continue
        try:
            meta = _snapshot_from_disk(root.parent.parent, directory)
        except OSError:
            continue
        if meta.get("id") == directory.name:
            rows.append(meta)
    rows.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return rows


def _valid_snapshot_id(snapshot_id: Any) -> str:
    """Snapshot ids are plain folder names; never let one escape the history folder."""
    value = str(snapshot_id or "").strip()
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        return ""
    return value


def get_snapshot(project: Any, snapshot_id: str) -> dict[str, Any] | None:
    value = _valid_snapshot_id(snapshot_id)
    if not value:
        return None
    directory = history_root(project) / value
    if not directory.is_dir():
        return None
    return _snapshot_from_disk(project, directory)


def latest_snapshot(project: Any, *, reason: str | None = None) -> dict[str, Any] | None:
    for snapshot in list_snapshots(project):
        if reason is None or snapshot.get("reason") == reason:
            return snapshot
    return None


def update_snapshot(project: Any, snapshot_id: str, **values: Any) -> dict[str, Any] | None:
    meta = get_snapshot(project, snapshot_id)
    if meta is None:
        return None
    meta.update(values)
    meta.pop("path", None)
    directory = history_root(project) / str(snapshot_id)
    atomic_write_json(directory / META_NAME, meta)
    meta["path"] = str(directory)
    return meta


def snapshot_files(project: Any, snapshot_id: str, limit: int = 400) -> list[str]:
    value = _valid_snapshot_id(snapshot_id)
    if not value:
        return []
    directory = history_root(project) / value / FILES_DIR
    if not directory.is_dir():
        return []
    rows: list[str] = []
    for path in directory.rglob("*"):
        if path.is_file():
            rows.append(str(path.relative_to(directory)).replace("\\", "/"))
            if len(rows) >= limit:
                break
    rows.sort()
    return rows


def delete_snapshot(project: Any, snapshot_id: str) -> bool:
    value = _valid_snapshot_id(snapshot_id)
    if not value:
        return False
    directory = history_root(project) / value
    if not directory.is_dir():
        return False
    root = project_root(project).resolve()
    try:
        if directory.resolve().parent != (root / HISTORY_DIR).resolve():
            return False
    except OSError:
        return False
    shutil.rmtree(directory, ignore_errors=True)
    return not directory.exists()


def _prune(root: Path) -> None:
    rows = list_snapshots(root)
    for snapshot in rows[MAX_SNAPSHOTS:]:
        directory = history_root(root) / str(snapshot.get("id"))
        shutil.rmtree(directory, ignore_errors=True)


def _keep_sets(files_dir: Path) -> tuple[set[str], set[str]]:
    files: set[str] = set()
    directories: set[str] = set()
    for path in files_dir.rglob("*"):
        if not path.is_file():
            continue
        relative = str(path.relative_to(files_dir)).replace("\\", "/")
        files.add(relative)
        parent = Path(relative).parent
        while str(parent) not in {"", "."}:
            directories.add(str(parent).replace("\\", "/"))
            parent = parent.parent
    return files, directories


def restore_snapshot(
    project: Any,
    snapshot_id: str,
    *,
    safety: bool = True,
) -> dict[str, Any]:
    """Restore files from a snapshot.

    ``.reasonable`` (including history), ``_engine``, ``.git`` and build caches
    are left untouched. A safety snapshot of the current state is created first,
    so the restore itself can be undone.
    """
    root = project_root(project).resolve()
    meta = get_snapshot(root, snapshot_id)
    if meta is None:
        raise ValueError(tr("Snapshot not found: {snapshot}", "Снимок не найден: {snapshot}", snapshot=snapshot_id))
    files_dir = history_root(root) / str(snapshot_id) / FILES_DIR
    if not files_dir.is_dir():
        raise ValueError(tr("The snapshot has no files.", "В снимке нет файлов."))

    safety_meta = (
        create_snapshot(root, label=_t("history.before_restore_label"), reason="before-restore")
        if safety
        else None
    )

    keep_files, keep_dirs = _keep_sets(files_dir)
    removed = 0
    # Remove files that do not exist in the snapshot. Work from the deepest
    # paths upwards so empty folders disappear naturally.
    current_files: list[Path] = []
    for current, directories, files in os.walk(root):
        current_path = Path(current)
        directories[:] = [name for name in directories if name not in IGNORED_DIRS]
        for name in files:
            current_files.append(current_path / name)
    for path in sorted(current_files, key=lambda item: len(item.parts), reverse=True):
        try:
            relative = str(path.relative_to(root)).replace("\\", "/")
        except ValueError:
            continue
        if relative in keep_files:
            continue
        if path.suffix.lower() in IGNORED_SUFFIXES:
            continue
        try:
            path.unlink()
            removed += 1
        except OSError:
            continue

    restored = 0
    for current, directories, files in os.walk(files_dir):
        current_path = Path(current)
        for name in files:
            source = current_path / name
            relative = source.relative_to(files_dir)
            destination = root / relative
            try:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                restored += 1
            except OSError:
                continue

    # Drop folders that are now empty, except protected roots.
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if not path.is_dir():
            continue
        try:
            relative = str(path.relative_to(root)).replace("\\", "/")
        except ValueError:
            continue
        if relative.split("/", 1)[0] in IGNORED_DIRS:
            continue
        if relative in keep_dirs:
            continue
        try:
            if not any(path.iterdir()):
                path.rmdir()
        except OSError:
            pass

    result = {
        "snapshot": meta,
        "restored": restored,
        "removed": removed,
        "safety_snapshot": safety_meta,
    }
    try:
        from .progress import record_event

        record_event(
            root,
            "history",
            tr("Restored version “{label}”", "Восстановлена версия «{label}»", label=meta.get("label")),
            {
                "snapshot": snapshot_id,
                "restored": restored,
                "removed": removed,
            },
        )
    except Exception:
        pass
    return result


def describe_snapshot(snapshot: dict[str, Any]) -> str:
    """Human readable one-line description for the history list."""
    reason = reason_label(str(snapshot.get("reason") or "manual"))
    changed = len(snapshot.get("changed_files") or [])
    suffix = _t("history.changed_files", count=changed) if changed else ""
    return f"{reason}{suffix}"
