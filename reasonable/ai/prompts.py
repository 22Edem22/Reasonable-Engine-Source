"""Prompts, skills and documentation shared by both agent modes.

The built-in agent and external agents receive the same knowledge about the
engine, the same quality bar and the same progress protocol. Keeping this in one
module prevents the two modes from drifting apart.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from reasonable.version import VERSION

ENGINE_API_GUIDE = r"""
# Reasonable Engine runtime — краткая карта API

Импорт:
```python
from reasonable.runtime import *
```

Runtime работает на pygame-ce/pygame и не зависит от PySide6. Игры и приложения
запускаются на Windows и Android из одного и того же кода.

## Приложение и сцены

```python
class MyGame(Game):
    def __init__(self):
        super().__init__("Название", (1280, 720), splash=True)
    def on_start(self):
        self.set_scene(MenuScene(self))

class MenuScene(Scene):
    def __init__(self, game):
        super().__init__(game, gradient=((10, 16, 30), (24, 36, 58)),
                         camera_pos=(640, 360))
    def on_enter(self): ...
    def handle_event(self, event): ...
    def update(self, dt): ...
```

`Game`: `input`, `set_scene`, `push_scene`, `pop_scene`, `change_scene`, `size`,
`clock`, `toggle_fullscreen`, `quit`.
`Scene`: `add(node)`, `remove`, `find`, `find_all`, `closest`, `camera`,
`tweens`, `particles`, `burst`, `shake`, `time`, `ui`.

Заставка Reasonable Engine включается автоматически (`splash=True`) и
проигрывается перед игрой/приложением. `RE_SKIP_SPLASH=1` отключает её для тестов.
`F11` — полноэкранный режим. Базовый размер, `window.mode` и `window.resizable`
читаются из `project.json`; шаблоны уже делают это и не требуют правки кода при
изменении настроек окна.

## Спрайты и графика

```python
player = Sprite("assets/sprites/player.png", 100, 200, scale=1.0, anchor=(0.5, 0.5))
scene.add(player)
player.pos = (300, 200); player.angle = 15; player.flip_x = True
player.tint = (255, 120, 100); player.shadow = True
frames = ["assets/sprites/run1.png", "assets/sprites/run2.png"]
runner = scene.add(AnimatedSprite(frames, 100, 300, fps=10, loop=True))
```

`Node`: `x`, `y`, `pos`, `angle`, `scale`, `visible`, `alpha`, `z`, `tags`,
`kill()`. `Sprite.rect` — прямоугольник для коллизий. `collide(other)`.
`Text`, `Shape` (`rect`, `circle`, `line`, `polygon`). `make_circle_surface`,
`make_rect_surface`, `ParticleSystem`, `TweenManager`.
Полезно: `render_text`, `draw_wrapped_text`, `draw_glow`, `draw_gradient`,
`draw_rounded_rect`, `load_image`, `with_alpha`, `mix`, `get_font`,
`ease_out_cubic`, `ease_out_back`, `clamp`, `lerp`.

Камера: `scene.camera.pos`, `zoom`, `target`, `smooth`, `bounds`,
`shake(force, time)`, `world_to_screen`.

## Ввод и мобильные устройства

`game.input`: `action_down("left")`, `action_pressed`, `vector()`,
`normalized_vector()`, `mouse_pressed()`, `key_pressed(pygame.K_SPACE)`.
Действия по умолчанию: left/right/up/down/action/confirm/cancel/pause/run.

```python
joystick = VirtualJoystick(radius=70)
joystick.place(self.camera.screen_size)
def handle_event(self, event):
    if joystick.handle_event(event): return True
def update(self, dt):
    joystick.update(dt)
    move = joystick.vector if joystick.active else game.input.normalized_vector()
```
`TouchButton(center, radius, label, accent)` — круглая кнопка с `pressed_once`.

## Звук и сохранения

`Audio.play("assets/audio/hit.wav")`, `Audio.music(path, volume, loop=True)`,
`play_sound(path)`. `SaveData(app_name, "save.json")`: `get/set/save/reset`.

## UI-приложения (десктопный стиль)

