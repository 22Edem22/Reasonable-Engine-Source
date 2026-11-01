"""Create a complete, self-contained Reasonable Engine project.

A generated project contains the game/app source, its assets, a copy of the
runtime in ``_engine/``, shared progress files, and instructions for both the
built-in and external AI agents. Nothing else is required to run it.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any

from reasonable.version import VERSION

from .paths import atomic_write_text, now_iso, slugify
from .progress import ensure_state, record_event, set_plan, set_status

# Folders that are not needed inside a project (the editor itself is PySide6).
_VENDOR_SKIP = {"editor", "templates", "__pycache__", ".pytest_cache"}


def vendor_engine(project_root: Path, *, protected: bool | None = None) -> Path:
    """Copy the runtime package into ``<project>/_engine/reasonable``.

    Frozen builds vendor a bytecode-only runtime when it is available, so the
    engine source is not shipped inside every project. Android exports can pass
    ``protected=False`` because python-for-android rebuilds the bytecode for the
    device and needs importable source files.
    """
    from .paths import engine_source_dir, protected_engine_available

    if protected is None:
        protected = protected_engine_available()
    source = engine_source_dir(protected=protected)
    has_bytecode = any(source.rglob("*.pyc"))
    target = Path(project_root) / "_engine" / "reasonable"
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    target.parent.mkdir(parents=True, exist_ok=True)

    def ignore(directory: str, names: list[str]) -> set[str]:
        ignored = set()
        for name in names:
            if name in _VENDOR_SKIP:
                ignored.add(name)
            elif name.endswith((".pyc", ".pyo")) and not protected:
                ignored.add(name)
            elif protected and name.endswith(".py") and has_bytecode:
                # Keep the protected tree bytecode-only; a plain .py would
                # defeat the purpose and could shadow the compiled module.
                ignored.add(name)
            elif name == "__pycache__":
                ignored.add(name)
        return ignored

    shutil.copytree(source, target, ignore=ignore)
    return target.parent


def _replace_tokens(text: str, project) -> str:
    window = project.manifest.get("window") or {}
    return (
        text.replace("__APP_NAME_REPR__", repr(project.name))
        .replace("__APP_TITLE__", project.name)
        .replace("__WINDOW_WIDTH__", str(int(window.get("width", 1280))))
        .replace("__WINDOW_HEIGHT__", str(int(window.get("height", 720))))
        .replace("__WINDOW_FULLSCREEN__", "True" if project.fullscreen else "False")
        .replace("__WINDOW_RESIZABLE__", "True" if project.resizable else "False")
    )


def _fallback_icon(path: Path, accent=(217, 119, 87)) -> None:
    try:
        from PIL import Image, ImageDraw

        image = Image.new("RGBA", (512, 512), (15, 17, 21, 255))
        draw = ImageDraw.Draw(image)
        draw.ellipse((52, 52, 460, 460), fill=(23, 26, 32, 255), outline=(122, 110, 101, 220), width=8)
        draw.ellipse((176, 176, 336, 336), fill=(231, 233, 236, 255))
        draw.ellipse((212, 212, 300, 300), fill=accent + (255,))
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path, "PNG")
    except Exception:
        pass


def _generate_assets(project) -> None:
    assets = project.root / "assets"
    (assets / "sprites").mkdir(parents=True, exist_ok=True)
    (assets / "backgrounds").mkdir(parents=True, exist_ok=True)
    (assets / "audio").mkdir(parents=True, exist_ok=True)
    icon_path = assets / "icon.png"
    goal = project.goal or project.name
    try:
        from reasonable.ai.sprites import generate_icon

        generate_icon(
            f"glowing star symbol for {goal}",
            icon_path,
            size=512,
            image_config={"provider": "procedural"},
        )
    except Exception:
        _fallback_icon(icon_path)
    # A pure-tkinter project needs no pygame artwork: no background and no
    # sprites, so the project never ships files its interface level never uses.
    if project.ui_levels == ["simple"]:
        return
    background_path = assets / "background.png"
    try:
        from reasonable.ai.sprites import generate_background

        generate_background(
            f"atmospheric game landscape for {goal}",
            background_path,
            width=int((project.manifest.get("window") or {}).get("width", 1280)),
            height=int((project.manifest.get("window") or {}).get("height", 720)),
            image_config={"provider": "procedural"},
        )
    except Exception:
        pass
    try:
        from reasonable.ai.sprites import generate_sprite

        generate_sprite(
            f"friendly hero character for {goal}",
            assets / "sprites" / "player.png",
            style=project.manifest.get("ai", {}).get("image_style", "flat"),
            size=256,
            image_config={"provider": "procedural"},
        )
        generate_sprite(
            "gold star collectible",
            assets / "sprites" / "star.png",
            style="flat",
            size=128,
            image_config={"provider": "procedural"},
        )
        generate_sprite(
            "green slime enemy creature",
            assets / "sprites" / "slime.png",
            style="flat",
            size=128,
            image_config={"provider": "procedural"},
        )
    except Exception:
        pass


def _write_readme(project) -> None:
    goal = project.goal or "Цель пока не описана — добавьте её в настройках проекта."
    notes = project.notes or "Первая задача агенту пишется уже после создания проекта — в разделе «ИИ-агент»."
    project_type = "игра" if project.project_type == "game" else "приложение"
    from .project import UI_LEVEL_LABELS

    levels_text = ", ".join(UI_LEVEL_LABELS.get(level, level) for level in project.ui_levels)
    readme = f"""# {project.name}

