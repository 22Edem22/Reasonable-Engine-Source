"""Create a complete, self-contained Reasonable Engine project.

A generated project contains the game/app source, its assets, a copy of the
runtime in ``_engine/``, shared progress files, and instructions for both the
built-in and external AI agents. Nothing else is required to run it.
"""

from __future__ import annotations

import math
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from reasonable.version import VERSION_LABEL

from .i18n import current_language, tr
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


def _wants_platformer(project) -> bool:
    """Use the platformer starter when the user explicitly asks for one."""
    text = f"{project.name} {getattr(project, 'goal', '')}".lower()
    hints = (
        "platformer",
        "platform game",
        "платформер",
        "платформенн",
        "прыжк",
        "уровни с платформ",
    )
    return any(hint in text for hint in hints)


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


def _starter_hero_shapes() -> list[dict]:
    return [
        {"type": "ellipse", "center": [50, 91], "radius": [28, 6], "fill": "#00000033"},
        {"type": "ellipse", "center": [18, 67], "radius": [7, 12], "fill": "#2F6FE4", "outline": "#14213D", "outline_width": 2},
        {"type": "ellipse", "center": [82, 67], "radius": [7, 12], "fill": "#2F6FE4", "outline": "#14213D", "outline_width": 2},
        {"type": "ellipse", "center": [50, 68], "radius": [27, 24], "fill": "#3F86FF", "outline": "#14213D", "outline_width": 2.2},
        {"type": "ellipse", "center": [50, 33], "radius": [23, 21], "fill": "#FFD1A6", "outline": "#14213D", "outline_width": 2.2},
        {"type": "arc", "box": [26, 10, 74, 48], "start": 180, "end": 360, "width": 5, "fill": "#3A2418"},
        {"type": "ellipse", "center": [42, 33], "radius": [3, 4], "fill": "#14213D"},
        {"type": "ellipse", "center": [58, 33], "radius": [3, 4], "fill": "#14213D"},
        {"type": "arc", "box": [43, 37, 57, 46], "start": 20, "end": 160, "width": 1.6, "fill": "#14213D"},
    ]


def _starter_star_shapes() -> list[dict]:
    points = []
    for index in range(20):
        angle = -90 + index * 18
        radius = 40 if index % 2 == 0 else 17
        points.append([50 + radius * math.cos(math.radians(angle)), 50 + radius * math.sin(math.radians(angle))])
    return [
        {"type": "polygon", "points": points, "fill": "#FFD447", "outline": "#6B4A12", "outline_width": 2.5},
        {"type": "ellipse", "center": [42, 39], "radius": [7, 9], "fill": "#FFF3B0", "opacity": 0.8},
    ]


def _starter_slime_shapes() -> list[dict]:
    return [
        {"type": "ellipse", "center": [50, 88], "radius": [30, 6], "fill": "#00000030"},
        {"type": "ellipse", "center": [50, 58], "radius": [34, 30], "fill": "#55D96B", "outline": "#173A21", "outline_width": 2.5},
        {"type": "ellipse", "center": [38, 47], "radius": [12, 8], "fill": "#B7F7C0", "opacity": 0.75},
        {"type": "ellipse", "center": [40, 58], "radius": [4, 5], "fill": "#173A21"},
        {"type": "ellipse", "center": [60, 58], "radius": [4, 5], "fill": "#173A21"},
        {"type": "arc", "box": [43, 64, 57, 74], "start": 20, "end": 160, "width": 1.8, "fill": "#173A21"},
    ]