```python
class NotesApp(UIApp):
    def build_ui(self):
        root = Panel(padding=24, spacing=14)
        root.add(Label("Заметки", size=32, bold=True, display=True))
        row = HStack(spacing=10, align_y="center")
        entry = Entry("Новая заметка", on_submit=lambda _v: self.add())
        row.add(entry, Button("Добавить"))
        root.add(row)
        col = VStack(spacing=8)
        col.add(Label("Первая заметка"))
        root.add(ScrollView(col, expand_y=True))
        self.root = root
        return root

NotesApp("Notes", (1100, 720)).run()
```

Доступные виджеты: `Panel`, `VStack`, `HStack`, `Grid`, `Label`, `Button`,
`IconButton`, `Entry`, `Toggle`, `Slider`, `ProgressBar`, `ScrollView`, `Tabs`,
`ImageWidget`, `Icon`, `Badge`, `Avatar`, `Divider`, `Spacer`, `Card`.
`UIApp` сам вызывает `layout` каждый кадр. `Theme` настраивает цвета/радиусы:
`UIApp(..., theme=Theme())` или меняйте поля `Theme` до создания окна.
Кнопки: `variant="primary" | "secondary" | "ghost" | "danger"`.
`ScrollView(content, expand_y=True, stick_to_bottom=True)`.
События обрабатываются автоматически; для своих виджетов наследуйте `Widget`,
реализуйте `measure`, `draw`, `handle_event`.

## ИИ внутри приложения

```python
from reasonable.runtime import AIChatPanel, AIConfig, AIClient
panel = AIChatPanel(AIConfig.load("Моё приложение"), app_name="Моё приложение")
root.add(panel)
```
`AIChatPanel` — готовый чат с настройкой endpoint/ключа. `AIClient(config).chat(messages)`.
Ключи хранятся локально у пользователя. Без ключа работают только локальные
модели (Ollama/LM Studio).
Используйте ИИ для генерации текста, подсказок, анализа данных, а не для отрисовки
каждого кадра.

## Ассеты и пути

Всегда используйте абсолютный путь от корня проекта:
```python
from pathlib import Path
PROJECT_DIR = Path(__file__).resolve().parent
def asset(name): return PROJECT_DIR / "assets" / name
```
Не полагайтесь на текущую рабочую директорию. Не удаляйте `assets/`,
`project.json`, `progress/`, `_engine/`.

## Качество

- Читаемая архитектура: сцены/экраны, данные и переиспользуемые виджеты.
- Плавная анимация, аккуратная типографика, согласованная палитра.
- Адаптивность: окно можно менять, на Android — касания и safe margins.
- Никаких заглушек «TODO» в готовом экране; каждая кнопка должна работать.
- Запускайте `python main.py` и проверяйте результат после крупных изменений.
- Для тестов без окна: `SDL_VIDEODRIVER=dummy RE_SKIP_SPLASH=1 RE_FRAMES=3 python main.py`.

## Ограничения

- Не используйте PySide6/PyQt в проекте: только `reasonable.runtime` + pygame.
- Pillow допустим для генерации ассетов, но не нужен в рантайме игры.
- Android: buildozer/python-for-android; не используйте Windows-специфичные API в игре.
- Python 3.10+. Не редактируйте `_engine/`: при необходимости обновите его
  командой `re.bat sync-engine`.
"""


AGENT_SYSTEM_PROMPT = f"""
Ты — старший разработчик игр и приложений внутри Reasonable Engine {VERSION}.
Твоя задача — доводить проект до работающего, красивого и целостного результата,
а не выдавать советы или фрагменты кода.

ГЛАВНЫЕ ПРАВИЛА
1. Работай только внутри папки проекта. Не трогай `_engine/` и системные файлы.
2. Сначала прочитай `project.json`, `AGENT_GUIDE.md`, `progress/state.json`,
   затем исследуй код и ассеты инструментами.
3. Составь план через инструмент `set_plan` и веди его: перед началом задачи —
   `update_task(..., "in_progress")`, после проверки — `"done"`.
4. Пиши полноценные файлы. Для больших изменений используй `write_file`, для
   точечных — `edit_file`. Не оставляй заглушек и синтаксических ошибок.
5. После каждого крупного этапа запускай `validate_project`, а затем `run_project`
   (короткий headless-прогон). Если есть ошибка — исправь и повтори.
6. Спрайты и фоны создавай инструментом `generate_sprite` / `generate_background`.
   Сначала пробуй удалённую модель (настройки изображений), при недоступности
   инструмент сам сделает офлайн-ассет; не рисуй десятки спрайтов вручную.
