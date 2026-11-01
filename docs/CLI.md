# CLI проекта: `re.bat`, `re.sh` и `python -m reasonable.cli`

CLI — общий интерфейс для встроенного агента, внешних агентов и человека. Через него обновляется прогресс, проверяется проект, генерируются ассеты и выполняется экспорт.

Внутри проекта используйте:

```bat
re.bat status
```

`re.bat` сам:

- переходит в кодировку UTF-8 (`chcp 65001`);
- добавляет `_engine` и корень проекта в `PYTHONPATH`;
- передаёт `--project "<папка проекта>"`;
- вызывает `python -m reasonable.cli`.

На Linux/macOS:

```bash
./re.sh status
```

Из корня движка:

```bat
python -m reasonable.cli --project "C:\path\to\project" status
```

> Глобальный флаг `--project` указывается **до** команды. Внутри проекта проще использовать `re.bat`, который делает это автоматически.

---

## Быстрый справочник

| Команда | Назначение |
|---|---|
| `status` | Проект, статус, процент, этап, план |
| `events` | Последние события прогресса |
| `plan` | Заменить план работ |
| `task` | Обновить статус задачи |
| `progress` | Процент, этап и сообщение |
| `event` | Добавить событие в ленту |
| `done` | Завершить проект на 100% |
| `validate` | Проверить структуру и синтаксис |
| `run` | Запустить проект |
| `sprite` | Сгенерировать спрайт |
| `bg` | Сгенерировать фон |
| `export` | Экспорт Windows или Android |
| `convert` | Новый проект с другой платформой или настройками |
| `sync-engine` | Обновить `_engine/` |
| `pack` | Обновить пакет инструкций агента |
| `init` | Создать проект из CLI |
| `settings` | Показать или сменить провайдера |
| `version` | Версия движка |

---

## Прогресс и план

### `status`

```bat
re.bat status
re.bat status --json
```

Текстовый вывод показывает имя, тип, режим, статус, процент, этап, задачи и папку. JSON содержит манифест проекта и снимок прогресса:

```json
{
  "project": {
    "name": "Космический кот",
    "type": "game",
    "mode": "builtin",
    "goal": "Кот собирает звёзды"
  },
  "progress": {
    "status": "running",
    "percent": 45.0,
    "stage": "Меню",
    "tasks": []
  }
}
```

### `events`

```bat
re.bat events
re.bat events --limit 80
re.bat events --json
```

По умолчанию показывает последние 40 событий. В текстовом режиме — время, тип и сообщение.

### `plan`

```bat
re.bat plan "Собрать меню" "Добавить уровни" "Проверить сборку"
re.bat plan "Меню" "Уровни" --json
```

Заменяет план целиком. Задачи получают идентификаторы `t1`, `t2`, … и статус `pending`.

### `task`

```bat
re.bat task t2 in_progress
re.bat task 3 done
re.bat task "уровни" done
```

Статусы:

- `pending` — ожидает;
- `in_progress` — в работе;
- `done` — готово;
- `skipped` — пропущено.

Вместо `t2` можно указать номер или часть названия задачи. Если задача не найдена, команда завершается с кодом `2`.

### `progress`

```bat
re.bat progress 45 "Готов экран меню" --stage "Меню"
re.bat progress 100 "Всё готово"
re.bat progress 30 "Черновик" --json
```

Процент ограничивается диапазоном `0…100`. При `100` статус становится `done`, иначе `running`.

### `event`

```bat
re.bat event "Добавлены враги"
re.bat event "Проверка пройдена" --type validate
re.bat event "Тест" --json
```

Тип события — произвольная строка (`agent`, `tool`, `validate`, `asset`, `export`, …). Тип по умолчанию — `event`.

### `done`

```bat
re.bat done
re.bat done "Игра готова к публикации"
re.bat done --json
```

Ставит `100%`, статус `done` и отмечает все задачи выполненными.

---

## Проверка и запуск

### `validate`

```bat
re.bat validate
re.bat validate --json
```

Проверяет:

- наличие `project.json` и корректность обязательных полей;
- точку входа;
- синтаксис всех Python-файлов проекта;
- структуру `assets/` и `progress/`;
- встроенный движок.

Коды возврата:

- `0` — ошибок нет;
- `1` — найдены ошибки.

Предупреждения не меняют код возврата. JSON — массив объектов:

```json
[
  {"level": "ok", "message": "Проект выглядит корректно…", "path": ""},
  {"level": "error", "message": "Синтаксическая ошибка…", "path": "main.py"}
]
```

### `run`

```bat
re.bat run
re.bat run --headless
re.bat run --headless --frames 12
re.bat run --timeout 60
```