{goal}

> {project_type.capitalize()}, созданный в **Reasonable Engine {VERSION}**.
> Режим разработки: **{'встроенный ИИ-агент' if project.mode == 'builtin' else 'внешний ИИ-агент'}**.
> Уровень интерфейса: **{levels_text}**.

## Быстрый запуск

```bat
run.bat
```

или

```bash
python main.py
```

Перед проектом всегда проигрывается заставка Reasonable Engine — она является
частью движка, и отключить её нельзя.

## Первая задача агенту

Проект уже создан, но первый промпт не записан заранее. Откройте проект в
редакторе Reasonable Engine → раздел **«ИИ-агент»** и опишите первую задачу
обычными словами. Внешний агент получает тот же текст через кнопку копирования
в панели подключения. Это позволяет сначала увидеть проект, а потом решить,
с чего начать.

## Окно

Размер и режим окна выбирает ИИ-агент под задачу проекта — специальные
настройки не требуются. `F11` переключает полноэкранный режим в любой момент.

## Заметки и требования

{notes}

## Структура

```
{project.name}/
├─ main.py              точка входа
├─ project.json         настройки проекта
├─ assets/              спрайты, фоны, иконка, звуки
├─ progress/            общий прогресс для редактора и агентов
├─ _engine/reasonable/  встроенная копия движка
├─ AGENT_GUIDE.md       инструкция для ИИ-агента
├─ skills/              навыки агента
├─ re.bat / re.sh       CLI для внешнего агента
└─ README.md
```

## Разработка с ИИ

- Встроенный агент: откройте проект в Reasonable Engine → «ИИ-агент».
- Внешний агент: прочитайте `AGENT_GUIDE.md`, подключите Claude Code, Codex,
  Cursor, Cline, Windsurf или другой агент к папке проекта. Прогресс появится
  в редакторе автоматически.

Полезные команды:

```bat
re.bat status
re.bat plan "Собрать меню" "Добавить уровни" "Проверить сборку"
re.bat task t1 in_progress
re.bat event "Готов экран меню"
re.bat validate
re.bat sprite "магический кристалл" assets/sprites/crystal.png
re.bat export android
```

## Управление

- Мышь / касания — интерфейс.
- `F11` — полноэкранный режим.
- `Esc` — пауза или выход из меню.

## Экспорт