7. Обновляй прогресс через `report_progress` и заверши `finish` только когда
   проект запускается и задача действительно выполнена.
8. Общайся с пользователем по-русски, кратко. В финале перечисли, что сделано,
   как запустить и что можно улучшить дальше.
9. Если tool calling недоступен, верни ровно один JSON-объект в блоке ```json
   с полями "tool" и "arguments" — например
   {{"tool": "write_file", "arguments": {{"path": "notes.md", "content": "..."}}}}
   и жди результат. Не пиши такой JSON, если инструменты работают нативно.

КАЧЕСТВО
- Игры: понятная цель, управление, обратная связь, звук/частицы, экран паузы и
  проигрыша, сохранение рекорда, поддержка касаний.
- Приложения: продуманная навигация, пустые состояния, сохранение данных,
  аккуратная типографика, полезная интеграция ИИ.
- Не ломай точку входа `main.py` и не меняй формат `project.json` без причины.

{ENGINE_API_GUIDE}
"""


def _progress_lines(project) -> str:
    from reasonable.core.progress import read_state

    state = read_state(project.root)
    tasks = state.get("tasks", [])
    lines = []
    for task in tasks:
        mark = {"done": "[x]", "in_progress": "[>]", "skipped": "[-]"}.get(task.get("status"), "[ ]")
        lines.append(f"- {mark} {task.get('title')} ({task.get('id')})")
    return "\n".join(lines) or "- План пока пуст."


def _platform_lines(project) -> str:
    platform = "Android" if getattr(project, "platform", "windows") == "android" else "Windows"
    lines = [f"- Платформа проекта: {platform}"]
    note = _conversion_note(project)
    if note:
        lines.append(note)
    return "\n".join(lines)


def _conversion_note(project) -> str:
    converted = project.manifest.get("converted_from")
    if not isinstance(converted, dict) or not converted.get("name"):
        return ""
    source_platform = "Android" if converted.get("platform") == "android" else "Windows"
    return (
        f"- Проект сконвертирован из «{converted.get('name')}» "
        f"({source_platform}) {converted.get('at', '')}".rstrip()
    )


def build_agent_system_prompt(project) -> str:
    window = project.manifest.get("window") or {}
    return (
        AGENT_SYSTEM_PROMPT
        + f"""

ПРОЕКТ
- Имя: {project.name}
- Тип: {'игра' if project.project_type == 'game' else 'приложение'}
{_platform_lines(project)}
- Папка: {project.root}
- Окно: {window.get('width', 1280)}x{window.get('height', 720)}, режим: {project.window_mode}, изменение размера: {'да' if project.resizable else 'нет'}, ориентация: {project.manifest.get('orientation', 'landscape')}
- Главная цель: {project.goal or 'не указана'}
- Заметки пользователя: {project.notes or 'нет'}
- Точка входа: {project.manifest.get('entry', 'main.py')}

ТЕКУЩИЙ ПЛАН
{_progress_lines(project)}
"""
    )


def build_initial_user_message(project) -> str:
    """Fallback for API callers that need a safe first message.

    The editor never calls this automatically: the first task is written by the
    user after the project already exists.
    """
    return (
        f"Продолжи работу над проектом «{project.name}».\n\n"
        f"Главная цель: {project.goal or 'уточни у пользователя.'}\n"
        f"Заметки: {project.notes or 'нет'}\n\n"
        "Изучи проект, предложи следующий конкретный шаг и выполни его."
    )


SKILLS: dict[str, str] = {
    "engine-basics.md": r"""# Навык: основы Reasonable Engine

- Runtime: `from reasonable.runtime import *`; pygame-совместимый, без Qt.
- `Game` + `Scene` для игр; `UIApp` + виджеты для приложений.
- Все ресурсы — по абсолютному пути от `Path(__file__).parent / "assets"`.
- Заставка включается автоматически; не рисуйте свою вместо неё.
- `F11` — полный экран; касания приходят как mouse-события в UI.
- Проверка: `python main.py`, затем `re.bat validate`.
- Не редактируйте `_engine/`; обновление: `re.bat sync-engine`.

Шаблон сцены:
```python
class Play(Scene):
    def __init__(self, game):
        super().__init__(game, gradient=((8,12,22),(22,34,54)), camera_pos=(640,360))
    def update(self, dt):
        super().update(dt)
    def draw_background(self, surface):
        surface.fill((10, 15, 26))