| Флаг | Значение |
|---|---|
| `--headless` | Запуск без окна: `SDL_VIDEODRIVER=dummy`, `SDL_AUDIODRIVER=dummy`; заставка завершается мгновенно |
| `--frames N` | Остановиться после N кадров (по умолчанию 8, только с `--headless`) |
| `--timeout SEC` | Принудительно завершить через SEC секунд; `0` — без лимита |

Команда возвращает код завершения дочернего процесса. Таймаут — код `3`.

Пример для CI:

```bash
PYTHONPATH="$PWD/_engine:$PWD" python3 -m reasonable.cli --project "$PWD" run --headless --frames 5
```

---

## Ассеты

### `sprite`

```bat
re.bat sprite "золотая звезда" assets/sprites/star.png
re.bat sprite "синий кристалл" assets/sprites/crystal.png --style pixel --size 128
re.bat sprite "слизень" assets/sprites/slime.png --provider procedural --seed 42
```

| Флаг | Значение |
|---|---|
| `--style` | `flat`, `pixel`, `painterly`, `icon`; по умолчанию `flat` |
| `--size` | 64…1024; по умолчанию 256 |
| `--provider` | `procedural`, `openai`; по умолчанию из настроек |
| `--seed` | Фиксирует результат |

Файл обязан находиться внутри `assets/`. Иначе команда завершается с кодом `2`. Результат всегда выводится JSON:

```json
{
  "prompt": "золотая звезда",
  "style": "flat",
  "size": 256,
  "seed": 12345,
  "provider": "procedural",
  "fallback": false,
  "path": "assets/sprites/star.png"
}
```

### `bg`

```bat
re.bat bg "ночной лес со светлячками" assets/backgrounds/forest.png
re.bat bg "космос" assets/backgrounds/space.png --width 1280 --height 720
re.bat bg "город" assets/backgrounds/city.png --provider procedural --seed 7
```

| Флаг | Значение |
|---|---|
| `--width` | Ширина, по умолчанию 1280 |
| `--height` | Высота, по умолчанию 720 |
| `--provider` | `procedural`, `openai` |
| `--seed` | Фиксирует результат |

Фон также сохраняется только в `assets/`.

---

## Экспорт

```bat
re.bat export windows
re.bat export windows --output "C:\Exports\MyGame"
re.bat export windows --mode pyinstaller
re.bat export android
re.bat export android --output "C:\Exports\MyGame-android.zip"
```

| Параметр | Значение |
|---|---|
| `windows` | Самодостаточная папка с `Play.bat` |
| `windows --mode pyinstaller` | Сборка `.exe`; требует установленного PyInstaller |
| `android` | ZIP с buildozer-проектом, инструкцией и GitHub Actions |
| `--output` | Папка или ZIP. Если папка занята чужим экспортом, создаётся новая |

`--mode` применяется только к Windows. Для Android он игнорируется.

Команда всегда выводит JSON с результатом: путь, лаунчер, ZIP и сообщение. Код `1` — ошибка экспорта.

---

## Конвертация

```bat
re.bat convert --to android
re.bat convert --to windows --name "Кот на ПК" --dir "D:\Projects"
re.bat convert --to android --orientation portrait --reset-progress
```

| Параметр | Значение |
|---|---|
| `--to` | `windows` или `android`, обязательно |
| `--name` | Новое имя; по умолчанию сохраняется |
| `--dir` | Родительская папка нового проекта |
| `--orientation` | `current`, `landscape`, `portrait` |
| `--mode` | `current`, `builtin`, `external` |
| `--window-mode` | `current`, `windowed`, `fullscreen` |
| `--resizable` | `current`, `yes`, `no` |
| `--width`, `--height` | Базовое разрешение нового проекта |
| `--reset-progress` | Очистить план, прогресс и события |
| `--json` | Машинный результат |

Конвертация создаёт новую папку и **никогда не меняет исходный проект**. Она копирует код и ассеты без `_engine/`, `dist/`, `build/`, кешей, `.git`, `.env`, `data.json` и `ai_config.json`, затем заново встраивает движок и пересобирает пакет агента. При смене платформы обновляются `platform`, ориентация, Android-пакет и окно.

Если все выбранные параметры совпадают с исходником, команда завершится ошибкой: точная копия не создаётся. Код `1` — ошибка или отсутствие изменений.

Результат в JSON:

```json
{
  "ok": true,
  "path": "D:\\Projects\\kot-na-telefone",
  "name": "Кот на телефоне",
  "platform": "android",
  "source_platform": "windows",
  "orientation": "portrait",
  "window_mode": "windowed",
  "width": 720,
  "height": 1280,
  "reset_progress": false,
  "changes": ["Платформа: Windows → Android", "Ориентация: альбомная → портретная"],
  "message": "Новый проект создан: …"
}
```

---

## Обслуживание проекта

### `sync-engine`

```bat
re.bat sync-engine
```

