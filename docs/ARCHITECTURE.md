# Архитектура Reasonable Engine

Документ описывает, как устроены редактор, runtime, ИИ-агент, протокол прогресса и экспорт. Он полезен тем, кто хочет расширить движок, писать плагины или понять, где искать причину ошибки.

---

## Общая картина

```text
┌──────────────────────────── Reasonable Engine ────────────────────────────┐
│                                                                          │
│  Редактор (PySide6, Windows)                                              │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐  │
│  │ Welcome      │ │ Мастер       │ │ Страница     │ │ Настройки,       │  │
│  │ и проекты    │ │ проекта      │ │ проекта      │ │ экспорт, темы    │  │
│  └──────────────┘ └──────────────┘ └──────┬───────┘ └──────────────────┘  │
│                                            │                              │
│           ┌────────────────────────────────┼──────────────────────┐       │
│           │                                │                      │       │
│      Встроенный агент              Ручной режим              Внешний агент │
│      chat + workers                код + ассеты              panel + files │
│           │                                │                      │       │
│           ▼                                ▼                      ▼       │
│      AI providers                    Project API             progress/     │
│      OpenAI / Anthropic              файлы, запуск           state.json    │
│           │                                │                      │       │
│           └──────────────┬─────────────────┴──────────────────────┘       │
│                          ▼                                                │
│                   проект на диске                                        │
│                   main.py · assets/ · project.json · _engine/             │
└──────────────────────────────────────────────────────────────────────────┘
                          │
                          ▼
              Runtime (pygame, без Qt)
              Windows / Android
```

Ключевое разделение:

- **редактор** — PySide6, только Windows;
- **runtime** — pygame + стандартная библиотека, Windows и Android;
- **агент** — обычный Python-код, который вызывает инструменты и пишет файлы;
- **проект** — самодостаточная папка без скрытой базы данных.

---

## Структура пакета

```text
reasonable/
├─ core/
│  ├─ paths.py          пути, slugify, атомарная запись, JSON
│  ├─ settings.py       настройки в %APPDATA%
│  ├─ project.py        манифест, безопасные операции, проверка, запуск
│  ├─ progress.py       state.json + events.jsonl
│  ├─ scaffold.py       создание проекта и vendor_engine
│  ├─ convert.py        конвертация в новый проект
│  └─ logging_setup.py  логирование
├─ ai/
│  ├─ providers.py      каталог провайдеров и моделей
│  ├─ client.py         OpenAI-совместимый и Anthropic клиенты
│  ├─ agent.py          цикл tool calling
│  ├─ tools.py          инструменты агента и песочница
│  ├─ prompts.py        системные промпты, guide и skills
│  ├─ sprites.py        процедурные и удалённые спрайты/фоны
│  └─ external.py       пакет инструкций для внешних агентов
├─ runtime/
│  ├─ app.py            App / Game / UIApp, цикл, splash
│  ├─ scene.py          Scene и GridScene
│  ├─ graphics.py       спрайты, камера, частицы, твины, фигуры
│  ├─ ui.py             виджеты и тема для приложений
│  ├─ input.py          клавиатура, мышь, касания, джойстик
│  ├─ audio.py          звук с ленивой инициализацией
│  ├─ save.py           JSON-сохранения
│  ├─ splash.py         процедурная заставка
│  ├─ ai.py             встроенный ИИ-чат для приложений
│  └─ utils.py          цвета, шрифты, рисование, анимации
├─ editor/
│  ├─ main_window.py    окно, меню, навигация
│  ├─ welcome.py        стартовый экран и недавние проекты
│  ├─ new_project.py    мастер из двух шагов
│  ├─ project_page.py   обзор, раздел агента, код, ассеты, запуск
│  ├─ chat.py           встроенный агент
│  ├─ external.py       панель внешнего агента
│  ├─ code.py           дерево файлов и редактор
│  ├─ assets.py         браузер и генерация ассетов
│  ├─ settings_dialog.py
│  ├─ project_settings.py
│  ├─ export_dialog.py
│  ├─ convert_dialog.py конвертация в новый проект
│  ├─ workers.py        QThread-обёртки
│  ├─ theme.py          QSS, шрифты, палитра
│  └─ widgets.py        Badge, Card, Avatar, EmptyState…
├─ templates/
│  ├─ game/main.py      стартовая игра
│  └─ app/main.py       стартовое приложение
├─ cli.py               re.bat / re.sh
├─ export.py            Windows и Android
├─ branding.py          имя, слоганы, палитра
└─ version.py
```