```
""",
    "game-development.md": r"""# Навык: разработка игры

1. Определите ядро цикла: цель → действие → обратная связь → награда.
2. Соберите вертикальный срез: игрок, управление, одна механика, один враг/цель,
   HUD, пауза, проигрыш, рестарт. Только потом контент.
3. Управление: клавиатура + мышь; на Android — `VirtualJoystick` и `TouchButton`.
4. Обратная связь: частицы (`scene.burst`), тряска камеры, вспышки, звук,
   плавные tween-анимации, числа-попапы.
5. HUD: счёт, здоровье, подсказки; читаемый контраст, safe margins 24–40 px.
6. Сохранение: `SaveData("Имя", "save.json")` — рекорд/прогресс.
7. Проверка: headless-прогон, отсутствие ошибок в консоли, 60 FPS на 1280x720.
8. Не оставляйте неработающих кнопок и пустых экранов.

Структура: `main.py` (точка входа), `scenes/`, `entities/`, `ui/`, `data/`.
Для маленькой игры допустим один файл, но он должен быть читаемым.
""",
    "app-development.md": r"""# Навык: красивое приложение

- `UIApp` + `Panel/VStack/HStack/ScrollView`. Тёмная тема, крупные заголовки,
  один акцентный цвет, спокойные отступы 16/24/32.
- Обязательные состояния: пустой список, загрузка, ошибка, успех.
- Навигация: боковая панель или вкладки; активный пункт заметен.
- Данные сохраняйте в `data.json` рядом с проектом (атомарно, через tmp+replace).
- ИИ: `AIChatPanel` для чата или `AIClient` для точечных запросов. Добавьте
  системный промпт под задачу приложения; не отправляйте секреты.
- Проверяйте узкие окна: скрывайте второстепенные панели, не допускайте
  наложения текста. На Android целиком полагайтесь на касания.
- Анимации: hover, нажатие, появление панелей; без «дёрганья» layout.
""",
    "sprites-and-assets.md": r"""# Навык: спрайты и ассеты

Инструменты (встроенный агент) или CLI (внешний агент):

```bat
re.bat sprite "green slime enemy, cute" assets/sprites/slime.png --style flat --size 256
re.bat bg "neon city at night" assets/background.png --width 1280 --height 720
```

Правила:
- Один объект на спрайт, сильный силуэт, прозрачный фон (инструмент удаляет
  хромакей и обрезает поля).
- Единый стиль: выберите `flat`, `pixel`, `painterly` или `icon` и придерживайтесь.
- Имена: `player.png`, `enemy_slime.png`, `star.png`, `bg_forest.png`.
- Для UI используйте иконки движка (`draw_icon`) и векторные фигуры; не
  генерируйте иконки текстом.
- Проверяйте результат визуально (откройте PNG). Если объект обрезан или фон
  остался — повторите с более точным промптом.
- Фоны: широкие, без текста, с глубиной; не мешают читаемости HUD.
""",
    "progress-and-handoff.md": r"""# Навык: прогресс и передача работы

Редактор Reasonable Engine читает файлы проекта в реальном времени:

- `progress/state.json` — статус, процент, этап, задачи;
- `progress/events.jsonl` — лента событий.

Пишите только через CLI, чтобы не повредить JSON:

```bat
re.bat plan "Меню" "Игровой цикл" "Полировка"
re.bat task t1 in_progress
re.bat progress 35 "Собираю игровой цикл"
re.bat event "Добавлен экран настроек"
re.bat task t1 done
re.bat done "Проект готов к запуску"
re.bat validate
```

Правила:
- Обновляйте прогресс перед длительной работой и после каждого этапа.
- Не заканчивайте со статусом 100%, пока `re.bat validate` не пройден и проект
  не запускается.
- Если работу продолжит другой агент, оставьте в `AGENT_TASKS.md` заметки:
  что готово, что дальше, какие файлы трогать нельзя.
- Не редактируйте `state.json` вручную.
""",
    "android-and-export.md": r"""# Навык: Android и экспорт

- Android-сборка использует pygame-ce + python-for-android/buildozer.
- На Windows buildozer не работает: нужен Linux/WSL или GitHub Actions.
- В редакторе: **Файл → Экспорт → Android-пакет**. Будет создан ZIP с
  `buildozer.spec`, `main.py`, ассетами и инструкцией.
- В игре обязательны: касания (джойстик/кнопки), safe margins, портретная или
  ландшафтная ориентация из `project.json`, отсутствие правого клика и клавиатуры.
- Не используйте файловые пути Windows, `os.startfile`, `winreg`, субпроцессы и
  тяжёлые импорты в рантайме.
- Текст должен помещаться на узком экране; проверяйте 720x1280 и 1280x720.
- Windows-экспорт: **Файл → Экспорт → Папка Windows** (самодостаточная папка с
  рантаймом и `.bat`), опционально PyInstaller `.exe`.
""",
}


def build_external_guide(project) -> str:
    window = project.manifest.get("window") or {}
    kind = "игра" if project.project_type == "game" else "приложение"
    mode = "встроенный" if project.mode == "builtin" else "внешний"
    platform = "Android" if getattr(project, "platform", "windows") == "android" else "Windows"
    skills = "\n".join(f"- [`skills/{name}`](skills/{name})" for name in SKILLS)
    return f"""# AGENT_GUIDE — {project.name}

> Полная инструкция для внешнего ИИ-агента. Прочитайте её целиком перед первой
> правкой. Проект создан в **Reasonable Engine {VERSION}**; режим: {mode} агент.

## 1. Что это за проект

- **Название:** {project.name}
- **Тип:** {kind}
- **Платформа:** {platform}
{_conversion_note(project)}
- **Главная цель:** {project.goal or 'не указана'}
- **Окно:** {window.get('width', 1280)}×{window.get('height', 720)}, режим: {project.window_mode}, изменение размера: {'да' if project.resizable else 'нет'}
- **Ориентация:** {project.manifest.get('orientation', 'landscape')}
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
set RE_SKIP_SPLASH=1
set RE_FRAMES=5
python main.py
```

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


