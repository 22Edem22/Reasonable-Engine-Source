"""Project manifest and safe project-level operations.

Every Reasonable project is a normal folder with ``project.json`` at the root.
The editor, the built-in agent and external agents all read the same manifest,
so there is no hidden database and no lock-in.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .i18n import tr
from .paths import (
    atomic_write_json,
    atomic_write_text,
    is_relative_to,
    now_iso,
    read_json,
    slugify,
    unique_directory,
)

MANIFEST_NAME = "project.json"
PROJECT_FORMAT = 1
ENGINE_DIR_NAME = "_engine"
PROJECT_TYPES = ("game", "app", "site", "other")
SCRATCH_PATTERN = re.compile(
    r"^(?:_check.*\.py|_probe.*\.py|_scan.*|_defs\.txt|_t\d+\.json|tmp_.*|scratch.*)$",
    re.IGNORECASE,
)

UI_LEVELS = ("simple", "standard", "advanced")
UI_LEVEL_LABELS = {
    "simple": "Простой (tkinter)",
    "standard": "Стандартный (движок)",
    "advanced": "Продвинутый (сцены и графика)",
}
IGNORED_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "_engine",
    "dist",
    "build",
    ".reasonable",
    ".idea",
    ".vscode",
}
TEXT_SUFFIXES = {
    ".py",
    ".json",
    ".md",
    ".txt",
    ".toml",
    ".cfg",
    ".ini",
    ".yml",
    ".yaml",
    ".html",
    ".css",
    ".js",
    ".ts",
    ".bat",
    ".sh",
    ".spec",
    ".xml",
    ".csv",
}


def normalise_ui_levels(value: Any, project_type: str = "game") -> list[str]:
    """Validate a ui_levels selection; fall back to sane defaults per type."""
    if isinstance(value, str):
        value = [value]
    levels = [str(item).strip().lower() for item in value] if isinstance(value, (list, tuple)) else []
    cleaned = [level for level in dict.fromkeys(levels) if level in UI_LEVELS]
    if not cleaned:
        cleaned = ["advanced", "standard"] if project_type == "game" else ["standard"]
    return cleaned


def default_manifest(
    name: str,
    *,
    project_type: str = "game",
    mode: str = "builtin",
    goal: str = "",
    notes: str = "",
    width: int = 1280,
    height: int = 720,
    window_mode: str = "windowed",
    resizable: bool = True,
    orientation: str = "landscape",
    template: str | None = None,
    platform: str = "windows",
    ui_levels: list[str] | None = None,
) -> dict[str, Any]:
    stamp = now_iso()
    project_type = project_type if project_type in PROJECT_TYPES else "game"
    return {
        "format": PROJECT_FORMAT,
        "name": name.strip() or tr("New project", "Новый проект"),
        "slug": slugify(name, "project"),
        "type": project_type,
        "platform": platform if platform in {"windows", "android"} else "windows",
        "mode": mode if mode in {"builtin", "external"} else "builtin",
        "goal": goal.strip(),
        "notes": notes.strip(),
        "template": template or project_type,
        "ui_levels": normalise_ui_levels(ui_levels, project_type),
        "created_at": stamp,
        "updated_at": stamp,
        "engine_version": "",
        "entry": "main.py",
        "window": {
            "width": int(width),
            "height": int(height),
            "title": name.strip() or "Reasonable Project",
            "mode": "fullscreen" if window_mode == "fullscreen" else "windowed",
            "resizable": bool(resizable),
        },
        "orientation": orientation if orientation in {"landscape", "portrait"} else "landscape",
        "splash": True,
        "icon": "assets/icon.png",
        "background": "assets/background.png",
        "android": {
            "package": "org.reasonable." + re.sub(r"[^a-z0-9]", "", slugify(name, "project")),
            "version": "1.0.0",
            "orientation": "landscape" if orientation != "portrait" else "portrait",
        },
        "ai": {
            "image_style": "flat",
            "notes": "",
        },
        "author": "",
    }


@dataclass
class ValidationIssue:
    level: str
    message: str
    path: str = ""


@dataclass
class Project:
    root: Path
    manifest: dict[str, Any] = field(default_factory=dict)

    # -- construction -----------------------------------------------------
    @classmethod
    def create(cls, root: Path, manifest: dict[str, Any], *, scaffold: bool = True) -> "Project":
        from .scaffold import scaffold_project

        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        project = cls(root=root, manifest=manifest)
        if scaffold:
            scaffold_project(project)
        else:
            project.save()
        return project

    @classmethod
    def load(cls, root: str | Path) -> "Project":
        root = Path(root).expanduser().resolve()
        data = read_json(root / MANIFEST_NAME, None)
        if not isinstance(data, dict):
            raise ValueError(tr("No valid {manifest} in the folder: {root}", "В папке нет корректного {manifest}: {root}", manifest=MANIFEST_NAME, root=root))
        return cls(root=root, manifest=data)

    @classmethod
    def is_project(cls, root: str | Path) -> bool:
        try:
            return isinstance(read_json(Path(root) / MANIFEST_NAME, None), dict)
        except OSError:
            return False

    # -- manifest ---------------------------------------------------------
    @property
    def name(self) -> str:
        return str(self.manifest.get("name") or self.root.name)

    @property
    def project_type(self) -> str:
        value = str(self.manifest.get("type") or "game")
        return value if value in PROJECT_TYPES else "game"

    @property
    def platform(self) -> str:
        """Primary target platform: ``windows`` or ``android``.

        Older projects created before this field existed are Windows projects.
        Exporting does not change the platform; converting creates a new project
        with a new manifest value.
        """
        value = str(self.manifest.get("platform") or "windows").lower()
        return value if value in {"windows", "android"} else "windows"

    @property
    def orientation(self) -> str:
        value = str(self.manifest.get("orientation") or "landscape").lower()
        return value if value in {"landscape", "portrait"} else "landscape"

    @property
    def mode(self) -> str:
        value = str(self.manifest.get("mode") or "builtin")
        return value if value in {"builtin", "external"} else "builtin"

    @property
    def ui_levels(self) -> list[str]:
        """Selected interface levels, e.g. ``["simple"]`` or ``["advanced", "standard"]``.

        Decides which UI toolkits and skills the project ships. The window
        itself is configured by the agent, not by the user.
        """
        return normalise_ui_levels(self.manifest.get("ui_levels"), self.project_type)

    @property
    def goal(self) -> str:
        return str(self.manifest.get("goal") or "")

    @property
    def notes(self) -> str:
        """Optional project brief, added after creation or by the agent."""
        return str(self.manifest.get("notes") or self.manifest.get("prompts") or "")

    @property
    def entry(self) -> Path:
        return self.root / str(self.manifest.get("entry") or "main.py")

    def scratch_files(self) -> list[Path]:
        """Temporary audit/probe files that must not ship with the project."""
        result: list[Path] = []
        try:
            for path in self.root.iterdir():
                if path.is_file() and SCRATCH_PATTERN.match(path.name):
                    result.append(path)
        except OSError:
            pass
        return result

    def missing_requirements(self) -> list[str]:
        """Package names from requirements.txt that are not importable here."""
        path = self.root / "requirements.txt"
        if not path.is_file():
            return []
        aliases = {
            "pillow": "PIL",
            "beautifulsoup4": "bs4",
            "python-dateutil": "dateutil",
            "pyyaml": "yaml",
            "opencv-python": "cv2",
            "scikit-learn": "sklearn",
        }
        missing: list[str] = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        for line in lines:
            value = line.strip()
            if not value or value.startswith(("#", "-", "git+", "http")):
                continue
            name = re.split(r"[\s\[<>=!~;]", value, maxsplit=1)[0].strip()
            if not name:
                continue
            module = aliases.get(name.lower(), name.replace("-", "_"))
            try:
                if importlib.util.find_spec(module) is None:
                    missing.append(name)
            except (ImportError, ValueError):
                missing.append(name)
        return list(dict.fromkeys(missing))

    def has_launch_block(self) -> bool:
        """Whether main.py contains executable launch code.

        A file with only imports, constants, functions and classes parses
        cleanly but does nothing when launched: the splash plays and the
        window closes. Game and app projects need a top-level call, a main
        loop or an ``if __name__ == "__main__"`` guard at the end.
        """
        if not self.entry.is_file() or self.entry.suffix != ".py":
            return True
        try:
            tree = ast.parse(self.entry.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            # A syntax error is reported separately by validate().
            return True
        runtime_nodes = (ast.Expr, ast.If, ast.While, ast.For, ast.Try, ast.With)
        return any(isinstance(node, runtime_nodes) for node in tree.body)

    @property
    def window(self) -> dict[str, Any]:
        return dict(self.manifest.get("window") or {})

    @property
    def android(self) -> dict[str, Any]:
        return dict(self.manifest.get("android") or {})

    @property
    def window_mode(self) -> str:
        mode = str(self.window.get("mode") or "windowed").lower()
        return "fullscreen" if mode == "fullscreen" else "windowed"

    @property
    def fullscreen(self) -> bool:
        return self.window_mode == "fullscreen"

    @property
    def resizable(self) -> bool:
        return bool(self.window.get("resizable", True))

    @property
    def icon_path(self) -> Path | None:
        value = self.manifest.get("icon")
        if not value:
            return None
        path = self.root / str(value)
        return path if path.exists() else None

    def save(self) -> None:
        self.manifest["updated_at"] = now_iso()
        atomic_write_json(self.root / MANIFEST_NAME, self.manifest)

    def update(self, **values: Any) -> None:
        self.manifest.update(values)
        self.save()

    # -- paths ------------------------------------------------------------
    def path(self, relative: str | Path) -> Path:
        return (self.root / relative).resolve()

    def ensure_inside(self, relative: str | Path) -> Path:
        path = self.path(relative)
        if not is_relative_to(path, self.root):
            raise ValueError(tr("You cannot leave the project folder.", "Нельзя выйти за пределы папки проекта."))
        return path

    def rel(self, path: str | Path) -> str:
        p = Path(path)
        try:
            return str(p.resolve().relative_to(self.root)).replace("\\", "/")
        except ValueError:
            return str(p).replace("\\", "/")

    # -- files ------------------------------------------------------------
    @staticmethod
    def _iter_walk(root: Path, *, include_engine: bool = False):
        """Yield ``(path, is_dir)`` without descending into ignored folders.

        ``Path.rglob`` walks the whole tree first and filters afterwards, which
        is very slow for projects with a vendored engine, ``build`` or a
        virtualenv. Scanning with ``os.scandir`` lets us prune those folders
        completely.
        """
        stack = [Path(root)]
        while stack:
            current = stack.pop()
            try:
                entries = list(os.scandir(current))
            except OSError:
                continue
            for entry in entries:
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                except OSError:
                    continue
                if is_dir and (
                    entry.name == "__pycache__"
                    or (not include_engine and entry.name in IGNORED_DIRS)
                ):
                    continue
                path = Path(entry.path)
                yield path, is_dir
                if is_dir:
                    stack.append(path)

    def list_files(self, *, include_engine: bool = False, limit: int = 1200) -> list[str]:
        rows: list[str] = []
        for path, is_dir in self._iter_walk(self.root, include_engine=include_engine):
            if len(rows) >= limit:
                break
            if is_dir:
                continue
            try:
                parts = path.relative_to(self.root).parts
            except ValueError:
                continue
            rows.append("/".join(parts))
        rows.sort(key=str.lower)
        return rows

    def list_tree(self, *, include_engine: bool = False) -> list[dict[str, Any]]:
        """Flat list of folders and files for the file browser."""
        rows: list[dict[str, Any]] = []
        for path, is_dir in self._iter_walk(self.root, include_engine=include_engine):
            try:
                parts = path.relative_to(self.root).parts
            except ValueError:
                continue
            try:
                stat = path.stat()
            except OSError:
                stat = None
            rows.append(
                {
                    "path": "/".join(parts),
                    "is_dir": is_dir,
                    "size": stat.st_size if (stat is not None and not is_dir) else 0,
                    "mtime": stat.st_mtime if stat is not None else 0.0,
                }
            )
        rows.sort(key=lambda item: (not item["is_dir"], item["path"].lower()))
        return rows

    def read_text(self, relative: str | Path, *, max_bytes: int = 2_000_000) -> str:
        path = self.ensure_inside(relative)
        if path.stat().st_size > max_bytes:
            raise ValueError(tr("The file is too large to read.", "Файл слишком большой для чтения."))
        return path.read_text(encoding="utf-8", errors="replace")

    def write_text(self, relative: str | Path, content: str) -> Path:
        path = self.ensure_inside(relative)
        atomic_write_text(path, content)
        return path

    def delete_path(self, relative: str | Path) -> None:
        path = self.ensure_inside(relative)
        if path == self.root:
            raise ValueError(tr("You cannot delete the project root.", "Нельзя удалить корень проекта."))
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()

    # -- running ----------------------------------------------------------
    def run_env(self) -> dict[str, str]:
        """Environment for running the project.

        The intro splash always plays: there is intentionally no user-facing
        way to disable it (headless runs finish it instantly on their own).
        """
        env = dict(os.environ)
        engine_root = self.root / ENGINE_DIR_NAME
        paths = [str(engine_root), str(self.root)]
        existing = env.get("PYTHONPATH")
        if existing:
            paths.append(existing)
        env["PYTHONPATH"] = os.pathsep.join(paths)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        return env

    def run_command(self, *, splash_wrapper: bool = False) -> list[str]:
        from .paths import project_launch_command, python_command

        if splash_wrapper and (self.root / ENGINE_DIR_NAME / "reasonable").is_dir():
            # The wrapper plays the intro before any project code, so even a
            # rewritten main.py cannot skip the engine branding.
            return [
                *python_command(),
                "-m",
                "reasonable.runtime.launch",
                str(self.entry),
            ]
        return project_launch_command(self.entry, project_root=self.root)

    def launch(self) -> subprocess.Popen:
        if not self.entry.exists():
            raise FileNotFoundError(tr("Entry point not found: {entry}", "Точка входа не найдена: {entry}", entry=self.entry))
        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        return subprocess.Popen(
            self.run_command(splash_wrapper=True),
            cwd=str(self.root),
            env=self.run_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )

    # -- validation -------------------------------------------------------
    def validate(self) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if not self.entry.exists():
            issues.append(ValidationIssue("error", tr("No entry point {name}", "Нет точки входа {name}", name=self.entry.name), "main.py"))
        for relative in ("assets", "progress"):
            if not (self.root / relative).is_dir():
                issues.append(ValidationIssue("warning", tr("Missing folder {folder}/", "Отсутствует папка {folder}/", folder=relative), relative))
        for path in self.root.rglob("*.py"):
            parts = path.relative_to(self.root).parts
            if any(part in IGNORED_DIRS for part in parts):
                continue
            try:
                source = path.read_text(encoding="utf-8")
                ast.parse(source, filename=str(path))
            except SyntaxError as exc:
                issues.append(
                    ValidationIssue(
                        "error",
                        tr("Syntax: {message} (line {line})", "Синтаксис: {message} (строка {line})", message=exc.msg, line=exc.lineno),
                        self.rel(path),
                    )
                )
            except OSError:
                continue
        manifest = self.manifest
        if not str(manifest.get("goal", "")).strip():
            issues.append(ValidationIssue("warning", tr("The main goal of the project is not filled in.", "Не заполнена главная цель проекта."), MANIFEST_NAME))
        if not self.entry.exists() and self.entry.suffix != ".py":
            issues.append(ValidationIssue("warning", tr("The entry point is not a Python file.", "Точка входа не является Python-файлом."), "project.json"))
        progress_state = read_json(self.root / "progress" / "state.json", {})
        if not progress_state:
            issues.append(ValidationIssue("warning", tr("The agent has not created progress/state.json yet.", "Агент ещё не создал progress/state.json."), "progress/state.json"))
        if self.project_type == "site":
            from .site import validate_site

            for issue in validate_site(self.root):
                if issue.get("level") == "ok" and issues:
                    continue
                issues.append(
                    ValidationIssue(
                        str(issue.get("level") or "warning"),
                        str(issue.get("message") or ""),
                        str(issue.get("path") or ""),
                    )
                )
        if (
            self.project_type in {"game", "app"}
            and self.entry.exists()
            and self.entry.suffix == ".py"
            and not self.has_launch_block()
        ):
            issues.append(
                ValidationIssue(
                    "error",
                    tr(
                        "The entry point has no launch code: the project would open and close immediately. "
                        "Add `if __name__ == \"__main__\": main()` or start the game at the end of the file.",
                        "В точке входа нет запуска: проект откроется и сразу закроется. "
                        "Добавьте `if __name__ == \"__main__\": main()` или запустите игру в конце файла.",
                    ),
                    self.rel(self.entry),
                )
            )
        try:
            if self.entry.is_file() and self.entry.stat().st_size > 120_000:
                issues.append(
                    ValidationIssue(
                        "warning",
                        tr(
                            "The entry point is larger than 120 KB. Split it into modules before adding more features; "
                            "a huge main.py is hard to verify and often hides missing code.",
                            "Точка входа больше 120 КБ. Разбейте её на модули перед добавлением новых функций: "
                            "в огромном main.py трудно проверять код и легко потерять целые куски.",
                        ),
                        self.rel(self.entry),
                    )
                )
        except OSError:
            pass
        missing_packages = self.missing_requirements()
        if missing_packages:
            issues.append(
                ValidationIssue(
                    "warning",
                    tr(
                        "Dependencies from requirements.txt are not installed: {names}. Install them before running.",
                        "Зависимости из requirements.txt не установлены: {names}. Установите их перед запуском.",
                        names=", ".join(missing_packages[:8]),
                    ),
                    "requirements.txt",
                )
            )
        for path in self.scratch_files():
            issues.append(
                ValidationIssue(
                    "error",
                    tr(
                        "Temporary verification file must be removed: {name}",
                        "Временный проверочный файл нужно удалить: {name}",
                        name=path.name,
                    ),
                    self.rel(path),
                )
            )
        if not issues:
            issues.append(ValidationIssue("ok", tr("The project looks correct: syntax and structure are fine.", "Проект выглядит корректно: синтаксис и структура в порядке.")))
        return issues

    def summary(self) -> str:
        levels = ", ".join(UI_LEVEL_LABELS.get(level, level) for level in self.ui_levels)
        kind = {
            "game": tr("game", "игра"),
            "app": tr("app", "приложение"),
            "site": tr("website", "сайт"),
            "other": tr("project", "проект"),
        }.get(self.project_type, tr("project", "проект"))
        return (
            f"{self.name} — {kind}, Python, "
            f"{tr('interface:', 'интерфейс:')} {levels}, {tr('mode', 'режим')} {self.mode}."
        ) if self.project_type in {"game", "app"} else (
            f"{self.name} — {kind}, Python, {tr('mode', 'режим')} {self.mode}."
        )

    # -- engine sync ------------------------------------------------------
    def has_vendored_engine(self) -> bool:
        return (self.root / ENGINE_DIR_NAME / "reasonable" / "runtime").is_dir()

    def sync_engine(self) -> Path:
        from .scaffold import vendor_engine

        return vendor_engine(self.root)


def find_projects(root: Path, limit: int = 60) -> list[Path]:
    root = Path(root)
    found: list[Path] = []
    try:
        for candidate in root.rglob(MANIFEST_NAME):
            if len(found) >= limit:
                break
            if any(part in {".git", "_engine", "node_modules", "__pycache__"} for part in candidate.parts):
                continue
            found.append(candidate.parent)
    except OSError:
        pass
    return found


def choose_project_dir(parent: Path, name: str) -> Path:
    return unique_directory(Path(parent), slugify(name, "project"))
