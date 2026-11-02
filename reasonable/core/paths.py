"""Filesystem helpers and well-known Reasonable Engine locations."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PACKAGE_DIR = Path(__file__).resolve().parent.parent
ENGINE_ROOT = PACKAGE_DIR.parent
BRAND_DIR = PACKAGE_DIR / "assets" / "brand"
FONT_DIR = PACKAGE_DIR / "assets" / "fonts"
TEMPLATES_DIR = PACKAGE_DIR / "templates"
DOCS_DIR = ENGINE_ROOT / "docs"

# Name of the portable Python folder that the Windows installer ships next to
# the editor. Keeping the name in one place makes frozen and source runs agree.
PYTHON_DIR_NAME = "python"
PLAYER_EXE_NAME = "ReasonablePlayer.exe"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def install_root() -> Path:
    """Folder where Reasonable Engine is installed (or the repo root in dev)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return ENGINE_ROOT


def bundled_python() -> Path | None:
    """Return the portable interpreter shipped by the installer, if present."""
    override = os.environ.get("REASONABLE_PYTHON")
    if override:
        candidate = Path(override).expanduser()
        if candidate.is_file():
            return candidate
    root = install_root()
    candidates = (
        root / PYTHON_DIR_NAME / "python.exe",
        root / "runtime" / "python.exe",
        root / "runtime" / PYTHON_DIR_NAME / "python.exe",
        root / "python" / "python.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def python_executable() -> Path | None:
    """Find a usable Python interpreter for project commands.

    In a frozen build ``sys.executable`` points at the editor itself, so using
    it to run a project would open a second editor window. Prefer the bundled
    portable Python, then a normal system installation.
    """
    if not is_frozen():
        return Path(sys.executable)
    bundled = bundled_python()
    if bundled is not None:
        return bundled
    for name in ("python.exe", "python", "python3"):
        found = shutil.which(name)
        if found:
            return Path(found)
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    for folder in sorted((local / "Programs" / "Python").glob("Python3*"), reverse=True):
        candidate = folder / "python.exe"
        if candidate.is_file():
            return candidate
    for candidate in (
        Path("C:/Python313/python.exe"),
        Path("C:/Python312/python.exe"),
        Path("C:/Python311/python.exe"),
    ):
        if candidate.is_file():
            return candidate
    return None


def python_command() -> list[str]:
    """Command prefix for running Python scripts or modules."""
    interpreter = python_executable()
    if interpreter is not None:
        return [str(interpreter)]
    return [sys.executable]


def player_executable() -> Path | None:
    """Standalone project runner built alongside the editor."""
    root = install_root()
    candidates = (
        root / PLAYER_EXE_NAME,
        root / "runtime" / PLAYER_EXE_NAME,
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


# Substrings that mark an entry file as a tkinter program (the "simple"
# interface level). ReasonablePlayer.exe deliberately ships without tkinter
# (it is excluded in ReasonablePlayer.spec to keep the binary small), so such
# projects must run on a full Python interpreter instead.
TKINTER_MARKERS = ("import tkinter", "from tkinter")


def entry_uses_tkinter(entry: str | Path) -> bool:
    """True when the entry file imports tkinter at the top level."""
    try:
        text = Path(entry).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    for line in text.splitlines():
        stripped = line.strip()
        if any(stripped.startswith(marker) for marker in TKINTER_MARKERS):
            return True
    return False


def project_needs_tkinter(project_root: str | Path, entry: str | Path) -> bool:
    """Decide whether a project must be launched with a tkinter-capable Python.

    The manifest's template/ui level is authoritative when present; otherwise
    the entry file itself is inspected.
    """
    manifest = read_json(Path(project_root) / "project.json", None)
    if isinstance(manifest, dict):
        template = str(manifest.get("template") or "").strip().lower()
        if template == "simple":
            return True
        levels = manifest.get("ui_levels")
        if (
            isinstance(levels, (list, tuple))
            and levels
            and all(str(level).strip().lower() == "simple" for level in levels)
        ):
            return True
    return entry_uses_tkinter(entry)


def project_launch_command(
    entry: str | Path, *, project_root: str | Path | None = None
) -> list[str]:
    """Command that runs a project entry point without starting the editor.

    In an installed build the small ``ReasonablePlayer.exe`` is preferred; it
    embeds the pygame runtime and needs no Python installation. Tkinter
    projects are the exception: the player has no tkinter bundled, so they go
    through the portable/system Python instead. In a source checkout we simply
    use the current interpreter.
    """
    entry = Path(entry)
    if is_frozen():
        needs_tkinter = False
        root = Path(project_root) if project_root else entry.parent
        try:
            from reasonable.core.project import MANIFEST_NAME
        except ImportError:  # pragma: no cover - defensive
            MANIFEST_NAME = "project.json"
        if (root / MANIFEST_NAME).is_file() or entry_uses_tkinter(entry):
            needs_tkinter = project_needs_tkinter(root, entry)
        if not needs_tkinter:
            player = player_executable()
            if player is not None:
                return [str(player), str(entry)]
    return [*python_command(), str(entry)]


def default_projects_dir() -> Path:
    """Projects are created inside the engine folder unless the user chooses."""
    override = os.environ.get("REASONABLE_PROJECTS")
    if override:
        return Path(override).expanduser().resolve()
    return install_root() / "Projects"


def ensure_projects_dir(path: str | Path | None = None) -> Path:
    target = Path(path).expanduser() if path else default_projects_dir()
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError:
        fallback = app_data_dir() / "Projects"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback
    return target.resolve()


def app_data_dir() -> Path:
    override = os.environ.get("REASONABLE_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "win32":
        root = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(root) / "ReasonableEngine"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ReasonableEngine"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "reasonable-engine"


def ensure_app_dirs() -> Path:
    base = app_data_dir()
    for child in (base, base / "logs", base / "cache", base / "sprites"):
        child.mkdir(parents=True, exist_ok=True)
    return base


def settings_path() -> Path:
    return app_data_dir() / "settings.json"


def resource_path(relative: str | Path) -> Path:
    """Resolve an asset that ships with the engine, including frozen builds."""
    relative = Path(relative)
    frozen_root = getattr(sys, "_MEIPASS", None)
    candidates = []
    if frozen_root:
        candidates.append(Path(frozen_root) / "reasonable" / relative)
        candidates.append(Path(frozen_root) / relative)
    candidates.append(PACKAGE_DIR / relative)
    candidates.append(ENGINE_ROOT / relative)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return PACKAGE_DIR / relative


def engine_source_dir(protected: bool = False) -> Path:
    """Return the package folder that ``vendor_engine`` should copy.

    A PyInstaller build keeps Python modules in an archive, so
    ``reasonable.__file__`` does not point at real ``.py`` files. The build
    ships two copies:

    * ``engine_source/reasonable`` — plain source, kept for Android exports
      that must be rebuilt with python-for-android;
    * ``engine_source_pyc/reasonable`` — bytecode-only runtime used for Windows
      projects, so the engine source is not exposed in every generated project.

    In a source checkout the package itself is used.
    """
    override = os.environ.get("REASONABLE_ENGINE_SOURCE")
    if override:
        path = Path(override).expanduser().resolve()
        if path.name != "reasonable" and (path / "reasonable").is_dir():
            path = path / "reasonable"
        return path
    if is_frozen():
        frozen_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        candidates = []
        if protected:
            candidates += [
                frozen_root / "engine_source_pyc" / "reasonable",
                frozen_root / "engine_source" / "reasonable",
            ]
        else:
            candidates += [frozen_root / "engine_source" / "reasonable"]
        candidates.append(frozen_root / "reasonable")
        for candidate in candidates:
            if (candidate / "runtime").is_dir():
                return candidate
    import reasonable as package

    return Path(package.__file__).resolve().parent


def protected_engine_available() -> bool:
    """Whether a bytecode-only runtime is available for vendoring."""
    if not is_frozen() and os.environ.get("REASONABLE_PROTECT_ENGINE") != "1":
        return False
    try:
        source = engine_source_dir(protected=True)
    except Exception:
        return False
    return any(source.rglob("*.pyc")) and not any(source.rglob("*.py"))


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def human_time(iso_value: str | None) -> str:
    if not iso_value:
        return "—"
    try:
        value = datetime.fromisoformat(iso_value)
        if value.tzinfo is None:
            value = value.astimezone()
        delta = datetime.now().astimezone() - value
        seconds = int(delta.total_seconds())
        if seconds < 10:
            return "только что"
        if seconds < 60:
            return f"{seconds} сек. назад"
        if seconds < 3600:
            return f"{seconds // 60} мин. назад"
        if seconds < 86400:
            return f"{seconds // 3600} ч. назад"
        return value.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return iso_value


_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "",
    "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def to_latin(value: str) -> str:
    """Transliterate cyrillic (and strip accents) without touching other chars."""
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return "".join(_TRANSLIT.get(ch.lower(), ch) if ch.isalpha() else ch for ch in value)


def slugify(value: str, fallback: str = "project") -> str:
    value = value.strip().lower()
    value = "".join(_TRANSLIT.get(ch, ch) for ch in value)
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^a-z0-9]+", "-", value, flags=re.IGNORECASE).strip("-")
    return value[:48] or fallback


def unique_directory(parent: Path, base_name: str) -> Path:
    candidate = parent / base_name
    index = 2
    while candidate.exists():
        candidate = parent / f"{base_name}-{index}"
        index += 1
    return candidate


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding=encoding)
    os.replace(tmp, path)


def atomic_write_json(path: Path, data: Any) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def rel_to(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False