Отдельно от пакета лежат `ReasonableEngine.spec`, `build_exe.bat` и `tools/build_editor_exe.py` — сборка редактора в Windows `.exe`.

---

## Жизненный цикл проекта

### Создание

```text
Мастер / CLI
  → default_manifest()
  → Project.create()
  → scaffold_project()
      → создать папки
      → скопировать шаблон main.py
      → сгенерировать иконку, фон, стартовые спрайты
      → записать README, run.bat, re.bat, .gitignore
      → создать progress/ и начальный план
      → generate_agent_pack()
      → vendor_engine()
  → Project.save()
```

Мастер задаёт только идею, тип, режим ИИ, имя и папку. Окно, заметки, ориентация и первая задача агенту настраиваются после создания. Это уменьшает первый экран и не заставляет писать техническое задание до того, как проект появился.

`vendor_engine()` копирует runtime в `<проект>/_engine/reasonable/`, исключая редактор, шаблоны и кеши. В dev-режиме копируются `.py`, в установленной сборке — только `.pyc` из `engine_source_pyc`, чтобы исходный код ядра не попадал в проекты. Android-экспорт всегда получает плоский исходник. Благодаря встроенной копии проект запускается без установленного редактора и переживает его обновление.

### Конвертация

```text
convert_project(project, "android")
  → conversion_plan(): проверить опции и изменения
  → unique_directory(): новая папка рядом, не внутри исходной
  → copytree() без _engine, dist, build, кешей, .git, .env и ai_config.json
  → обновить project.json: платформа, окно, ориентация, режим агента
  → записать converted_from + conversions[]
  → APP_NAME и заголовок README при смене имени
  → vendor_engine()
  → generate_agent_pack()
  → сохранить или сбросить progress/
  → записать CONVERSION.md
```

Исходная папка не изменяется. Платформа — главная ось, но тем же путём поддерживаются ориентация, режим агента, режим окна, resizable, базовое разрешение и чистовой прогресс. Замена шаблона игры на приложение и импорт сторонних движков намеренно не автоматизируются.

### Запуск

```text
Project.run_env()
  → PYTHONPATH = <проект>/_engine ; <проект> ; старый PYTHONPATH
  → python main.py
  → App.run()
      → pygame.init()
      → play_splash()
      → on_start()
      → цикл: events → update → draw
      → on_exit()
```

Редактор запускает проект через `QProcess`, передаёт `PYTHONUNBUFFERED=1`, читает stdout/stderr в консоль и позволяет остановить процесс.

### Ручное редактирование

Код и ассеты — обычные файлы. Редактор не держит их в базе и не блокирует агентом:

- `CodePage` строит дерево, открывает текст или изображение, сохраняет по `Ctrl+S`;
- `AssetsPage` показывает ассеты и вызывает генератор;
- перед запуском и экспортом вызывается `save_all()`;
- внешние изменения подхватываются при обновлении дерева и списка ассетов.

---

## Формат проекта

`project.json` — единственный обязательный манифест:

```json
{
  "format": 1,
  "name": "Космический кот",
  "slug": "kosmicheskii-kot",
  "type": "game",
  "platform": "windows",
  "mode": "builtin",
  "goal": "Кот собирает звёзды",
  "notes": "Меню, три уровня, враги, сохранение рекорда",
  "template": "game",
  "entry": "main.py",
  "window": {
    "width": 1280,
    "height": 720,
    "title": "Космический кот",
    "mode": "windowed",
    "resizable": true
  },
  "orientation": "landscape",
  "splash": true,
  "icon": "assets/icon.png",
  "background": "assets/background.png",
  "android": {
    "package": "org.reasonable.kosmicheskiikot",
    "version": "1.0.0",
    "orientation": "landscape"
  },
  "ai": {"image_style": "flat", "notes": ""},
  "engine_version": "0.1.0",
  "created_at": "…",
  "updated_at": "…"
}
```