В редакторе: **Экспорт**. Доступны папка Windows, самодостаточный `.exe`
(PyInstaller) и Android-пакет (python-for-android/buildozer + инструкция).
Android-сборка выполняется на Linux/WSL, потому что buildozer не работает на
Windows напрямую.

Сам редактор Reasonable Engine тоже можно собрать в `.exe` из корня движка:
`build_exe.bat` или `python tools/build_editor_exe.py`.
"""
    atomic_write_text(project.root / "README.md", readme)


def _write_launchers(project) -> None:
    atomic_write_text(
        project.root / "re.bat",
        """@echo off
setlocal
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "HERE=%~dp0"
set "ROOT=%HERE:~0,-1%"
set "PYTHONPATH=%HERE%_engine;%ROOT%;%PYTHONPATH%"
call :find_python
"%PY%" -m reasonable.cli --project "%ROOT%" %*
exit /b %ERRORLEVEL%

:find_python
set "PY=%REASONABLE_PYTHON%"
if not defined PY if exist "%HERE%..\\python\\python.exe" set "PY=%HERE%..\\python\\python.exe"
if not defined PY if exist "%HERE%..\\..\\python\\python.exe" set "PY=%HERE%..\\..\\python\\python.exe"
if not defined PY if exist "%HERE%..\\runtime\\python\\python.exe" set "PY=%HERE%..\\runtime\\python\\python.exe"
if not defined PY if exist "%HERE%..\\..\\runtime\\python\\python.exe" set "PY=%HERE%..\\..\\runtime\\python\\python.exe"
if not defined PY if exist "%HERE%..\\..\\..\\runtime\\python\\python.exe" set "PY=%HERE%..\\..\\..\\runtime\\python\\python.exe"
if not defined PY set "PY=python"
exit /b 0
""",
    )
    atomic_write_text(
        project.root / "re.sh",
        """#!/usr/bin/env bash
set -e
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="$HERE/_engine:$HERE:${PYTHONPATH:-}"
exec "${REASONABLE_PYTHON:-python3}" -m reasonable.cli --project "$HERE" "$@"
""",
    )
    try:
        os.chmod(project.root / "re.sh", 0o755)
    except OSError:
        pass
    atomic_write_text(
        project.root / "run.bat",
        """@echo off
setlocal
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "HERE=%~dp0"
set "ROOT=%HERE:~0,-1%"
set "PYTHONPATH=%HERE%_engine;%ROOT%;%PYTHONPATH%"
cd /d "%ROOT%"
call :find_python
"%PY%" main.py
if errorlevel 1 pause
exit /b %ERRORLEVEL%

:find_python
set "PY=%REASONABLE_PYTHON%"
if not defined PY if exist "%HERE%..\\python\\python.exe" set "PY=%HERE%..\\python\\python.exe"
if not defined PY if exist "%HERE%..\\..\\python\\python.exe" set "PY=%HERE%..\\..\\python\\python.exe"
if not defined PY if exist "%HERE%..\\runtime\\python\\python.exe" set "PY=%HERE%..\\runtime\\python\\python.exe"
if not defined PY if exist "%HERE%..\\..\\runtime\\python\\python.exe" set "PY=%HERE%..\\..\\runtime\\python\\python.exe"
if not defined PY if exist "%HERE%..\\..\\..\\runtime\\python\\python.exe" set "PY=%HERE%..\\..\\..\\runtime\\python\\python.exe"
if not defined PY set "PY=python"
exit /b 0
""",
    )
    atomic_write_text(
        project.root / "run.sh",
        """#!/usr/bin/env bash
set -e
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="$HERE/_engine:$HERE:${PYTHONPATH:-}"
cd "$HERE"
exec "${REASONABLE_PYTHON:-python3}" main.py
""",
    )
    try:
        os.chmod(project.root / "run.sh", 0o755)
    except OSError:
        pass


def _write_support_files(project) -> None:
    atomic_write_text(
        project.root / ".gitignore",
        """# Reasonable Engine / Python
