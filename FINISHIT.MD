# FINISHIT.MD — что осталось доделать в Reasonable Engine

Рабочая папка: `C:\Users\22Edem22\Desktop\Reasonable Engine`
Python: `python` (3.13.13; pytest, PySide6, pygame-ce, Pillow, PyInstaller 6.22.3 установлены).
Установленное приложение у пользователя: `C:\Users\22Edem22\AppData\Local\Programs\Reasonable Engine`
(проекты лежат рядом, в подпапке `Projects` — их терять нельзя).
Тесты: `python -m pytest tests/<файл> -q` из корня. Сборка установщика: `python tools/build_installer.py` (Inno Setup: `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`).

---

## ✅ УЖЕ СДЕЛАНО (не переделывать)

1. **Краш pygame исправлен** (`reasonable/runtime/ui.py`): `MOUSEWHEEL` не имеет `event.pos` — добавлен хелпер `event_pos()`; исправлены `Container.handle_event` и `ScrollView.handle_event`. Найден и исправлен ВТОРОЙ баг: `Button.__init__` обращался к `self.theme` до `super().__init__()` — любая кнопка без явного `height` роняла приложение (это и было «задачи не добавляются / программа не работает»). `Entry` теперь безопасно читает `event.mod`.
2. **Защита приложения от падения**: `App.run` больше не умирает от одного плохого события проекта (лог раз в уникальный трейс, `reasonable/runtime/app.py`).
3. **Заставка неубиваемая** (`reasonable/runtime/splash.py`): убраны `RE_SKIP_SPLASH`, клик-пропуск, надпись «ПРОПУСТИТЬ›». Хедлес (`SDL_VIDEODRIVER=dummy`) завершает заставку мгновенно (нужно для проверок агента). Единственный обход — ключ разработчика: env `RE_SPLASH_DEV_TOKEN`, чей SHA-256 равен `DEV_TOKEN_HASH = "fd0575fca0f9344e27a35b70c539137200281c9a3ad8bacd11a0a5b1cccf6230"`. **Ключ разработчика (секрет, отдать пользователю): `cd800e3e93931562b9f52aa8d562929f`**. Инструмент: `tools/dev_splash_key.py` (--gen/--hash/--check).
4. **История чата**: новый модуль `reasonable/core/chatlog.py` (`.reasonable/chat.json`; API: `load_chat`, `append_message`, `recent_messages`, `clear_chat`).
5. **Прогресс без нулей**: `reasonable/core/progress.py` — `derived_percent(state)` (явный процент приоритетен, иначе доля выполненных задач) + авто-подъём процента в `set_plan`/`update_task`.
6. **Безлимитные шаги агента**: `settings.py` (`agent.max_steps` дефолт 0 = без лимита, миграция 60→0, удалён блок `preview`); `ai/agent.py` — цикл `while True`, убрано «Достигнут лимит шагов», добавлена защита от зацикливания (`_track_tool_call`/`_stuck_after_repeats`, 6 одинаковых результатов подряд → стоп с понятным сообщением), история чата сеется в контекст (`_seed_chat_history`) и сохраняется (`_persist_chat` в `finally`).
7. **Прочее**: `ai/tools.py` и `cli.py` — убраны `run_env(skip_splash=...)`/`RE_SKIP_SPLASH`/флаг `--no-splash`; `ai/prompts.py` — правила агента (не зацикливаться, сообщать прогресс, помнить историю), из промпта убран размер окна, добавлены 3 навыка уровней интерфейса (`ui-simple-tkinter.md`, `ui-standard-widgets.md`, `ui-advanced-scenes.md`), `skills_for_project(project)` (только нужные навыки), `AGENT_GUIDE` переписан (окно выбирает агент, уровень интерфейса, «без движка так круто не сделать»), `EXTERNAL_CONNECTION_GUIDE` сокращён до 3 шагов; `ai/external.py` — пишутся только нужные навыки, лишние удаляются; `core/project.py` — `ui_levels` в `default_manifest`, свойство `Project.ui_levels`, `run_env()` без splash-параметра, `summary()` без размера окна; `core/scaffold.py` — шаблон `simple` выбирается при `ui_levels == ["simple"]`, для tkinter-проектов не генерируются фон/спрайты, README переписан; тесты `tests/test_ui_events.py` (5/5 зелёные).

Проверить перед продолжением: `python -m compileall reasonable -q` и `python -m pytest tests/test_ui_events.py -q` — всё зелёное на момент передачи. (Временный файл `build/_check_splash.py` можно удалить.)

---

## 🔲 ОСТАЛОСЬ СДЕЛАТЬ