def _generate_assets(project) -> None:
    assets = project.root / "assets"
    (assets / "sprites").mkdir(parents=True, exist_ok=True)
    (assets / "backgrounds").mkdir(parents=True, exist_ok=True)
    (assets / "audio").mkdir(parents=True, exist_ok=True)
    icon_path = assets / "icon.png"
    goal = project.goal or project.name
    _fallback_icon(icon_path)
    # A pure-tkinter project needs no pygame artwork: no background and no
    # sprites, so the project never ships files its interface level never uses.
    if project.ui_levels == ["simple"]:
        return
    background_path = assets / "background.png"
    try:
        from reasonable.ai.sprites import procedural_background

        image, _meta = procedural_background(
            f"atmospheric game landscape for {goal}",
            width=int((project.manifest.get("window") or {}).get("width", 1280)),
            height=int((project.manifest.get("window") or {}).get("height", 720)),
        )
        image.save(background_path, "PNG")
    except Exception:
        pass
    try:
        from reasonable.ai.drawing import draw_sprite

        # Starter art for the sample game only. Each object is drawn from its
        # own description; the agent replaces these assets as soon as the user's
        # real task starts.
        draw_sprite(assets / "sprites" / "player.png", shapes=_starter_hero_shapes(), size=256)
        draw_sprite(assets / "sprites" / "star.png", shapes=_starter_star_shapes(), size=128)
        draw_sprite(assets / "sprites" / "slime.png", shapes=_starter_slime_shapes(), size=128)
    except Exception:
        pass


def _copy_site_tree(project) -> None:
    """Copy the website starter (HTML/CSS/JS) into the project's site/ folder."""
    from .paths import TEMPLATES_DIR

    source = TEMPLATES_DIR / "site" / "site"
    target = project.root / "site"
    if not source.is_dir():
        return
    text_suffixes = {".html", ".css", ".js", ".md", ".json", ".txt", ".svg"}
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        destination = target / relative
        if path.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix.lower() in text_suffixes:
            atomic_write_text(
                destination,
                _replace_tokens(path.read_text(encoding="utf-8", errors="replace"), project),
            )
        else:
            shutil.copy2(path, destination)


