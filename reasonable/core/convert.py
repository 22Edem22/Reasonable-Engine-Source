"""Convert a project into a new project without touching the source.

The primary use case is changing the target platform (Windows <-> Android).
The same safe copy-and-adjust pipeline also supports other useful variants:

* orientation (landscape/portrait) with an automatic resolution swap;
* AI agent mode (built-in/external);
* window mode, resizable flag and base resolution;
* a fresh progress plan, or preserved progress.

The conversion deliberately does not replace the game template with the app
template (or vice versa), rewrite game logic, or import projects from other
engines. Those operations require human design decisions, so the editor and the
agent should do them as ordinary edits after the new project exists.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from reasonable.version import VERSION

from .paths import atomic_write_text, is_relative_to, now_iso, slugify, unique_directory
from .progress import ensure_state, record_event, set_plan, set_status
from .project import ENGINE_DIR_NAME, Project

PLATFORM_NAMES = {"windows": "Windows", "android": "Android"}
ORIENTATION_NAMES = {"landscape": "альбомная", "portrait": "портретная"}
AGENT_MODE_NAMES = {"builtin": "встроенный ИИ", "external": "внешний агент"}
WINDOW_MODE_NAMES = {"windowed": "окно", "fullscreen": "полный экран"}

# Runtime data, dependency caches and previous exports are not source code.
# ``ai_config.json`` and ``.env`` may contain API keys and are intentionally not
# copied into a new project.
COPY_IGNORE = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".reasonable",
    "node_modules",
    "dist",
    "build",
    ENGINE_DIR_NAME,
    "data.json",
    "ai_config.json",
    ".reasonable-export",
}


def _copy_ignore(directory: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        if name in COPY_IGNORE or name.endswith((".pyc", ".pyo", ".tmp")):
            ignored.add(name)
        elif name == ".env" or name.startswith(".env."):
            ignored.add(name)
    return ignored


def _choice(value: Any, current: str, allowed: dict[str, str], label: str) -> str:
    if value is None or value == "" or value == "current":
        return current
    text = str(value).strip().lower()
    if text not in allowed:
        raise ValueError(f"Неизвестная {label}: {value}")
    return text


def _normalise_size(value: Any, current: int, minimum: int) -> int:
    if value is None or value == "":
        return int(current)
    try:
        return max(minimum, int(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Некорректный размер: {value}") from exc


def _normalise_resizable(value: Any, current: bool) -> bool:
    if value is None or value == "" or value == "current":
        return bool(current)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"yes", "true", "1", "да"}:
            return True
        if lowered in {"no", "false", "0", "нет"}:
            return False
        raise ValueError(f"Некорректное значение изменения размера: {value}")
    return bool(value)


def _default_package(name: str) -> str:
    return "org.reasonable." + re.sub(r"[^a-z0-9]", "", slugify(name, "project"))


def _path_error(project: Project, target_root: Path) -> str | None:
    if target_root == project.root:
        return "Новый проект не может находиться в той же папке, что и исходный."
    if is_relative_to(target_root, project.root):
        return "Новую папку нельзя создавать внутри исходного проекта."
    return None


def conversion_plan(
    project: Project,
    target: str,
    *,
    name: str | None = None,
    output: str | Path | None = None,
    orientation: str | None = None,
    mode: str | None = None,
    window_mode: str | None = None,
    resizable: Any = None,
    width: int | None = None,
    height: int | None = None,
    ui_levels: list[str] | None = None,
    reset_progress: bool = False,
) -> dict[str, Any]:
    """Validate conversion options and describe the resulting project.

    Nothing is written to disk. The editor uses this for a live preview; the
    CLI/GUI call :func:`convert_project` afterwards.
    """
    target_platform = str(target or "").strip().lower()
    if target_platform not in PLATFORM_NAMES:
        raise ValueError("Платформа должна быть windows или android.")

    current_orientation = project.orientation
    new_name = (name if name is not None else project.name).strip()
    if not new_name:
        raise ValueError("Название нового проекта не может быть пустым.")

    new_orientation = _choice(orientation, current_orientation, ORIENTATION_NAMES, "ориентация")
    new_mode = _choice(mode, project.mode, AGENT_MODE_NAMES, "режим агента")
    new_window_mode = _choice(window_mode, project.window_mode, WINDOW_MODE_NAMES, "режим окна")
    new_resizable = _normalise_resizable(resizable, project.resizable)

    window = project.window
    current_width = int(window.get("width", 1280))
    current_height = int(window.get("height", 720))
    width_supplied = width not in (None, "")
    height_supplied = height not in (None, "")
    new_width = _normalise_size(width, current_width, 320)
    new_height = _normalise_size(height, current_height, 240)

    # Changing orientation without an explicit resolution keeps the physical
    # shape sensible: 1280x720 landscape -> 720x1280 portrait.
    if new_orientation != current_orientation and not width_supplied and not height_supplied:
        if new_orientation == "portrait" and new_width > new_height:
            new_width, new_height = new_height, new_width
        elif new_orientation == "landscape" and new_height > new_width:
            new_width, new_height = new_height, new_width

    parent = Path(output).expanduser().resolve() if output else project.root.parent
    if parent.exists() and not parent.is_dir():
        raise ValueError(f"Путь для нового проекта не является папкой: {parent}")
    target_root = unique_directory(parent, slugify(new_name, "project"))
    path_error = _path_error(project, target_root)
    if path_error:
        raise ValueError(path_error)

    old_platform = project.platform
    android = dict(project.manifest.get("android") or {})
    package = str(android.get("package") or "").strip()
    old_default = _default_package(project.name)
    if not package or package == old_default:
        package = _default_package(new_name)
    android["package"] = package
    android["orientation"] = new_orientation

    changes: list[str] = []
    if old_platform != target_platform:
        changes.append(
            f"Платформа: {PLATFORM_NAMES[old_platform]} → {PLATFORM_NAMES[target_platform]}"
        )
    if new_name != project.name:
        changes.append(f"Название: {project.name} → {new_name}")
    if new_orientation != current_orientation:
        changes.append(
            f"Ориентация: {ORIENTATION_NAMES[current_orientation]} → {ORIENTATION_NAMES[new_orientation]}"
        )
    if new_mode != project.mode:
        changes.append(f"Агент: {AGENT_MODE_NAMES[project.mode]} → {AGENT_MODE_NAMES[new_mode]}")
    if new_window_mode != project.window_mode:
        changes.append(
            f"Режим окна: {WINDOW_MODE_NAMES[project.window_mode]} → {WINDOW_MODE_NAMES[new_window_mode]}"
        )
    if (new_width, new_height) != (current_width, current_height):
        changes.append(f"Базовый размер: {current_width}×{current_height} → {new_width}×{new_height}")
    if new_resizable != project.resizable:
        changes.append(
            "Изменение размера окна: "
            + ("выключено → включено" if new_resizable else "включено → выключено")
        )
    if reset_progress:
        changes.append("Прогресс, план и лента событий: сбросить")

    return {
        "source": str(project.root),
        "source_name": project.name,
        "source_platform": old_platform,
        "target": target_platform,
        "target_root": target_root,
        "target_name": new_name,
        "orientation": new_orientation,
        "mode": new_mode,
        "window_mode": new_window_mode,
        "resizable": new_resizable,
        "width": new_width,
        "height": new_height,
        "android": android,
        "reset_progress": bool(reset_progress),
        "changes": changes,
        "has_changes": bool(changes),
    }


def _rename_sources(root: Path, old_name: str, new_name: str) -> None:
    """Update the generated ``APP_NAME`` and README heading when renamed."""
    main = root / "main.py"
    try:
        text = main.read_text(encoding="utf-8")
    except OSError:
        text = ""
    if text:
        lines = text.splitlines(keepends=True)
        changed = False
        for index, line in enumerate(lines):
            if re.match(r"^\s*APP_NAME\s*=", line):
                prefix = line.split("=", 1)[0]
                ending = "\r\n" if line.endswith("\r\n") else ("\n" if line.endswith("\n") else "")
                lines[index] = f"{prefix}= {new_name!r}{ending}"
                changed = True
                break
        if changed:
            atomic_write_text(main, "".join(lines))

    readme = root / "README.md"
    try:
        text = readme.read_text(encoding="utf-8")
    except OSError:
        return
    lines = text.splitlines(keepends=True)
    if lines and lines[0].strip() == f"# {old_name}":
        ending = "\r\n" if lines[0].endswith("\r\n") else ("\n" if lines[0].endswith("\n") else "")
        lines[0] = f"# {new_name}{ending}"
        atomic_write_text(readme, "".join(lines))


def _conversion_tasks(plan: dict[str, Any]) -> list[str]:
    platform = PLATFORM_NAMES[plan["target"]]
    return [
        "Изучить проект после конвертации",
        f"Проверить окно, управление и компоновку под платформу {platform}",
        "Запустить проект и исправить найденные ошибки",
        "Обновить README и проверить экспорт",
    ]


def _write_conversion_doc(project: Project, plan: dict[str, Any], record: dict[str, Any]) -> None:
    changes = "\n".join(f"- {change}" for change in plan["changes"]) or "- Изменений нет."
    source = plan["source"]
    text = f"""# Конвертация проекта