Для старых проектов поле `platform` отсутствует — `Project.platform` считает их Windows-проектами. Поле `prompts` больше не создаётся; `Project.notes` читает `notes`, а у старых манифестов — `prompts` как резервный источник. Конвертированный проект дополнительно содержит `converted_from` и `conversions`.

Свойства `Project` нормализуют значения: неизвестный `type` становится `game`, неизвестный `mode` — `builtin`, неизвестная платформа — `windows`. Все операции с файлами проходят через `ensure_inside()`, поэтому выход за папку проекта запрещён.

---

## Runtime

### App / Game / UIApp

- `App` — окно, цикл, события, F11, splash (играет всегда; headless-прогон завершает его мгновенно), `RE_FRAMES`.
- `Game` — сцены, стек сцен, `Input`, камера.
- `UIApp` — приложение с корневым виджетом и UI-событиями.

Цикл:

```python
dt = min(0.05, clock.tick(fps) / 1000)
handle events → on_update(dt) → on_draw(surface) → flip
```

Ограничение `dt` защищает физику и анимации от огромных скачков после паузы.

### Сцены

`Scene` хранит камеру, UI и узлы. `GridScene` помогает с сеточными играми. Переходы:

```python
game.change_scene(MenuScene())
game.push_scene(PauseScene())
game.pop_scene()
```

### Графика

- `Sprite`, `AnimatedSprite`, `Shape`, `Text`, `Node`;
- `Camera` с зумом и следованием;
- `ParticleSystem`;
- `TweenManager` и easing-функции;
- утилиты рисования: градиенты, скругления, свечение, обрезка текста.

### UI

Собственный toolkit на pygame:

`Panel`, `Card`, `VStack`, `HStack`, `Grid`, `Label`, `Button`, `IconButton`, `Entry`, `Toggle`, `Slider`, `ProgressBar`, `ScrollView`, `Tabs`, `Badge`, `Avatar`, `ImageWidget`.

Он работает и на Windows, и на Android, потому что не зависит от Qt. Касания преобразуются в mouse-события, есть фокус и прокрутка.

### Ввод

`Input` собирает клавиши, мышь и касания. `VirtualJoystick` и `TouchButton` дают мобильное управление без отдельной сборки.

### Сохранения

`SaveData` пишет JSON в `%APPDATA%\ReasonableGames\<имя>\save.json` (или аналогичную папку на другой ОС). Запись атомарная: временный файл + `os.replace`.

### Заставка

`play_splash()` рисует минималистичную заставку (в духе Unity/Godot):

- длительность ~1,8 с: тёмный фон, логотип, тихая подпись;
- играет всегда и целиком — отключить или пропустить её пользователю нельзя;
- в headless-прогоне (`SDL_VIDEODRIVER=dummy`) завершается мгновенно;
- логотип берётся из бренд-ассетов движка; работает офлайн на Windows и Android.

### Встроенный ИИ в приложении

`runtime/ai.py` содержит `AIClient` и `AIChatPanel`:

- по умолчанию OpenRouter; ключ вводит конечный пользователь;
- конфигурация из `ai_config.json` проекта или локального файла приложения;
- ключ хранится локально, не в экспортированном проекте;
- панель можно встроить в любое приложение.

---

## ИИ-подсистема

### Провайдеры

`ai/providers.py` — данные, а не логика. Каждый провайдер описывает:

- `id`, имя, группу;
- тип API (`openai` или `anthropic`);
- Base URL и модель по умолчанию;
- нужен ли ключ;
- подсказки моделей, заголовки, ссылки.

`Settings` хранит активного провайдера и переопределения. Ключи лежат только в `%APPDATA%`.

### Клиент

`ai/client.py`:

- OpenAI-совместимый `/chat/completions` с `tools`;
- нативный Anthropic Messages API;
- повторы при временных ошибках;
- таймауты;
- `list_models()` для кнопки «Загрузить модели»;
- fallback-парсинг JSON-инструментов, если модель не умеет tool calling.

### Агент

`ai/agent.py` — цикл:

```text
system prompt + задача
  → запрос к модели
  → есть tool_calls?
      → выполнить каждый инструмент
      → добавить tool-результаты
      → следующий шаг
  → нет tool_calls → финальный текст
```

Ограничения:

- `max_steps` из настроек (по умолчанию 42);
- `context_messages` для обрезки истории;
- отмена через `threading.Event`;
- события `step`, `assistant`, `tool_start`, `tool_result`, `usage`, `done`, `error`;
- зеркалирование статуса в `progress/`.

### Инструменты

`ai/tools.py` предоставляет:

| Инструмент | Действие |
|---|---|
| `list_files` | Список файлов и папок |
| `read_file` | Чтение текста с диапазоном строк |
| `write_file` | Создание или полная замена |
| `edit_file` | Точечная замена уникального фрагмента |
| `delete_path` | Удаление файла или папки |
| `search_text` | Поиск текста или регулярного выражения |
| `run_command` | Команда в папке проекта |
| `run_project` | Headless-запуск |
| `validate_project` | Проверка структуры и синтаксиса |
| `generate_sprite` | Спрайт в `assets/` |
| `generate_background` | Фон в `assets/` |
| `inspect_image` | Размер, прозрачность, палитра |
| `get_progress` | Состояние и события |
| `set_plan` | План работ |
| `update_task` | Статус задачи |
| `report_progress` | Процент и этап |
| `finish` | Завершение на 100% |

Песочница:

- пути только внутри проекта;
- `_engine/` защищён от изменений;
- `main.py`, `project.json`, `progress/state.json`, `progress/events.jsonl` защищены от удаления;
- опасные команды блокируются;
- запись и чтение ограничены по размеру.

Это **не** полноценная ОС-песочница: команды выполняются с правами пользователя. Защита уменьшает риск случайных разрушительных действий, но не заменяет осторожность.

### Промпты и навыки

`ai/prompts.py` собирает:

- системный промпт агента с описанием runtime и правил;
- стартовое сообщение с целью, заметками и платформой проекта;
- `AGENT_GUIDE.md` с платформой и историей конвертации;
- `EXTERNAL_AGENT.md`;
- шесть навыков `skills/*.md`;
- `AGENT_TASKS.md`.

Промпты содержат реальные имена классов runtime, чтобы модель не придумывала несуществующий API.

---

## Протокол прогресса

Один протокол для встроенного и внешнего агентов:

```text
progress/state.json    текущий снимок
progress/events.jsonl  поток событий
```

Запись:

- `ensure_state()`;
- `set_status()`;
- `set_progress()`;
- `set_plan()`;
- `update_task()`;
- `record_event()`;
- `finish_progress()`.

Все функции используют `RLock`, атомарную запись JSON и дописывание событий. Файл событий обрезается при превышении ~2 МБ.

Редактор:

- `ProjectPage` и `ExternalAgentPanel` опрашивают файлы каждые 1,5–1,6 с;
- сравнивают сигнатуры, чтобы не перерисовывать интерфейс без изменений;
- показывают статус, процент, план, события и недавние файлы.

Почему файлы, а не сокеты:

- внешний агент может быть любым процессом;
- состояние переживает перезапуск;
- файлы удобно читать, отлаживать и хранить в Git;
- нет конфликтов портов и блокировок.

---

## Редактор

### Навигация

`MainWindow` держит `QStackedWidget`:

- `WelcomePage` — недавние проекты, создание, настройки;
- `ProjectPage` — рабочая область проекта.

`ProjectPage` содержит разделы:

1. **Обзор** — цель, заметки, прогресс, план, события, быстрые действия.
2. **ИИ-агент** — единый раздел: встроенный чат или панель внешнего агента в зависимости от `project.mode`.
3. **Код** — дерево, редактор, подсветка, изображения.
4. **Ассеты** — браузер и генерация.