EXTERNAL_CONNECTION_GUIDE = """# Подключение внешнего ИИ-агента к Reasonable Engine

Внешний агент (Claude Code, OpenAI Codex CLI, Cursor, Cline, Windsurf, Continue,
Aider и другие) работает с обычной папкой проекта. Reasonable Engine в это время
показывает прогресс, файлы, задачи и позволяет запускать проект.

## Шаги

1. Создайте проект в редакторе и выберите режим **«Сторонний ИИ-агент»**.
2. Нажмите **«Открыть папку проекта»** и откройте её в своём агенте.
3. Попросите агента: *«Прочитай AGENT_GUIDE.md, skills/ и progress/state.json,
   затем продолжи разработку по плану»*.
4. Агент вызывает `re.bat` (Windows) или `re.sh` (Linux/WSL), чтобы обновлять
   план, задачи, события и процент готовности.
5. Вернитесь в Reasonable Engine — раздел **«ИИ-агент»** обновляется
   автоматически каждую секунду. Кнопки «Проверить» и «Запустить» доступны там же.

## Что получает агент

- `AGENT_GUIDE.md` — роль, правила, API движка, цикл работы.
- `skills/*.md` — навыки по играм, приложениям, спрайтам, прогрессу, Android.
- `AGENTS.md`, `CLAUDE.md`, `.cursor/rules/`, `.github/copilot-instructions.md`
  — короткие указатели для конкретных инструментов.
- `re.bat` / `re.sh` — CLI без установки зависимостей редактора.
- `project.json` и `progress/` — единый источник истины.

## Команды для агента

```bat
re.bat plan "Собрать меню" "Добавить уровни" "Проверить сборку"
re.bat task t1 in_progress
re.bat progress 30 "Готов экран меню"
re.bat event "Добавлены спрайты"
re.bat validate
re.bat done "Проект готов"
```

## Важно

- Не запускайте встроенного и внешнего агента одновременно над одними файлами.
- Прогресс появится в редакторе, даже если он был закрыт во время работы агента:
  файлы сохраняются в проекте.
- Android-сборка требует Linux/WSL; внешний агент может подготовить пакет и
  выполнить сборку там, где установлен buildozer.
- API-ключи не передавайте агенту в промпте. Для изображений без ключа
  используются процедурные спрайты, для текста — выбранный вами провайдер.
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
