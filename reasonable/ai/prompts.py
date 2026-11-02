"""Prompts, skills and documentation shared by both agent modes.

The built-in agent and external agents receive the same knowledge about the
engine, the same quality bar and the same progress protocol. Keeping this in one
module prevents the two modes from drifting apart.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from reasonable.version import VERSION_LABEL

from .prompts_en import (  # noqa: F401  (re-exported for existing imports)
    AGENT_LANGUAGE_RULE,
    ENGINE_API_GUIDE,
    EXTERNAL_CONNECTION_GUIDE,
    SKILLS,
    build_agent_system_prompt_body,
)


def skills_for_project(project) -> dict[str, str]:
    """Only the skills this project actually needs — no extra files.

    Base knowledge + a type-specific skill + one skill per selected interface
    level. A pure-tkinter project never receives the advanced-scenes skill and
    a game never receives the tkinter skill unless the user picked that level.
    """
    result: dict[str, str] = {}
    for name in ("engine-basics.md", "sprites-and-assets.md", "progress-and-handoff.md", "android-and-export.md"):
        if name in SKILLS:
            result[name] = SKILLS[name]
    type_skill = "game-development.md" if project.project_type == "game" else "app-development.md"
    if type_skill in SKILLS:
        result[type_skill] = SKILLS[type_skill]
    for level in project.ui_levels:
        skill = {"simple": "ui-simple-tkinter.md", "standard": "ui-standard-widgets.md", "advanced": "ui-advanced-scenes.md"}.get(level)
        if skill and skill in SKILLS:
            result[skill] = SKILLS[skill]
    return result


UI_LEVEL_LABELS_RU = {
    "simple": "простой (tkinter)",
    "standard": "стандартный (виджеты движка)",
    "advanced": "продвинутый (сцены и графика)",
}


def build_external_guide(project) -> str:
    kind = "игра" if project.project_type == "game" else "приложение"
    mode = "встроенный" if project.mode == "builtin" else "внешний"
    platform = "Android" if getattr(project, "platform", "windows") == "android" else "Windows"
    skills = "\n".join(f"- [`skills/{name}`](skills/{name})" for name in skills_for_project(project))
    levels = ", ".join(UI_LEVEL_LABELS_RU.get(level, level) for level in project.ui_levels)
    return f"""# AGENT_GUIDE — {project.name}

> Полная инструкция для внешнего ИИ-агента. Прочитайте её целиком перед первой
> правкой. Проект создан в **Reasonable Engine {VERSION_LABEL}**; режим: {mode} агент.

## 1. Что это за проект

- **Название:** {project.name}
- **Тип:** {kind}
- **Платформа:** {platform}
- **Уровень интерфейса:** {levels} — соответствующие навыки уже в `skills/`
{_conversion_note(project)}
- **Главная цель:** {project.goal or 'не указана'}
- **Окно:** размер и режим выбирает агент под задачу; пользователь эти
  настройки не видит. База — окно 1280×720 с изменением размера, F11 — полный экран.
- **Точка входа:** `{project.manifest.get('entry', 'main.py')}`
- **Папка:** `{project.root}`

Заметки пользователя:

```
{project.notes or 'нет'}
```

## 2. Твоя роль

Ты — автономный разработчик. Доведи проект до состояния, когда он запускается,
выглядит цельно и полностью выполняет цель. Не ограничивайся советами и
фрагментами: меняй файлы, создавай ассеты, проверяй результат.

Без этого движка проект сделать так же круто нельзя: виджеты, заставка,
камера, частицы, сохранения, генерация ассетов и проверка запуска — встроены.
Пользуйся ими (`reasonable.runtime`, `skills/`) вместо самодельных аналогов.

## 3. Обязательный рабочий цикл

1. **Изучи:** `project.json`, этот файл, `progress/state.json`, `main.py`,
   `assets/`, `skills/`. Не начинай писать код, пока не понял текущее состояние.
2. **Спланируй:** `re.bat plan "..." "..."` (или `re.sh`). Задачи должны быть
   конкретными и проверяемыми.
3. **Веди статусы:** `re.bat task t1 in_progress`, затем `done` после проверки.
4. **Пиши код небольшими этапами.** После каждого этапа запускай проект:
   `python main.py` (или headless-проверку ниже).
5. **Проверяй:** `re.bat validate`; исправляй ошибки до нуля.
6. **Сообщай прогресс:** `re.bat progress 45 "Готов игровой цикл"` и
   `re.bat event "Добавлен экран паузы"`. Редактор покажет это пользователю.
7. **Заверши:** `re.bat done "Что сделано, как запустить"` только после успешной
   проверки.

Headless-проверка (Windows PowerShell / cmd):