Сверху — название, тип, платформа, режим агента, активная модель, статус и кнопки запуска/экспорта. Снизу — консоль запущенного проекта.

### Потоки

Qt требует, чтобы UI жил в главном потоке. Долгие операции вынесены в `QThread`:

- `Worker` — универсальная обёртка;
- `AgentWorker` — агент;
- `ProviderTestWorker` — проверка провайдера;
- `SpriteWorker` — генерация ассетов;
- `ExportWorker` — экспорт;
- `ConvertWorker` — конвертация;
- `ScaffoldWorker` — создание проекта.

Сигналы `done`, `failed`, `stage` возвращают результат в UI. При закрытии диалогов рабочие потоки завершаются.

### Тема

`theme.py` содержит QSS, палитру, шрифты и загрузку логотипа. Интерфейс редактора намеренно сдержанный: графитовые поверхности, один тёплый акцент и приглушённые статусные цвета. Заголовки набраны тем же Inter, что и основной текст, — иерархия строится размером и насыщенностью, а не вторым декоративным шрифтом.

---

## Экспорт

### Windows

```text
export_windows()
  → выбрать свободную папку
  → скопировать проект (без .git, кешей, настроек)
  → добавить _engine/, если нужно
  → создать иконку .ico
  → создать Play.bat
  → записать README_WINDOWS.txt и config.json
  → маркер .reasonable-export
```

`mode="pyinstaller"` дополнительно вызывает PyInstaller, если он установлен. Обычная папка не требует сторонних инструментов.

### Android

```text
export_android()
  → скопировать проект
  → гарантировать _engine/
  → создать buildozer.spec
  → подготовить icon.png и presplash.png
  → записать README_ANDROID.md
  → добавить .github/workflows/android.yml
  → упаковать в ZIP
```

Сборка APK не выполняется на Windows. ZIP — это вход для buildozer на Linux/WSL2. Подробности: [ANDROID.md](ANDROID.md).

---

## Конвертация

```text
convert_project()
  → conversion_plan(): валидировать target/options, посчитать изменения
  → copytree(source, target, ignore=...)
  → manifest: platform, orientation, mode, window, android, converted_from
  → vendor_engine()
  → generate_agent_pack()
  → progress: preserve или reset
  → CONVERSION.md
```

Правила:

- исходный проект не мутируется;
- новая папка создаётся рядом и не может быть внутри исходной;
- копирование исключает `_engine/`, `dist/`, `build/`, `.git`, кеши, `.reasonable/`, `data.json`, `ai_config.json` и `.env`;
- движок всегда пересобирается из текущей версии Reasonable Engine;
- прогресс по умолчанию сохраняется, `reset_progress=True` очищает `state.json` и `events.jsonl`;
- при смене имени обновляются `APP_NAME` в `main.py`, заголовок README и стандартный Android-пакет.

Оси конвертации: `windows|android`, `landscape|portrait`, `builtin|external`, `windowed|fullscreen`, `resizable`, базовое разрешение и `reset_progress`. Замена game↔app и импорт сторонних движков не автоматизируются.

---

## Сборка редактора и установщик

`ReasonableEngine.spec` + `tools/build_editor_exe.py` собирают one-file PyInstaller `.exe` без консоли. В бандл входят `reasonable/assets`, `reasonable/templates`, `docs`, `README.md` и две копии движка:

- `engine_source/reasonable` — плоский исходник для Android-экспорта и аварийного fallback;
- `engine_source_pyc/reasonable` — bytecode-only дерево, которое получают проекты.

`engine_source_dir(protected=...)` выбирает нужную копию при `sys.frozen`, а `protected_engine_available()` включает защищённый вариант только если в дереве есть `.pyc` и нет `.py`.

Запуск проекта в установленной версии идёт через `project_launch_command()`:

1. `ReasonablePlayer.exe` рядом с редактором (PyInstaller + pygame, без системного Python);
2. портативный Python `runtime/python/python.exe` (pygame + Pillow) для `re.bat`;
3. системный Python — только в dev-режиме.