### 1. `reasonable/core/convert.py` — довести ui_levels (частично начато)
- В `conversion_plan(...)`: параметр `ui_levels: list[str] | None = None` уже добавлен в сигнатуру. В теле: нормализовать (`from .project import normalise_ui_levels`; `new_levels = normalise_ui_levels(ui_levels if ui_levels is not None else project.ui_levels, project.project_type)`), добавить в возвращаемый dict ключ `"ui_levels": new_levels`, и в `changes` строку `f"Интерфейс: {старое} → {новое}"` (метки — `from .project import UI_LEVEL_LABELS`) если отличается.
- В `convert_project(...)`: тот же параметр, пробросить в `conversion_plan`, в новом манифесте: `manifest["ui_levels"] = plan["ui_levels"]`.
- В тексте ошибки «все параметры совпадают» упомянуть интерфейс.

### 2. `reasonable/version.py`
- `VERSION = "0.2.0"`, `VERSION_NAME = "Comet"` (или похожее).

### 3. Редактор — упрощение (файлы `reasonable/editor/`)
- **project_page.py**:
  - План/задачи в «Обзоре» — ТОЛЬКО ЧТЕНИЕ: удалить кнопку «+ Задача», кнопку «% Готовность», переключение статуса кликом и контекстные меню задач; удалить их обработчики и диалоги.
  - Все проценты через `from reasonable.core.progress import derived_percent` → `derived_percent(state)`.
  - Кнопка «Экспорт» — заметная: крупнее, с глифом «⤴ Экспорт», `objectName "teal"` (стиль есть в `reasonable/editor/theme.py`), в ряду кнопок ПЕРВОЙ, перед «Запустить» (она остаётся primary).
  - Строка ~1085: убрать `skip_splash = bool((self.settings.data.get("preview") or {}).get("skip_splash"))` и вызов `self.project.run_env(skip_splash=skip_splash)` → просто `self.project.run_env()`.
  - Убрать подсказки, объясняющие удалённые кнопки.
- **chat.py**: при инициализации панели — `chatlog.load_chat(self.project.root)` и отрисовать последние ~40 сообщений (пузыри user/assistant, тул-пузыри не восстанавливать); сохранять в chatlog: отправка пользователя (role "user"), успешное завершение (assistant, финальный текст), ошибка (assistant, «⚠ »+текст); «Очистить» → `chatlog.clear_chat`; процент в панели через `derived_percent`.
- **external.py**: переработать блок инструкций — ровно 3 строки: 1) «Откройте папку проекта в вашем ИИ-агенте (Claude Code, Cursor, Codex CLI, Cline…).» 2) «Скопируйте промпт ниже и вставьте его агенту.» 3) «Прогресс появится здесь автоматически — агент обновляет его сам.» Ниже — read-only бокс с готовым промптом (самодостаточный, 2–4 предложения: работать в папке проекта, прочитать AGENT_GUIDE.md и skills/, довести проект до рабочего состояния, обновлять прогресс через re.bat, завершить через re.bat done) + большая кнопка «Скопировать промпт» (QApplication.clipboard()) + маленькая «Открыть папку проекта». УДАЛИТЬ: карточку «Команды прогресса», карточку «Созданные инструкции», подробный чеклист (заменить одной строкой «Пакет для агента готов ✓»). Живую часть сохранить (процент через derived_percent, статус, события, файлы).
- **project_settings.py**: удалить карточку окна целиком (window_mode_combo, спинбоксы ширины/высоты, resizable_check, orientation combo) — пользователь вообще не видит настройки окна; оставить название/автор/цель/заметки; в «расширенных» оставить только версию Android. Не удалять `manifest["window"]` при сохранении. Текст-подсказка: окно агент настроит сам. Почистить импорты.
- **settings_dialog.py**: удалить оба чекбокса «Пропускать заставку…» (simple_skip_splash и skip_splash) и их сохранение; удалить спинбокс max_steps, если есть (агент без лимита); провести ревизию на «мусорные» для обычного пользователя детали, НО сохранить настройки провайдера/API-ключа, папки проектов, цвета.
- **convert_dialog.py**: добавить мультивыбор уровней интерфейса (три чекбокса: «Простой (tkinter)», «Стандартный (движок)», «Продвинутый (сцены и графика)», минимум один) и передавать `ui_levels=[...]` в convert; убрать окно/размер, если показываются.
- **welcome.py / main_window.py**: поправить тексты, упоминающие размер окна или пропускаемую заставку.

### 4. Мастер создания проекта (`reasonable/editor/new_project.py`)
- Шаг 1: секция «Уровень интерфейса» (мультивыбор, минимум один):
  - «Простой (tkinter)» — «Обычные окна, кнопки и списки. Для утилит и программ Windows» → `simple`
  - «Стандартный (движок)» — «Готовые виджеты движка: тёмная тема, панели, списки, прокрутка» → `standard`
  - «Продвинутый (сцены и графика)» — «Своя графика, частицы, анимации. Для игр» → `advanced`
  - Дефолты: игра → advanced+standard; приложение → standard; blank → standard. При смене типа применять дефолты, если пользователь не трогал уровни сам.
  - Прокинуть выбор в `default_manifest(..., ui_levels=[...])`.