```bat
set SDL_VIDEODRIVER=dummy
set SDL_AUDIODRIVER=dummy
set RE_FRAMES=5
python main.py
```

(Заставка при headless-запуске завершается мгновенно сама.)

## 4. Правила

- Работай только внутри папки проекта. Не меняй `_engine/`, `progress/*.json`
  вручную и системные файлы.
- Не удаляй `project.json`, `assets/`, точку входа без необходимости.
- Не используй PySide6/PyQt; проект должен запускаться на pygame.
- Секреты и API-ключи не коммить и не записывай в код. Ключ пользователя
  хранится вне проекта; локальные модели работают без ключа.
- Не оставляй `TODO`, заглушек, неработающих кнопок и битых импортов.
- Сохраняй стиль существующего кода; комментарии — по делу, на русском или английском.
- Для больших файлов используй аккуратные правки, не перезаписывай чужую работу.

## 5. Инструменты

### CLI проекта

```bat
re.bat status
re.bat events
re.bat plan "Задача 1" "Задача 2"
re.bat task t1 in_progress
re.bat task t1 done
re.bat progress 40 "Этап"
re.bat event "Сообщение"
re.bat validate
re.bat run
re.bat sprite "green slime, cute" assets/sprites/slime.png --style flat --size 256
re.bat bg "neon city" assets/background.png --width 1280 --height 720
re.bat export windows
re.bat export android
re.bat sync-engine
re.bat done "Итог"
```

### Встроенный агент (если пользователь работает в редакторе)

Он может читать/писать файлы, запускать команды, генерировать спрайты и фоны,
менять план и прогресс. Твои изменения в файлах он увидит; не запускай
одновременно с ним разрушительные операции.

### Генерация спрайтов

Всегда генерируй ассеты в `assets/`. Стили: `flat`, `pixel`, `painterly`, `icon`.
Один объект на изображение, прозрачный фон, сильный силуэт. Проверяй PNG глазами
или по размеру/альфе. Не вставляй base64-картинки в код.

## 6. Навыки

Прочитай релевантные файлы перед работой:

{skills}

## 7. Архитектура и качество

- Игра: `Game` + `Scene`, ввод, HUD, пауза, проигрыш/победа, рестарт, сохранение,
  частицы/анимации, поддержка касаний.
- Приложение: `UIApp` + виджеты, навигация, пустые состояния, сохранение данных,
  адаптивная компоновка, полезный ИИ-ассистент.
- Заставка Reasonable Engine уже встроена — не заменяй её.
- Все пути к ассетам — от `Path(__file__).resolve().parent`, не от cwd.
- Целевые платформы: Windows и Android. Проверяй узкие экраны и касания.
- Производительность: 60 FPS на 1280×720; избегай создания Surface каждый кадр
  без кэша; ограничивай число частиц.

## 8. API движка

{ENGINE_API_GUIDE}

## 9. Передача работы

Перед завершением обнови `AGENT_TASKS.md`: что готово, что осталось, какие файлы
важны. Затем:

```bat
re.bat validate
re.bat done "Краткий итог для пользователя"
```

Если работу продолжит другой агент, он прочитает `AGENT_GUIDE.md`,
`progress/state.json` и `AGENT_TASKS.md`.
"""


EXTERNAL_CONNECTION_GUIDE = """# Подключение внешнего ИИ-агента

1. Откройте папку проекта в вашем ИИ-агенте (Claude Code, Codex CLI, Cursor,
   Cline, Windsurf, Aider…).
2. Вставьте готовый промпт из панели «ИИ-агент» в Reasonable Engine.
3. Следите за прогрессом в той же панели — агент обновляет его сам через `re.bat`.

Всё остальное (инструкции, навыки, API движка) агент читает в файлах проекта:
`AGENT_GUIDE.md`, `skills/`, `AGENTS.md`, `CLAUDE.md`.
"""


def build_agent_tasks(project) -> str:
    from reasonable.core.progress import read_state

    state = read_state(project.root)
    rows = []
    for task in state.get("tasks", []):
        mark = {"done": "[x]", "in_progress": "[>]", "skipped": "[-]"}.get(task.get("status"), "[ ]")
        rows.append(f"- {mark} **{task.get('title')}** — `{task.get('id')}` ({task.get('status')})")
    return f"""# AGENT_TASKS — {project.name}

Обновляется вручную или агентом. Машинный прогресс: `progress/state.json`.
Команды: `re.bat status`, `re.bat plan ...`, `re.bat task ...`.

## Текущий план

{chr(10).join(rows) or '- План пока пуст.'}

## Журнал

- {project.manifest.get('created_at', '')}: проект создан в Reasonable Engine.

## Заметки для следующего агента

- Что готово:
- Что дальше:
- Файлы, которые нельзя ломать: `main.py`, `project.json`, `assets/`.
"""
