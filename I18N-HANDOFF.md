# Задание для ИИ-агента: завершить двуязычность (RU/EN) Reasonable Engine

Ты видишь этот проект впервые. Это бриф на продолжение незавершённой работы.
Работай в корне репозитория. Не переписывай сделанное — только доделай перечисленное.

## 1. Контекст проекта

Reasonable Engine — конструктор игр/приложений (Python + pygame + PySide6):
- `reasonable/editor/*` — редактор на PySide6 (весь UI пользователя).
- `reasonable/core/*` — ядро: `i18n.py`, `settings.py`, `paths.py`, `convert.py`, `scaffold.py`, `history.py`, `progress.py`, `project.py`.
- `reasonable/ai/*` — встроенный ИИ-агент (`agent.py`, `tools.py`, `prompts_en.py`, `providers.py`, `client.py`, `sprites.py`).
- `reasonable/runtime/*` — pygame-рантайм, вендорится в проекты (`_engine/reasonable`, включая `core/i18n.py`).
- `installer/ReasonableEngine.iss` — Inno Setup 6; `tools/build_installer.py`.
- Тесты: `python -m pytest tests -q` (для Qt-тестов ставится `QT_QPA_PLATFORM=offscreen`).

## 2. Цель задачи (не менять!)

Пользователь выбирает русский/английский **в установщике** → весь установщик, весь редактор
и вся установленная программа работают **на выбранном языке**. Материал для ИИ-агента
(инструменты, навыки, гайды, промпты) — **только английский**. Агент отвечает **на языке
задачи пользователя** (кириллица → русский ответ, латиница → английский).

## 3. Механика i18n (уже реализована, используй как есть)

- `reasonable/core/i18n.py`: `t(key, **values)` — берёт пару из `TRANSLATIONS`;
  `current_language()` = env `REASONABLE_LANG` → override → `settings.json` (`ui.language`)
  → маркер установщика → `"ru"`. `set_override()`, `invalidate_cache()`,
  `detect_user_language()`, `task_language_note()`, `splash_caption()`.
- Пары: `_pair("русский", "english")`. Перевод — через `.format(**values)`, плейсхолдеры `{name}`.
- Отсутствующий ключ → возвращается сам ключ (для динамических ключей есть приём-фолбэк,
  см. `_tl()` в `editor/project_page.py`).
- Импорт в editor-файлах: `from reasonable.core.i18n import t`.

## 4. Конвенции (соблюдать строго)

1. Русский текст в `_pair(...)` — **байт-в-байт** прежний литерал (тесты сверяют русские строки!).
2. Ключи ASCII: `<префикс>.<snake_case>`. Префиксы: `settings.`, `projectpage.`, `newproj.`,
   `projset.`, `chat.`, `workers.`, `widgets.`, `export.` (только core/export.py),
   `exportdlg.` (editor/export_dialog.py), `historydlg.`, `convdlg.`, `extpanel.`,
   `assets.`, `code.`, `aipanel.` (runtime/ai.py), `cli.`, `branding.`
   Занятые чужие префиксы: `history.*`, `convert.*`, `external.*`, `welcome.*`, `progress.*`,
   `common.*`, `menu.*`, `status.*`, `dialog.*` — их **переиспользовать**, не дублировать.
3. НЕ переводить: имена провайдеров/моделей, URL, пути, команды, `re.bat`, имена файлов,
   бренд «Reasonable Engine», «Windows»/«Android», техтокены.
4. Существующие ключи сначала искать в `TRANSLATIONS` (читай `core/i18n.py` перед работой).
5. Новый блок ключей добавляй в `i18n.py` секцией с комментарием-заголовком.
6. НЕ трогать: `ai/tools.py` (кириллица только внутри `_t("EN", "RU")` пар — это норма),
   `ai/prompts_en.py` (4 строки кириллицы — легитимные подсказки пользователя),
   `templates/*`, содержимое project-файлов.

## 5. Якоря тестов (нарушишь — упадут тесты)

- `tests/test_editor.py` (язык по умолчанию ru): кнопки навигации `["Обзор", "ИИ-агент", "Код", "Ассеты"]`;
  `side_meta` содержит `Интерфейс:`; кнопка `Конвертировать…`; мастер: сводка содержит
  `Интерфейс:`, `внешний агент`, `встроенный ИИ`, `Пустой проект`; `mode_hint` содержит
  `Внешний агент` и `Встроенный`; welcome-кнопки содержат `ИИ`, `Открыть`, `Пустой`;
  external-панель: `Пока задача не написана`, `Задача добавлена в промпт`, `ПЕРВАЯ ЗАДАЧА`, `re.bat done`.
- `tests/test_convert.py`: русские строки изменений конвертации (`Платформа:`, `внешний агент`, `полный экран`).
- Русские тексты в парах уже подобраны так, чтобы всё выше проходило — не «улучшай» их.

## 6. Что УЖЕ сделано (не переделывать)