- Шаг 2: поле «Название проекта (латиницей)» — обязательное, валидация `^[A-Za-z][A-Za-z0-9][A-Za-z0-9 _-]{0,58}$`, подсказка «Используется для папки и файлов проекта», автозаполнение из цели допустимо, но имя задаёт пользователь; имя манифеста = это английское название.
- Итоговая страница: УДАЛИТЬ строку «Окно: 1280×720 …», ДОБАВИТЬ «Интерфейс: …» (метки уровней), убрать запись `manifest["preview"] = {"skip_splash": False}` (~строка 633).

### 5. Экспорт (`reasonable/export.py`, `reasonable/editor/workers.py`, `reasonable/editor/export_dialog.py`)
- **export.py**:
  - `ProgressCB = Callable[[str, float, float], None]` (этап, % этапа, общий %). Все экспорт-функции принимают `progress: ProgressCB | None = None` и зовут её часто (каждые ~50 файлов или 2% этапа; в начале и конце этапа).
  - Windows: Подготовка 0→4; «Копирую файлы проекта» 4→34 (инкрементально); «Встраиваю движок» 34→48; «Иконка и лаунчер» 48→58; «Сборка exe» 58→94; «Финализация» 94→100. Режим папки — без exe-этапа. Android: Подготовка 0→5; Копирование 5→35; Движок 35→50; Конфиги 50→62; ZIP 62→97 (по-файлово); Финализация 97→100.
  - `_copy_project`: заменить `shutil.copytree` на ручную рекурсивную копию с прогрессом (правила игнора сохранить: COPY_IGNORE, .pyc, .spec, точечные папки кроме .github).
  - PyInstaller: читать stdout инкрементально; % = min(92, 60 + строки*0.4); 94 при успехе.
  - **Починка «лишнего сломанного окна»**: УБРАТЬ `--collect-submodules reasonable` (тянет редактор и PySide6 в exe); оставить `--collect-data reasonable`; добавить `--exclude-module PySide6 --exclude-module shiboken6 --exclude-module reasonable.editor --exclude-module reasonable.templates`; после успешной сборки скопировать `project.json` рядом с получившимся exe (шаблоны в frozen-режиме читают манифест из папки exe — это учтено в шаблонах только после задачи 6).
  - `def desktop_dir() -> Path` (первый существующий из %USERPROFILE%\Desktop, %OneDrive%\Desktop, Path.home()/"Desktop", иначе Path.home()); `_pick_output` при `output=None` → `desktop_dir()/default_name`.
  - `export_windows(..., exe_name: str = "")`: `--name <проверенный exe_name или slug>` (^[A-Za-z][A-Za-z0-9-_]*$, санитизация через slugify), в результате ключ `"exe"` с путём. Сохранить совместимость сигнатур (проверить вызовы в `reasonable/cli.py`).
  - Удалить «Проверка без заставки: `set RE_SKIP_SPLASH=1`» из текста README в экспорте (~строка 148).
- **workers.py**: `ExportWorker` — сигнал `progress = Signal(str, float, float)`, колбэк экспорта эмитит его.
- **export_dialog.py**: поле «Имя файла .exe (латиницей)» (дефолт = slug проекта, валидация `^[A-Za-z][A-Za-z0-9_-]{0,60}$`, не давать стартовать до валидного); путь по умолчанию — Рабочий стол (строка «Папка: …» + кнопка «Изменить…» через QFileDialog); ДВЕ шкалы: «Общий прогресс» + название этапа + шкала этапа; во время работы запрещены старт и смена режима; в конце — карточка результата (путь, «Открыть папку», затраченное время); при ошибке — хвост stderr.

