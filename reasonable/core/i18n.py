"""Runtime language support for the editor and the installed program.

The Windows installer asks for a language (Russian or English) on its first
page and writes the choice into ``settings.json`` (``ui.language``). Every part
of the application reads it through this module:

* ``t(key, **values)`` returns a translated UI string; Russian stays the
  default so existing installs behave exactly as before.
* :func:`agent_language_note` tells the built-in AI agent (whose tools and
  skills ship only in English) which language the *user's task* is written in,
  so the agent answers in that same language.

The language can also be forced with the ``REASONABLE_LANG`` environment
variable (``ru``/``en``, also used by the splash screen of exported games).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

SUPPORTED_LANGUAGES = ("ru", "en")
DEFAULT_LANGUAGE = "ru"

# Cyrillic letters are enough to recognise a Russian-language request.
_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")

_ACTIVE_OVERRIDE: str | None = None
_CACHED_SETTINGS_LANGUAGE: str | None = None
_CACHED_SETTINGS_PATH: str | None = None


def normalize_language(value: Any) -> str:
    """Map anything ('RU', 'en-US', 'russian') onto 'ru' or 'en'."""
    text = str(value or "").strip().lower()
    if text.startswith("en"):
        return "en"
    if text.startswith("ru"):
        return "ru"
    return DEFAULT_LANGUAGE


def settings_file_path() -> Path:
    from .paths import settings_path

    return settings_path()


def read_settings_language() -> str:
    """Language stored in settings.json without importing the Settings class."""
    global _CACHED_SETTINGS_LANGUAGE, _CACHED_SETTINGS_PATH
    path = settings_file_path()
    key = str(path)
    if _CACHED_SETTINGS_PATH == key and _CACHED_SETTINGS_LANGUAGE is not None:
        return _CACHED_SETTINGS_LANGUAGE
    language = DEFAULT_LANGUAGE
    try:
        from .paths import read_json

        data = read_json(path, {})
        if isinstance(data, dict):
            ui = data.get("ui")
            if isinstance(ui, dict):
                language = normalize_language(ui.get("language"))
    except Exception:
        language = DEFAULT_LANGUAGE
    _CACHED_SETTINGS_PATH = key
    _CACHED_SETTINGS_LANGUAGE = language
    return language


def invalidate_cache() -> None:
    global _CACHED_SETTINGS_LANGUAGE
    _CACHED_SETTINGS_LANGUAGE = None


def current_language() -> str:
    """Active language: env override > explicit set_override > settings.json."""
    if _ACTIVE_OVERRIDE:
        return _ACTIVE_OVERRIDE
    env = os.environ.get("REASONABLE_LANG", "").strip()
    if env:
        return normalize_language(env)
    return read_settings_language()


def set_override(language: str | None) -> None:
    """Force the language for the running process (used by tests and bootstrap)."""
    global _ACTIVE_OVERRIDE
    _ACTIVE_OVERRIDE = normalize_language(language) if language else None


def detect_user_language(text: str) -> str:
    """Language of the user's own task — what the AI agent must reply in."""
    return "ru" if _CYRILLIC_RE.search(text or "") else "en"


_TASK_LANGUAGE_NOTES = {
    "ru": (
        "[SYSTEM NOTE] The user's task below is written in Russian. "
        "Reply to the user strictly in Russian until they switch languages. "
        "Tool names, code and file contents stay in English."
    ),
    "en": (
        "[SYSTEM NOTE] The user's task below is written in English. "
        "Reply to the user strictly in English until they switch languages. "
        "Tool names, code and file contents stay in English."
    ),
}


def task_language_note(text: str) -> str:
    """Instruction injected before a user message so the agent answers in the
    language of exactly that task (tools/skills themselves are English-only)."""
    return _TASK_LANGUAGE_NOTES[detect_user_language(text)]


def t(key: str, **values: Any) -> str:
    """Translate ``key`` into the active language, then interpolate values.

    Agent tool/skill material is English-only by design (see
    :mod:`reasonable.ai.prompts_en`); a missing key therefore falls back to
    the key text itself instead of crashing — except for ``tools.<ru literal>``
    schema keys, which must exist so the Russian UI stays translated.
    """
    table = TRANSLATIONS.get(key)
    if not table:
        if key.startswith("tools.") and _CYRILLIC_RE.search(key):
            raise KeyError(f"Unknown translation key: {key}")
        return key
    template = table.get(current_language())
    if template is None:
        template = table[DEFAULT_LANGUAGE]
    if values:
        try:
            return template.format(**values)
        except (KeyError, IndexError, ValueError):
            return template
    return template


