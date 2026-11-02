"""Tools available to the built-in AI agent.

Every tool is sandboxed to the project folder. Results are compact JSON strings so
models with small context windows stay usable. The tool layer is also used by the
CLI (for example ``re validate``) and by tests.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from reasonable.core.paths import is_relative_to
from reasonable.core.progress import (
    finish_progress,
    read_events,
    read_state,
    record_event,
    set_plan,
    set_progress,
    update_task,
)
from reasonable.core.project import IGNORED_DIRS, Project, TEXT_SUFFIXES
from reasonable.core.i18n import tr


def _t(en: str, ru: str, **values) -> str:
    """User-facing tool message in the UI language.

    Tool schemas themselves stay English-only (they are AI-facing material);
    only messages returned to the user through the chat panel are localized.
    """
    return tr(en, ru, **values)

MAX_WRITE_BYTES = 600_000
MAX_READ_BYTES = 400_000
PROTECTED = {"project.json", "main.py", "progress/state.json", "progress/events.jsonl"}


class ToolError(RuntimeError):
    pass


def _schema(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required or [],
            "additionalProperties": False,
        },
    }


TOOL_SCHEMAS: list[dict[str, Any]] = [
    _schema(
        "list_files",
        "List the project's files and folders. Use at the start of a job.",
        {
            "path": {"type": "string", "description": "Folder relative to the project root", "default": "."},
            "depth": {"type": "integer", "description": "Traversal depth", "default": 3, "minimum": 1, "maximum": 8},
        },
    ),
    _schema(
        "read_file",
        "Read a project text file. For large files use start_line/end_line.",
        {
            "path": {"type": "string", "description": "Path relative to the project root"},
            "start_line": {"type": "integer", "default": 1, "minimum": 1},
            "end_line": {"type": "integer", "description": "Last line, inclusive", "default": 800},
        },
        ["path"],
    ),
    _schema(
        "write_file",
        "Create or fully replace a file. Prefer edit_file for targeted changes.",
        {
            "path": {"type": "string", "description": "Path relative to the project root"},
            "content": {"type": "string", "description": "Full file contents"},
        },
        ["path", "content"],
    ),
    _schema(
        "edit_file",
        "Replace an exact fragment of a file. old_text must occur exactly once (or pass replace_all).",
        {
            "path": {"type": "string"},
            "old_text": {"type": "string", "description": "Exact existing fragment"},
            "new_text": {"type": "string", "description": "Replacement fragment"},
            "replace_all": {"type": "boolean", "default": False},
        },
        ["path", "old_text", "new_text"],
    ),
    _schema(
        "delete_path",
        "Delete a file or folder inside the project. Protected files cannot be deleted.",
        {
            "path": {"type": "string"},
            "recursive": {"type": "boolean", "description": "Delete the folder with all its contents", "default": False},
        },
        ["path"],
    ),
    _schema(
        "search_text",
        "Find a string or regex in the project's text files.",
        {
            "query": {"type": "string"},
            "path": {"type": "string", "default": "."},
            "regex": {"type": "boolean", "default": False},
            "limit": {"type": "integer", "default": 60, "minimum": 1, "maximum": 200},
        },
        ["query"],
    ),
    _schema(
        "run_command",
        "Run a command inside the project folder (e.g. python -m pytest or python -m py_compile main.py).",
        {
            "command": {"type": "string"},
            "timeout": {"type": "integer", "default": 120, "minimum": 5, "maximum": 300},
        },
        ["command"],
    ),
    _schema(
        "run_project",
        "Run the project headless for a few frames and return any errors. Use after major changes.",
        {
            "frames": {"type": "integer", "default": 8, "minimum": 1, "maximum": 600},
            "timeout": {"type": "integer", "default": 90, "minimum": 10, "maximum": 240},
        },
    ),
    _schema(
        "validate_project",
        "Validate structure, project.json and the syntax of every Python file in the project.",
        {},
    ),
    _schema(
        "generate_sprite",
        "Generate a sprite (one object, transparent background) and save it into assets/.",
        {
            "prompt": {"type": "string", "description": "What to draw, in English or Russian"},
            "path": {"type": "string", "description": "For example assets/sprites/player.png"},
            "style": {"type": "string", "enum": ["flat", "pixel", "painterly", "icon"], "default": "flat"},
            "size": {"type": "integer", "default": 256, "minimum": 64, "maximum": 1024},
        },
        ["prompt", "path"],
    ),
    _schema(
        "generate_background",
        "Generate a scene background and save it into assets/.",
        {
            "prompt": {"type": "string"},
            "path": {"type": "string", "description": "For example assets/backgrounds/forest.png"},
            "width": {"type": "integer", "default": 1280, "minimum": 320, "maximum": 1920},
            "height": {"type": "integer", "default": 720, "minimum": 240, "maximum": 1080},
        },
        ["prompt", "path"],
    ),
    _schema(
        "inspect_image",
        "Inspect a PNG: size, transparency, object bounds and dominant colors.",
        {"path": {"type": "string"}},
        ["path"],
    ),
    _schema(
        "set_plan",
        "Replace the work plan with a list of concrete tasks.",
        {
            "tasks": {
                "type": "array",
                "items": {"type": "string"},
                "description": "3–8 concrete tasks in order",
            }
        },
        ["tasks"],
    ),
    _schema(
        "update_task",
        "Update the status of a plan task.",
        {
            "task": {"type": "string", "description": "Task id (t1), number or title"},
            "status": {"type": "string", "enum": ["pending", "in_progress", "done", "skipped"]},
        },
        ["task", "status"],
    ),
    _schema(
        "report_progress",
        "Update the percentage, stage and user-visible message in the editor.",
        {
            "percent": {"type": "number", "minimum": 0, "maximum": 100},
            "stage": {"type": "string"},
            "message": {"type": "string"},
        },
        ["percent"],
    ),
    _schema(
        "get_progress",
        "Read the current progress, plan and recent project events.",
        {},
    ),
    _schema(
        "finish",
        "Finish the job: 100%, all tasks done, final message.",
        {"message": {"type": "string"}},
        ["message"],
    ),
]


class AgentTools:
    def __init__(self, project: Project, *, image_config: dict | None = None) -> None:
        self.project = project
        self.image_config = image_config or {}
        # Work evidence used to decide whether ``finish`` is allowed. Installing
        # a library or reading files does not count as completing the task.
        self.files_changed = 0
        self.install_commands = 0
        self.validation_attempts = 0
        self.validation_passed = False
        self.run_attempts = 0
        self.run_passed = False
        self.last_validation_errors: list[str] = []
        self.last_run_error = ""
        # Human-readable audit trail of every project file the agent touched.
        # The editor shows it after a run and stores it in the history snapshot,
        # so a bad edit can be inspected before it is rolled back.
        self._changes: dict[str, dict[str, Any]] = {}

    @property
    def changed_files(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._changes.values()]

    def _record_change(self, path: Path, action: str, **extra: Any) -> None:
        try:
            relative = self._relative(path)
        except (ValueError, OSError):
            return
        if not relative:
            return
        previous = self._changes.get(relative)
        if previous is None:
            entry: dict[str, Any] = {"path": relative, "action": action}
            self._changes[relative] = entry
        else:
            entry = previous
            # A delete always wins; a generated asset keeps its own label.
            if action == "delete" or previous.get("action") not in {"create", "generate"}:
                entry["action"] = action
        entry.update({key: value for key, value in extra.items() if value is not None})
        if path.is_file():
            try:
                entry["size"] = path.stat().st_size
            except OSError:
                pass

    def readiness(self) -> dict[str, Any]:
        missing: list[str] = []
        if self.files_changed <= 0:
            missing.append("no project file has been modified yet")
        if not self.validation_passed:
            missing.append("validate_project has not passed without errors")
        if not self.run_passed:
            missing.append("run_project has not finished successfully")
        return {
            "files_changed": self.files_changed,
            "changed_files": self.changed_files,
            "validation_passed": self.validation_passed,
            "run_passed": self.run_passed,
            "install_commands": self.install_commands,
            "ready": not missing,
            "missing": missing,
        }

    # -- helpers ----------------------------------------------------------
    def _path(self, relative: str, *, allow_protected: bool = True) -> Path:
        if not str(relative).strip():
            raise ToolError(_t("Empty path.", "Пустой путь."))
        path = self.project.ensure_inside(relative)
        parts = path.relative_to(self.project.root).parts
        if parts and parts[0] == "_engine":
            raise ToolError(_t("The built-in engine folder _engine/ is read-only. Use re.bat sync-engine instead.", "Нельзя изменять встроенный движок _engine/. Используйте re.bat sync-engine."))
        rel = "/".join(parts)
        if not allow_protected and rel in PROTECTED:
            raise ToolError(_t("Protected file: {rel}", "Файл защищён: {rel}", rel=rel))
        return path

    def _relative(self, path: Path) -> str:
        return self.project.rel(path)

    def _ok(self, **payload: Any) -> str:
        payload.setdefault("ok", True)
        return json.dumps(payload, ensure_ascii=False)

    def _fail(self, message: str, **payload: Any) -> str:
        payload.update({"ok": False, "error": message})
        return json.dumps(payload, ensure_ascii=False)

    # -- dispatch ---------------------------------------------------------
    def call(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        arguments = arguments or {}
        handler: Callable[..., str] | None = getattr(self, f"tool_{name}", None)
        if handler is None:
            return self._fail(_t("Unknown tool: {name}", "Неизвестный инструмент: {name}", name=name))
        try:
            return handler(**arguments)
        except TypeError as exc:
            return self._fail(_t("Invalid arguments for {name}: {exc}", "Неверные аргументы для {name}: {exc}", exc=exc, name=name))
        except ToolError as exc:
            return self._fail(str(exc))
        except Exception as exc:
            return self._fail(f"{type(exc).__name__}: {exc}")

    # -- exploration ------------------------------------------------------
    def tool_list_files(self, path: str = ".", depth: int = 3) -> str:
        base = self._path(path or ".", allow_protected=True)
        if not base.exists():
            raise ToolError(_t("Folder not found: {path}", "Папка не найдена: {path}", path=path))
        if base.is_file():
            return self._ok(path=self._relative(base), size=base.stat().st_size)
        depth = max(1, min(8, int(depth)))
        rows: list[str] = []
        root_depth = len(base.parts)
        for item in sorted(base.rglob("*"), key=lambda p: (p.is_file(), str(p).lower())):
            parts = item.relative_to(base).parts
            if len(parts) > depth:
                continue
            if any(part in IGNORED_DIRS for part in parts):
                continue
            if any(part == "__pycache__" for part in parts):
                continue
            suffix = "/" if item.is_dir() else ""
            size = f"  {item.stat().st_size} B" if item.is_file() else ""
            rows.append("  " * (len(parts) - 1) + item.name + suffix + size)
            if len(rows) >= 700:
                rows.append(_t("... (truncated)", "… (обрезано)"))
                break
        return self._ok(path=self._relative(base), entries=rows)

    def tool_read_file(self, path: str, start_line: int = 1, end_line: int = 800) -> str:
        file_path = self._path(path)
        if not file_path.is_file():
            raise ToolError(_t("File not found: {path}", "Файл не найден: {path}", path=path))
        if file_path.suffix.lower() not in TEXT_SUFFIXES and file_path.stat().st_size > MAX_READ_BYTES:
            raise ToolError(_t("Not a text file. Use inspect_image for images.", "Это не текстовый файл. Используйте inspect_image для изображений."))
        if file_path.stat().st_size > MAX_READ_BYTES:
            raise ToolError(_t("File too large. Pass start_line/end_line.", "Файл слишком большой. Укажите start_line/end_line."))
        text = file_path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        start = max(1, int(start_line))
        end = min(len(lines), max(start, int(end_line)))
        chunk = "\n".join(lines[start - 1 : end])
        return self._ok(
            path=self._relative(file_path),
            start_line=start,
            end_line=end,
            total_lines=len(lines),
            content=chunk,
        )

    def tool_search_text(self, query: str, path: str = ".", regex: bool = False, limit: int = 60) -> str:
        base = self._path(path or ".")
        limit = max(1, min(200, int(limit)))
        pattern = None
        if regex:
            try:
                pattern = re.compile(query, re.IGNORECASE)
            except re.error as exc:
                raise ToolError(_t("Bad regular expression: {exc}", "Плохое регулярное выражение: {exc}", exc=exc))
        matches: list[dict[str, Any]] = []
        candidates = [base] if base.is_file() else base.rglob("*")
        for file_path in candidates:
            if len(matches) >= limit:
                break
            if not file_path.is_file() or file_path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            try:
                parts = file_path.relative_to(self.project.root).parts
            except ValueError:
                continue
            if any(part in IGNORED_DIRS for part in parts):
                continue
            try:
                if file_path.stat().st_size > 500_000:
                    continue
                lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for number, line in enumerate(lines, start=1):
                hit = bool(pattern.search(line)) if pattern else (query.lower() in line.lower())
                if hit:
                    matches.append({"path": self._relative(file_path), "line": number, "text": line[:300]})
                    if len(matches) >= limit:
                        break
        return self._ok(query=query, count=len(matches), matches=matches)

    # -- editing ----------------------------------------------------------
    def tool_write_file(self, path: str, content: str) -> str:
        if len(content.encode("utf-8")) > MAX_WRITE_BYTES:
            raise ToolError(_t("File too large. Split it into several files.", "Слишком большой файл. Разделите его на несколько."))
        file_path = self._path(path)
        if file_path.suffix.lower() == ".json":
            try:
                json.loads(content)
            except ValueError as exc:
                raise ToolError(_t("Invalid JSON: {exc}", "Некорректный JSON: {exc}", exc=exc))
        existed = file_path.exists()
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        self.files_changed += 1
        self.validation_passed = False
        self.run_passed = False
        self._record_change(file_path, "edit" if existed else "create")
        return self._ok(path=self._relative(file_path), bytes=len(content.encode("utf-8")), message=_t("File written.", "Файл записан."))

    def tool_edit_file(self, path: str, old_text: str, new_text: str, replace_all: bool = False) -> str:
        if not old_text:
            raise ToolError(_t("old_text must not be empty.", "old_text не может быть пустым."))
        file_path = self._path(path)
        if not file_path.is_file():
            raise ToolError(_t("File not found: {path}", "Файл не найден: {path}", path=path))
        text = file_path.read_text(encoding="utf-8")
        count = text.count(old_text)
        if count == 0:
            raise ToolError(_t("old_text fragment not found. Re-read the file first.", "Фрагмент old_text не найден. Прочитайте файл заново."))
        if count > 1 and not replace_all:
            raise ToolError(_t("Fragment occurs {count} times. Add more context or pass replace_all=true.", "Фрагмент встречается {count} раз. Уточните контекст или передайте replace_all=true.", count=count))
        updated = text.replace(old_text, new_text) if replace_all else text.replace(old_text, new_text, 1)
        file_path.write_text(updated, encoding="utf-8")
        self.files_changed += 1
        self.validation_passed = False
        self.run_passed = False
        self._record_change(file_path, "edit", replacements=count if replace_all else 1)
        return self._ok(
            path=self._relative(file_path),
            replacements=count if replace_all else 1,
            message=_t("File edited.", "Файл изменён."),
        )

    def tool_delete_path(self, path: str, recursive: bool = False) -> str:
        file_path = self._path(path, allow_protected=False)
        rel = self._relative(file_path)
        if rel in {"assets", "progress", "_engine"}:
            raise ToolError(_t("This folder is protected.", "Эта папка защищена."))
        if file_path.is_dir():
            if not recursive and any(file_path.iterdir()):
                raise ToolError(_t("Folder is not empty. Pass recursive=true.", "Папка не пуста. Укажите recursive=true."))
        was_directory = file_path.is_dir()
        self.project.delete_path(path)
        self.files_changed += 1
        self.validation_passed = False
        self.run_passed = False
        self._record_change(file_path, "delete", directory=was_directory)
        return self._ok(path=rel, message=_t("Deleted.", "Удалено."))

    # -- execution --------------------------------------------------------
    def tool_run_command(self, command: str, timeout: int = 120) -> str:
        command = command.strip()
        if not command:
            raise ToolError(_t("Empty command.", "Пустая команда."))
        lowered = command.lower()
        forbidden = ("format ", "shutdown", "rm -rf /", "del /s /q c:", "remove-item -recurse c:\\")
        if any(item in lowered for item in forbidden):
            raise ToolError(_t("Command blocked as unsafe.", "Команда заблокирована как небезопасная."))
        install_markers = (
            "pip install",
            "pip3 install",
            "pip uninstall",
            "uv pip install",
            "conda install",
            "npm install",
            "winget install",
            "choco install",
        )
        package_install = any(marker in lowered for marker in install_markers)
        if package_install:
            self.install_commands += 1
        timeout = max(5, min(300, int(timeout)))
        try:
            result = subprocess.run(
                command,
                cwd=str(self.project.root),
                env=self.project.run_env(),
                shell=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return self._fail(_t("Command did not finish within {timeout} s.", "Команда не завершилась за {timeout} сек.", timeout=timeout))
        output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
        return self._ok(
            command=command,
            returncode=result.returncode,
            package_install=package_install,
            output=output[-9000:],
        )

    def tool_run_project(self, frames: int = 8, timeout: int = 90) -> str:
        entry = self.project.entry
        if not entry.exists():
            raise ToolError(_t("Entry point main.py not found.", "Точка входа main.py не найдена."))
        env = self.project.run_env()
        env["SDL_VIDEODRIVER"] = "dummy"
        env["SDL_AUDIODRIVER"] = "dummy"
        env["RE_FRAMES"] = str(max(1, min(600, int(frames))))
        timeout = max(10, min(240, int(timeout)))
        started = time.perf_counter()
        command = self.project.run_command()
        self.run_attempts += 1
        try:
            result = subprocess.run(
                command,
                cwd=str(self.project.root),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            self.run_passed = False
            self.last_run_error = _t("Project did not exit within {timeout} s.", "Проект не завершился за {timeout} сек.", timeout=timeout)
            return self._fail(self.last_run_error + _t(" Check infinite loops or blocking dialogs.", " Проверьте бесконечные циклы/диалоги."))
        elapsed = time.perf_counter() - started
        output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
        self.run_passed = result.returncode == 0
        self.last_run_error = "" if self.run_passed else (result.stderr or result.stdout or "")[-1200:]
        return self._ok(
            returncode=result.returncode,
            seconds=round(elapsed, 2),
            output=output[-9000:],
            message=_t("The project ran without exceptions.", "Проект запустился без исключений.") if result.returncode == 0 else _t("The project exited with an error.", "Проект завершился с ошибкой."),
            readiness=self.readiness(),
        )

    def tool_validate_project(self) -> str:
        issues = self.project.validate()
        errors = [issue for issue in issues if issue.level == "error"]
        self.validation_attempts += 1
        self.validation_passed = not errors
        self.last_validation_errors = [issue.message for issue in errors]
        return self._ok(
            issues=[
                {"level": issue.level, "message": issue.message, "path": issue.path}
                for issue in issues
            ],
            has_errors=bool(errors),
            readiness=self.readiness(),
        )

    # -- assets -----------------------------------------------------------
    def tool_generate_sprite(self, prompt: str, path: str, style: str = "flat", size: int = 256) -> str:
        from reasonable.ai.sprites import generate_sprite

        target = self._path(path)
        assets = self.project.root / "assets"
        if not is_relative_to(target, assets):
            raise ToolError(_t("Save sprites only under assets/.", "Спрайты сохраняйте только в assets/."))
        result = generate_sprite(
            prompt,
            target,
            style=style,
            size=size,
            image_config=self.image_config,
            allow_fallback=True,
        )
        if result.get("fallback"):
            record_event(self.project.root, "asset", _t("Sprite created offline: {path}", "Спрайт создан офлайн: {path}", path=self._relative(target)))
        else:
            record_event(self.project.root, "asset", _t("Sprite generated: {path}", "Спрайт сгенерирован: {path}", path=self._relative(target)))
        self.files_changed += 1
        self._record_change(target, "generate", kind="sprite", prompt=prompt)
        return self._ok(**result)

    def tool_generate_background(
        self,
        prompt: str,
        path: str,
        width: int = 1280,
        height: int = 720,
    ) -> str:
        from reasonable.ai.sprites import generate_background

        target = self._path(path)
        assets = self.project.root / "assets"
        if not is_relative_to(target, assets):
            raise ToolError(_t("Save backgrounds only under assets/.", "Фоны сохраняйте только в assets/."))
        result = generate_background(
            prompt,
            target,
            width=width,
            height=height,
            image_config=self.image_config,
            allow_fallback=True,
        )
        record_event(self.project.root, "asset", _t("Background created: {path}", "Фон создан: {path}", path=self._relative(target)))
        self.files_changed += 1
        self._record_change(target, "generate", kind="background", prompt=prompt)
        return self._ok(**result)

    def tool_inspect_image(self, path: str) -> str:
        file_path = self._path(path)
        if not file_path.is_file():
            raise ToolError(_t("File not found: {path}", "Файл не найден: {path}", path=path))
        try:
            from PIL import Image
        except ImportError:
            raise ToolError(_t("Pillow is not installed.", "Pillow не установлен."))
        try:
            image = Image.open(file_path).convert("RGBA")
        except Exception as exc:
            raise ToolError(_t("Could not open image: {exc}", "Не удалось открыть изображение: {exc}", exc=exc))
        alpha = image.getchannel("A")
        bbox = alpha.getbbox()
        small = image.copy()
        small.thumbnail((96, 96))
        colors: dict[tuple[int, int, int], int] = {}
        for r, g, b, a in small.getdata():
            if a < 40:
                continue
            key = (r // 32 * 32, g // 32 * 32, b // 32 * 32)
            colors[key] = colors.get(key, 0) + 1
        palette = [
            "#%02x%02x%02x" % key
            for key, _count in sorted(colors.items(), key=lambda item: item[1], reverse=True)[:6]
        ]
        opaque = sum(1 for _r, _g, _b, a in small.getdata() if a > 30)
        total = max(1, small.width * small.height)
        return self._ok(
            path=self._relative(file_path),
            size=image.size,
            mode=image.mode,
            alpha_bbox=bbox,
            opaque_percent=round(opaque / total * 100, 1),
            dominant_colors=palette,
        )

    # -- progress ---------------------------------------------------------
    def tool_get_progress(self) -> str:
        state = read_state(self.project.root)
        events = read_events(self.project.root, limit=20)
        return self._ok(state=state, events=events)

    def tool_set_plan(self, tasks: list[str]) -> str:
        if not isinstance(tasks, list) or not tasks:
            raise ToolError(_t("A non-empty list of tasks is required.", "Нужен непустой список задач."))
        state = set_plan(self.project.root, [str(item) for item in tasks][:12])
        return self._ok(tasks=state.get("tasks", []), message=_t("Plan updated.", "План обновлён."))

    def tool_update_task(self, task: str, status: str) -> str:
        state = update_task(self.project.root, task, status)
        return self._ok(tasks=state.get("tasks", []), message=_t("Task updated.", "Задача обновлена."))

    def tool_report_progress(self, percent: float, stage: str = "", message: str = "") -> str:
        ready = self.readiness()
        requested = float(percent)
        capped = requested
        note = ""
        if requested >= 100 and not ready["ready"]:
            capped = 99
            note = _t(" 100% is reserved until validation and a successful run.", " 100% зарезервировано до успешной проверки и запуска проекта.")
        state = set_progress(
            self.project.root,
            capped,
            stage=stage or None,
            message=((message or "") + note).strip() or None,
            status="running" if capped < 100 else "done",
        )
        return self._ok(
            percent=state.get("percent"),
            stage=state.get("stage"),
            message=state.get("message"),
            readiness=ready,
        )

    def tool_finish(self, message: str) -> str:
        ready = self.readiness()
        if not ready["ready"]:
            missing = "; ".join(ready["missing"])
            return self._fail(
                _t(
                    "Too early to finish. Still missing: {missing}. Keep going: "
                    "edit the project files, run validate_project, fix every error "
                    "and then run_project. Installing a library or reading files is "
                    "not a completed task.",
                    "Завершать работу рано. Не выполнено: {missing}. Продолжай: "
                    "измени файлы проекта, запусти validate_project, исправь ошибки "
                    "и запусти run_project. Установка библиотеки или чтение файлов "
                    "не считается выполненной задачей.",
                    missing=missing,
                ),
                readiness=ready,
            )
        state = finish_progress(self.project.root, message or _t("Project ready", "Проект готов"))
        return self._ok(percent=state.get("percent"), message=message, readiness=ready)