Так кнопка «Запустить» больше не открывает второй экземпляр редактора (`sys.executable` в frozen-сборке указывает на сам редактор).

Полный установщик собирает `tools/build_installer.py`:

```
protected bytecode → ReasonablePlayer.exe → portable Python → ReasonableEngine.exe → Inno Setup
```

`installer/ReasonableEngine.iss` ставит всё для текущего пользователя в `%LOCALAPPDATA%\Programs\Reasonable Engine`, показывает `installer/EULA.txt`, создаёт папку `Projects` и не требует прав администратора. Портативный Python и player кладутся рядом, поэтому установка работает на чистой Windows без Python.

После сборки инструмент запускает `dist/ReasonableEngine.exe --self-test` с `QT_QPA_PLATFORM=offscreen` и `REASONABLE_SELF_TEST_REPORT`; отчёт проверяет ресурсы, окно редактора, создание проекта, защищённый движок, команду запуска, окно, заметки и конвертацию.

---

## Безопасность и границы доверия

| Граница | Что защищено | Что не защищено |
|---|---|---|
| Файлы проекта | Выход за папку, `_engine/`, защищённые файлы | Произвольные команды с правами пользователя |
| API-ключи | Не попадают в проект, маскируются в UI | Локальный `settings.json` не шифруется |
| Внешний агент | Инструкции и прогресс | Сам процесс не ограничен редактором |
| Экспорт | Копирование без служебных папок | Целостность чужого кода не проверяется |
| Конвертация | Копия без `_engine`, кешей, старых экспортов и секретов | Логика и вёрстка автоматически не адаптируются |
| Android | Пакет и инструкция | Сборка и подпись — ответственность пользователя |

Рекомендации: Git или резервные копии, проверка команд агента, отдельный ключ с минимальными правами, не хранить `release.keystore` в репозитории.

---

## Расширение

### Новый провайдер

1. Добавьте `ProviderPreset` в `reasonable/ai/providers.py`.
2. Укажите `kind="openai"` или `kind="anthropic"`.
3. Проверьте `/models` и tool calling.
4. Добавьте тест или ручную проверку.

### Новый инструмент агента

1. Опишите схему в `TOOL_SCHEMAS`.
2. Реализуйте метод `tool_*` в `AgentTools`.
3. Добавьте ветку в `call()`.
4. Проверьте песочницу и лимиты.
5. Обновите `AGENT_GUIDE.md` и навыки при необходимости.

### Новый виджет runtime

1. Наследуйтесь от `Widget` в `runtime/ui.py`.
2. Реализуйте `layout()`, `draw()`, `handle_event()`.
3. Проверьте на Windows и на касаниях.
4. Добавьте в `runtime/__init__.py`.

### Новый шаблон проекта

1. Создайте `reasonable/templates/<name>/main.py`.
2. Используйте токены, которые заменяет `_replace_tokens()`.
3. Подключите шаблон к типу проекта или CLI; мастер сейчас предлагает только игру и приложение.
4. Проверьте `validate` и headless-запуск.

---

## Ограничения текущей версии

- Только 2D.
- Нет визуального редактора сцен и физического движка.
- Нет мультиплеера и сетевого слоя.
- Нет встроенного магазина ассетов.
- Android-сборка требует внешней Linux-среды.
- Конвертация меняет платформу и настройки, но не переписывает игру и не адаптирует вёрстку автоматически.
- Качество агента зависит от модели и поддержки инструментов.
- Редактор официально ориентирован на Windows.

---

## Связанные документы

- [CLI.md](CLI.md) — команды и коды возврата.
- [EXTERNAL_AGENTS.md](EXTERNAL_AGENTS.md) — протокол для внешних агентов.
- [AI_PROVIDERS.md](AI_PROVIDERS.md) — провайдеры и ключи.
- [ANDROID.md](ANDROID.md) — сборка APK.
- [TESTING.md](TESTING.md) — тесты и ручная проверка.