def _write_readme(project) -> None:
    if project.project_type in {"site", "other"}:
        _write_simple_readme(project)
        return
    if current_language() == "en":
        goal = project.goal or "The goal is not described yet — add it in the project settings."
        notes = project.notes or "The first task for the agent is written after the project is created — in the “AI agent” section."
        project_type = "game" if project.project_type == "game" else "app"
        from .project import UI_LEVEL_LABELS

        levels_text = ", ".join(UI_LEVEL_LABELS.get(level, level) for level in project.ui_levels)
        starter = str(project.manifest.get("template") or project.project_type)
        starter_section = ""
        if starter == "platformer" and project.ui_levels != ["simple"]:
            starter_section = """## What is already built

The project starts as a working platformer: tile collisions, a following
camera, double jump, dash, coins, spikes and a goal. Extend this base instead
of rewriting physics and the game loop from scratch.

"""
        elif starter in {"game", "app"} and project.ui_levels != ["simple"]:
            starter_section = """## What is already built

The starter is not an empty window — it is a working product you can play or
use right away:

- **Game**: title menu, how-to-play screen, enemy waves, combo multiplier,
  invulnerable dash, four power-ups, procedural sound, saved high score and a
  results screen. Mouse, keyboard and an on-screen joystick all work.
- **App**: task planner with priorities, tags, search, sorting, weekly
  statistics, a day streak, undo-delete and a context-aware AI assistant. Data
  is stored in `data.json` next to the project.

"""
        readme = f"""# {project.name}

{goal}

> A {project_type} built with **Reasonable Engine {VERSION_LABEL}**.
> Development mode: **{'built-in AI agent' if project.mode == 'builtin' else 'external AI agent'}**.
> Interface level: **{levels_text}**.

## Quick start

```bat
run.bat
```

or

```bash
python main.py
```

The Reasonable Engine splash always plays before the project — it is part of
the engine and cannot be disabled.

{starter_section}## First task for the agent

The project is created, but the first prompt is not written in advance. Open
the project in the Reasonable Engine editor → the **“AI agent”** section and
describe the first task in plain words. An external agent receives the same
text via the copy button in the connection panel. This lets you see the project
first and then decide where to start.

## Window

The AI agent picks the window size and mode for the project's task — no special
settings are required. `F11` toggles fullscreen at any moment.

## Notes and requirements

{notes}

## Structure

```
{project.name}/
├─ main.py              entry point
├─ project.json         project settings
├─ assets/              sprites, backgrounds, icon, sounds
├─ scenes/              visual scenes (main.json = starter level)
├─ progress/            shared progress for the editor and agents
├─ _engine/reasonable/  bundled copy of the engine
├─ AGENT_GUIDE.md       instructions for the AI agent
├─ skills/              agent skills
├─ re.bat / re.sh       CLI for the external agent
└─ README.md
```

## Development with AI

- Built-in agent: open the project in Reasonable Engine → “AI agent”.
- External agent: read `AGENT_GUIDE.md`, connect Claude Code, Codex, Cursor,
  Cline, Windsurf or another agent to the project folder. Progress appears
  in the editor automatically.

Useful commands:

```bat
re.bat status
re.bat plan "Build the menu" "Add levels" "Check the build"
re.bat task t1 in_progress
re.bat event "Menu screen is done"
re.bat validate
re.bat sprite "magic crystal" assets/sprites/crystal.png
re.bat export android
```

## Controls

- Mouse / touches — interface.
- `F11` — fullscreen.
- `Esc` — pause or exit the menu.

## Export

In the editor: **Export**. Available: a Windows folder, a self-contained `.exe`
(PyInstaller) and an Android package (python-for-android/buildozer + guide).
Android builds run on Linux/WSL because buildozer does not work on Windows
directly.

The Reasonable Engine editor itself can also be built into an `.exe` from the
engine root: `build_exe.bat` or `python tools/build_editor_exe.py`.
"""
        atomic_write_text(project.root / "README.md", readme)
        return
    goal = project.goal or "Цель пока не описана — добавьте её в настройках проекта."
    notes = project.notes or "Первая задача агенту пишется уже после создания проекта — в разделе «ИИ-агент»."
    project_type = "игра" if project.project_type == "game" else "приложение"
    from .project import UI_LEVEL_LABELS

    levels_text = ", ".join(UI_LEVEL_LABELS.get(level, level) for level in project.ui_levels)
    starter = str(project.manifest.get("template") or project.project_type)
    starter_section = ""
    if starter == "platformer" and project.ui_levels != ["simple"]:
        starter_section = """## Что уже готово

Проект начинается как рабочий платформер: тайловые коллизии, камера,
двойной прыжок, дэш, монеты, шипы и финиш. Расширяйте эту основу, а не
переписывайте физику и игровой цикл с нуля.

"""
    elif starter in {"game", "app"} and project.ui_levels != ["simple"]:
        starter_section = """## Что уже готово

Стартовый пример — не пустое окно, а рабочий продукт, которым можно
пользоваться сразу:

- **Игра**: титульное меню, экран обучения, волны врагов, комбо-множитель,
  неуязвимый рывок, четыре бонуса, процедурный звук, сохранение рекорда и экран
  результатов. Работают мышь, клавиатура и экранный джойстик.
- **Приложение**: планировщик задач с приоритетами, тегами, поиском,
  сортировкой, недельной статистикой, серией дней, отменой удаления и
  контекстным ИИ-помощником. Данные хранятся в `data.json` рядом с проектом.

"""
    readme = f"""# {project.name}

{goal}

> {project_type.capitalize()}, созданный в **Reasonable Engine {VERSION_LABEL}**.
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

{starter_section}## Первая задача агенту

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
├─ scenes/              визуальные сцены (main.json — стартовый уровень)
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


def _write_simple_readme(project) -> None:
    """README for site/other projects: plain Python, no engine splash."""
    from reasonable.version import VERSION_LABEL

    is_site = project.project_type == "site"
    kind = tr("website", "сайт") if is_site else tr("Python project", "проект на Python")
    mode = (
        tr("built-in AI agent", "встроенный ИИ-агент")
        if project.mode == "builtin"
        else tr("external AI agent", "внешний ИИ-агент")
    )
    if is_site:
        structure = """```
{name}/
├─ main.py        local server and --check
├─ site/          index.html, styles.css, app.js and your pages
├─ project.json   project settings
├─ progress/      shared progress for the editor and agents
└─ README.md
```""".format(name=project.name)
        extra = tr(
            "Edit `site/index.html` and `site/styles.css`, add pages to `site/`, "
            "then run `python main.py` and open the printed URL. `python main.py --check` "
            "verifies that every page is served.",
            "Редактируйте `site/index.html` и `site/styles.css`, добавляйте страницы в "
            "`site/`, запускайте `python main.py` и открывайте напечатанный адрес. "
            "`python main.py --check` проверяет, что все страницы отдаются.",
        )
    else:
        structure = """```
{name}/
├─ main.py        entry point (python main.py)
├─ project.json   project settings
├─ progress/      shared progress for the editor and agents
└─ README.md
```""".format(name=project.name)
        extra = tr(
            "Replace the skeleton in `main.py` with the real program. Keep the "
            "`--check` flag working: the editor and the agent use it to verify the project.",
            "Замените заготовку в `main.py` реальной программой. Сохраните флаг "
            "`--check` — редактор и агент используют его для проверки проекта.",
        )
    goal = project.goal or tr("The goal is not described yet.", "Цель пока не описана.")
    atomic_write_text(
        project.root / "README.md",
        f"""# {project.name}