__pycache__/
*.pyc
.venv/
venv/
dist/
build/
.reasonable/
.progress.tmp
progress/*.tmp
data.json
ai_config.json
""",
    )
    atomic_write_text(
        project.root / "ai_config.example.json",
        """{
  "base_url": "https://openrouter.ai/api/v1",
  "model": "meta-llama/llama-3.3-70b-instruct:free",
  "api_key": "",
  "system_prompt": "Ты — ИИ-ассистент приложения, созданного в Reasonable Engine.",
  "temperature": 0.6,
  "title": "ИИ-ассистент"
}
""",
    )
    try:
        window = project.manifest.get("window") or {}
        import pygame  # noqa: F401  (only to ensure a consistent placeholder size)
        from PIL import Image, ImageDraw

        for size, name in ((32, "icon_32.png"), (128, "icon_128.png")):
            icon = Image.open(project.root / "assets" / "icon.png").convert("RGBA")
            icon.resize((size, size), Image.Resampling.LANCZOS).save(project.root / "assets" / name)
    except Exception:
        pass


def _initial_plan(project) -> None:
    plan = [
        {"id": "t1", "title": "Изучить AGENT_GUIDE.md и структуру проекта", "status": "pending"},
        {"id": "t2", "title": "Спроектировать экраны и основной игровой цикл", "status": "pending"},
        {"id": "t3", "title": "Собрать рабочий вертикальный срез", "status": "pending"},
        {"id": "t4", "title": "Добавить контент, ассеты и полировку", "status": "pending"},
        {"id": "t5", "title": "Проверить запуск, сохранить прогресс и экспортировать", "status": "pending"},
    ]
    set_plan(project.root, plan)


def scaffold_project(project) -> None:
    project.root.mkdir(parents=True, exist_ok=True)
    for folder in (
        "assets",
        "assets/sprites",
        "assets/backgrounds",
        "assets/audio",
        "progress",
        ".reasonable",
    ):
        (project.root / folder).mkdir(parents=True, exist_ok=True)

    template_name = str(project.manifest.get("template") or project.project_type)
    if template_name not in {"game", "app", "blank", "simple"}:
        template_name = project.project_type
    # A project built only on the "simple (tkinter)" level uses the tkinter
    # template and never receives pygame artwork or widget skills.
    if template_name in {"game", "app"} and project.ui_levels == ["simple"]:
        template_name = "simple"
    from .paths import TEMPLATES_DIR

    template_main = TEMPLATES_DIR / template_name / "main.py"
    if template_main.exists():
        source = template_main.read_text(encoding="utf-8")
        atomic_write_text(project.entry, _replace_tokens(source, project))
    else:
        atomic_write_text(
            project.entry,
            '"""Generated project."""\n\nfrom reasonable.runtime import Game\n\n'
            f'class Project(Game):\n    pass\n\nProject("{project.name}", (960, 540)).run()\n',
        )

    _generate_assets(project)
    _write_readme(project)
    _write_launchers(project)
    _write_support_files(project)
    project.manifest["engine_version"] = VERSION
    project.save()

    ensure_state(project.root, project.mode)
    _initial_plan(project)
    set_status(project.root, "idle", "Проект создан. Опишите задачу агенту.")
    record_event(project.root, "created", f"Проект «{project.name}» создан в Reasonable Engine.", {"mode": project.mode})

    try:
        from reasonable.ai.external import generate_agent_pack

        generate_agent_pack(project)
    except Exception as exc:
        try:
            atomic_write_text(
                project.root / "AGENT_GUIDE.md",
                f"# AGENT_GUIDE\n\nНе удалось сгенерировать расширенную инструкцию: {exc}\n",
            )
        except OSError:
            pass

    try:
        vendor_engine(project.root)
    except Exception as exc:
        print(f"[Reasonable] Не удалось встроить движок в проект: {exc}", file=sys.stderr)