Проект **{project.name}** создан из **{plan['source_name']}**.

- Исходная платформа: **{PLATFORM_NAMES[plan['source_platform']]}**
- Новая платформа: **{PLATFORM_NAMES[plan['target']]}**
- Дата: {record['at']}
- Исходная папка: `{source}`
- Версия движка: Reasonable Engine {VERSION}

Исходный проект не изменялся. Это отдельная папка со своей копией кода,
ассетов и встроенного движка.

## Что изменилось

{changes}

## Что конвертация не делает

- Не переписывает игровую логику и не адаптирует интерфейс под маленький экран
  автоматически. После конвертации попросите ИИ-агента проверить компоновку,
  размеры касаний и safe margins.
- Не заменяет шаблон игры на приложение и наоборот: это меняет смысл проекта и
  требует ручного решения.
- Не импортирует проекты сторонних движков.
- Не собирает APK. Android-пакет по-прежнему собирается через buildozer на
  Linux/WSL2: `re.bat export android`, затем `buildozer -v android debug`.

## Полезные команды

```bat
re.bat status
re.bat validate
re.bat run
re.bat export windows
re.bat export android
re.bat convert --to windows --dir ".."
```

Конвертировать можно не только платформу, но и ориентацию, режим агента, режим
окна, базовое разрешение и прогресс. Откройте **Настройки проекта** или пункт
**Конвертировать** в редакторе.
"""
    atomic_write_text(project.root / "CONVERSION.md", text)


def _update_progress(project: Project, plan: dict[str, Any]) -> None:
    if plan["reset_progress"]:
        progress = project.root / "progress"
        for name in ("state.json", "events.jsonl"):
            try:
                (progress / name).unlink()
            except OSError:
                pass
        ensure_state(project.root, plan["mode"])
        set_plan(project.root, _conversion_tasks(plan))
        set_status(
            project.root,
            "idle",
            "Проект сконвертирован. Опишите первую задачу агенту.",
        )
    else:
        ensure_state(project.root, plan["mode"])

    record_event(
        project.root,
        "conversion",
        f"Проект сконвертирован: {plan['source_name']} ({PLATFORM_NAMES[plan['source_platform']]}) "
        f"→ {project.name} ({PLATFORM_NAMES[plan['target']]}).",
        {
            "source": plan["source"],
            "from": plan["source_platform"],
            "to": plan["target"],
            "changes": plan["changes"],
            "reset_progress": plan["reset_progress"],
        },
    )


def convert_project(
    project: Project,
    target: str,
    *,
    name: str | None = None,
    output: str | Path | None = None,
    orientation: str | None = None,
    mode: str | None = None,
    window_mode: str | None = None,
    resizable: Any = None,
    width: int | None = None,
    height: int | None = None,
    reset_progress: bool = False,
) -> dict[str, Any]:
    """Create a converted copy of ``project`` and return a JSON-safe summary."""
    plan = conversion_plan(
        project,
        target,
        name=name,
        output=output,
        orientation=orientation,
        mode=mode,
        window_mode=window_mode,
        resizable=resizable,
        width=width,
        height=height,
        reset_progress=reset_progress,
    )
    if not plan["has_changes"]:
        raise ValueError(
            "Все выбранные параметры совпадают с исходным проектом. "
            "Измените платформу, имя, ориентацию, окно, режим агента или сбросьте прогресс."
        )

    target_root: Path = plan["target_root"]
    target_root.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(project.root, target_root, ignore=_copy_ignore)
        stamp = now_iso()
        record = {
            "at": stamp,
            "from": {
                "name": project.name,
                "platform": plan["source_platform"],
                "path": str(project.root),
            },
            "to": {
                "name": plan["target_name"],
                "platform": plan["target"],
            },
            "changes": plan["changes"],
            "engine_version": VERSION,
        }
        manifest = dict(project.manifest)
        manifest["name"] = plan["target_name"]
        manifest["slug"] = slugify(plan["target_name"], "project")
        manifest["platform"] = plan["target"]
        manifest["orientation"] = plan["orientation"]
        manifest["mode"] = plan["mode"]
        manifest["engine_version"] = VERSION
        manifest["window"] = {
            **project.window,
            "width": plan["width"],
            "height": plan["height"],
            "title": plan["target_name"],
            "mode": plan["window_mode"],
            "resizable": plan["resizable"],
        }
        manifest["android"] = plan["android"]
        history = manifest.get("conversions")
        history = history if isinstance(history, list) else []
        history.append(record)
        manifest["conversions"] = history[-20:]
        manifest["converted_from"] = {
            "name": project.name,
            "platform": plan["source_platform"],
            "path": str(project.root),
            "at": stamp,
        }

        converted = Project(root=target_root, manifest=manifest)
        if plan["target_name"] != project.name:
            _rename_sources(target_root, project.name, plan["target_name"])
        converted.save()

        from .scaffold import vendor_engine

        # Android's python-for-android rebuilds bytecode on the device and needs
        # importable source; Windows projects keep the protected runtime.
        vendor_engine(target_root, protected=False if converted.platform == "android" else None)

        from reasonable.ai.external import generate_agent_pack

        generate_agent_pack(converted)
        _update_progress(converted, plan)
        _write_conversion_doc(converted, plan, record)
        converted.save()
    except Exception:
        shutil.rmtree(target_root, ignore_errors=True)
        raise

    return {
        "ok": True,
        "path": str(target_root),
        "name": plan["target_name"],
        "platform": plan["target"],
        "source": str(project.root),
        "source_platform": plan["source_platform"],
        "orientation": plan["orientation"],
        "mode": plan["mode"],
        "window_mode": plan["window_mode"],
        "width": plan["width"],
        "height": plan["height"],
        "reset_progress": plan["reset_progress"],
        "changes": plan["changes"],
        "message": (
            f"Новый проект создан: {target_root}. "
            f"{PLATFORM_NAMES[plan['source_platform']]} → {PLATFORM_NAMES[plan['target']]}."
        ),
    }