### 6. Шаблоны (`reasonable/templates/**`) — frozen-режим
- В `game/main.py`, `app/main.py`, `blank/main.py`: `PROJECT_DIR` с веткой `getattr(sys, "frozen", False)` → папка exe; хелпер `_project_file(relative)` — искать файл сначала в `PROJECT_DIR`, потом рядом с `__file__` (в exe ассеты лежат в _MEIPASS); `data.json` писать в папку exe.
- **Создать `reasonable/templates/simple/main.py`** — tkinter-шаблон (уровень «Простой»): сначала заставка (`from reasonable.runtime.splash import play_splash`, в try/except, после — `pygame.quit()`), затем tkinter-окно (тёмная тема ttk, акцент #D97757, заголовок = имя проекта, рабочий список задач: добавление по кнопке и Enter, отметка выполнения, удаление, счётчик, пустое состояние, сохранение в data.json атомарно, ~250–350 строк, только stdlib+tkinter, без GLFW/pygame-рендера). Токены: `__APP_NAME_REPR__`, `__APP_TITLE__` (scaffold их заменяет).

### 7. Тесты
- `tests/test_scaffold.py`: `_run_project` без `skip_splash`/`RE_SKIP_SPLASH` (env: только SDL dummy + RE_FRAMES); убрать ассерт `"RE_SKIP_SPLASH" in readme` (заменить на `assertNotIn`); проверить, что при `ui_levels=["simple"]` создаётся шаблон simple и нет assets/sprites/*.png.
- `tests/test_project.py::test_run_env_includes_project_and_engine`: убрать `skip_splash=True` и проверку `RE_SKIP_SPLASH`.
- `tests/test_export.py`: колбэк прогресса вызывается с немонотонно убывающим общим % на папочном экспорте во tmp (явный output, не Desktop!); `desktop_dir()` возвращает существующую папку; убрать RE_SKIP_SPLASH-ассерты.
- `tests/test_progress.py`: добавить кейсы `derived_percent` (явный процент приоритетен; 0 задач → 0; 2/4 done → 50).
- Новый `tests/test_chatlog.py`: append/load/clear/recent.
- Прогнать ВСЁ: `python -m pytest tests/ -q` — все зелёные.

### 8. Документация
- Корневой `README.md`: убрать упоминания RE_SKIP_SPLASH/настроек окна; описать уровни интерфейса, экспорт на рабочий стол, англ. имя проекта.
- `docs/EXTERNAL_AGENTS.md`: сократить до формата «открыть папку → вставить промпт → смотреть прогресс».
- Создать `docs/DEV_SPLASH_KEY.md`: секретный ключ разработчика заставки `cd800e3e93931562b9f52aa8d562929f` + команда `setx RE_SPLASH_DEV_TOKEN <ключ>` + объяснение (только владелец движка; хеш вшит в bytecode).
- Выполнить для пользователя: `setx RE_SPLASH_DEV_TOKEN cd800e3e93931562b9f52aa8d562929f` (чтобы на ЕГО машине заставку можно было убирать — он и есть разработчик движка).

### 9. Сборка и переустановка (обязательно в конце)
1. `python tools/build_installer.py` (сборит protected-байткод, ReasonablePlayer.exe, портативный Python, ReasonableEngine.exe и Inno Setup). Дождаться `ReasonableEngine-Setup-0.2.0.exe` в `dist/`.
2. БЭКАП: скопировать `C:\Users\22Edem22\AppData\Local\Programs\Reasonable Engine\Projects` во временную папку (не терять!).
3. Запустить `dist\ReasonableEngine-Setup-0.2.0.exe /SILENT` (UsePreviousAppDir — установится туда же; [InstallDelete] стирает только runtime\python; папка Projects сохраняется).
4. Обновить встроенный движок в СУЩЕСТВУЮЩИХ проектах, чтобы применить фиксы (ui.py/Button/заставка): для каждого проекта из `...\Reasonable Engine\Projects\*` выполнить вендоринг из нового защищённого байткода: запустить python с env `REASONABLE_ENGINE_SOURCE=<путь к распакованному engine_source_pyc из нового exe>` — либо проще: открыть каждый проект в новом редакторе, если добавить авто-синк (опционально: в ProjectPage при открытии, если `manifest.engine_version != VERSION` — фоново `project.sync_engine()`).
5. Проверить падавший проект пользователя `udobnaya-programma-upravlyayuschaya-internet-tra`: headless-запуск с SDL dummy + RE_FRAMES=5 через портативный python — не должно быть AttributeError по event.pos; скролл колесом — без краша.
6. Финальная проверка по списку претензий пользователя (см. разделы выше) и отчёт пользователю: что исправлено, ключ заставки, как переносились проекты.

---

## Ключевые контракты (не сломать)
- `derived_percent(state: dict) -> float` — в `reasonable/core/progress.py`.
- `chatlog.load_chat/append_message/recent_messages/clear_chat(project_dir, ...)` — в `reasonable/core/chatlog.py`.
- `default_manifest(..., ui_levels: list[str] | None = None)`, `Project.ui_levels`, `normalise_ui_levels`, `UI_LEVELS`, `UI_LEVEL_LABELS` — в `reasonable/core/project.py`.
- `run_env()` больше НЕ принимает `skip_splash` — все вызовы уже обновлены; не добавлять обратно.
- Заставка: никаких `RE_SKIP_SPLASH`/`skip_splash` нигде; только `developer_splash_bypass()` (RE_SPLASH_DEV_TOKEN) и headless-dummy.
- Экспорт: `progress: Callable[[str, float, float], None]` — (этап, %этапа, общий%).