Копирует актуальный runtime из установленного Reasonable Engine в `_engine/`. Используйте после обновления движка. Закройте запущенный проект перед синхронизацией.

### `pack`

```bat
re.bat pack
```

Перегенерирует:

- `AGENT_GUIDE.md`;
- `EXTERNAL_AGENT.md`;
- `AGENTS.md`, `CLAUDE.md`;
- `.cursor/rules/reasonable-engine.mdc`;
- `.github/copilot-instructions.md`;
- `skills/*.md`;
- `.reasonable/agent_pack.json`.

`AGENT_TASKS.md` не перезаписывается. Ваш код и настройки проекта не затрагиваются.

---

## Создание проекта

```bat
python -m reasonable.cli init --name "Космический кот"
```

| Флаг | Значение |
|---|---|
| `--name` | Имя проекта, обязательно |
| `--type` | `game` или `app`; по умолчанию `game` |
| `--mode` | `builtin` или `external`; по умолчанию `builtin` |
| `--goal` | Короткая главная цель |
| `--notes` | Необязательные требования и пожелания |
| `--dir` | Родительская папка; по умолчанию текущая |
| `--width`, `--height` | Базовое окно; по умолчанию 1280×720 |
| `--window-mode` | `windowed` или `fullscreen` |
| `--fixed-size` | Запретить изменение размера окна |
| `--orientation` | `landscape` или `portrait` |

Пример:

```bat
python -m reasonable.cli init ^
  --name "Планировщик" ^
  --type app ^
  --mode external ^
  --goal "Умный планировщик задач" ^
  --notes "Задачи, дедлайны, статистика, ИИ-помощник" ^
  --width 720 --height 1280 ^
  --orientation portrait ^
  --window-mode windowed ^
  --dir "D:\Projects"
```

Создаётся полный самодостаточный проект: код, ассеты, `_engine`, прогресс и пакет агента.

---

## Настройки

```bat
re.bat settings
re.bat settings --show
re.bat settings --provider openrouter
```

- Без флагов — путь к `settings.json` и активный провайдер.
- `--show` — конфигурация активного провайдера; ключ маскируется.
- `--provider ID` — переключить активного провайдера и сохранить настройки.

ID провайдеров: `ollama`, `lmstudio`, `openrouter`, `groq`, `gemini`, `cerebras`, `mistral`, `github`, `huggingface`, `openai`, `anthropic`, `custom`.

Настройки находятся в `%APPDATA%\ReasonableEngine\settings.json` и не попадают в проект.

---

## Версия

```bat
re.bat version
python -m reasonable.cli --version
python -m reasonable --version
```

Выводит версию движка, кодовое имя, версию Python и платформу.

---

## JSON и автоматизация

Флаг `--json` поддерживают:

- `status`
- `events`
- `plan`
- `task`
- `progress`
- `event`
- `done`
- `validate`
- `convert`

Команды `sprite`, `bg`, `export` и `settings --show` всегда печатают JSON.

Пример PowerShell:

```powershell
$state = re.bat status --json | ConvertFrom-Json
if ($state.progress.percent -ge 100) { Write-Host "Готово" }
```

Пример Bash:

```bash
re.sh status --json | python3 -c "import json,sys; print(json.load(sys.stdin)['progress']['percent'])"
```

---

## Коды возврата

| Код | Значение |
|---|---|
| `0` | Успех |
| `1` | Ошибка проверки, генерации или экспорта |
| `2` | Неверные аргументы, отсутствует точка входа, задача не найдена, файл вне `assets/` |
| `3` | Таймаут `run` |
| `130` | Прерывание с клавиатуры (`Ctrl+C`) |
| другое | Код дочернего процесса для `run` |

---

## Частые ошибки

| Симптом | Решение |
|---|---|
| `В папке нет корректного project.json` | Запустите команду в папке проекта или укажите `--project` |
| `No module named reasonable` | Используйте `re.bat` или добавьте `_engine` в `PYTHONPATH` |
| `Точка входа не найдена` | Проверьте `entry` в `project.json` и файл `main.py` |
| `Сохраняйте спрайты в assets/` | Укажите путь внутри `assets/…` |
| `Задача не найдена` | Посмотрите `re.bat status` и используйте точный id или название |
| Кракозябры | `chcp 65001`, `PYTHONIOENCODING=utf-8` |
| `run --headless` зависает | Укажите `--frames 5` и/или `--timeout 30` |

---

## Связанные документы

- [EXTERNAL_AGENTS.md](EXTERNAL_AGENTS.md) — как внешний агент использует CLI.
- [ANDROID.md](ANDROID.md) — сборка APK из Android-экспорта.
- [AI_PROVIDERS.md](AI_PROVIDERS.md) — провайдеры и ключи.
- [TESTING.md](TESTING.md) — автоматические и ручные проверки.