def tagline() -> str:
    return t("app.tagline")


def splash_caption() -> str:
    """Caption under the logo on the intro splash (works without settings.json,
    e.g. inside exported standalone games)."""
    env = os.environ.get("REASONABLE_LANG", "").strip()
    language = normalize_language(env) if env else read_settings_language()
    return SPLASH_CAPTIONS.get(language, SPLASH_CAPTIONS[DEFAULT_LANGUAGE])


SPLASH_CAPTIONS = {
    "ru": "СОЗДАВАЙ. ИГРАЙ. РАЗУМНО.",
    "en": "CREATE. PLAY. REASONABLY.",
}


def _pair(russian: str, english: str) -> dict[str, str]:
    return {"ru": russian, "en": english}


TRANSLATIONS: dict[str, dict[str, str]] = {
    # -- brand ---------------------------------------------------------
    "app.tagline": _pair("Разумный движок для смелых идей", "A reasonable way to make games"),
    "app.title": _pair("Reasonable Engine — {tagline}", "Reasonable Engine — {tagline}"),
    # -- main window: menus -------------------------------------------
    "menu.file": _pair("Файл", "&File"),
    "menu.project": _pair("Проект", "&Project"),
    "menu.help": _pair("Помощь", "&Help"),
    "menu.new_project": _pair("Новый проект с ИИ…", "New AI project…"),
    "menu.blank_project": _pair("Пустой проект вручную…", "Blank project by hand…"),
    "menu.open_project": _pair("Открыть проект…", "Open project…"),
    "menu.recent": _pair("Недавние проекты", "Recent projects"),
    "menu.recent_empty": _pair("Пока нет проектов", "No projects yet"),
    "menu.recent_clear": _pair("Очистить список", "Clear list"),
    "menu.settings": _pair("Настройки…", "Settings…"),
    "menu.quit": _pair("Выход", "Exit"),
    "menu.run": _pair("Запустить проект", "Run project"),
    "menu.export": _pair("Экспорт…", "Export…"),
    "menu.convert": _pair("Конвертировать в новый проект…", "Convert to a new project…"),
    "menu.project_settings": _pair("Настройки проекта…", "Project settings…"),
    "menu.history": _pair("История версий…", "Version history…"),
    "menu.delete_project": _pair("Удалить проект…", "Delete project…"),
    "menu.back_to_list": _pair("К списку проектов", "Back to project list"),
    "menu.about": _pair("О Reasonable Engine", "About Reasonable Engine"),
    "menu.open_readme": _pair("Открыть README", "Open README"),
    "section.overview": _pair("Обзор", "Overview"),
    "section.agent": _pair("ИИ-агент", "AI agent"),
    "section.code": _pair("Код", "Code"),
    "section.assets": _pair("Ассеты", "Assets"),
    # -- main window: status & dialogs ---------------------------------
    "status.ready": _pair(
        "Reasonable Engine {version_name} ({version_label}) готова к работе.",
        "Reasonable Engine {version_name} ({version_label}) is ready.",
    ),
    "status.welcome_hint": _pair(
        "Выберите недавний проект или создайте новый.",
        "Pick a recent project or create a new one.",
    ),
    "status.settings_saved": _pair("Настройки сохранены.", "Settings saved."),
    "status.recents_updated": _pair("Список проектов обновлён.", "Project list updated."),
    "status.project_deleted": _pair("Проект «{name}» удалён с диска.", "Project “{name}” was deleted from disk."),
    "status.not_a_project": _pair(
        "Папка не похожа на проект Reasonable Engine — удаление отменено.",
        "This folder does not look like a Reasonable Engine project — deletion cancelled.",
    ),
    "dialog.open_project_title": _pair(
        "Открыть проект Reasonable Engine", "Open a Reasonable Engine project"
    ),
    "dialog.open_failed_title": _pair("Не удалось открыть проект", "Could not open the project"),
    "dialog.project_running_title": _pair("Проект запущен", "Project is running"),
    "dialog.project_running_text": _pair(
        "Проект ещё запущен. Остановить его и переключиться?",
        "The project is still running. Stop it and switch?",
    ),
    "dialog.delete_title": _pair("Удалить проект", "Delete project"),
    "dialog.delete_text": _pair("Удалить проект «{name}»?", "Delete the project “{name}”?"),
    "dialog.delete_info": _pair(
        "Можно убрать проект только из списка недавних или удалить папку проекта с диска:\n{path}",
        "You can either remove the project from the recent list only, or delete its folder from disk:\n{path}",
    ),
    "dialog.delete_remove": _pair("Убрать из списка", "Remove from list"),
    "dialog.delete_disk": _pair("Удалить с диска", "Delete from disk"),
    "dialog.delete_no_manifest": _pair(
        "В этой папке нет project.json — удаление с диска недоступно.",
        "There is no project.json in this folder — deleting from disk is unavailable.",
    ),
    "dialog.delete_protected_title": _pair("Удаление проекта", "Deleting the project"),
    "dialog.delete_protected_text": _pair(
        "Эта папка защищена: удалять её целиком нельзя. Проект убран из списка.",
        "This folder is protected: it cannot be deleted entirely. The project was removed from the list.",
    ),
    "dialog.delete_failed_title": _pair("Не удалось удалить проект", "Could not delete the project"),
    "dialog.delete_failed_text": _pair(
        "Папка проекта не удалена:\n{error}\n\nПроект убран из списка недавних.",
        "The project folder was not deleted:\n{error}\n\nThe project was removed from the recent list.",
    ),
    "about.text": _pair(
        "<p style='color:#9AA1AB'>версия {version_label} · {tagline}</p>"
        "<p>Редактор игр и приложений с ИИ-агентом, спрайтами, живым прогрессом "
        "и экспортом на Windows и Android.</p>",
        "<p style='color:#9AA1AB'>version {version_label} · {tagline}</p>"
        "<p>A game and app editor with a built-in AI agent, sprites, live progress "
        "and export to Windows and Android.</p>",
    ),
    "docs.title": _pair("Документация", "Documentation"),
    "docs.readme_missing": _pair("README.md не найден.", "README.md was not found."),
    "error.unexpected_title": _pair("Неожиданная ошибка", "Unexpected error"),
    "error.unexpected_text": _pair(
        "Reasonable Engine столкнулась с ошибкой, но продолжает работу.",
        "Reasonable Engine hit an error but keeps running.",
    ),
    # -- welcome page ---------------------------------------------------
    "welcome.version_line": _pair("версия {version} · {tagline}", "version {version} · {tagline}"),
    "welcome.settings": _pair("Настройки", "Settings"),
    "welcome.eyebrow": _pair("РЕДАКТОР ИГР И ПРИЛОЖЕНИЙ", "GAME AND APP EDITOR"),
    "welcome.heading": _pair("Создайте игру\nиз одной идеи", "Make a game\nfrom a single idea"),
    "welcome.intro": _pair(
        "Три пути — без анкеты и без обязательной настройки ИИ. Создайте проект с агентом, "
        "откройте готовый или начните с пустого файла вручную. Провайдера и модель спросим "
        "только тогда, когда они действительно понадобятся.",
        "Three ways in — no questionnaire, no mandatory AI setup. Create a project with the "
        "agent, open an existing one, or start from an empty file by hand. We only ask about "
        "the provider and model when they are really needed.",
    ),
    "welcome.create_ai": _pair("Создать с ИИ", "Create with AI"),
    "welcome.create_ai_tip": _pair(
        "Опишите идею — агент соберёт игру или приложение.",
        "Describe the idea — the agent builds the game or app.",
    ),
    "welcome.open_project": _pair("Открыть проект", "Open project"),
    "welcome.open_project_tip": _pair(
        "Выбрать существующую папку проекта.", "Choose an existing project folder."
    ),
    "welcome.blank_project": _pair("Пустой проект", "Blank project"),
    "welcome.blank_project_tip": _pair(
        "Минимальный main.py и сразу редактор кода.", "A minimal main.py and straight into the code editor."
    ),
    "welcome.external_guide": _pair("Как подключить внешнего агента", "How to connect an external agent"),
    "welcome.what_next": _pair("ЧТО БУДЕТ ДАЛЬШЕ", "WHAT HAPPENS NEXT"),
    "welcome.step1_title": _pair("Сразу к результату", "Straight to results"),
    "welcome.step1_text": _pair(
        "Проект создаётся без выбора провайдера и длинной анкеты.",
        "Projects are created without picking a provider or filling a long form.",
    ),
    "welcome.step2_title": _pair("Прозрачный агент", "A transparent agent"),
    "welcome.step2_text": _pair(
        "Видно, какие файлы он меняет, что получилось и что сломалось.",
        "See which files it changes, what worked and what broke.",
    ),
    "welcome.step3_title": _pair("История и откат", "History and rollback"),
    "welcome.step3_text": _pair(
        "Перед каждым запуском агента сохраняется рабочая версия.",
        "A working version is saved before every agent run.",
    ),
    "welcome.recent_projects": _pair("Недавние проекты", "Recent projects"),
    "welcome.recent_hint": _pair(
        "Продолжите с того места, где остановились.", "Pick up where you left off."
    ),
    "welcome.recent_empty": _pair(
        "Пока пусто. Создайте первый проект — это займёт минуту.",
        "Nothing here yet. Creating your first project takes a minute.",
    ),
    "welcome.ai_helper": _pair("ИИ-помощник", "AI helper"),
    "welcome.ai_checking": _pair("Проверка", "Checking"),
    "welcome.ai_hint": _pair(
        "Провайдер и модель понадобятся только для встроенного агента. Можно создать "
        "проект и сначала посмотреть его.",
        "A provider and model are only needed for the built-in agent. You can create a "
        "project and look around first.",
    ),
    "welcome.configure_ai": _pair("Настроить ИИ", "Configure AI"),
    "welcome.footer_splash": _pair(
        "Заставка Reasonable Engine всегда играет перед запуском проекта.",
        "The Reasonable Engine splash always plays before a project starts.",
    ),
    "welcome.projects_folder": _pair("Проекты: {path}", "Projects: {path}"),
    "welcome.projects_folder_tip": _pair(
        "Папка по умолчанию для новых проектов. Меняется в настройках.",
        "Default folder for new projects. Change it in settings.",
    ),
    "welcome.external_title": _pair("Внешний агент", "External agent"),
    "welcome.external_text": _pair(
        "Выберите «Внешний агент» при создании проекта. Редактор создаст AGENT_GUIDE.md, "
        "skills/, re.bat и покажет прогресс агента в разделе «ИИ-агент».",
        "Choose “External agent” when creating a project. The editor generates AGENT_GUIDE.md, "
        "skills/, re.bat and shows the agent's progress in the “AI agent” section.",
    ),
    "welcome.ai_need_key": _pair("Нужен ключ", "Key required"),
    "welcome.ai_need_key_text": _pair(
        "Встроенный агент попросит ключ, когда вы впервые попросите его изменить проект. "
        "Создание проекта и ручная работа доступны без него.",
        "The built-in agent will ask for a key the first time you ask it to change the project. "
        "Creating projects and manual work do not need it.",
    ),
    "welcome.ai_add_key": _pair("Добавить ключ", "Add a key"),
    "welcome.ai_ready": _pair("Готов", "Ready"),
    "welcome.ai_key_saved": _pair("Ключ сохранён", "Key saved"),
    "welcome.ai_no_key_needed": _pair("Работает без ключа", "Works without a key"),
    "welcome.ai_check_settings": _pair("Проверить настройки", "Check settings"),
    "welcome.ai_not_selected": _pair("Не выбран", "Not selected"),
    "welcome.ai_model_unspecified": _pair("модель не указана", "no model set"),
    "welcome.default_project_name": _pair("Проект", "Project"),
    # -- shared / generic ------------------------------------------------
    "common.cancel": _pair("Отмена", "Cancel"),
    "common.close": _pair("Закрыть", "Close"),
    "common.browse": _pair("Выбрать…", "Browse…"),
    "common.next": _pair("Далее", "Next"),
    "common.back": _pair("Назад", "Back"),
    "common.folder": _pair("Папка", "Folder"),
    "common.name": _pair("Название", "Name"),
    "common.game": _pair("Игра", "Game"),
    "common.app": _pair("Приложение", "App"),
    "common.not_set": _pair("не указано", "not set"),
    "common.type_game": _pair("игра", "game"),
    "common.type_app": _pair("приложение", "app"),
    # -- project validation issues (core/project.py) --------------------
    "project.new_name": _pair("Новый проект", "New project"),
    "project.manifest_missing": _pair(
        "В папке нет корректного {file}: {path}", "No valid {file} in this folder: {path}"
    ),
    "project.outside_folder": _pair(
        "Нельзя выйти за пределы папки проекта.", "You cannot leave the project folder."
    ),
    "project.file_too_big": _pair("Файл слишком большой для чтения.", "The file is too large to read."),
    "project.cannot_delete_root": _pair(
        "Нельзя удалить корень проекта.", "The project root cannot be deleted."
    ),
    "project.entry_not_found": _pair(
        "Точка входа не найдена: {entry}", "Entry point not found: {entry}"
    ),
    "project.entry_missing": _pair(
        "Нет точки входа {entry}", "The entry point {entry} is missing"
    ),
    "project.no_assets_folder": _pair(
        "Отсутствует папка {folder}/", "The {folder}/ directory is missing"
    ),
    "project.syntax_error": _pair(
        "Синтаксис: {message} (строка {line})", "Syntax: {message} (line {line})"
    ),
    "project.goal_missing": _pair(
        "Не заполнена главная цель проекта.", "The main project goal is empty."
    ),
    "project.entry_not_python": _pair(
        "Точка входа не является Python-файлом.", "The entry point is not a Python file."
    ),
    "project.no_state_file": _pair(
        "Агент ещё не создал progress/state.json.", "The agent has not created progress/state.json yet."
    ),
    "project.validation_ok": _pair(
        "Проект выглядит корректно: синтаксис и структура в порядке.",
        "The project looks good: syntax and structure are fine.",
    ),
    "project.summary": _pair(
        "{name} — {kind}, {platform}, интерфейс: {levels}, режим {mode}.",
        "{name} — {kind}, {platform}, UI: {levels}, {mode} mode.",
    ),
    "project.ui_simple": _pair("Простой (tkinter)", "Simple (tkinter)"),
    "project.ui_standard": _pair("Стандартный (движок)", "Standard (engine widgets)"),
    "project.ui_advanced": _pair("Продвинутый (сцены и графика)", "Advanced (scenes and graphics)"),
    # -- progress defaults (core/progress.py) ---------------------------
    "progress.idle_stage": _pair("Ожидание", "Idle"),
    "progress.heartbeat": _pair("Агент работает", "Agent is working"),
    "progress.task_numbered": _pair("Задача {index}", "Task {index}"),
    "progress.plan_updated": _pair("План работ обновлён", "Work plan updated"),
    "progress.task_not_found": _pair("Задача не найдена: {ref}", "Task not found: {ref}"),
    "progress.task_status": _pair("Задача «{title}»: {status}", "Task “{title}”: {status}"),
    "progress.done_message": _pair("Проект готов", "Project is ready"),
    "progress.done_stage": _pair("Готово", "Done"),
    # -- snapshots (core/history.py) -------------------------------------
    "history.agent_run": _pair("Запуск ИИ-агента", "AI agent run"),
    "history.manual": _pair("Ручной снимок", "Manual snapshot"),
    "history.before_restore": _pair("Перед восстановлением", "Before restore"),
    "history.before_run": _pair("Перед запуском", "Before run"),
    "history.snapshot": _pair("Снимок", "Snapshot"),
    "history.root_missing": _pair("Папка проекта не найдена: {path}", "Project folder not found: {path}"),
    "history.snapshot_created": _pair("Снимок проекта: {label}", "Project snapshot: {label}"),
    "history.snapshot_not_found": _pair("Снимок не найден: {id}", "Snapshot not found: {id}"),
    "history.snapshot_empty": _pair("В снимке нет файлов.", "The snapshot contains no files."),
    "history.before_restore_label": _pair(
        "Перед восстановлением версии", "Before restoring a version"
    ),
    "history.restored": _pair("Восстановлена версия «{label}»", "Restored version “{label}”"),
    "history.changed_files": _pair(" · изменено {count} файл(ов)", " · {count} file(s) changed"),
    # -- scaffolding documents (core/scaffold.py) -------------------------
    "scaffold.goal_placeholder": _pair(
        "Цель пока не описана — добавьте её в настройках проекта.",
        "The goal is not described yet — add it in the project settings.",
    ),
    "scaffold.notes_placeholder": _pair(
        "Первая задача агенту пишется уже после создания проекта — в разделе «ИИ-агент».",
        "The first task for the agent is written after the project exists — in the “AI agent” section.",
    ),
    "scaffold.none_word": _pair("нет", "none"),
    "scaffold.mode_builtin": _pair("встроенный ИИ-агент", "built-in AI agent"),
    "scaffold.mode_external": _pair("внешний ИИ-агент", "external AI agent"),
    # -- CLI output -------------------------------------------------------
    "cli.status_line": _pair("Статус: {status}  ·  {percent}%", "Status: {status}  ·  {percent}%"),
    "cli.stage_line": _pair("Этап: {stage}", "Stage: {stage}"),
    "cli.message_line": _pair("Сообщение: {message}", "Message: {message}"),
    "cli.tasks_line": _pair("Задачи: {done}/{total}", "Tasks: {done}/{total}"),
    "cli.updated_line": _pair("Обновлено: {time}", "Updated: {time}"),
    "cli.folder_line": _pair("Папка: {path}", "Folder: {path}"),
    "cli.dash": _pair("—", "—"),
    "cli.import_error": _pair(
        "Reasonable Engine: не удалось загрузить редактор.\nПричина: {error}\n\n"
        "Установите зависимости:\n  python -m pip install -r requirements.txt\n",
        "Reasonable Engine: could not load the editor.\nReason: {error}\n\n"
        "Install the dependencies:\n  python -m pip install -r requirements.txt\n",
    ),
    "cli.editor_not_started": _pair(
        "Reasonable Engine: редактор не запущен.\nПричина: {error}\n\n"
        "Установите зависимости:\n  python -m pip install -r requirements.txt\n",
        "Reasonable Engine: the editor did not start.\nReason: {error}\n\n"
        "Install the dependencies:\n  python -m pip install -r requirements.txt\n",
    ),
    # -- agent tool messages & schemas (ai/tools.py) ---------------
    "tools. 100% зарезервировано до успешной проверки и запуска проекта.": _pair(" 100% зарезервировано до успешной проверки и запуска проекта.", " 100% is reserved until the project passes validation and launches."),
    "tools. Проверьте бесконечные циклы/диалоги.": _pair(" Проверьте бесконечные циклы/диалоги.", " Check for infinite loops/dialogs."),
    "tools.3–8 выполнимых задач по порядку": _pair("3–8 выполнимых задач по порядку", "3–8 concrete tasks in order"),
    "tools.Pillow не установлен.": _pair("Pillow не установлен.", "Pillow is not installed."),
    "tools.id задачи (t1), номер или название": _pair("id задачи (t1), номер или название", "task id (t1), number or title"),
    "tools.old_text не может быть пустым.": _pair("old_text не может быть пустым.", "old_text cannot be empty."),
    "tools.run_project ещё не завершился успешно": _pair("run_project ещё не завершился успешно", "run_project has not succeeded yet"),
    "tools.validate_project ещё не пройден без ошибок": _pair("validate_project ещё не пройден без ошибок", "validate_project has not passed without errors yet"),
    "tools.Выполнить команду в папке проекта (например, python -m pytest или python -m py_compile main.py).": _pair("Выполнить команду в папке проекта (например, python -m pytest или python -m py_compile main.py).", "Run a command inside the project folder (e.g. python -m pytest or python -m py_compile main.py)."),
    "tools.Глубина обхода": _pair("Глубина обхода", "Traversal depth"),
    "tools.Завершать работу рано. Не выполнено: {missing}. Продолжай: измени файлы проекта, запусти validate_project, исправь ошибки и запусти run_project. Установка библиотеки или чтение файлов не считается выполненной задачей.": _pair("Завершать работу рано. Не выполнено: {missing}. Продолжай: измени файлы проекта, запусти validate_project, исправь ошибки и запусти run_project. Установка библиотеки или чтение файлов не считается выполненной задачей.", "It is too early to finish. Still missing: {missing}. Keep going: change project files, run validate_project, fix the errors and run run_project. Installing a library or reading files does not count as completing the task."),
    "tools.Завершить работу: 100%, все задачи выполнены, итоговое сообщение.": _pair("Завершить работу: 100%, все задачи выполнены, итоговое сообщение.", "Finish the job: 100%, all tasks done, final message."),
    "tools.Задача обновлена.": _pair("Задача обновлена.", "Task updated."),
    "tools.Заменить план работ списком конкретных задач.": _pair("Заменить план работ списком конкретных задач.", "Replace the work plan with a list of concrete tasks."),
    "tools.Запустить проект в headless-режиме на несколько кадров и вернуть ошибки. Используй после крупных изменений.": _pair("Запустить проект в headless-режиме на несколько кадров и вернуть ошибки. Используй после крупных изменений.", "Run the project headless for a few frames and return any errors. Use after major changes."),
    "tools.Команда заблокирована как небезопасная.": _pair("Команда заблокирована как небезопасная.", "Command blocked as unsafe."),
    "tools.Команда не завершилась за {timeout} сек.": _pair("Команда не завершилась за {timeout} сек.", "The command did not finish within {timeout} s."),
    "tools.Найти строку или регулярное выражение в текстовых файлах проекта.": _pair("Найти строку или регулярное выражение в текстовых файлах проекта.", "Find a string or regex in the project's text files."),
    "tools.Например assets/backgrounds/forest.png": _pair("Например assets/backgrounds/forest.png", "e.g. assets/backgrounds/forest.png"),
    "tools.Например assets/sprites/player.png": _pair("Например assets/sprites/player.png", "e.g. assets/sprites/player.png"),
    "tools.Не удалось открыть изображение: {exc}": _pair("Не удалось открыть изображение: {exc}", "Could not open the image: {exc}"),
    "tools.Неверные аргументы для {name}: {exc}": _pair("Неверные аргументы для {name}: {exc}", "Invalid arguments for {name}: {exc}"),
    "tools.Неизвестный инструмент: {name}": _pair("Неизвестный инструмент: {name}", "Unknown tool: {name}"),
    "tools.Некорректный JSON: {exc}": _pair("Некорректный JSON: {exc}", "Invalid JSON: {exc}"),
    "tools.Нельзя изменять встроенный движок _engine/. Используйте re.bat sync-engine.": _pair("Нельзя изменять встроенный движок _engine/. Используйте re.bat sync-engine.", "The bundled engine _engine/ must not be modified. Use re.bat sync-engine."),
    "tools.Новый фрагмент": _pair("Новый фрагмент", "Replacement text"),
    "tools.Нужен непустой список задач.": _pair("Нужен непустой список задач.", "A non-empty task list is required."),
    "tools.Обновить процент, этап и сообщение для пользователя в редакторе.": _pair("Обновить процент, этап и сообщение для пользователя в редакторе.", "Update the percentage, stage and user-visible message in the editor."),
    "tools.Обновить статус задачи плана.": _pair("Обновить статус задачи плана.", "Update the status of a plan task."),
    "tools.Папка не найдена: {path}": _pair("Папка не найдена: {path}", "Folder not found: {path}"),
    "tools.Папка не пуста. Укажите recursive=true.": _pair("Папка не пуста. Укажите recursive=true.", "The folder is not empty. Pass recursive=true."),
    "tools.Папка относительно корня проекта": _pair("Папка относительно корня проекта", "Folder relative to the project root"),
    "tools.План обновлён.": _pair("План обновлён.", "Plan updated."),
    "tools.Плохое регулярное выражение: {exc}": _pair("Плохое регулярное выражение: {exc}", "Bad regular expression: {exc}"),
    "tools.Показать файлы и папки проекта. Используй в начале работы.": _pair("Показать файлы и папки проекта. Используй в начале работы.", "List the project's files and folders. Use at the start of a job."),
    "tools.Полное содержимое файла": _pair("Полное содержимое файла", "Full file content"),
    "tools.Последняя строка включительно": _pair("Последняя строка включительно", "Last line, inclusive"),
    "tools.Проверить PNG: размер, прозрачность, границы объекта и основные цвета.": _pair("Проверить PNG: размер, прозрачность, границы объекта и основные цвета.", "Inspect a PNG: size, transparency, object bounds and dominant colors."),
    "tools.Проверить структуру, project.json и синтаксис всех Python-файлов проекта.": _pair("Проверить структуру, project.json и синтаксис всех Python-файлов проекта.", "Validate structure, project.json and the syntax of every Python file in the project."),
    "tools.Проект готов": _pair("Проект готов", "Project is ready"),
    "tools.Проект завершился с ошибкой.": _pair("Проект завершился с ошибкой.", "The project exited with an error."),
    "tools.Проект запустился без исключений.": _pair("Проект запустился без исключений.", "The project ran without exceptions."),
    "tools.Проект не завершился за {timeout} сек.": _pair("Проект не завершился за {timeout} сек.", "The project did not finish within {timeout} s."),
    "tools.Прочитать текстовый файл проекта. Для больших файлов используй start_line/end_line.": _pair("Прочитать текстовый файл проекта. Для больших файлов используй start_line/end_line.", "Read a project text file. For large files use start_line/end_line."),
    "tools.Прочитать текущий прогресс, план и последние события проекта.": _pair("Прочитать текущий прогресс, план и последние события проекта.", "Read the current progress, plan and recent project events."),
    "tools.Пустая команда.": _pair("Пустая команда.", "Empty command."),
    "tools.Пустой путь.": _pair("Пустой путь.", "Empty path."),
    "tools.Путь относительно корня проекта": _pair("Путь относительно корня проекта", "Path relative to the project root"),
    "tools.Сгенерировать спрайт (один объект, прозрачный фон) и сохранить в assets/.": _pair("Сгенерировать спрайт (один объект, прозрачный фон) и сохранить в assets/.", "Generate a sprite (one object, transparent background) and save it into assets/."),
    "tools.Сгенерировать фон сцены и сохранить в assets/.": _pair("Сгенерировать фон сцены и сохранить в assets/.", "Generate a scene background and save it into assets/."),
    "tools.Слишком большой файл. Разделите его на несколько.": _pair("Слишком большой файл. Разделите его на несколько.", "The file is too large. Split it into several files."),
    "tools.Создать или полностью заменить файл. Для правок лучше edit_file.": _pair("Создать или полностью заменить файл. Для правок лучше edit_file.", "Create or fully replace a file. Prefer edit_file for targeted changes."),
    "tools.Спрайт сгенерирован: {path}": _pair("Спрайт сгенерирован: {path}", "Sprite generated: {path}"),
    "tools.Спрайт создан офлайн: {path}": _pair("Спрайт создан офлайн: {path}", "Sprite created offline: {path}"),
    "tools.Спрайты сохраняйте только в assets/.": _pair("Спрайты сохраняйте только в assets/.", "Save sprites only under assets/."),
    "tools.Точечно заменить точный фрагмент файла. old_text должен встречаться ровно один раз (или укажи replace_all).": _pair("Точечно заменить точный фрагмент файла. old_text должен встречаться ровно один раз (или укажи replace_all).", "Replace an exact fragment of a file. old_text must occur exactly once (or pass replace_all)."),
    "tools.Точка входа main.py не найдена.": _pair("Точка входа main.py не найдена.", "Entry point main.py not found."),
    "tools.Точный существующий фрагмент": _pair("Точный существующий фрагмент", "Exact existing fragment"),
    "tools.Удалено.": _pair("Удалено.", "Deleted."),
    "tools.Удалить папку со всем содержимым": _pair("Удалить папку со всем содержимым", "Delete the folder with all its contents"),
    "tools.Удалить файл или папку внутри проекта. Защищённые файлы удалять нельзя.": _pair("Удалить файл или папку внутри проекта. Защищённые файлы удалять нельзя.", "Delete a file or folder inside the project. Protected files cannot be deleted."),
    "tools.Файл записан.": _pair("Файл записан.", "File written."),
    "tools.Файл защищён: {rel}": _pair("Файл защищён: {rel}", "The file is protected: {rel}"),
    "tools.Файл изменён.": _pair("Файл изменён.", "File updated."),
    "tools.Файл не найден: {path}": _pair("Файл не найден: {path}", "File not found: {path}"),
    "tools.Файл слишком большой. Укажите start_line/end_line.": _pair("Файл слишком большой. Укажите start_line/end_line.", "The file is too large. Specify start_line/end_line."),
    "tools.Фон создан: {path}": _pair("Фон создан: {path}", "Background created: {path}"),
    "tools.Фоны сохраняйте только в assets/.": _pair("Фоны сохраняйте только в assets/.", "Save backgrounds only under assets/."),
    "tools.Фрагмент old_text не найден. Прочитайте файл заново.": _pair("Фрагмент old_text не найден. Прочитайте файл заново.", "The old_text fragment was not found. Re-read the file."),
    "tools.Фрагмент встречается {count} раз. Уточните контекст или передайте replace_all=true.": _pair("Фрагмент встречается {count} раз. Уточните контекст или передайте replace_all=true.", "The fragment occurs {count} times. Add context or pass replace_all=true."),
    "tools.Что изобразить, по-английски или по-русски": _pair("Что изобразить, по-английски или по-русски", "What to draw, in English or Russian"),
    "tools.Эта папка защищена.": _pair("Эта папка защищена.", "This folder is protected."),
    "tools.Это не текстовый файл. Используйте inspect_image для изображений.": _pair("Это не текстовый файл. Используйте inspect_image для изображений.", "This is not a text file. Use inspect_image for images."),
    "tools.ни один файл проекта не изменён": _pair("ни один файл проекта не изменён", "no project file was changed"),
    "tools.… (обрезано)": _pair("… (обрезано)", "… (truncated)"),
}