{goal}

> {kind.capitalize()} · built with **Reasonable Engine {VERSION_LABEL}**.
> Development mode: **{mode}**.

## Quick start

```bash
python main.py
```

{extra}

## Structure

{structure}

## Development with AI

- Built-in agent: open the project in Reasonable Engine → “AI agent”.
- External agent: read `AGENT_GUIDE.md` and connect any coding agent to the folder.

## Notes and requirements

{project.notes or tr("none", "нет")}
""",
    )


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
"%PY%" -m reasonable.runtime.launch main.py
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
exec "${REASONABLE_PYTHON:-python3}" -m reasonable.runtime.launch main.py
""",
    )
    try:
        os.chmod(project.root / "run.sh", 0o755)
    except OSError:
        pass
    if project.project_type in {"site", "other"}:
        # Plain Python projects must not import the pygame runtime or play the
        # engine splash: run the entry file directly.
        atomic_write_text(
            project.root / "run.bat",
            """@echo off
setlocal
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "HERE=%~dp0"
cd /d "%HERE%"
call :find_python
"%PY%" main.py %*
if errorlevel 1 pause
exit /b %ERRORLEVEL%

:find_python
set "PY=%REASONABLE_PYTHON%"
if not defined PY if exist "%HERE%..\\python\\python.exe" set "PY=%HERE%..\\python\\python.exe"
if not defined PY if exist "%HERE%..\\..\\python\\python.exe" set "PY=%HERE%..\\..\\python\\python.exe"
if not defined PY if exist "%HERE%..\\runtime\\python\\python.exe" set "PY=%HERE%..\\runtime\\python\\python.exe"
if not defined PY set "PY=python"
exit /b 0
""",
        )
        atomic_write_text(
            project.root / "run.sh",
            """#!/usr/bin/env bash
set -e
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
exec "${REASONABLE_PYTHON:-python3}" main.py "$@"
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
    ai_title = tr("AI assistant", "ИИ-ассистент")
    atomic_write_text(
        project.root / "ai_config.example.json",
        "{\n"
        '  "base_url": "https://openrouter.ai/api/v1",\n'
        '  "model": "meta-llama/llama-3.3-70b-instruct:free",\n'
        '  "api_key": "",\n'
        '  "system_prompt": "You are the AI assistant of an app built with Reasonable Engine. Reply in the language the user writes in.",\n'
        '  "temperature": 0.6,\n'
        f'  "title": "{ai_title}"\n'
        "}\n",
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
    if project.project_type == "site":
        titles = [
            tr("Read AGENT_GUIDE.md and the site structure", "Изучить AGENT_GUIDE.md и структуру сайта"),
            tr("Design the pages, navigation and content", "Спроектировать страницы, навигацию и контент"),
            tr("Build the responsive design system", "Собрать адаптивную дизайн-систему"),
            tr("Fill pages with real content and assets", "Наполнить страницы контентом и ассетами"),
            tr("Validate links, run the site and polish", "Проверить ссылки, запустить сайт и отполировать"),
        ]
    elif project.project_type == "other":
        titles = [
            tr("Read AGENT_GUIDE.md and the project structure", "Изучить AGENT_GUIDE.md и структуру проекта"),
            tr("Define the behaviour and the data model", "Определить поведение и модель данных"),
            tr("Build a minimal working version", "Собрать минимальную рабочую версию"),
            tr("Add the remaining features and edge cases", "Добавить остальные функции и крайние случаи"),
            tr("Test, document and finalize", "Проверить, документировать и завершить"),
        ]
    else:
        titles = [
            tr("Read AGENT_GUIDE.md and the project structure", "Изучить AGENT_GUIDE.md и структуру проекта"),
            tr("Design the screens and the main game loop", "Спроектировать экраны и основной игровой цикл"),
            tr("Build a working vertical slice", "Собрать рабочий вертикальный срез"),
            tr("Add content, assets and polish", "Добавить контент, ассеты и полировку"),
            tr("Check the launch, save progress and export", "Проверить запуск, сохранить прогресс и экспортировать"),
        ]
    plan = [
        {"id": f"t{index}", "title": title, "status": "pending"}
        for index, title in enumerate(titles, start=1)
    ]
    set_plan(project.root, plan)


def scaffold_project(project) -> None:
    project.root.mkdir(parents=True, exist_ok=True)
    plain = project.project_type in {"site", "other"}
    folders = (
        "assets",
        "progress",
        ".reasonable",
    )
    if not plain:
        folders += ("assets/sprites", "assets/backgrounds", "assets/audio", "scenes")
    elif project.project_type == "site":
        folders += ("site", "site/assets")
    for folder in folders:
        (project.root / folder).mkdir(parents=True, exist_ok=True)

    template_name = str(project.manifest.get("template") or project.project_type)
    if template_name == "game" and _wants_platformer(project):
        template_name = "platformer"
    if template_name not in {"game", "app", "blank", "simple", "site", "other", "platformer"}:
        template_name = project.project_type
    # A project built only on the "simple (tkinter)" level uses the tkinter
    # template and never receives pygame artwork or widget skills.
    if template_name in {"game", "app", "platformer"} and project.ui_levels == ["simple"]:
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

    if project.project_type == "site":
        _copy_site_tree(project)
    if not plain:
        _generate_assets(project)
    if template_name in {"game", "app", "platformer"}:
        try:
            from .scene import create_scene, list_scenes

            if not list_scenes(project.root):
                window = project.manifest.get("window") or {}
                size = (int(window.get("width") or 1280), int(window.get("height") or 720))
                is_game = template_name in {"game", "platformer"}
                create_scene(
                    project.root,
                    tr("Main level", "Главный уровень") if is_game else tr("Main screen", "Главный экран"),
                    size=size,
                    template="level" if is_game else "app",
                    identifier="main",
                )
        except Exception as exc:  # a broken starter scene must not block creation
            print(tr("[Reasonable] Could not create the starter scene: {error}", "[Reasonable] Не удалось создать стартовую сцену: {error}", error=exc), file=sys.stderr)
    _write_readme(project)
    _write_launchers(project)
    _write_support_files(project)
    project.manifest["engine_version"] = VERSION_LABEL
    project.save()

    ensure_state(project.root, project.mode)
    _initial_plan(project)
    set_status(project.root, "idle", tr("The project is created. Describe the task for the agent.", "Проект создан. Опишите задачу агенту."))
    record_event(project.root, "created", tr("Project “{name}” created in Reasonable Engine.", "Проект «{name}» создан в Reasonable Engine.", name=project.name), {"mode": project.mode})

    try:
        from reasonable.ai.external import generate_agent_pack

        generate_agent_pack(project)
    except Exception as exc:
        try:
            atomic_write_text(
                project.root / "AGENT_GUIDE.md",
                "# AGENT_GUIDE\n\n" + tr("Could not generate the extended guide: {error}", "Не удалось сгенерировать расширенную инструкцию: {error}", error=exc) + "\n",
            )
        except OSError:
            pass

    try:
        vendor_engine(project.root)
    except Exception as exc:
        print(tr("[Reasonable] Failed to vendor the engine into the project: {error}", "[Reasonable] Не удалось встроить движок в проект: {error}", error=exc), file=sys.stderr)