- 4 падающих теста починены; полный сет: `122 passed`.
- Установщик: диалог языка RU/EN (`ShowLanguageDialog=yes`, Russian.isl + Default.isl),
  `[CustomMessages]` на двух языках, пост-инсталл маркер `%APPDATA%\ReasonableEngine\installer-language.txt`;
  `i18n.read_installer_language()` + `Settings._consume_installer_language()` переносят выбор
  в `settings.json` (`ui.language`) и удаляют маркер. Тесты `InstallerLanguageTests`.
- Полностью локализованы: `editor/settings_dialog.py` (+ переключатель «Язык интерфейса»
  с сохранением и подсказкой о перезапуске), `editor/project_page.py`, `editor/new_project.py`.
- В `i18n.py` добавлены секции `settings.*`, `projectpage.*`, `newproj.*`, `convert.*`.

## 7. Что ОСТАЛОСЬ сделать (порядок важен)

1. `editor/project_settings.py` (22 кириллические строки) — префикс `projset.`.
   Простые литералы: заголовки, QFormLayout-подписи (`addRow("Название", ...)` — обернуть в t()),
   QMessageBox, Badge «ИГРА/ПРИЛОЖЕНИЕ» (переиспользуй `projectpage.badge_game/badge_app`),
   «ВСТРОЕННЫЙ/ВНЕШНИЙ» (новые ключи `projset.badge_builtin/badge_external`).
2. `editor/chat.py` (70) + `editor/workers.py` (8) + `editor/widgets.py` (2) — префиксы `chat.`, `workers.`, `widgets.`.
   В workers.py — сообщения этапов скаффолдинга (эмитятся в `progress_stage`).
3. `editor/export_dialog.py` (69) — префикс `exportdlg.`; и `editor/history_dialog.py` (47) —
   переиспользуй `history.*`, новое — `historydlg.`.
4. `editor/convert_dialog.py` (60) — префикс `convdlg.` (переиспользуй `convert.*`), и
   `editor/external.py` (59) — префикс `extpanel.` (переиспользуй `external.check_*`).
   В external.py: шаблон промпта для внешнего агента — заголовок «ПЕРВАЯ ЗАДАЧА» через t()
   (ru — прежний текст!), служебные английские куски не трогать.
5. `editor/assets.py` (56) — префикс `assets.`; `editor/code.py` (51) — префикс `code.`.
6. `editor/welcome.py` (44) — переиспользуй `welcome.*`; `editor/main_window.py` (30) —
   замени `branding.TAGLINE_RU` в заголовке окна на `i18n.tagline()`, статус «…готова к работе»
   на `t("status.ready")`, проверь остальные литералы (префикс `main.`).
7. `core/branding.py` (2) — если там только TAGLINE_RU/TAGLINE_EN, оставь (используется i18n);
   `reasonable/__main__.py` (3) — локализуй через t() (префикс `main.`).
8. `runtime/splash.py` (1) — подключи: `self.sub = i18n.splash_caption()` c
   `try/except Exception` фолбэком на прежнюю строку (рантайм вендорится в проекты —
   `core/i18n.py` там есть; import внутри функции, как в `_load_logo`).
9. `runtime/ai.py` (24) — префикс `aipanel.`; `runtime/app.py`, `ui.py`, `audio.py`,
   `graphics.py`, `utils.py` — по 1–3 строки, префикс `rt.`.
10. `ai/providers.py` (76) — русские описания/примечания пресетов видны в настройках.
    Локализуй через `t()` при построении пресетов (ключи `provider.<id>.name/.description/.note`),
    группирующие названия — `provider.group_*`. Названия «Свой сервер (…)» локализуй,
    но сверься с проверкой `startswith(("Свой ", "Custom "))` в `editor/settings_dialog.py::_list_name`.
11. `reasonable/cli.py` (71) и `reasonable/export.py` (83) — вывод CLI в консоль;
    префиксы `cli.` и `export.`. Осторожно: часть сообщений идёт в файлы проекта
    (если найдёшь такие — оставь как есть и отметь в отчёте).
12. `ai/agent.py` (40), `ai/client.py` (30), `ai/sprites.py` (31) — проверь: если кириллица
    внутри `_t(...)`/`t(...)` пар — это норма, не трогай; голые русские литералы — оберни.
13. Финал: `python -m pytest tests -q` — все зелёные; `git diff --stat` — только ожидаемые файлы.

## 8. Проверка руками

- `REASONABLE_LANG=en python -m reasonable` — редактор на английском.
- `REASONABLE_LANG=ru python -m reasonable` — на русском.
- Переключатель в «Настройках» меняет `ui.language`, после перезапуска язык применяется.

## 9. Ограничения среды

- Параллельные субагенты в этой среде нестабильны — работай сам, последовательно.
- Правки только через read/edit/write; после каждого файла — `python -m py_compile <файл>`.
- Не запускай сборку установщика (нужен Inno Setup) — ограничься проверкой синтаксиса .iss вручную.
