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


# The Windows installer writes the language chosen on its first page into this
# ASCII marker file; the application merges it into settings.json on first run
# and deletes the marker (the installer itself must not rewrite UTF-8 JSON).
INSTALLER_LANGUAGE_MARKER = "installer-language.txt"


def installer_language_paths() -> list[Path]:
    """Locations where the installer language marker may live."""
    from .paths import app_data_dir, install_root

    paths = [app_data_dir() / INSTALLER_LANGUAGE_MARKER]
    # The marker next to the editor binary exists only in installed builds;
    # a source checkout must not pick up stray files from the repository root.
    from .paths import is_frozen

    if is_frozen():
        paths.append(install_root() / INSTALLER_LANGUAGE_MARKER)
    return paths


def read_installer_language() -> str:
    """Language chosen in the installer ('ru'/'en') or '' when no marker exists."""
    for path in installer_language_paths():
        try:
            text = path.read_text(encoding="utf-8", errors="replace").strip().lower()
        except OSError:
            continue
        if text:
            return normalize_language(text)
    return ""


def remove_installer_language_marker() -> None:
    """Delete the installer marker(s); called after the choice is persisted."""
    for path in installer_language_paths():
        try:
            path.unlink()
        except OSError:
            pass


def read_settings_language() -> str:
    """Language stored in settings.json without importing the Settings class."""
    global _CACHED_SETTINGS_LANGUAGE, _CACHED_SETTINGS_PATH
    path = settings_file_path()
    key = str(path)
    if _CACHED_SETTINGS_PATH == key and _CACHED_SETTINGS_LANGUAGE is not None:
        return _CACHED_SETTINGS_LANGUAGE
    language = DEFAULT_LANGUAGE
    stored_language = False
    try:
        from .paths import read_json

        data = read_json(path, {})
        if isinstance(data, dict):
            ui = data.get("ui")
            if isinstance(ui, dict):
                raw = str(ui.get("language") or "").strip()
                if raw:
                    language = normalize_language(raw)
                    stored_language = True
    except Exception:
        language = DEFAULT_LANGUAGE
    if not stored_language:
        # Fresh install: fall back to the language picked in the installer.
        marker = read_installer_language()
        if marker:
            language = marker
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
    if not (text or "").strip():
        return DEFAULT_LANGUAGE
    return "ru" if _CYRILLIC_RE.search(text) else "en"


_TASK_LANGUAGE_NOTES = {
    "ru": (
        "[SYSTEM NOTE] The editor UI language is Russian. "
        "Think, plan, report progress and answer the user strictly in Russian, "
        "even if the task text is written in another language. "
        "Tool names, code, identifiers and file contents stay in English."
    ),
    "en": (
        "[SYSTEM NOTE] The editor UI language is English. "
        "Think, plan, report progress and answer the user strictly in English, "
        "even if the task text is written in another language. "
        "Tool names, code, identifiers and file contents stay in English."
    ),
}


def task_language_note(text: str) -> str:
    """Instruction injected before a user message so the agent answers in the
    language of exactly that task (tools/skills themselves are English-only)."""
    return _TASK_LANGUAGE_NOTES[detect_user_language(text)]


def language_note(language: str | None = None) -> str:
    """Same instruction for a hidden task whose reply language is chosen by the UI."""
    return _TASK_LANGUAGE_NOTES[normalize_language(language or current_language())]


def tr(en: str, ru: str, **values: Any) -> str:
    """Return a string chosen by the current UI language.

    Used for user-facing runtime messages (tool output, agent narration).
    AI-facing material (tool schemas, skills, prompts) is English-only and
    must not use this helper.
    """
    template = ru if current_language() == "ru" else en
    return template.format(**values) if values else template


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
    table = _resolve(table)
    template = table.get(current_language())
    if template is None:
        template = table[DEFAULT_LANGUAGE]
    if values:
        try:
            return template.format(**values)
        except (KeyError, IndexError):
            # A placeholder in the template is missing from ``values`` — e.g.
            # a translated variant of an agent prompt uses different braces.
            # Fall back to the Russian base template, which always matches the
            # call-site arguments, so the text stays interpolable.
            if isinstance(TRANSLATIONS.get(key), dict):
                try:
                    return TRANSLATIONS[key][DEFAULT_LANGUAGE].format(**values)
                except (KeyError, IndexError, ValueError):
                    return template
            return template
        except ValueError:
            return template
    # No interpolation requested: strip single-brace placeholders so raw
    # templates (e.g. extpanel.agent_prompt with {name}/{root}) never show
    # braces to the user.  Keys listed in _RAW_TEMPLATE_KEYS are returned
    # untouched because their callers interpolate them explicitly.
    if key not in _RAW_TEMPLATE_KEYS and "{" in template and "}" in template and _CYRILLIC_RE.search(template):
        return re.sub(r"\{[^{}]*\}", "", template)
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


def _resolve(entry: dict[str, str] | tuple[str]) -> dict[str, str]:
    if isinstance(entry, tuple):
        return TRANSLATIONS[entry[0]]
    return entry


# Keys whose templates are interpolated by callers other than t() (e.g. the
# external agent prompt is filled via ``agent_prompt()``); t() must return
# them raw instead of stripping their placeholders.
_RAW_TEMPLATE_KEYS = {"extpanel.agent_prompt"}


TRANSLATIONS: dict[str, dict[str, str] | tuple[str]] = {
    # -- brand ---------------------------------------------------------
    "app.tagline": _pair("Разумный движок для смелых идей", "A reasonable way to make games"),
    "app.title": _pair("Reasonable Engine — {tagline}", "Reasonable Engine — {tagline}"),
    # -- relative time (core/paths.human_time) --------------------------
    "time.just_now": _pair("только что", "just now"),
    "time.seconds_ago": _pair("{count} сек. назад", "{count} s ago"),
    "time.minutes_ago": _pair("{count} мин. назад", "{count} min ago"),
    "time.hours_ago": _pair("{count} ч. назад", "{count} h ago"),
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
    "welcome.ai_ready_text": _pair(
        "{key_state}. Настройка не обязательна: её можно открыть из проекта, когда понадобится.",
        "{key_state}. Setup is optional: you can open it from the project when needed.",
    ),
    # -- shared / generic ------------------------------------------------
    "common.cancel": _pair("Отмена", "Cancel"),
    "common.save": _pair("Сохранить", "Save"),
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
    # --- Settings dialog (editor/settings_dialog.py) --------------------
    "settings.title": _pair("Настройки — Reasonable Engine", "Settings — Reasonable Engine"),
    "settings.heading": _pair("Настройки", "Settings"),
    "settings.subtitle": _pair(
        "Основные настройки · расширенные — по переключателю",
        "Essentials · advanced behind a toggle",
    ),
    "settings.advanced_toggle": _pair("Расширенные настройки", "Advanced settings"),
    "settings.advanced_tooltip": _pair(
        "Провайдеры, модели, Base URL, картинки, параметры агента, Android и внешние агенты.",
        "Providers, models, Base URL, images, agent parameters, Android and external agents.",
    ),
    "settings.badge_local": _pair("ДАННЫЕ ХРАНЯТСЯ ЛОКАЛЬНО", "DATA STAYS LOCAL"),
    "settings.nav_providers": _pair("Провайдеры ИИ", "AI providers"),
    "settings.nav_free": _pair("Бесплатные API", "Free APIs"),
    "settings.nav_images": _pair("Картинки и спрайты", "Images and sprites"),
    "settings.nav_agent": _pair("Агент и предпросмотр", "Agent and preview"),
    "settings.no_key_title": _pair("Без ключа", "Without a key"),
    "settings.no_key_text": _pair(
        "OpenRouter, Groq, Gemini и другие бесплатные тарифы требуют ключ. "
        "Ollama и LM Studio работают полностью локально, если запущены на этом ПК.",
        "OpenRouter, Groq, Gemini and other free tiers need a key. Ollama and LM Studio "
        "run fully locally when started on this PC.",
    ),
    "settings.custom_server": _pair("Свой сервер", "Custom server"),
    "settings.simple_title": _pair("Основные настройки", "Essential settings"),
    "settings.simple_intro": _pair(
        "Только необходимое для работы. Провайдеры, модели, Base URL, картинки, "
        "параметры Android и внешних агентов находятся в расширенных настройках.",
        "Only what you need to get going. Providers, models, Base URL, images, Android "
        "and external agent parameters live in the advanced settings.",
    ),
    "settings.setup_provider": _pair("Настроить провайдера и модель…", "Set up provider and model…"),
    "settings.projects_title": _pair("Папка проектов", "Projects folder"),
    "settings.projects_hint": _pair(
        "Где создаются новые проекты. Существующие папки не перемещаются.",
        "Where new projects are created. Existing folders are not moved.",
    ),
    "settings.projects_placeholder": _pair(
        "По умолчанию: папка Projects рядом с движком",
        "Default: the Projects folder next to the engine",
    ),
    "settings.reset_default": _pair("По умолчанию", "Default"),
    "settings.preview_title": _pair("Предпросмотр", "Preview"),
    "settings.preview_hint": _pair(
        "Заставка Reasonable Engine всегда играет перед запуском проекта — "
        "и в редакторе, и в готовой игре. Отключить её может только разработчик движка.",
        "The Reasonable Engine splash always plays before a project starts — in the editor "
        "and in the finished game. Only the engine developer can disable it.",
    ),
    "settings.language_title": _pair("Язык интерфейса", "Interface language"),
    "settings.language_hint": _pair(
        "Язык установщика, редактора и всех окон программы. Применяется после перезапуска.",
        "The language of the installer, the editor and every window. Applied after a restart.",
    ),
    "settings.restart_hint": _pair(
        "Язык интерфейса применится после перезапуска Reasonable Engine.",
        "The interface language will be applied after restarting Reasonable Engine.",
    ),
    "settings.simple_need_key": _pair(
        "{name} · {model}\nКлюч понадобится только для встроенного агента. Ручная работа "
        "и запуск проекта доступны без него.",
        "{name} · {model}\nThe key is only needed for the built-in agent. Manual work and "
        "running the project work without it.",
    ),
    "settings.simple_ready_line": _pair("{name} · {model}\n{key_state}.", "{name} · {model}\n{key_state}."),
    "settings.folder_dialog": _pair("Папка для новых проектов", "Folder for new projects"),
    "settings.model_for_agent": _pair("Модель для агента", "Model for the agent"),
    "settings.pick_provider": _pair(
        "Выберите провайдера. Ключ нужен не всем.", "Pick a provider. Not everyone needs a key."
    ),
    "settings.active_badge": _pair("АКТИВНЫЙ", "ACTIVE"),
    "settings.key_required_badge": _pair("НУЖЕН КЛЮЧ", "KEY REQUIRED"),
    "settings.no_key_badge": _pair("БЕЗ КЛЮЧА", "NO KEY"),
    "settings.label_model": _pair("Модель", "Model"),
    "settings.key_placeholder": _pair("API-ключ (если требуется)", "API key (if required)"),
    "settings.show": _pair("Показать", "Show"),
    "settings.hide": _pair("Скрыть", "Hide"),
    "settings.get_key": _pair("Получить ключ", "Get a key"),
    "settings.label_api_key": _pair("API-ключ", "API key"),
    "settings.load_models": _pair("Загрузить модели", "Load models"),
    "settings.test_connection": _pair("Проверить подключение", "Test connection"),
    "settings.how_it_works": _pair("Как это работает", "How it works"),
    "settings.how_it_works_text": _pair(
        "Reasonable Engine общается с моделями через OpenAI-совместимый /chat/completions "
        "или нативный Anthropic API. Для агента важна поддержка tool calling: Claude, "
        "GPT-4.1, Gemini 2.5, Qwen и Llama 3.3 подходят. Если провайдер отклонит инструменты, "
        "агент переключится на текстовый JSON-протокол.",
        "Reasonable Engine talks to models through the OpenAI-compatible /chat/completions or "
        "the native Anthropic API. The agent needs tool calling: Claude, GPT-4.1, Gemini 2.5, "
        "Qwen and Llama 3.3 all work. If a provider rejects tools, the agent falls back to the "
        "text JSON protocol.",
    ),
    "settings.get_api_key_link": _pair("Получить API-ключ", "Get an API key"),
    "settings.docs_link": _pair("Документация", "Documentation"),
    "settings.specify_base_url": _pair("Укажите Base URL.", "Specify the Base URL."),
    "settings.enter_api_key": _pair("Введите API-ключ.", "Enter the API key."),
    "settings.enter_key_models": _pair(
        "Введите API-ключ, чтобы загрузить список моделей.",
        "Enter the API key to load the model list.",
    ),
    "settings.testing": _pair("Проверяю соединение…", "Testing the connection…"),
    "settings.success_prefix": _pair("Успешно: ", "Success: "),
    "settings.connection_ok": _pair("Подключение работает.", "The connection works."),
    "settings.error_prefix": _pair("Ошибка: ", "Error: "),
    "settings.connection_failed": _pair(
        "Не удалось подключиться к модели.", "Could not connect to the model."
    ),
    "settings.loading_models": _pair("Загружаю список моделей…", "Loading the model list…"),
    "settings.empty_model_list": _pair(
        "Провайдер не вернул список. Введите модель вручную.",
        "The provider returned no list. Enter the model manually.",
    ),
    "settings.models_loaded": _pair("Загружено моделей: {count}", "Models loaded: {count}"),
    "settings.shown_first_500": _pair(" (показаны первые 500)", " (first 500 shown)"),
    "settings.load_failed_prefix": _pair(
        "Не удалось загрузить список: ", "Could not load the list: "
    ),
    "settings.load_failed_suffix": _pair(
        " Можно ввести модель вручную.", " You can enter the model manually."
    ),
    "settings.free_title": _pair("Бесплатные API-ключи", "Free API keys"),
    "settings.free_intro": _pair(
        "Эти сервисы дают бесплатный уровень или пробные кредиты. Лимиты меняются — "
        "проверяйте условия на сайте. Локальные модели вообще не требуют ключа.",
        "These services offer a free tier or trial credits. Limits change — check the terms "
        "on their site. Local models need no key at all.",
    ),
    "settings.local_no_key_text": _pair(
        "Ollama / LM Studio — запустите локальный сервер и укажите модель.\n"
        "Для остальных провайдеров добавьте бесплатный API-ключ.",
        "Ollama / LM Studio — start a local server and enter a model.\n"
        "For other providers, add a free API key.",
    ),
    "settings.setup_provider_btn": _pair("Настроить провайдера", "Set up provider"),
    "settings.open_site": _pair("Открыть сайт", "Open site"),
    "settings.images_intro": _pair(
        "Внешняя модель изображений используется кнопкой «Сгенерировать спрайт» и "
        "инструментом generate_sprite. Без неё встроенный агент рисует спрайты сам "
        "через draw_sprite — шаблоны больше не подставляются.",
        "The external image model is used by the “Generate sprite” button and the "
        "generate_sprite tool. Without one the built-in agent draws sprites itself "
        "with draw_sprite — no templates are substituted.",
    ),
    "settings.label_provider": _pair("Провайдер", "Provider"),
    "settings.label_description": _pair("Описание", "Description"),
    "settings.label_base_url": _pair("Base URL", "Base URL"),
    "settings.tip_title": _pair("Совет", "Tip"),
    "settings.tip_text": _pair(
        "Для спрайтов лучше всего работают короткие предметные промпты: "
        "«золотая звезда, флэт, прозрачный фон». Без внешней модели агент рисует "
        "предмет сам фигурами или пиксельной сеткой.",
        "Short, concrete prompts work best for sprites: “golden star, flat, transparent "
        "background”. Without an external model the agent draws the object itself from "
        "shapes or a pixel grid.",
    ),
    "settings.label_temperature": _pair("Температура", "Temperature"),
    "settings.label_context": _pair("Помнить сообщений", "Messages to remember"),
    "settings.auto_continue_title": _pair(
        "Автопродолжение после ошибок",
        "Automatic continue after errors",
    ),
    "settings.auto_continue_hint": _pair(
        "Агент сам отправит «Продолжай» после выбранных ошибок. "
        "Если ничего не выбрано, автопродолжение выключено. "
        "Число попыток не ограничено; при повторных ошибках интервал увеличивается.",
        "The agent will send “Continue” automatically after the selected errors. "
        "With nothing selected, automatic continuation is off. "
        "Attempts are unlimited; the interval grows when errors repeat.",
    ),
    "settings.supervisor_title": _pair(
        "Проверка выполнения задачи",
        "Task completion check",
    ),
    "settings.supervisor_hint": _pair(
        "Перед финальным ответом отдельный проход сверяет исходную задачу, "
        "изменённые файлы, проверку и запуск. Если что-то не сделано, агент "
        "продолжает работу, а не объявляет готовый результат.",
        "Before the final answer a separate pass compares the original task with "
        "the changed files, validation and run result. If something is missing, "
        "the agent keeps working instead of declaring success.",
    ),
    "settings.supervisor_check": _pair(
        "Проверять, что агент сделал именно задачу",
        "Check that the agent did exactly the task",
    ),
    "settings.supervisor_check_tip": _pair(
        "Дополнительный запрос к модели после завершения. Отключите, если "
        "экономите токены или хотите завершать работу сразу.",
        "An extra model request after completion. Disable it to save tokens or "
        "to finish immediately.",
    ),
    "settings.parallel_title": _pair(
        "Параллельная разработка",
        "Parallel development",
    ),
    "settings.parallel_hint": _pair(
        "Главный агент планирует работу и раздаёт независимые задачи специалистам "
        "по коду и ассетам. Затем он сам проверяет запуск, устраивает независимый "
        "аудит и отправляет точечные исправления. При сбое автоматически "
        "возвращается обычный режим.",
        "A master agent plans the work and assigns independent tasks to code and "
        "asset specialists. It then verifies the launch, runs an independent audit "
        "and sends focused repairs. On failure it falls back to the regular mode.",
    ),
    "settings.parallel_check": _pair(
        "Работать несколькими агентами одновременно",
        "Work with several agents at once",
    ),
    "settings.parallel_check_tip": _pair(
        "Ускоряет большие задачи. Отключите для максимально предсказуемого "
        "последовательного режима.",
        "Speeds up large tasks. Disable for the most predictable sequential mode.",
    ),
    "settings.parallel_workers": _pair(
        "Специалистов одновременно",
        "Specialists at once",
    ),
    "settings.parallel_rounds": _pair(
        "Кругов исправлений",
        "Repair rounds",
    ),
    "settings.projects_hint2": _pair(
        "По умолчанию новые проекты создаются в папке Projects рядом с движком. "
        "Можно выбрать любую другую папку — путь сохранится.",
        "By default, new projects are created in the Projects folder next to the engine. "
        "You can pick any other folder — the path is remembered.",
    ),
    "settings.preview_splash_title": _pair("Предпросмотр и заставка", "Preview and splash"),
    "settings.external_title": _pair("Внешний агент", "External agent"),
    "settings.external_text": _pair(
        "Для внешнего режима в каждом проекте создаются AGENT_GUIDE.md, AGENTS.md, "
        "CLAUDE.md, правила для Cursor/Copilot, skills/, AGENT_TASKS.md и re.bat. "
        "Агент обновляет прогресс командами `re.bat progress`, `re.bat task` и `re.bat event` — "
        "редактор показывает их в реальном времени.",
        "External mode adds AGENT_GUIDE.md, AGENTS.md, CLAUDE.md, Cursor/Copilot rules, "
        "skills/, AGENT_TASKS.md and re.bat to every project. The agent updates progress "
        "with `re.bat progress`, `re.bat task` and `re.bat event` — the editor shows them "
        "in real time.",
    ),
    "settings.save": _pair("Сохранить настройки", "Save settings"),
    # --- Project page (editor/project_page.py) --------------------------
    "projectpage.status_running": _pair("РАБОТАЕТ", "RUNNING"),
    "projectpage.status_done": _pair("ГОТОВО", "DONE"),
    "projectpage.status_error": _pair("ОШИБКА", "ERROR"),
    "projectpage.status_idle": _pair("ОЖИДАНИЕ", "IDLE"),
    "projectpage.badge_success": _pair("УСПЕШНО", "SUCCESS"),
    "projectpage.badge_failure": _pair("ОШИБКА", "ERROR"),
    "projectpage.badge_running": _pair("ЗАПУЩЕН", "RUNNING"),
    "projectpage.badge_not_run": _pair("НЕ ЗАПУСКАЛСЯ", "NOT RUN"),
    "projectpage.back_tooltip": _pair("Ко всем проектам", "Back to all projects"),
    "projectpage.badge_game": _pair("ИГРА", "GAME"),
    "projectpage.badge_app": _pair("ПРИЛОЖЕНИЕ", "APP"),
    "projectpage.badge_mode_builtin": _pair("ВСТРОЕННЫЙ ИИ", "BUILT-IN AI"),
    "projectpage.badge_mode_external": _pair("ВНЕШНИЙ АГЕНТ", "EXTERNAL AGENT"),
    "projectpage.goal_missing": _pair("Цель пока не описана", "No goal described yet"),
    "projectpage.goal_missing_long": _pair(
        "Цель не описана. Добавьте её в настройках проекта.",
        "The goal is not described. Add it in the project settings.",
    ),
    "projectpage.export_btn": _pair("Экспорт", "Export"),
    "projectpage.export_tooltip": _pair(
        "Собрать проект в exe / APK / портативную папку (по умолчанию на Рабочий стол)",
        "Build the project into an exe / APK / portable folder (to the Desktop by default)",
    ),
    "projectpage.run_btn": _pair("Запустить", "Run"),
    "projectpage.stop_btn": _pair("Остановить", "Stop"),
    "projectpage.sections_label": _pair("РАЗДЕЛЫ", "SECTIONS"),
    "projectpage.nav_overview": _pair("Обзор", "Overview"),
    "projectpage.nav_agent": _pair("ИИ-агент", "AI agent"),
    "projectpage.nav_code": _pair("Код", "Code"),
    "projectpage.nav_assets": _pair("Ассеты", "Assets"),
    "projectpage.nav_scene": _pair("Сцена", "Scene"),
    "projectpage.project_label": _pair("ПРОЕКТ", "PROJECT"),
    "projectpage.project_settings_btn": _pair("Настройки проекта", "Project settings"),
    "projectpage.history_btn": _pair("История версий", "Version history"),
    "projectpage.history_tooltip": _pair(
        "Снимки проекта и возврат к рабочей версии",
        "Project snapshots and returning to a working version",
    ),
    "projectpage.open_folder_btn": _pair("Открыть папку", "Open folder"),
    "projectpage.convert_btn": _pair("Конвертировать…", "Convert…"),
    "projectpage.convert_tooltip": _pair(
        "Создать новый проект для другой платформы или с другими настройками",
        "Create a new project for another platform or with different settings",
    ),
    "projectpage.delete_btn": _pair("Удалить проект", "Delete project"),
    "projectpage.delete_tooltip": _pair(
        "Убрать проект из списка или удалить его папку с диска",
        "Remove the project from the list or delete its folder from disk",
    ),
    "projectpage.ai_project_title": _pair("ИИ проекта", "Project AI"),
    "projectpage.guide_btn": _pair("Инструкции агента", "Agent instructions"),
    "projectpage.run_result_label": _pair("Результат запуска", "Run result"),
    "projectpage.run_result_idle_title": _pair(
        "Проверьте проект в предпросмотре", "Check the project in the preview"
    ),
    "projectpage.run_result_idle_detail": _pair(
        "Быстрый цикл: запустите проект, посмотрите результат, исправьте код или "
        "попросите ИИ — и запустите снова.",
        "Fast loop: run the project, look at the result, fix the code or ask the AI — "
        "and run again.",
    ),
    "projectpage.run_again_btn": _pair("Запустить снова", "Run again"),
    "projectpage.fix_ai_btn": _pair("Исправить с ИИ", "Fix with AI"),
    "projectpage.fix_ai_tooltip": _pair(
        "Подготовить задачу агенту с текстом ошибки и открыть ИИ-агента",
        "Prepare an agent task with the error text and open the AI agent",
    ),
    "projectpage.rollback_btn": _pair("Вернуть рабочую версию", "Restore working version"),
    "projectpage.rollback_tooltip": _pair(
        "Восстановить последний снимок проекта", "Restore the latest project snapshot"
    ),
    "projectpage.run_history_btn": _pair("История", "History"),
    "projectpage.progress_title": _pair("Прогресс разработки", "Development progress"),
    "projectpage.stat_tasks": _pair("Задачи", "Tasks"),
    "projectpage.stat_tasks_hint": _pair("план работ", "work plan"),
    "projectpage.stat_files": _pair("Файлы", "Files"),
    "projectpage.stat_files_hint": _pair("в проекте", "in project"),
    "projectpage.open_agent_btn": _pair("Открыть агента", "Open agent"),
    "projectpage.open_agent_btn_full": _pair("Открыть ИИ-агента", "Open AI agent"),
    "projectpage.edit_code_btn": _pair("Редактировать код", "Edit code"),
    "projectpage.sprites_btn": _pair("Спрайты", "Sprites"),
    "projectpage.scene_btn": _pair("Сцена", "Scene"),
    "projectpage.scene_btn_tip": _pair(
        "Открыть визуальный редактор сцен",
        "Open the visual scene editor",
    ),
    "projectpage.plan_title": _pair("План работ", "Work plan"),
    "projectpage.plan_hint": _pair(
        "План ведёт ИИ-агент. Здесь он показывается для чтения.",
        "The AI agent maintains the plan. It is shown here read-only.",
    ),
    "projectpage.events_title": _pair("События", "Events"),
    "projectpage.goal_notes_title": _pair("Цель и заметки", "Goal and notes"),
    "projectpage.edit_btn": _pair("Изменить", "Edit"),
    "projectpage.recent_files_title": _pair("Недавние файлы", "Recent files"),
    "projectpage.refresh_btn": _pair("Обновить", "Refresh"),
    "projectpage.history_title": _pair("История версий", "Version history"),
    "projectpage.history_empty_initial": _pair(
        "Снимки появятся перед первым запуском агента.",
        "Snapshots will appear before the first agent run.",
    ),
    "projectpage.open_history_btn": _pair("Открыть историю", "Open history"),
    "projectpage.snapshot_now_btn": _pair("Снимок сейчас", "Snapshot now"),
    "projectpage.snapshot_now_tooltip": _pair(
        "Сохранить текущее состояние как версию, к которой можно вернуться",
        "Save the current state as a version you can return to",
    ),
    "projectpage.history_empty": _pair(
        "Снимков пока нет. Перед каждым запуском ИИ-агента рабочая версия "
        "сохраняется автоматически.",
        "No snapshots yet. Before every AI agent run the working version is saved "
        "automatically.",
    ),
    "projectpage.history_files_line": _pair("{time} · файлов {count}", "{time} · {count} files"),
    "projectpage.console_title": _pair("Запуск проекта", "Project run"),
    "projectpage.console_title_splash": _pair(
        "Запуск проекта · заставка Reasonable Engine", "Project run · Reasonable Engine splash"
    ),
    "projectpage.hide_console_tooltip": _pair("Скрыть консоль", "Hide console"),
    "projectpage.back_running_text": _pair(
        "Проект ещё запущен. Остановить его и вернуться к списку?",
        "The project is still running. Stop it and return to the list?",
    ),
    "projectpage.guide_missing_title": _pair("Инструкция", "Instructions"),
    "projectpage.guide_missing_text": _pair(
        "AGENT_GUIDE.md ещё не создан.", "AGENT_GUIDE.md has not been created yet."
    ),
    "projectpage.restored_title": _pair("Версия восстановлена", "Version restored"),
    "projectpage.restored_detail": _pair(
        "Файлы проекта возвращены к выбранному снимку. Запустите проект, чтобы проверить результат.",
        "Project files are back at the chosen snapshot. Run the project to check the result.",
    ),
    "projectpage.restored_status": _pair(
        "Версия проекта восстановлена. Предыдущее состояние сохранено в истории.",
        "The project version was restored. The previous state is kept in history.",
    ),
    "projectpage.snapshot_dialog_title": _pair("Снимок версии", "Version snapshot"),
    "projectpage.snapshot_dialog_label": _pair(
        "Название версии (необязательно):", "Version name (optional):"
    ),
    "projectpage.manual_snapshot_label": _pair(
        "Ручной снимок рабочей версии", "Manual snapshot of the working version"
    ),
    "projectpage.snapshot_failed_title": _pair(
        "Не удалось создать снимок", "Could not create the snapshot"
    ),
    "projectpage.snapshot_created_status": _pair(
        "Снимок «{label}» создан. Его можно вернуть из истории.",
        "Snapshot “{label}” created. You can restore it from history.",
    ),
    "projectpage.restore_confirm_title": _pair("Отменить изменения", "Undo changes"),
    "projectpage.restore_confirm_text": _pair(
        "Вернуть версию «{label}»?\n\n"
        "Текущее состояние сначала сохранится отдельным снимком, поэтому "
        "восстановление тоже можно отменить.",
        "Restore version “{label}”?\n\n"
        "The current state will first be saved as a separate snapshot, so the restore "
        "itself can be undone.",
    ),
    "projectpage.restore_failed_title": _pair(
        "Не удалось вернуть версию", "Could not restore the version"
    ),
    "projectpage.restored_files_status": _pair(
        "Версия «{label}» восстановлена: файлов {restored}, удалено {removed}.",
        "Version “{label}” restored: {restored} files restored, {removed} removed.",
    ),
    "projectpage.no_snapshots_title": _pair("Нет снимков", "No snapshots"),
    "projectpage.no_snapshots_text": _pair(
        "Пока нет сохранённых версий. Они создаются автоматически перед запуском агента.",
        "No saved versions yet. They are created automatically before agent runs.",
    ),
    "projectpage.agent_running_text": _pair(
        "Дождитесь завершения агента или остановите его — затем можно "
        "создавать снимки и возвращать версии.",
        "Wait for the agent to finish or stop it — then you can create snapshots "
        "and restore versions.",
    ),
    "projectpage.project_settings_saved": _pair(
        "Настройки проекта сохранены.", "Project settings saved."
    ),
    "projectpage.ai_settings_saved": _pair("Настройки ИИ сохранены.", "AI settings saved."),
    "projectpage.export_done_default": _pair("Экспорт завершён.", "Export finished."),
    "projectpage.converted_status": _pair(
        "Новый проект создан: {path}", "New project created: {path}"
    ),
    "projectpage.orientation_portrait": _pair("портрет", "portrait"),
    "projectpage.orientation_landscape": _pair("альбом", "landscape"),
    "projectpage.meta_ui_line": _pair("Интерфейс: {levels}", "UI: {levels}"),
    "projectpage.meta_window_note": _pair("окно настроит агент", "the agent sets up the window"),
    "projectpage.model_not_selected": _pair("модель не выбрана", "no model selected"),
    "projectpage.fallback_ai": _pair("ИИ", "AI"),
    "projectpage.active_model_tooltip": _pair(
        "Активная модель: {full} · {model}", "Active model: {full} · {model}"
    ),
    "projectpage.access_external": _pair(
        "внешний агент · API не требуется", "external agent · no API needed"
    ),
    "projectpage.access_need_key": _pair("нужен API-ключ", "API key needed"),
    "projectpage.access_key_saved": _pair("ключ сохранён", "key saved"),
    "projectpage.access_no_key": _pair("работает без ключа", "works without a key"),
    "projectpage.hint_module_missing": _pair(
        "Не установлена нужная библиотека. Установите её или попросите агента убрать зависимость.",
        "A required library is not installed. Install it or ask the agent to drop the dependency.",
    ),
    "projectpage.hint_import": _pair(
        "Ошибка импорта: модуль есть, но импортируется неверное имя или не хватает зависимости.",
        "Import error: the module exists but is imported by the wrong name or a dependency is missing.",
    ),
    "projectpage.hint_syntax": _pair(
        "В коде синтаксическая ошибка — файл нужно исправить и сохранить.",
        "There is a syntax error in the code — fix the file and save it.",
    ),
    "projectpage.hint_filenotfound": _pair(
        "Код обращается к файлу, которого нет в проекте. Проверьте путь к ассету.",
        "The code opens a file that is not in the project. Check the asset path.",
    ),
    "projectpage.hint_permission": _pair(
        "Не хватает прав на файл или папку. Закройте занявший файл и попробуйте снова.",
        "Missing permissions for a file or folder. Close whatever holds the file and try again.",
    ),
    "projectpage.hint_pygame": _pair(
        "Ошибка pygame: окно, звук или поверхность созданы неправильно для этого окружения.",
        "pygame error: a window, sound or surface was created incorrectly for this environment.",
    ),
    "projectpage.hint_type": _pair(
        "Ошибка в данных или вызове функции. Агент может найти точное место по трассировке.",
        "An error in data or a function call. The agent can find the exact place from the traceback.",
    ),
    "projectpage.hint_timeout": _pair(
        "Проект не завершился вовремя — проверьте бесконечные циклы или ожидание ввода.",
        "The project did not finish in time — check for infinite loops or waiting for input.",
    ),
    "projectpage.hint_generic": _pair(
        "Проект завершился с ошибкой. Полный вывод и трассировка остаются в консоли ниже.",
        "The project exited with an error. The full output and traceback stay in the console below.",
    ),
    "projectpage.success_title": _pair(
        "Проект запустился и завершился без ошибок",
        "The project ran and exited without errors",
    ),
    "projectpage.success_detail": _pair(
        "Предпросмотр работает. Можно менять код или попросить ИИ о следующем шаге.",
        "The preview works. You can edit the code or ask the AI for the next step.",
    ),
    "projectpage.no_start_title": _pair("Проект не запустился", "The project did not start"),
    "projectpage.exit_code_title": _pair(
        "Проект завершился с кодом {code}", "The project exited with code {code}"
    ),
    "projectpage.running_title": _pair(
        "Проект запущен в предпросмотре", "The project is running in the preview"
    ),
    "projectpage.running_detail": _pair(
        "Посмотрите окно проекта. Ошибки появятся здесь сразу после завершения процесса.",
        "Look at the project window. Errors will appear here as soon as the process exits.",
    ),
    "projectpage.external_agent_text": _pair(
        "Этот проект работает с внешним агентом. Скопируйте ошибку из консоли "
        "в задачу для Claude Code, Codex, Cursor или другого агента.",
        "This project works with an external agent. Copy the error from the console into "
        "a task for Claude Code, Codex, Cursor or another agent.",
    ),
    "projectpage.default_error": _pair("Проект завершился с ошибкой.", "The project exited with an error."),
    "projectpage.fix_prompt": _pair(
        "Проект не запускается. Найди причину, исправь файлы и проверь запуск.\n\n"
        "Ошибка запуска:\n{error}\n\n"
        "Сначала прочитай нужные файлы, затем измени только необходимое. "
        "В конце вызови validate_project и run_project.",
        "The project does not start. Find the cause, fix the files and verify it runs.\n\n"
        "Run error:\n{error}\n\n"
        "First read the relevant files, then change only what is necessary. "
        "Call validate_project and run_project at the end.",
    ),
    "projectpage.fix_prepared_status": _pair(
        "Задача с текстом ошибки подготовлена в ИИ-агенте.",
        "A task with the error text is prepared in the AI agent.",
    ),
    "projectpage.already_running": _pair("Проект уже запущен.", "The project is already running."),
    "projectpage.no_entry_title": _pair("Нет точки входа", "No entry point"),
    "projectpage.no_entry_text": _pair("Файл {name} не найден.", "The file {name} was not found."),
    "projectpage.console_project": _pair(
        "Проект: {name}\nПапка: {folder}\n", "Project: {name}\nFolder: {folder}\n"
    ),
    "projectpage.start_failed_console": _pair(
        "Не удалось запустить процесс.\n", "Could not start the process.\n"
    ),
    "projectpage.start_failed_title": _pair(
        "Не удалось запустить процесс", "Could not start the process"
    ),
    "projectpage.start_failed_detail": _pair(
        "Python или папка проекта недоступны. Проверьте установку Python в настройках.",
        "Python or the project folder is unavailable. Check the Python installation in the settings.",
    ),
    "projectpage.start_failed_error": _pair(
        "Процесс не стартовал за 5 секунд.", "The process did not start within 5 seconds."
    ),
    "projectpage.run_started_status": _pair(
        "Проект запущен. Заставка ~3 секунды, затем игра/приложение.",
        "The project is running. The splash takes ~3 seconds, then the game/app.",
    ),
    "projectpage.exit_console": _pair(
        "\nПроцесс завершён с кодом {code}.\n", "\nThe process exited with code {code}.\n"
    ),
    "projectpage.console_finished": _pair("Проект завершён", "Project finished"),
    "projectpage.console_finished_error": _pair(
        "Проект завершён с ошибкой ({code})", "Project exited with an error ({code})"
    ),
    "projectpage.event_success": _pair(
        "Проект запустился без ошибок", "The project ran without errors"
    ),
    "projectpage.event_failed": _pair(
        "Проект завершился с ошибкой (код {code})", "The project exited with an error (code {code})"
    ),
    "projectpage.finished_status": _pair("Проект завершён.", "The project finished."),
    "projectpage.finished_status_code": _pair(
        "Проект завершился с кодом {code}.", "The project exited with code {code}."
    ),
    "projectpage.process_error_console": _pair(
        "\nОшибка процесса: {error}\n", "\nProcess error: {error}\n"
    ),
    "projectpage.process_error_title": _pair("Ошибка запуска процесса", "Process start error"),
    "projectpage.process_error_detail": _pair(
        "Процесс не смог стартовать. Проверьте путь к Python и папку проекта.",
        "The process could not start. Check the Python path and the project folder.",
    ),
    "projectpage.stopping_console": _pair("\nОстанавливаю проект…\n", "\nStopping the project…\n"),
    "projectpage.console_stopped": _pair("Проект остановлен.", "Project stopped."),
    "projectpage.stopped_status": _pair("Проект остановлен пользователем.", "The project was stopped by the user."),
    "projectpage.stopped_title": _pair("Запуск остановлен", "Run stopped"),
    "projectpage.stopped_detail": _pair(
        "Проект остановлен до завершения. Запустите снова, когда будете готовы.",
        "The project was stopped before finishing. Run again when you are ready.",
    ),
    "projectpage.stat_tasks_value": _pair("задач выполнено", "tasks done"),
    "projectpage.activity": _pair("Активность: {time}", "Activity: {time}"),
    "projectpage.stat_files_value": _pair("файлов в проекте", "files in project"),
    "projectpage.notes_empty": _pair(
        "Заметок пока нет. Их можно добавить в настройках проекта или попросить агента.",
        "No notes yet. Add them in the project settings or ask the agent.",
    ),
    "projectpage.plan_empty": _pair(
        "План пока пуст. Агент создаст его при запуске.",
        "The plan is empty for now. The agent will create it when it runs.",
    ),
    "projectpage.files_tooltip": _pair(
        "Двойной клик — открыть в редакторе", "Double-click to open in the editor"
    ),
    "projectpage.files_empty": _pair("Пока нет изменённых файлов.", "No changed files yet."),
    "projectpage.agent_error_title": _pair(
        "Агент не смог завершить работу", "The agent could not finish"
    ),
    "projectpage.agent_error_detail": _pair(
        "Подробности — в чате агента. Проверьте ключ, модель и сеть, "
        "затем запустите задачу снова.",
        "Details are in the agent chat. Check the key, the model and the network, "
        "then run the task again.",
    ),
    "projectpage.agent_error_fallback": _pair("Ошибка ИИ-агента.", "AI agent error."),
    "projectpage.agent_incomplete_title": _pair(
        "Агент не завершил работу", "The agent did not finish"
    ),
    "projectpage.agent_incomplete_detail": _pair(
        "Агент остановился до проверки и запуска. Запустите проект, "
        "чтобы увидеть результат, или продолжите задачу в чате.",
        "The agent stopped before validating and running. Run the project to see the "
        "result, or continue the task in the chat.",
    ),
    "projectpage.agent_done_title": _pair(
        "Агент изменил проект — проверьте предпросмотр",
        "The agent changed the project — check the preview",
    ),
    "projectpage.agent_done_detail": _pair(
        "Запустите проект, чтобы увидеть результат. Если стало хуже, верните версию из истории.",
        "Run the project to see the result. If it got worse, restore a version from history.",
    ),
    "projectpage.agent_finished_status": _pair(
        "Агент завершил работу. Прогресс обновлён.", "The agent finished. Progress updated."
    ),
    # --- New-project wizard (editor/new_project.py) ---------------------
    "newproj.title": _pair("Новый проект — Reasonable Engine", "New project — Reasonable Engine"),
    "newproj.heading": _pair("Новый проект", "New project"),
    "newproj.pill_idea": _pair("Идея", "Idea"),
    "newproj.pill_name": _pair("Название", "Name"),
    "newproj.pill_blank": _pair("Пустой проект", "Blank project"),
    "newproj.goal_page_title": _pair("С чего начинается проект?", "Where does a project start?"),
    "newproj.goal_page_sub": _pair(
        "Одно короткое предложение — главная идея. Детали, окно и первую задачу "
        "агенту добавим после создания, когда проект уже будет перед глазами.",
        "One short sentence — the main idea. Details, the window and the first agent "
        "task come after creation, once the project is in front of you.",
    ),
    "newproj.goal_label": _pair("Главная цель", "Main goal"),
    "newproj.goal_placeholder": _pair(
        "Например: 2D-платформер, где кот собирает звёзды и убегает от слизней",
        "For example: a 2D platformer where a cat collects stars and runs from slugs",
    ),
    "newproj.goal_hint": _pair(
        "Коротко и по делу: жанр + герой + главное действие.",
        "Short and to the point: genre + hero + main action.",
    ),
    "newproj.type_section": _pair("Что создаём", "What are we building"),
    "newproj.type_game": _pair("ИГРА", "GAME"),
    "newproj.type_game_hint": _pair("Уровни, персонажи, очки, геймплей", "Levels, characters, scores, gameplay"),
    "newproj.type_app": _pair("ПРИЛОЖЕНИЕ", "APP"),
    "newproj.type_app_hint": _pair("Экраны, списки, формы, ИИ-панели", "Screens, lists, forms, AI panels"),
    "newproj.levels_section": _pair("Уровень интерфейса", "Interface level"),
    "newproj.level_hint_simple": _pair(
        "Обычные окна, кнопки и списки. Для утилит и программ Windows",
        "Plain windows, buttons and lists. For utilities and Windows programs",
    ),
    "newproj.level_hint_standard": _pair(
        "Готовые виджеты движка: тёмная тема, панели, списки, прокрутка",
        "Ready-made engine widgets: dark theme, panels, lists, scrolling",
    ),
    "newproj.level_hint_advanced": _pair(
        "Своя графика, частицы, анимации. Для игр",
        "Your own graphics, particles, animations. For games",
    ),
    "newproj.levels_hint": _pair(
        "Можно выбрать несколько: в проект лягут только нужные инструменты и навыки.",
        "You can pick several: only the tools and skills you need go into the project.",
    ),
    "newproj.mode_section": _pair("Кто будет собирать проект", "Who will build the project"),
    "newproj.mode_builtin": _pair("ВСТРОЕННЫЙ ИИ", "BUILT-IN AI"),
    "newproj.mode_builtin_hint": _pair("Агент работает прямо в редакторе", "The agent works right in the editor"),
    "newproj.mode_external": _pair("ВНЕШНИЙ АГЕНТ", "EXTERNAL AGENT"),
    "newproj.mode_external_hint": _pair("Claude Code, Codex, Cursor, Cline…", "Claude Code, Codex, Cursor, Cline…"),
    "newproj.mode_hint_initial": _pair(
        "Встроенный агент сразу читает проект, меняет файлы, рисует спрайты и показывает прогресс.",
        "The built-in agent reads the project right away, edits files, draws sprites and shows progress.",
    ),
    "newproj.mode_hint_external": _pair(
        "Внешний агент: редактор подготовит AGENT_GUIDE.md, навыки, re.bat и будет "
        "показывать его прогресс в реальном времени. Работает с Claude Code, Codex, Cursor, Cline и другими.",
        "External agent: the editor prepares AGENT_GUIDE.md, skills, re.bat and shows its "
        "progress in real time. Works with Claude Code, Codex, Cursor, Cline and others.",
    ),
    "newproj.mode_hint_builtin": _pair(
        "Встроенный агент: работает сразу в редакторе, меняет файлы, рисует спрайты и "
        "показывает план и прогресс. Нужен настроенный провайдер ИИ.",
        "Built-in agent: works right in the editor, edits files, draws sprites and shows "
        "the plan and progress. Needs a configured AI provider.",
    ),
    "newproj.after_title": _pair("Что будет дальше", "What happens next"),
    "newproj.after_text": _pair(
        "После создания откроется проект и раздел «ИИ-агент». Там вы напишете "
        "первую задачу и сможете менять окно, заметки, код и ассеты.",
        "After creation the project opens with the “AI agent” section. There you write "
        "the first task and can change the window, notes, code and assets.",
    ),
    "newproj.blank_title": _pair("Минимальный шаблон", "Minimal template"),
    "newproj.blank_text": _pair(
        "Будет создан короткий main.py с пустым окном, project.json, папка assets "
        "и инструкции для агента. Никакая игра и никакие вопросы про ИИ не создаются: "
        "вы сразу попадёте в редактор кода и сможете писать сами или позвать агента.",
        "A short main.py with an empty window, project.json, an assets folder and agent "
        "instructions will be created. No game and no AI questions: you land straight in "
        "the code editor and can write yourself or call the agent.",
    ),
    "newproj.blank_header": _pair("Пустой проект", "Blank project"),
    "newproj.blank_sub": _pair(
        "Сразу к результату: создаём минимальный проект без игры и без вопросов "
        "про ИИ. Вы начнёте с пустого main.py, который уже запускается.",
        "Straight to the result: we create a minimal project with no game and no AI "
        "questions. You start with an empty main.py that already runs.",
    ),
    "newproj.blank_name_placeholder": _pair("Мой проект", "My project"),
    "newproj.finish_header": _pair("Название и место", "Name and location"),
    "newproj.finish_sub": _pair(
        "Последний штрих. Укажите имя проекта и папку — остальное Reasonable Engine сделает сам.",
        "The last touch. Give the project a name and a folder — Reasonable Engine does the rest.",
    ),
    "newproj.name_label": _pair("Название проекта (на английском)", "Project name (in English)"),
    "newproj.name_hint": _pair(
        "Латиницей, например «Task Manager». Используется для папки и файлов проекта.",
        "Latin letters, e.g. “Task Manager”. Used for the project folder and files.",
    ),
    "newproj.ai_title": _pair("ИИ для проекта", "AI for the project"),
    "newproj.configure_ai": _pair("Настроить ИИ", "Configure AI"),
    "newproj.summary_label": _pair("Сводка", "Summary"),
    "newproj.task_after_title": _pair("Первая задача — после создания", "First task — after creation"),
    "newproj.task_after_text": _pair(
        "Мастер не просит писать техническое задание заранее. После создания "
        "откроется раздел «ИИ-агент», где вы опишете первую задачу обычными словами.",
        "The wizard does not ask for a spec in advance. After creation the “AI agent” "
        "section opens, where you describe the first task in plain words.",
    ),
    "newproj.progress_title": _pair("Собираю проект", "Building the project"),
    "newproj.progress_stage": _pair("Готовлю папки и файлы…", "Preparing folders and files…"),
    "newproj.open_project_btn": _pair("Открыть проект", "Open project"),
    "newproj.goal_required_title": _pair("Нужна цель", "Goal needed"),
    "newproj.goal_required_text": _pair(
        "Опишите главную цель проекта хотя бы тремя символами.",
        "Describe the main goal of the project with at least three characters.",
    ),
    "newproj.create_btn": _pair("Создать проект", "Create project"),
    "newproj.folder_dialog": _pair("Куда сохранить проект", "Where to save the project"),
    "newproj.folder_hint": _pair("Проект появится здесь: {target}", "The project will appear here: {target}"),
    "newproj.model_unspecified": _pair("не указана", "unspecified"),
    "newproj.badge_not_required": _pair("Не требуется", "Not required"),
    "newproj.external_api_text": _pair(
        "{name} · {model}\nВнешний режим не использует API редактора. Если захотите "
        "включить встроенного агента позже, ключ можно добавить в настройках.",
        "{name} · {model}\nExternal mode does not use the editor API. If you enable the "
        "built-in agent later, the key can be added in the settings.",
    ),
    "newproj.need_key_text": _pair(
        "{name} · {model}\nДля этой модели нужен API-ключ. Проект можно создать сейчас, "
        "но агент запустится только после настройки.",
        "{name} · {model}\nThis model needs an API key. The project can be created now, "
        "but the agent will only run after setup.",
    ),
    "newproj.local_provider": _pair("Локальный провайдер", "Local provider"),
    "newproj.ready_text": _pair(
        "{name} · {model}\n{base_url}", "{name} · {model}\n{base_url}"
    ),
    "newproj.kind_game": _pair("Игра", "Game"),
    "newproj.kind_app": _pair("Приложение", "App"),
    "newproj.summary_blank": _pair(
        "Пустой проект · минимальный main.py\n"
        "Без игры и без вопросов про ИИ\n"
        "После создания откроется раздел «Код»\n"
        "Папка: {folder}",
        "Blank project · minimal main.py\n"
        "No game and no AI questions\n"
        "The “Code” section opens after creation\n"
        "Folder: {folder}",
    ),
    "newproj.summary_line": _pair(
        "{kind} · {mode}\nИнтерфейс: {levels}\nПапка: {folder}",
        "{kind} · {mode}\nUI: {levels}\nFolder: {folder}",
    ),
    "newproj.fallback_name": _pair("Новый проект", "New project"),
    "newproj.name_dialog_title": _pair("Название проекта", "Project name"),
    "newproj.name_invalid_text": _pair(
        "Название должно быть на английском: начинаться с буквы, содержать только "
        "латинские буквы, цифры, пробелы, дефис или подчёркивание (2–60 символов).\n"
        "Например: Task Manager или my-great-game",
        "The name must be in English: start with a letter, contain only Latin letters, "
        "digits, spaces, a hyphen or underscore (2–60 characters).\n"
        "For example: Task Manager or my-great-game",
    ),
    "newproj.mkdir_failed_title": _pair("Не удалось создать папку", "Could not create the folder"),
    "newproj.done_title": _pair("Проект готов!", "Project ready!"),
    "newproj.done_stage_blank": _pair("{name} · пустой проект", "{name} · blank project"),
    "newproj.done_detail_blank": _pair(
        "Созданы минимальный main.py, project.json, папка assets и инструкции для агента.\n"
        "Сейчас откроется раздел «Код» — можно писать самому или позвать ИИ-агента.",
        "A minimal main.py, project.json, an assets folder and agent instructions were "
        "created.\nThe “Code” section opens next — write yourself or call the AI agent.",
    ),
    "newproj.done_stage": _pair("{name} · {mode}", "{name} · {mode}"),
    "newproj.done_detail": _pair(
        "Созданы main.py, project.json, иконка, фон, стартовые спрайты, "
        "progress/ и инструкции для агента.\n"
        "Первая задача пишется в разделе «ИИ-агент» — уже после создания.",
        "main.py, project.json, an icon, a background, starter sprites, progress/ and "
        "agent instructions were created.\n"
        "The first task is written in the “AI agent” section — after creation.",
    ),
    "newproj.failed_title": _pair("Не удалось создать проект", "Could not create the project"),
    "newproj.close_confirm_title": _pair("Создание проекта", "Creating the project"),
    "newproj.close_confirm_text": _pair(
        "Проект ещё создаётся. Закрыть окно? Это может оставить неполные файлы.",
        "The project is still being created. Close the window? This may leave incomplete files.",
    ),
    # --- Conversion preview (core/convert.py) ---------------------------
    "convert.orientation.landscape": _pair("альбомная", "landscape"),
    "convert.orientation.portrait": _pair("портретная", "portrait"),
    "convert.mode.builtin": _pair("встроенный ИИ", "built-in AI"),
    "convert.mode.external": _pair("внешний агент", "external agent"),
    "convert.window_mode.windowed": _pair("окно", "windowed"),
    "convert.window_mode.fullscreen": _pair("полный экран", "fullscreen"),
    "convert.change.platform": _pair("Платформа: {old} → {new}", "Platform: {old} → {new}"),
    "convert.change.name": _pair("Название: {old} → {new}", "Name: {old} → {new}"),
    "convert.change.orientation": _pair("Ориентация: {old} → {new}", "Orientation: {old} → {new}"),
    "convert.change.mode": _pair("Агент: {old} → {new}", "Agent: {old} → {new}"),
    "convert.change.window_mode": _pair("Режим окна: {old} → {new}", "Window mode: {old} → {new}"),
    "convert.change.size": _pair("Базовый размер: {old} → {new}", "Base size: {old} → {new}"),
    "convert.change.resizable_on": _pair(
        "Изменение размера окна: выключено → включено", "Window resizing: off → on"
    ),
    "convert.change.resizable_off": _pair(
        "Изменение размера окна: включено → выключено", "Window resizing: on → off"
    ),
    "convert.change.ui_levels": _pair("Интерфейс: {old} → {new}", "UI: {old} → {new}"),
    "convert.change.reset": _pair(
        "Прогресс, план и лента событий: сбросить", "Progress, plan and event feed: reset"
    ),
    # --- External-agent UI (checklist labels; the agent pack itself is English-only) ---
    "external.check_guide": _pair("AGENT_GUIDE.md создан", "AGENT_GUIDE.md created"),
    "external.check_guide_hint": _pair("Полная инструкция для агента", "Full instructions for the agent"),
    "external.check_skills": _pair("Навыки skills/ на месте", "skills/ pack present"),
    "external.check_skills_hint": _pair("Игровой и UI-опыт", "Game and UI know-how"),
    "external.check_cli": _pair("CLI re.bat / re.sh", "CLI re.bat / re.sh"),
    "external.check_cli_hint": _pair("Обновление прогресса и экспорт", "Progress updates and export"),
    "external.check_state": _pair("progress/state.json", "progress/state.json"),
    "external.check_state_hint": _pair("Живой прогресс в редакторе", "Live progress in the editor"),
    "external.check_pointers": _pair("Указатели для агентов", "Agent pointer files"),
    "external.check_pointers_hint": _pair("Claude Code, Codex, Cursor, Cline", "Claude Code, Codex, Cursor, Cline"),
    "external.check_engine": _pair("Встроенный движок", "Vendored engine"),
    "external.check_engine_hint": _pair("Проект самодостаточен", "The project is self-contained"),
    "external.readme_header": _pair("Внешний агент · {name}", "External agent · {name}"),
    # --- Project settings dialog (editor/project_settings.py) ---
    "projset.title": _pair("Настройки проекта", "Project settings"),
    "projset.advanced": _pair("Расширенные параметры", "Advanced options"),
    "projset.advanced_hint": _pair("Версия Android и служебные параметры.", "Android version and service settings."),
    "projset.badge_builtin": _pair("ВСТРОЕННЫЙ", "BUILT-IN"),
    "projset.badge_external": _pair("ВНЕШНИЙ", "EXTERNAL"),
    "projset.intro": _pair(
        "Меняйте название, цель и заметки в любой момент. Расширенные параметры — "
        "под переключателем. Папка проекта остаётся на месте.",
        "Change the name, goal and notes at any time. Advanced options are under "
        "the toggle. The project folder stays where it is.",
    ),
    "projset.author": _pair("Автор", "Author"),
    "projset.goal": _pair("Главная цель", "Main goal"),
    "projset.notes_placeholder": _pair(
        "Необязательные требования и пожелания. Первую задачу агенту пишите в разделе «ИИ-агент».",
        "Optional requirements and wishes. Write the first task for the agent in the \"AI agent\" section.",
    ),
    "projset.notes": _pair("Заметки и требования", "Notes and requirements"),
    "projset.android_version": _pair("Версия Android", "Android version"),
    "projset.advanced_note": _pair(
        "Параметры окна агент настраивает сам — пользователь их не видит. "
        "Ориентация экрана для Android применяется при следующем экспорте. "
        "Платформа проекта меняется через «Конвертировать…» — создаётся новый "
        "проект, эта папка остаётся как есть.",
        "The agent configures window options itself — the user does not see them. "
        "Android screen orientation applies on the next export. The project platform "
        "changes via \"Convert…\" — a new project is created and this folder stays as is.",
    ),
    "projset.save": _pair("Сохранить", "Save"),
    "projset.empty_name": _pair("Название проекта не может быть пустым.", "The project name cannot be empty."),
    "projset.save_error": _pair("Ошибка сохранения", "Save error"),
    # --- Background workers (editor/workers.py) ---
    "workers.scaffold_structure": _pair("Создаю структуру проекта…", "Creating the project structure…"),
    "workers.scaffold_assets": _pair(
        "Генерирую иконку, фон и стартовые спрайты…",
        "Generating the icon, background and starter sprites…",
    ),
    "workers.sprite_image": _pair("Генерирую изображение…", "Generating the image…"),
    "workers.convert_copy": _pair(
        "Копирую проект без кэшей и старых экспортов…",
        "Copying the project without caches and old exports…",
    ),
    "workers.convert_engine": _pair(
        "Применяю настройки и встраиваю движок…",
        "Applying settings and embedding the engine…",
    ),
    "workers.convert_progress": _pair(
        "Обновляю инструкции агента и прогресс…",
        "Updating agent instructions and progress…",
    ),
    "workers.provider_test_prompt": _pair(
        "Ответь ровно одним словом: работает",
        "Answer with exactly one word: works",
    ),
    "workers.provider_test_ok": _pair(
        "Модель ответила пустым сообщением, но соединение работает.",
        "The model returned an empty message, but the connection works.",
    ),
    # --- Chat panel (editor/chat.py) ---
    "chat.role_user": _pair("Вы", "You"),
    "chat.role_tool": _pair("Инструмент", "Tool"),
    "chat.role_system": _pair("Система", "System"),
    "chat.role_error": _pair("Ошибка", "Error"),
    "chat.show_full": _pair("Показать полностью", "Show full text"),
    "chat.collapse": _pair("Свернуть", "Collapse"),
    "chat.action_create": _pair("создан", "created"),
    "chat.action_edit": _pair("изменён", "edited"),
    "chat.action_delete": _pair("удалён", "deleted"),
    "chat.action_generate": _pair("сгенерирован", "generated"),
    "chat.changes_heading": _pair("Что изменил агент", "What the agent changed"),
    "chat.file_count": _pair("{count} файл(ов)", "{count} file(s)"),
    "chat.no_changes": _pair(
        "Агент не изменил файлы проекта. Проверьте план и формулировку задачи.",
        "The agent did not change any project files. Check the plan and the task wording.",
    ),
    "chat.open_in_code": _pair("Клик — открыть в редакторе кода", "Click to open in the code editor"),
    "chat.more_files": _pair(
        "Ещё {count} файл(ов) — полный список в истории.",
        "{count} more file(s) — the full list is in the history.",
    ),
    "chat.snapshot_note": _pair(
        "Рабочая версия сохранена перед запуском: «{label}». "
        "Если результат хуже — верните её одним кликом.",
        "A working version was saved before the run: “{label}”. "
        "If the result is worse, restore it with a single click.",
    ),
    "chat.undo_button": _pair("↶ Отменить эти изменения", "↶ Undo these changes"),
    "chat.undo_tip": _pair(
        "Восстановить файлы из снимка, созданного перед запуском агента",
        "Restore files from the snapshot created before the agent run",
    ),
    "chat.history_button": _pair("История версий", "Version history"),
    "chat.title": _pair("ИИ-агент", "AI agent"),
    "chat.model_none": _pair("модель не выбрана", "no model selected"),
    "chat.ai_fallback": _pair("ИИ", "AI"),
    "chat.status_ready_badge": _pair("ГОТОВ", "READY"),
    "chat.stop_button": _pair("■  Остановить", "■  Stop"),
    "chat.clear_button": _pair("Очистить", "Clear"),
    "chat.chat_label": _pair("Чат:", "Chat:"),
    "chat.chat_select_tip": _pair("Выберите сохранённый чат", "Choose a saved chat"),
    "chat.untitled_chat": _pair("Новый чат", "New chat"),
    "chat.new_chat_tip": _pair("Создать новый чат", "Create a new chat"),
    "chat.delete_chat_tip": _pair("Удалить текущий чат", "Delete the current chat"),
    "chat.delete_chat_title": _pair("Удалить чат?", "Delete chat?"),
    "chat.delete_chat_text": _pair(
        "Чат «{title}» будет удалён без возможности восстановления.",
        "The chat “{title}” will be deleted permanently.",
    ),
    "chat.improve_button": _pair("Улучшить", "Improve"),
    "chat.improve_tip": _pair(
        "Проанализировать весь код и предложить улучшения",
        "Review all code and suggest improvements",
    ),
    "chat.improve_chat_title": _pair("Улучшения", "Improvements"),
    "chat.improve_working": _pair(
        "Изучаю проект и готовлю предложения…",
        "Reviewing the project and preparing suggestions…",
    ),
    "chat.intro_heading": _pair("Опишите первую задачу", "Describe the first task"),
    "chat.intro_text": _pair(
        "Агент прочитает проект, составит план, изменит файлы и проверит запуск.",
        "The agent will read the project, build a plan, change files and check that it runs.",
    ),
    "chat.suggest_vertical_slice": _pair("Собери вертикальный срез", "Build a vertical slice"),
    "chat.suggest_vertical_slice_prompt": _pair(
        "Собери рабочий вертикальный срез проекта и проверь запуск.",
        "Build a working vertical slice of the project and check that it runs.",
    ),
    "chat.suggest_visual": _pair("Улучши визуал", "Improve the visuals"),
    "chat.suggest_visual_prompt": _pair(
        "Улучши визуал: фон, спрайты, частицы, анимации и переходы.",
        "Improve the visuals: background, sprites, particles, animations and transitions.",
    ),
    "chat.suggest_menu": _pair("Добавь меню и сохранение", "Add a menu and saving"),
    "chat.suggest_menu_prompt": _pair(
        "Добавь главное меню, экран настроек и сохранение прогресса.",
        "Add a main menu, a settings screen and progress saving.",
    ),
    "chat.suggest_fix": _pair("Проверь и исправь", "Check and fix"),
    "chat.suggest_fix_prompt": _pair(
        "Проверь проект, исправь ошибки и доведи его до стабильного запуска.",
        "Check the project, fix the errors and bring it to a stable launch.",
    ),
    "chat.plan_heading": _pair("Текущий план", "Current plan"),
    "chat.plan_hint": _pair(
        "План появится после первой задачи: агент разобьёт работу на шаги и будет отмечать их здесь.",
        "The plan appears after the first task: the agent will break the work into steps and mark them here.",
    ),
    "chat.plan_more_tasks": _pair(
        "+{count} задач — во вкладке «Обзор».",
        "+{count} tasks — on the \"Overview\" tab.",
    ),
    "chat.input_placeholder": _pair(
        "Напишите задачу агенту…  Enter — отправить, Ctrl+Enter — новая строка",
        "Write a task for the agent…  Enter to send, Ctrl+Enter for a new line",
    ),
    "chat.input_hint": _pair(
        "Агент меняет файлы в проекте и показывает прогресс.",
        "The agent changes project files and shows progress.",
    ),
    "chat.send_button": _pair("Отправить", "Send"),
    "chat.prefill_note": _pair(
        "Задача подготовлена — проверьте текст и отправьте агенту.",
        "Task prepared — check the text and send it to the agent.",
    ),
    "chat.step_progress_total": _pair(
        "Шаг {step} из {total} · агент работает…",
        "Step {step} of {total} · the agent is working…",
    ),
    "chat.step_progress": _pair("Шаг {step} · агент работает…", "Step {step} · the agent is working…"),
    "chat.tool_label": _pair("Инструмент: {name}", "Tool: {name}"),
    "chat.token_count": _pair("{count} токенов", "{count} tokens"),
    "chat.usage_total": _pair(
        "Всего: {tokens} токенов · {time}",
        "Total: {tokens} tokens · {time}",
    ),
    "chat.usage_tooltip": _pair(
        "За всё время в этом проекте\nЗапросов: {requests}\nОтправлено: {prompt}\nПолучено: {completion}\nВремя генерации: {time}",
        "All time in this project\nRequests: {requests}\nSent: {prompt}\nReceived: {completion}\nGeneration time: {time}",
    ),
    "chat.time_less_minute": _pair("меньше минуты", "less than a minute"),
    "chat.time_minutes": _pair("{minutes} мин", "{minutes} min"),
    "chat.time_hours_minutes": _pair("{hours} ч {minutes:02d} мин", "{hours} h {minutes:02d} min"),
    "chat.snapshot_saved": _pair(
        "Снимок рабочей версии сохранён — изменения можно отменить.",
        "Working version snapshot saved — changes can be undone.",
    ),
    "chat.snapshot_failed": _pair(
        "Не удалось сохранить снимок проекта.",
        "Could not save the project snapshot.",
    ),
    "chat.done_short": _pair("Готово.", "Done."),
    "chat.incomplete_prefix": _pair("Работа не завершена: ", "Work not finished: "),
    "chat.incomplete_default": _pair(
        "агент остановился раньше времени.",
        "the agent stopped too early.",
    ),
    "chat.badge_done": _pair("ГОТОВО", "DONE"),
    "chat.badge_error": _pair("ОШИБКА", "ERROR"),
    "chat.badge_working": _pair("РАБОТАЕТ", "WORKING"),
    "chat.badge_incomplete": _pair("НЕ ЗАВЕРШЕНО", "INCOMPLETE"),
    "chat.badge_stopped": _pair("ОСТАНОВЛЕН", "STOPPED"),
    "chat.finish_done": _pair(
        "Агент завершил работу. Файлы проекта изменены, проверка и запуск пройдены.",
        "The agent finished. Project files changed; checks and the test run passed.",
    ),
    "chat.finish_incomplete": _pair(
        "Агент остановился, не доведя работу до проверки и запуска.",
        "The agent stopped before finishing the checks and the test run.",
    ),
    "chat.finish_failed": _pair("Ошибка: {message}", "Error: {message}"),
    "chat.finish_cancelled": _pair("Работа остановлена.", "Work stopped."),
    "chat.stopping": _pair("Останавливаю…", "Stopping…"),
    "chat.stopping_step": _pair(
        "Останавливаю агента после текущего шага…",
        "Stopping the agent after the current step…",
    ),
    "chat.studying": _pair("Агент изучает проект…", "The agent is studying the project…"),
    "chat.not_configured_title": _pair("ИИ не настроен", "AI is not configured"),
    "chat.not_configured_text": _pair(
        "{reason}.\n\nОткройте настройки и выберите провайдера или добавьте ключ.",
        "{reason}.\n\nOpen the settings and choose a provider or add a key.",
    ),
    "chat.agent_running_title": _pair("Агент работает", "The agent is running"),
    "chat.agent_running_text": _pair(
        "Сначала остановите агента.",
        "Stop the agent first.",
    ),
    "chat.step_tasks": _pair("{stage}  ·  задачи {done}/{total}", "{stage}  ·  tasks {done}/{total}"),
    # -- agent error categories (core/agent_errors.py) ------------------
    "errors.kind_server": _pair("Ошибки сервера (5xx)", "Server errors (5xx)"),
    "errors.kind_server_hint": _pair(
        "Провайдер временно не смог обработать запрос.",
        "The provider temporarily could not process the request.",
    ),
    "errors.kind_rate_limit": _pair("Перегрузка и лимиты (429)", "Overload and rate limits (429)"),
    "errors.kind_rate_limit_hint": _pair(
        "Слишком много запросов или бесплатный лимит исчерпан.",
        "Too many requests or the free limit is exhausted.",
    ),
    "errors.kind_timeout": _pair("Тайм-аут ответа", "Response timeout"),
    "errors.kind_timeout_hint": _pair(
        "Сервер не ответил за отведённое время.",
        "The server did not answer in time.",
    ),
    "errors.kind_network": _pair("Обрыв или отказ соединения", "Connection lost or refused"),
    "errors.kind_network_hint": _pair(
        "Проблема с сетью, локальным сервером или портом.",
        "A problem with the network, local server or port.",
    ),
    "errors.kind_bad_response": _pair("Некорректный ответ сервера", "Invalid server response"),
    "errors.kind_bad_response_hint": _pair(
        "Сервер вернул пустой или нечитаемый ответ.",
        "The server returned an empty or unreadable response.",
    ),
    # -- chat: continue after a server error -----------------------------
    "chat.continue_button": _pair("Продолжай", "Continue"),
    "chat.continue_prompt": _pair("Продолжай", "Continue"),
    "chat.auto_continue_check": _pair("Продолжать автоматически", "Continue automatically"),
    "chat.auto_continue_check_tip": _pair(
        "Автоматически отправлять «Продолжай» после таких ошибок. "
        "Отключить можно в настройках.",
        "Send “Continue” automatically after these errors. "
        "You can turn this off in settings.",
    ),
    "chat.auto_continue_hint": _pair(
        "В следующий раз агент продолжит сам после такой ошибки.",
        "Next time the agent will continue by itself after this error.",
    ),
    "chat.supervisor_found": _pair(
        "Независимая проверка нашла невыполненные пункты.",
        "The independent check found unfinished items.",
    ),
    "chat.auto_continue_hint_on": _pair(
        "Автопродолжение включено. Число попыток не ограничено; интервал растёт, "
        "чтобы не перегружать сервер. Отключить можно в настройках.",
        "Automatic continuation is on. Attempts are unlimited; the interval grows "
        "so the server is not hammered. You can turn it off in settings.",
    ),
    # -- chat: compact tool call cards (editor/chat.py) -----------------
    "chat.tool_group": _pair("Вызовы инструментов", "Tool calls"),
    "chat.tool_group_hint": _pair(
        "Свернуть или развернуть все вызовы",
        "Collapse or expand all calls",
    ),
    "chat.tool_toggle_hint": _pair(
        "Нажмите, чтобы показать или скрыть подробности",
        "Click to show or hide the details",
    ),
    "chat.tool_list_files": _pair("Файлы проекта", "Project files"),
    "chat.tool_read_file": _pair("Чтение файла", "Reading a file"),
    "chat.tool_write_file": _pair("Запись файла", "Writing a file"),
    "chat.tool_edit_file": _pair("Правка файла", "Editing a file"),
    "chat.tool_delete_path": _pair("Удаление", "Deleting"),
    "chat.tool_search_text": _pair("Поиск по проекту", "Searching the project"),
    "chat.tool_run_command": _pair("Команда", "Command"),
    "chat.tool_run_project": _pair("Запуск проекта", "Running the project"),
    "chat.tool_validate_project": _pair("Проверка проекта", "Validating the project"),
    "chat.tool_generate_sprite": _pair("Генерация спрайта", "Generating a sprite"),
    "chat.tool_draw_sprite": _pair("Рисование спрайта", "Drawing a sprite"),
    "chat.tool_generate_background": _pair("Генерация фона", "Generating a background"),
    "chat.tool_inspect_image": _pair("Проверка изображения", "Inspecting an image"),
    "chat.tool_set_plan": _pair("План работ", "Work plan"),
    "chat.tool_update_task": _pair("Обновление задачи", "Updating a task"),
    "chat.tool_report_progress": _pair("Прогресс", "Progress"),
    "chat.tool_get_progress": _pair("Чтение прогресса", "Reading progress"),
    "chat.tool_finish": _pair("Завершение", "Finishing"),
    "chat.tool_unknown": _pair("Инструмент", "Tool"),
    "chat.tool_running": _pair("Выполняется…", "Running…"),
    "chat.tool_stopped": _pair("Остановлено", "Stopped"),
    "chat.tool_task_count": _pair("задач: {count}", "tasks: {count}"),
    "chat.tool_no_output": _pair("Нет вывода", "No output"),
    "chat.tool_no_matches": _pair("Совпадений нет", "No matches"),
    "chat.tool_no_issues": _pair("Ошибок нет", "No errors"),
    "chat.tool_truncated": _pair("… (сокращено)", "… (truncated)"),
    "chat.task_status_pending": _pair("ожидает", "pending"),
    "chat.task_status_in_progress": _pair("в работе", "in progress"),
    "chat.task_status_done": _pair("готово", "done"),
    "chat.task_status_skipped": _pair("пропущено", "skipped"),
    # --- Reusable widgets (editor/widgets.py) ---
    "widgets.kind_game": _pair("Игра", "Game"),
    "widgets.kind_app": _pair("Приложение", "App"),
    "widgets.delete_project": _pair("Удалить проект", "Delete project"),
    # --- Export dialog (editor/export_dialog.py) ---
    "exportdlg.android_help": _pair(
        "Сборка APK выполняется на Linux или в WSL2:\n"
        "\n"
        "1. Установите WSL: wsl --install\n"
        "2. В Ubuntu выполните:\n"
        "   sudo apt update && sudo apt install -y git zip unzip openjdk-17-jdk \\\\\n"
        "     autoconf libtool pkg-config zlib1g-dev libncurses5-dev libncursesw5-dev \\\\\n"
        "     libtinfo6 cmake libffi-dev libssl-dev\n"
        "   pip install --user buildozer cython\n"
        "3. cd <папка-экспорта>\n"
        "4. buildozer -v android debug\n"
        "5. APK появится в bin/ — установите через adb install -r bin/*.apk\n"
        "\n"
        "В экспортированном пакете есть README_ANDROID.md и готовый GitHub Actions\n"
        "workflow: загрузите проект в GitHub и получите APK во вкладке Actions.",
        "The APK is built on Linux or inside WSL2:\n"
        "\n"
        "1. Install WSL: wsl --install\n"
        "2. In Ubuntu run:\n"
        "   sudo apt update && sudo apt install -y git zip unzip openjdk-17-jdk \\\n"
        "     autoconf libtool pkg-config zlib1g-dev libncurses5-dev libncursesw5-dev \\\n"
        "     libtinfo6 cmake libffi-dev libssl-dev\n"
        "   pip install --user buildozer cython\n"
        "3. cd <export folder>\n"
        "4. buildozer -v android debug\n"
        "5. The APK appears in bin/ — install it with adb install -r bin/*.apk\n"
        "\n"
        "The exported package contains README_ANDROID.md and a ready GitHub Actions\n"
        "workflow: push the project to GitHub and get the APK in the Actions tab.",
    ),
    "exportdlg.window_title": _pair("Экспорт — Reasonable Engine", "Export — Reasonable Engine"),
    "exportdlg.header": _pair("Экспорт проекта", "Project export"),
    "exportdlg.subtitle": _pair(
        "Windows — папка или .exe. Android — готовый buildozer-пакет.",
        "Windows — folder or .exe. Android — ready-to-build buildozer package.",
    ),
    "exportdlg.choice_windows": _pair("WINDOWS · ПАПКА", "WINDOWS · FOLDER"),
    "exportdlg.choice_windows_hint": _pair("Play.bat и файлы проекта.", "Play.bat and the project files."),
    "exportdlg.choice_exe": _pair("WINDOWS · .EXE", "WINDOWS · .EXE"),
    "exportdlg.choice_exe_hint": _pair("Один файл через PyInstaller.", "A single file via PyInstaller."),
    "exportdlg.choice_android": _pair("ANDROID · ПАКЕТ", "ANDROID · PACKAGE"),
    "exportdlg.choice_android_hint": _pair("buildozer.spec, ZIP и инструкция.", "buildozer.spec, a ZIP and instructions."),
    "exportdlg.explain_windows": _pair("Папка Windows", "Windows folder"),
    "exportdlg.explain_windows_text": _pair(
        "Самодостаточная папка: main.py, assets/, встроенный движок и Play.bat. "
        "Запускается на Windows с Python 3.10+. Заставка Reasonable Engine играет всегда.",
        "A self-contained folder: main.py, assets/, the bundled engine and Play.bat. "
        "Runs on Windows with Python 3.10+. The Reasonable Engine splash always plays.",
    ),
    "exportdlg.output_title": _pair("Куда сохранить", "Where to save"),
    "exportdlg.browse": _pair("Изменить…", "Change…"),
    "exportdlg.output_hint_windows": _pair(
        "По умолчанию — Рабочий стол. Если папка уже есть, новая получит суффикс -2.",
        "Defaults to the Desktop. If the folder already exists, the new one gets a -2 suffix.",
    ),
    "exportdlg.contents_title": _pair("Что внутри", "What is inside"),
    "exportdlg.contents_windows": _pair(
        "main.py · project.json · assets/ · _engine/ · progress/ · AGENT_GUIDE.md · "
        "Play.bat · README_WINDOWS.txt · app.ico",
        "main.py · project.json · assets/ · _engine/ · progress/ · AGENT_GUIDE.md · "
        "Play.bat · README_WINDOWS.txt · app.ico",
    ),
    "exportdlg.exe_label": _pair("Имя файла .exe:", ".exe file name:"),
    "exportdlg.exe_placeholder": _pair("например, MyGame", "for example, MyGame"),
    "exportdlg.exe_hint": _pair(
        "Латиницей — это имя получит готовый файл программы.",
        "Latin letters only — this becomes the name of the finished program file.",
    ),
    "exportdlg.one_file": _pair(
        "Собрать один .exe (медленнее, но удобнее для отправки)",
        "Build a single .exe (slower, but easier to share)",
    ),
    "exportdlg.overall_progress": _pair("Общий прогресс", "Overall progress"),
    "exportdlg.stage": _pair("Этап", "Stage"),
    "exportdlg.ready": _pair("Готово", "Done"),
    "exportdlg.open_folder": _pair("Открыть папку", "Open folder"),
    "exportdlg.android_instructions": _pair("Инструкция Android", "Android instructions"),
    "exportdlg.close": _pair("Закрыть", "Close"),
    "exportdlg.export": _pair("Экспортировать", "Export"),
    "exportdlg.explain_exe": _pair("Windows .exe через PyInstaller", "Windows .exe via PyInstaller"),
    "exportdlg.explain_exe_text": _pair(
        "Соберёт автономный .exe с иконкой. Первая сборка занимает несколько минут. "
        "Если PyInstaller не установлен, установите его командой python -m pip install pyinstaller.",
        "Builds a standalone .exe with an icon. The first build takes a few minutes. "
        "If PyInstaller is missing, install it with: python -m pip install pyinstaller.",
    ),
    "exportdlg.output_hint_exe": _pair(
        "Папка на Рабочем столе. Внутри появится .exe и вспомогательные файлы.",
        "A folder on the Desktop. It will contain the .exe and helper files.",
    ),
    "exportdlg.output_hint_exe_missing": _pair(
        "PyInstaller не найден — установите его, чтобы включить этот режим.",
        "PyInstaller not found — install it to enable this mode.",
    ),
    "exportdlg.contents_exe": _pair(
        "Исполняемый файл проекта · иконка · ассеты · встроенный движок. "
        "Заставка и все ресурсы включены.",
        "The project executable · icon · assets · bundled engine. "
        "The splash screen and all resources are included.",
    ),
    "exportdlg.explain_android": _pair("Android-пакет", "Android package"),
    "exportdlg.explain_android_text": _pair(
        "Готовый проект python-for-android/buildozer с buildozer.spec, README_ANDROID.md, "
        "иконкой, presplash и GitHub Actions. APK собирается на Linux/WSL — это ограничение buildozer, "
        "а не движка.",
        "A ready python-for-android/buildozer project with buildozer.spec, README_ANDROID.md, "
        "an icon, presplash and GitHub Actions. The APK is built on Linux/WSL — that is a "
        "buildozer limitation, not an engine one.",
    ),
    "exportdlg.output_hint_android": _pair(
        "ZIP на Рабочем столе и папка проекта рядом с ним.",
        "A ZIP on the Desktop and the project folder next to it.",
    ),
    "exportdlg.contents_android": _pair(
        "main.py · buildozer.spec · assets/ · _engine/ · progress/ · README_ANDROID.md · "
        ".github/workflows/android.yml",
        "main.py · buildozer.spec · assets/ · _engine/ · progress/ · README_ANDROID.md · "
        ".github/workflows/android.yml",
    ),
    "exportdlg.save_android": _pair("Сохранить Android-пакет", "Save the Android package"),
    "exportdlg.pick_folder": _pair("Выберите папку для экспорта", "Choose a folder for the export"),
    "exportdlg.apk_build_title": _pair("Сборка Android APK", "Building the Android APK"),
    "exportdlg.apk_build_text": _pair(
        "Android-пакет готов к сборке через buildozer.",
        "The Android package is ready to build with buildozer.",
    ),
    "exportdlg.exe_name_invalid": _pair(
        "Имя: латиница, цифры, пробел и дефис. Начинается с буквы.",
        "Name: Latin letters, digits, spaces and hyphens. Must start with a letter.",
    ),
    "exportdlg.exe_ready_file": _pair("Готовый файл: {name}.exe", "Output file: {name}.exe"),
    "exportdlg.no_path_title": _pair("Путь не задан", "No path set"),
    "exportdlg.no_path_text": _pair(
        "Укажите папку или файл для экспорта.",
        "Specify a folder or file for the export.",
    ),
    "exportdlg.no_pyinstaller_title": _pair("PyInstaller не установлен", "PyInstaller is not installed"),
    "exportdlg.no_pyinstaller_text": _pair(
        "Установите PyInstaller командой:\n\npython -m pip install pyinstaller\n\n"
        "Или выберите экспорт в папку Windows.",
        "Install PyInstaller with:\n\npython -m pip install pyinstaller\n\n"
        "Or choose the Windows folder export instead.",
    ),
    "exportdlg.exe_name_title": _pair("Имя .exe", ".exe name"),
    "exportdlg.exe_name_text": _pair(
        "Имя файла латиницей, начинается с буквы; допустимы цифры, пробел и дефис.",
        "Latin file name starting with a letter; digits, spaces and hyphens are allowed.",
    ),
    "exportdlg.running_button": _pair("Экспортирую…", "Exporting…"),
    "exportdlg.preparing": _pair("Подготовка…", "Preparing…"),
    "exportdlg.again_button": _pair("Экспортировать ещё", "Export again"),
    "exportdlg.finished_message": _pair("Экспорт завершён.", "Export finished."),
    "exportdlg.done_prefix": _pair("Готово: ", "Done: "),
    "exportdlg.build_time": _pair("Время сборки: {minutes} мин {seconds} с.", "Build time: {minutes} min {seconds} s."),
    "exportdlg.splash_note": _pair(
        "Заставка Reasonable Engine включена в сборку.",
        "The Reasonable Engine splash screen is included in the build.",
    ),
    "exportdlg.next_step_android": _pair(
        "Следующий шаг: buildozer android debug на Linux/WSL или GitHub Actions.",
        "Next step: buildozer android debug on Linux/WSL or GitHub Actions.",
    ),
    "exportdlg.retry_button": _pair("Повторить экспорт", "Retry export"),
    "exportdlg.error_prefix": _pair("Ошибка: ", "Error: "),
    "exportdlg.failed_title": _pair("Экспорт не удался", "Export failed"),
    "exportdlg.close_running_title": _pair("Экспорт", "Export"),
    "exportdlg.close_running_text": _pair(
        "Экспорт ещё выполняется. Закрыть окно?",
        "The export is still running. Close the window?",
    ),
    # -- version history dialog (editor/history_dialog.py) ----------------
    "historydlg.title": _pair("История версий — Reasonable Engine", "Version history — Reasonable Engine"),
    "historydlg.heading": _pair("История версий", "Version history"),
    "historydlg.subtitle": _pair(
        "Перед каждым запуском ИИ-агента сохраняется полная рабочая версия. "
        "Любую из них можно вернуть — текущее состояние тоже сохранится.",
        "A full working version is saved before every AI agent run. "
        "Any of them can be restored — the current state will be saved too.",
    ),
    "historydlg.create_button": _pair("＋  Создать снимок", "＋  Create snapshot"),
    "historydlg.versions_label": _pair("Версии", "Versions"),
    "historydlg.empty_hint": _pair(
        "Снимков пока нет. Они появятся автоматически перед первым запуском агента "
        "или по кнопке «Создать снимок».",
        "No snapshots yet. They appear automatically before the first agent run "
        "or when you press “Create snapshot”.",
    ),
    "historydlg.changed_suffix": _pair(" · {count} файл(ов)", " · {count} file(s)")
    ,
    "historydlg.files_count_tooltip": _pair("Файлов: {count}", "Files: {count}"),
    "historydlg.saved_versions": _pair("Сохранено версий: {count}", "Saved versions: {count}"),
    "historydlg.select_hint": _pair(
        "Выберите версию слева, чтобы увидеть файлы и вернуть её.",
        "Select a version on the left to see its files and restore it.",
    ),
    "historydlg.size_line": _pair(
        "{time} · файлов: {count} · {kb} КБ",
        "{time} · files: {count} · {kb} KB",
    ),
    "historydlg.outcome_done": _pair("Агент завершил работу", "Agent finished the work"),
    "historydlg.outcome_incomplete": _pair("Агент не завершил работу", "Agent did not finish the work"),
    "historydlg.outcome_cancelled": _pair("Работа остановлена", "Work cancelled"),
    "historydlg.outcome_error": _pair("Ошибка агента", "Agent error"),
    "historydlg.outcome_stopped": _pair("Агент остановился", "Agent stopped"),
    "historydlg.outcome_line": _pair("Результат запуска: {outcome}", "Run outcome: {outcome}"),
    "historydlg.changed_after_title": _pair(
        "Файлы, изменённые после снимка", "Files changed after the snapshot"
    ),
    "historydlg.action_create": _pair("создан", "created"),
    "historydlg.action_edit": _pair("изменён", "changed"),
    "historydlg.action_delete": _pair("удалён", "deleted"),
    "historydlg.action_generate": _pair("сгенерирован", "generated"),
    "historydlg.snapshot_contents": _pair("Содержимое снимка", "Snapshot contents"),
    "historydlg.restore_button": _pair("↶  Вернуть эту версию", "↶  Restore this version"),
    "historydlg.open_folder_button": _pair("Открыть папку снимка", "Open snapshot folder"),
    "historydlg.delete_button": _pair("Удалить снимок", "Delete snapshot"),
    "historydlg.manual_snapshot_label": _pair(
        "Ручной снимок рабочей версии", "Manual snapshot of the working version"
    ),
    "historydlg.create_failed_title": _pair("Не удалось создать снимок", "Could not create a snapshot"),
    "historydlg.created_status": _pair(
        "Снимок создан. Теперь его можно вернуть в любой момент.",
        "Snapshot created. You can restore it at any time now.",
    ),
    "historydlg.restore_title": _pair("Вернуть версию", "Restore version"),
    "historydlg.restore_text": _pair(
        "Вернуть версию «{label}»?\n\n"
        "Файлы проекта будут заменены содержимым снимка. Текущее состояние "
        "сначала сохранится отдельным снимком, поэтому действие можно отменить.",
        "Restore the version “{label}”?\n\n"
        "Project files will be replaced with the snapshot contents. The current state "
        "is saved as a separate snapshot first, so the action can be undone.",
    ),
    "historydlg.restore_failed_title": _pair(
        "Не удалось вернуть версию", "Could not restore the version"
    ),
    "historydlg.restored_status": _pair(
        "Версия возвращена: файлов восстановлено {restored}, "
        "удалено {removed}. Текущее состояние сохранено отдельно.",
        "Version restored: {restored} file(s) recovered, "
        "{removed} deleted. The current state was saved separately.",
    ),
    "historydlg.delete_text": _pair(
        "Удалить снимок «{label}»? Это освободит место, но вернуть "
        "эту версию будет уже нельзя.",
        "Delete the snapshot “{label}”? This frees up space, but this version "
        "can no longer be restored.",
    ),
    "historydlg.deleted_status": _pair("Снимок удалён.", "Snapshot deleted."),
    # -- convert dialog (editor/convert_dialog.py) -------------------------
    "convdlg.title": _pair("Конвертировать проект — Reasonable Engine", "Convert project — Reasonable Engine"),
    "convdlg.heading": _pair("Конвертировать проект", "Convert project"),
    "convdlg.subtitle": _pair(
        "Создаётся отдельная папка. Исходный проект остаётся без изменений.",
        "A separate folder is created. The source project stays unchanged.",
    ),
    "convdlg.result_ready": _pair("Новый проект готов", "New project is ready"),
    "convdlg.open_folder": _pair("Открыть папку", "Open folder"),
    "convdlg.open_new": _pair("Открыть новый проект", "Open the new project"),
    "convdlg.create_button": _pair("Создать новый проект", "Create a new project"),
    "convdlg.platform_new": _pair("Новая платформа", "New platform"),
    "convdlg.platform_current": _pair("Сейчас: {name}", "Now: {name}"),
    "convdlg.platform_windows_hint": _pair("Папка, Play.bat и опционально .exe", "Folder, Play.bat and optionally .exe"),
    "convdlg.platform_android_hint": _pair(
        "buildozer-пакет, касания и портрет/альбом", "buildozer package, touches and portrait/landscape"
    ),
    "convdlg.name_folder_title": _pair("Название и папка", "Name and folder"),
    "convdlg.name_placeholder": _pair("Название нового проекта", "New project name"),
    "convdlg.field_name": _pair("Название", "Name"),
    "convdlg.field_folder": _pair("Папка", "Folder"),
    "convdlg.browse_button": _pair("Выбрать…", "Browse…"),
    "convdlg.folder_hint": _pair(
        "В выбранной папке появится новая подпапка. Если имя занято, добавится суффикс -2.",
        "A new subfolder appears in the chosen folder. If the name is taken, a -2 suffix is added.",
    ),
    "convdlg.options_title": _pair("Что ещё можно изменить", "What else can be changed"),
    "convdlg.keep_as_project": _pair("Как в проекте", "As in the project"),
    "convdlg.orientation_landscape": _pair("Альбомная", "Landscape"),
    "convdlg.orientation_portrait": _pair("Портретная", "Portrait"),
    "convdlg.field_orientation": _pair("Ориентация", "Orientation"),
    "convdlg.agent_builtin": _pair("Встроенный ИИ", "Built-in AI"),
    "convdlg.agent_external": _pair("Внешний агент", "External agent"),
    "convdlg.field_agent_mode": _pair("Режим агента", "Agent mode"),
    "convdlg.field_ui_levels": _pair("Уровень интерфейса", "Interface level"),
    "convdlg.reset_check": _pair(
        "Сбросить план, прогресс и ленту событий в новом проекте",
        "Reset the plan, progress and event feed in the new project",
    ),
    "convdlg.options_note": _pair(
        "Окно, разрешение и ориентацию агент подберёт сам — здесь это не настраивается. "
        "Код и ассеты не переписываются: после создания попросите агента адаптировать "
        "компоновку под новую платформу. APK собирается через buildozer на Linux/WSL2.",
        "The agent picks window, resolution and orientation itself — not configurable here. "
        "Code and assets are not rewritten: after creation ask the agent to adapt "
        "the layout to the new platform. The APK is built via buildozer on Linux/WSL2.",
    ),
    "convdlg.preview_title": _pair("Предпросмотр", "Preview"),
    "convdlg.limits_title": _pair("Что важно знать", "What you should know"),
    "convdlg.limits_note": _pair(
        "Платформа — главная ось конвертации. Ориентация, агент и уровни интерфейса "
        "применяются к копии сразу. Код и ассеты не переписываются: после создания "
        "попросите агента адаптировать компоновку, управление и safe margins под Android. "
        "APK по-прежнему собирается через buildozer на Linux/WSL2.",
        "Platform is the main conversion axis. Orientation, agent and interface levels "
        "apply to the copy immediately. Code and assets are not rewritten: after creation "
        "ask the agent to adapt the layout, controls and safe margins for Android. "
        "The APK is still built via buildozer on Linux/WSL2.",
    ),
    "convdlg.hint_android": _pair(
        "Android: проект получит android-ориентацию и пакет. "
        "Проверьте касания и размеры элементов; APK собирается на Linux/WSL2.",
        "Android: the project gets android orientation and packaging. "
        "Check touches and element sizes; the APK is built on Linux/WSL2.",
    ),
    "convdlg.hint_windows": _pair(
        "Windows: проект будет ориентирован на окно Windows, папку и .exe. "
        "Ориентация портрет тоже поддерживается, если она нужна приложению.",
        "Windows: the project targets a Windows window, folder and .exe. "
        "Portrait orientation is also supported if the app needs it.",
    ),
    "convdlg.hint_same_platform": _pair(
        " Платформа не меняется — это будет новая версия проекта.",
        " The platform does not change — this will be a new version of the project.",
    ),
    "convdlg.browse_title": _pair("Куда сохранить новый проект", "Where to save the new project"),
    "convdlg.badge_error": _pair("Ошибка", "Error"),
    "convdlg.badge_ready": _pair("ГОТОВО", "READY"),
    "convdlg.badge_no_changes": _pair("БЕЗ ИЗМЕНЕНИЙ", "NO CHANGES"),
    "convdlg.no_changes_hint": _pair(
        "Измените платформу, имя, ориентацию, уровни интерфейса, агент или прогресс — "
        "точную копию можно создать только с хотя бы одним отличием.",
        "Change the platform, name, orientation, interface levels, agent or progress — "
        "an exact copy can only be created with at least one difference.",
    ),
    "convdlg.new_project_path": _pair("Новый проект: {path}", "New project: {path}"),
    "convdlg.copying_status": _pair("Копирую проект…", "Copying the project…"),
    "convdlg.running_button": _pair("Конвертирую…", "Converting…"),
    "convdlg.created_message": _pair("Новый проект создан.", "The new project was created."),
    "convdlg.another_copy_button": _pair("Создать ещё одну копию", "Create another copy"),
    "convdlg.source_unchanged": _pair("Исходный проект не изменён.", "The source project was not changed."),
    "convdlg.error_prefix": _pair("Ошибка: ", "Error: "),
    "convdlg.failed_title": _pair("Конвертация не удалась", "Conversion failed"),
    "convdlg.close_running_title": _pair("Конвертация", "Conversion"),
    "convdlg.close_running_text": _pair(
        "Конвертация ещё выполняется. Закрыть окно?",
        "The conversion is still running. Close the window?",
    ),

    # ---- editor/external.py — external agent panel (prefix extpanel.) ----
    "extpanel.agent_prompt": _pair(
        """Ты работаешь над проектом «{name}» в папке:
{root}

1. Прочитай AGENT_GUIDE.md, skills/ и progress/state.json — там полные правила и API движка.
2. Работай автономно: меняй файлы, генерируй ассеты, проверяй запуск (re.bat validate, re.bat run --headless).
3. Обновляй план и прогресс через re.bat (plan/task/progress/event) — пользователь видит его в Reasonable Engine.
4. Заверши через re.bat done "итог" только когда проект запускается и задача выполнена.

Не трогай папку _engine — это встроенная копия движка. Шаги не ограничены:
работай до результата, не повторяй одно и то же действие.""",
        """You are working on the project "{name}" in the folder:
{root}

1. Read AGENT_GUIDE.md, skills/ and progress/state.json — they contain the full rules and engine API.
2. Work autonomously: change files, generate assets, verify the run (re.bat validate, re.bat run --headless).
3. Update the plan and progress via re.bat (plan/task/progress/event) — the user sees it in Reasonable Engine.
4. Finish via re.bat done "summary" only when the project runs and the task is complete.

Do not touch the _engine folder — it is a built-in copy of the engine. Steps are unlimited:
work until there is a result, do not repeat the same action.""",
    ),
    "extpanel.title": ("section.agent",),  # reuse: "ИИ-агент" / "AI agent"
    "extpanel.subtitle": _pair(
        "Внешний режим · Claude Code / Codex / Cursor / Cline — прогресс виден здесь",
        "External mode · Claude Code / Codex / Cursor / Cline — progress shows here",
    ),
    "extpanel.badge_waiting": _pair("ОЖИДАНИЕ", "WAITING"),
    "extpanel.pack_button": _pair("Обновить пакет агента", "Refresh the agent pack"),
    "extpanel.open_folder_button": _pair("Открыть папку проекта", "Open the project folder"),
    "extpanel.howto_title": _pair("Как подключить агента", "How to connect an agent"),
    "extpanel.step1_title": _pair("Откройте папку проекта", "Open the project folder"),
    "extpanel.step1_text": _pair(
        "В Claude Code, Codex CLI, Cursor, Cline или другом агенте откройте папку проекта.",
        "Open the project folder in Claude Code, Codex CLI, Cursor, Cline or another agent.",
    ),
    "extpanel.step2_title": _pair("Вставьте промпт", "Paste the prompt"),
    "extpanel.step2_text": _pair(
        "Скопируйте промпт ниже и вставьте его агенту — при желании сначала допишите свою задачу.",
        "Copy the prompt below and paste it to the agent — optionally add your own task first.",
    ),
    "extpanel.step3_title": _pair("Смотрите прогресс здесь", "Watch the progress here"),
    "extpanel.step3_text": _pair(
        "Агент обновляет план и процент сам — эта панель следит за папкой проекта.",
        "The agent updates the plan and percentage itself — this panel watches the project folder.",
    ),
    "extpanel.prompt_card_title": _pair("Промпт для внешнего агента", "Prompt for the external agent"),
    "extpanel.copy_prompt_button": _pair("Скопировать промпт", "Copy the prompt"),
    "extpanel.prompt_note": _pair(
        "Напишите задачу своими словами. Ниже показан полный текст, который "
        "получит агент: путь к проекту, обязательный рабочий цикл и ваша задача. "
        "Кнопка копирует именно его.",
        "Write the task in your own words. Below is the full text the agent "
        "will receive: the project path, the required work loop and your task. "
        "The button copies exactly that.",
    ),
    "extpanel.task_label": _pair("Ваша задача", "Your task"),
    "extpanel.task_placeholder": _pair(
        "Например: собери меню, первый уровень и экран паузы, затем проверь запуск.",
        "For example: build a menu, the first level and a pause screen, then verify the run.",
    ),
    "extpanel.full_prompt_label": _pair("Полный промпт", "Full prompt"),
    "extpanel.copy_task_button": _pair("Скопировать только задачу", "Copy only the task"),
    "extpanel.pack_ready": _pair(
        "Пакет для агента готов ✓  (AGENT_GUIDE.md, skills/, AGENTS.md, re.bat)",
        "The agent pack is ready ✓  (AGENT_GUIDE.md, skills/, AGENTS.md, re.bat)",
    ),
    "extpanel.live_title": _pair("Живой прогресс", "Live progress"),
    "extpanel.mode_badge": _pair("ВНЕШНИЙ РЕЖИМ", "EXTERNAL MODE"),
    "extpanel.waiting_stage": _pair("Ожидание внешнего агента", "Waiting for the external agent"),
    "extpanel.events_title": _pair("Лента событий", "Event feed"),
    "extpanel.files_title": _pair("Недавние файлы", "Recent files"),
    "extpanel.open_guide_button": _pair("Открыть AGENT_GUIDE.md", "Open AGENT_GUIDE.md"),
    "extpanel.first_task": _pair("ПЕРВАЯ ЗАДАЧА", "FIRST TASK"),
    "extpanel.first_task_default": _pair(
        "Изучи проект, предложи план и начни с самого важного шага.",
        "Study the project, propose a plan and start with the most important step.",
    ),
    "extpanel.hint_task_added": _pair("Задача добавлена в промпт · {count} символов", "Task added to the prompt · {count} characters"),
    "extpanel.hint_no_task": _pair(
        "Пока задача не написана — в промпте будет просьба изучить проект и предложить план.",
        "No task written yet — the prompt will ask the agent to study the project and propose a plan.",
    ),
    "extpanel.no_task_title": _pair("Задача не описана", "No task described"),
    "extpanel.no_task_copy_text": _pair(
        "Скопировать промпт без конкретной задачи? Агент просто изучит проект "
        "и предложит план.\n\nЛучше сначала написать задачу.",
        "Copy the prompt without a specific task? The agent will simply study the "
        "project and propose a plan.\n\nIt is better to write the task first.",
    ),
    "extpanel.no_task_only_text": _pair(
        "Напишите задачу в поле выше, чтобы скопировать только её.",
        "Write the task in the field above to copy only it.",
    ),
    "extpanel.copied_status": _pair("Скопировано в буфер обмена.", "Copied to the clipboard."),
    "extpanel.badge_copied": _pair("СКОПИРОВАНО", "COPIED"),
    "extpanel.file_not_created": _pair("Файл ещё не создан: {name}", "The file does not exist yet: {name}"),
    "extpanel.pack_failed_status": _pair("Не удалось обновить пакет: {error}", "Failed to refresh the pack: {error}"),
    "extpanel.pack_failed_text": _pair(
        "Не удалось обновить пакет — попробуйте ещё раз.",
        "Failed to refresh the pack — please try again.",
    ),
    "extpanel.pack_updated_status": _pair("Пакет агента обновлён.", "The agent pack was refreshed."),
    "extpanel.badge_pack_updated": _pair("ПАКЕТ ОБНОВЛЁН", "PACK REFRESHED"),
    "extpanel.badge_running": _pair("АГЕНТ РАБОТАЕТ", "AGENT RUNNING"),
    "extpanel.badge_done": _pair("ЗАВЕРШЕНО", "DONE"),
    "extpanel.badge_error": _pair("ОШИБКА", "ERROR"),
    "extpanel.activity_prefix": _pair("активность: ", "activity: "),
    "extpanel.stage_idle": ("progress.idle_stage",),
    "extpanel.last_activity": _pair("Последняя активность: {time}", "Last activity: {time}"),
    "extpanel.no_plan": _pair("Агент ещё не создал план.", "The agent has not created a plan yet."),
    "extpanel.no_files": _pair("Пока нет изменённых файлов.", "No changed files yet."),

    # -- scene editor (editor/scene_editor.py) --------------------------
    "scene.title": _pair("Редактор сцены", "Scene editor"),
    "scene.scenes": _pair("СЦЕНЫ", "SCENES"),
    "scene.new_scene": _pair("Новая сцена", "New scene"),
    "scene.manage": _pair("Управление сценой", "Manage scene"),
    "scene.new_level": _pair("Уровень", "Level"),
    "scene.new_menu": _pair("Меню", "Menu"),
    "scene.new_empty": _pair("Пустая сцена", "Empty scene"),
    "scene.new_prompt": _pair("Название сцены:", "Scene name:"),
    "scene.new_default_name": _pair("Сцена {index}", "Scene {index}"),
    "scene.rename": _pair("Переименовать сцену…", "Rename scene…"),
    "scene.duplicate": _pair("Дублировать сцену", "Duplicate scene"),
    "scene.delete": _pair("Удалить сцену", "Delete scene"),
    "scene.delete_last": _pair(
        "Нельзя удалить последнюю сцену — в проекте должна остаться хотя бы одна.",
        "The last scene cannot be deleted — a project must keep at least one.",
    ),
    "scene.delete_text": _pair(
        "Удалить сцену «{title}»? Это действие нельзя отменить.",
        "Delete the scene “{title}”? This cannot be undone.",
    ),
    "scene.settings": _pair("Настройки сцены…", "Scene settings…"),
    "scene.settings_title": _pair("Настройки сцены", "Scene settings"),
    "scene.settings_saved": _pair("Настройки сцены сохранены: {title}", "Scene settings saved: {title}"),
    "scene.opened": _pair("Открыта сцена: {title}", "Scene opened: {title}"),
    "scene.created": _pair("Создана сцена: {title}", "Scene created: {title}"),
    "scene.renamed": _pair("Сцена переименована: {title}", "Scene renamed: {title}"),
    "scene.deleted": _pair("Сцена удалена. Открыта: {title}", "Scene deleted. Opened: {title}"),
    "scene.run": _pair("Запустить", "Run"),
    "scene.run_tip": _pair("Запустить проект и проверить сцену в игре", "Run the project and test the scene in the game"),
    "scene.field_grid": _pair("Шаг сетки", "Grid step"),
    "scene.empty_title": _pair("Пустая сцена", "Empty scene"),
    "scene.empty_text": _pair(
        "Добавьте первый объект или начните с маркера игрока. "
        "Дальше объекты можно двигать мышью и настраивать справа.",
        "Add your first object or start with a player marker. "
        "Objects can then be dragged and tuned on the right.",
    ),
    "scene.add_platform": _pair("Прямоугольник", "Rectangle"),
    "scene.add_circle": _pair("Круг", "Circle"),
    "scene.add_text": _pair("Текст", "Text"),
    "scene.add_player": _pair("Старт игрока", "Player start"),
    "scene.add_player_tip": _pair(
        "Скрытый маркер: в примере игры задаёт точку появления игрока.",
        "A hidden marker: in the sample game it sets the player spawn point.",
    ),
    "scene.marker_tip": _pair(
        "Маркер появления: невидим в игре, но задаёт позицию персонажа или предмета.",
        "Spawn marker: invisible in the game but defines where an entity appears.",
    ),
    "scene.markers": _pair("Маркеры появления", "Spawn markers"),
    "scene.add_star": _pair("Звезда", "Star"),
    "scene.add_slime": _pair("Слизень", "Slime"),
    "scene.objects": _pair("ОБЪЕКТЫ", "OBJECTS"),
    "scene.inspector": _pair("ИНСПЕКТОР", "INSPECTOR"),
    "scene.tool_select": _pair("Выбор и перемещение (V)", "Select and move (V)"),
    "scene.tool_rect": _pair("Прямоугольник (R)", "Rectangle (R)"),
    "scene.tool_circle": _pair("Круг (O)", "Circle (O)"),
    "scene.tool_text": _pair("Текст (T)", "Text (T)"),
    "scene.tool_panel": _pair("Панель (P)", "Panel (P)"),
    "scene.tool_image": _pair("Изображение из ассетов", "Image from assets"),
    "scene.tool_delete": _pair("Удалить объект (Del)", "Delete object (Del)"),
    "scene.tool_duplicate": _pair("Дублировать (Ctrl+D)", "Duplicate (Ctrl+D)"),
    "scene.snap": _pair("Привязка к сетке", "Snap to grid"),
    "scene.grid": _pair("Сетка", "Grid"),
    "scene.zoom": _pair("Масштаб", "Zoom"),
    "scene.zoom_in": _pair("Приблизить", "Zoom in"),
    "scene.zoom_out": _pair("Отдалить", "Zoom out"),
    "scene.reset_view": _pair("Сбросить вид (0)", "Reset view (0)"),
    "scene.bring_front": _pair("На передний план", "Bring to front"),
    "scene.send_back": _pair("На задний план", "Send to back"),
    "scene.save": _pair("Сохранить сцену (Ctrl+S)", "Save scene (Ctrl+S)"),
    "scene.saved": _pair("Сцена сохранена: {path}", "Scene saved: {path}"),
    "scene.load_failed": _pair("Не удалось открыть сцену: {error}", "Could not open the scene: {error}"),
    "scene.save_failed": _pair("Не удалось сохранить сцену: {error}", "Could not save the scene: {error}"),
    "scene.empty_hint": _pair(
        "Добавьте объекты кнопками на панели или перетащите изображение из «Ассетов».",
        "Add objects with the toolbar or drag an image from Assets.",
    ),
    "scene.field_name": _pair("Имя", "Name"),
    "scene.field_position": _pair("Позиция", "Position"),
    "scene.field_size": _pair("Размер", "Size"),
    "scene.field_rotation": _pair("Поворот", "Rotation"),
    "scene.field_color": _pair("Цвет", "Colour"),
    "scene.field_text": _pair("Текст", "Text"),
    "scene.field_asset": _pair("Изображение", "Image"),
    "scene.field_z": _pair("Слой", "Layer"),
    "scene.field_radius": _pair("Скругление", "Corner radius"),
    "scene.field_visible": _pair("Видимый", "Visible"),
    "scene.pick_asset": _pair("Выбрать…", "Choose…"),
    "scene.no_selection": _pair("Объект не выбран", "No object selected"),
    "scene.object_default": _pair("Объект {index}", "Object {index}"),
    "scene.image_missing": _pair("Файл изображения не найден", "Image file not found"),
    "scene.added": _pair("Объект добавлен на сцену.", "Object added to the scene."),
    "scene.bg_color": _pair("Фон сцены", "Scene background"),
    "scene.footer_hint": _pair(
        "ЛКМ — выбрать/создать и перетащить · R/O/T/P — инструменты · "
        "колесо — масштаб · средняя кнопка — панорама · Del — удалить",
        "Click to select/create and drag · R/O/T/P — tools · "
        "wheel to zoom · middle drag to pan · Del to delete",
    ),
    "scene.save_hint": _pair("Изменения сохраняются автоматически", "Changes are saved automatically"),
    "scene.dirty": _pair("Есть несохранённые изменения", "Unsaved changes"),

    # -- assets page / generation dialog -------------------------------
    "assets.gen_title_bg": _pair("Генерация фона", "Background generation"),
    "assets.gen_title_sprite": _pair("Генерация спрайта", "Sprite generation"),
    "assets.new_bg": _pair("Новый фон", "New background"),
    "assets.new_sprite": _pair("Новый спрайт", "New sprite"),
    "assets.badge_ai_gen": _pair("ИИ-ГЕНЕРАЦИЯ", "AI GENERATION"),
    "assets.intro": _pair(
        "Опишите предмет или сцену. Для спрайтов лучше короткие промпты и прозрачный фон.",
        "Describe the object or scene. Short prompts and a transparent background work best for sprites.",
    ),
    "assets.filename_label": _pair("Имя файла", "File name"),
    "assets.prompt_example_sprite": _pair(
        "Например: золотая звезда с мягким свечением, флэт-стиль, прозрачный фон",
        "For example: a golden star with a soft glow, flat style, transparent background",
    ),
    "assets.prompt_example_bg": _pair(
        "Например: ночной лес с светлячками, мягкий туман, тёмно-синяя палитра",
        "For example: a night forest with fireflies, soft fog, dark blue palette",
    ),
    "assets.style_label": _pair("Стиль", "Style"),
    "assets.style_flat": _pair("Флэт", "Flat"),
    "assets.style_pixel": _pair("Пиксель-арт", "Pixel art"),
    "assets.style_painterly": _pair("Живописный", "Painterly"),
    "assets.style_icon": _pair("Иконка", "Icon"),
    "assets.size_label": _pair("Размер", "Size"),
    "assets.provider_label": _pair("Провайдер", "Provider"),
    "assets.random_button": _pair("Случайный", "Random"),
    "assets.preview_placeholder": _pair("Здесь появится результат", "The result will appear here"),
    "assets.generate_button": _pair("Сгенерировать", "Generate"),
    "assets.generate_again_button": _pair("Сгенерировать ещё", "Generate another"),
    "assets.note_openai": _pair(
        "OpenAI-совместимый сервер изображений. Нужны Base URL и ключ в настройках. "
        "Без модели попросите агента нарисовать ассет через draw_sprite.",
        "OpenAI-compatible image server. Requires a Base URL and key in settings. "
        "Without a model, ask the agent to draw the asset with draw_sprite.",
    ),
    "assets.need_prompt_title": _pair("Нужен промпт", "Prompt required"),
    "assets.need_prompt_text": _pair(
        "Опишите, что должно быть на изображении.",
        "Describe what the image should show.",
    ),
    "assets.status_generating": _pair("Генерирую изображение…", "Generating the image…"),
    "assets.status_done": _pair("Готово: {name} · {provider} {fallback}", "Done: {name} · {provider} {fallback}"),
    "assets.status_done_fallback": _pair("· локальный fallback", "· local fallback"),
    "assets.error_prefix": _pair("Ошибка: ", "Error: "),
    "assets.failed_title": _pair("Не удалось сгенерировать", "Generation failed"),
    "assets.close_running_title": _pair("Генерация", "Generation"),
    "assets.close_running_text": _pair(
        "Изображение ещё генерируется. Закрыть окно?",
        "The image is still being generated. Close the window?",
    ),
    "assets.page_title": ("section.assets",),
    "assets.page_subtitle": _pair(
        "Спрайты, фоны и звуки проекта. Генерация встроена.",
        "Sprites, backgrounds and sounds of the project. Generation is built in.",
    ),
    "assets.import_button": _pair("Импортировать", "Import"),
    "assets.open_folder_button": _pair("Открыть папку", "Open folder"),
    "assets.background_button": _pair("Фон", "Background"),
    "assets.gen_sprite_button": _pair("Сгенерировать спрайт", "Generate sprite"),
    "assets.library_title": _pair("Библиотека", "Library"),
    "assets.search_placeholder": _pair("Поиск по имени…", "Search by name…"),
    "assets.preview_title": _pair("Предпросмотр", "Preview"),
    "assets.choose_asset": _pair("Выберите ассет", "Select an asset"),
    "assets.delete_button": _pair("Удалить", "Delete"),
    "assets.edit_button": _pair("Открыть в редакторе", "Open in editor"),
    "assets.empty_list": _pair(
        "Ассетов пока нет.\nСгенерируйте спрайт или импортируйте файл.",
        "No assets yet.\nGenerate a sprite or import a file.",
    ),
    "assets.badge_empty": _pair("ПУСТО", "EMPTY"),
    "assets.badge_image": _pair("ИЗОБРАЖЕНИЕ", "IMAGE"),
    "assets.badge_sound": _pair("ЗВУК", "SOUND"),
    "assets.badge_file": _pair("ФАЙЛ", "FILE"),
    "assets.meta_kb": _pair("{size} КБ", "{size} KB"),
    "assets.meta_image": _pair(
        "{width} × {height} px  ·  {size} КБ\n{suffix}",
        "{width} × {height} px  ·  {size} KB\n{suffix}",
    ),
    "assets.image_open_failed": _pair("Не удалось открыть изображение", "Could not open the image"),
    "assets.audio_file": _pair("Аудиофайл  ·  {size} КБ", "Audio file  ·  {size} KB"),
    "assets.no_preview": _pair("\nПредпросмотр недоступен", "\nPreview unavailable"),
    "assets.created_status": _pair("Ассет создан: {rel}", "Asset created: {rel}"),
    "assets.import_dialog_title": _pair("Импортировать файлы", "Import files"),
    "assets.import_filter": _pair(
        "Изображения и звуки (*.png *.jpg *.jpeg *.webp *.gif *.wav *.ogg *.mp3);;Все файлы (*.*)",
        "Images and sounds (*.png *.jpg *.jpeg *.webp *.gif *.wav *.ogg *.mp3);;All files (*.*)",
    ),
    "assets.import_error_title": _pair("Импорт", "Import"),
    "assets.import_error_text": _pair(
        "Не удалось скопировать {name}: {error}",
        "Could not copy {name}: {error}",
    ),
    "assets.imported_status": _pair("Импортировано файлов: {count}", "Files imported: {count}"),
    "assets.delete_title": _pair("Удалить ассет", "Delete asset"),
    "assets.delete_text": _pair(
        "Удалить {rel}? Это действие нельзя отменить.",
        "Delete {rel}? This action cannot be undone.",
    ),
    "assets.delete_error_title": _pair("Ошибка удаления", "Deletion error"),
    "assets.deleted_status": _pair("Удалено: {rel}", "Deleted: {rel}"),

    # -- code page (editor) ---------------------------------------------
    "code.page_title": _pair("Код проекта", "Project code"),
    "code.page_subtitle": _pair(
        "Полноценный редактор: правьте файлы вручную или вместе с агентом.",
        "A full editor: fix files by hand or together with the agent.",
    ),
    "code.validate_button": _pair("Проверить", "Validate"),
    "code.run_button": ("projectpage.run_btn",),
    "code.files_title": _pair("Файлы", "Files"),
    "code.refresh_button": _pair("Обновить", "Refresh"),
    "code.refresh_tip": _pair("Обновить дерево файлов", "Refresh the file tree"),
    "code.search_placeholder": _pair("Поиск файла…", "Search for a file…"),
    "code.new_file_button": _pair("+ Файл", "+ File"),
    "code.new_folder_button": _pair("+ Папка", "+ Folder"),
    "code.no_file_selected": _pair("Файл не выбран", "No file selected"),
    "code.badge_modified": _pair("ИЗМЕНЁН", "MODIFIED"),
    "code.save_button": _pair("Сохранить", "Save"),
    "code.empty_title": _pair("Выберите файл", "Pick a file"),
    "code.empty_text": _pair(
        "Слева — дерево проекта. Кликните по файлу, чтобы открыть его. Ctrl+S сохраняет.",
        "On the left is the project tree. Click a file to open it. Ctrl+S saves.",
    ),
    "code.status_ready": _pair("Готово", "Ready"),
    "code.tree_root": _pair("Проект", "Project"),
    "code.file_not_found": _pair("Файл не найден: {path}", "File not found: {path}"),
    "code.binary_file": _pair("Бинарный файл — предпросмотр недоступен.", "Binary file — preview unavailable."),
    "code.read_error_title": _pair("Ошибка чтения", "Read error"),
    "code.image_open_failed": _pair("Не удалось открыть изображение.", "Could not open the image."),
    "code.image_caption": _pair("{path}  ·  {width} × {height} px  ·  {kb} КБ", "{path}  ·  {width} × {height} px  ·  {kb} KB"),
    "code.cursor_status": _pair(
        "Строка {line}, столбец {column}   ·   {count} символов   ·   UTF-8",
        "Line {line}, column {column}   ·   {count} characters   ·   UTF-8",
    ),
    "code.image_preview_status": _pair("Предпросмотр изображения", "Image preview"),
    "code.unsaved_title": _pair("Несохранённые изменения", "Unsaved changes"),
    "code.unsaved_text": _pair("Сохранить изменения в {path}?", "Save the changes in {path}?"),
    "code.saved_status": _pair("Сохранено: {path}", "Saved: {path}"),
    "code.save_error_title": _pair("Ошибка сохранения", "Save error"),
    "code.agent_updated_file": _pair("Файл обновлён агентом: {path}", "File updated by the agent: {path}"),
    "code.new_file_title": _pair("Новый файл", "New file"),
    "code.new_file_label": _pair("Путь внутри проекта:", "Path inside the project:"),
    "code.file_exists_title": _pair("Файл существует", "File exists"),
    "code.file_exists_text": _pair("Такой файл уже есть.", "This file already exists."),
    "code.create_file_error": _pair("Не удалось создать файл", "Could not create the file"),
    "code.new_folder_title": _pair("Новая папка", "New folder"),
    "code.create_folder_error": _pair("Не удалось создать папку", "Could not create the folder"),
    "code.menu_open": _pair("Открыть", "Open"),
    "code.menu_rename": _pair("Переименовать…", "Rename…"),
    "code.menu_delete": ("assets.delete_button",),
    "code.rename_title": _pair("Переименовать", "Rename"),
    "code.rename_label": _pair("Новый путь:", "New path:"),
    "code.rename_exists_title": _pair("Уже существует", "Already exists"),
    "code.rename_exists_text": _pair("Файл или папка с таким именем уже есть.", "A file or folder with this name already exists."),
    "code.rename_error_title": _pair("Ошибка переименования", "Rename error"),
    "code.delete_text": _pair("Удалить {path}? Действие нельзя отменить.", "Delete {path}? This action cannot be undone."),
    "code.delete_error_title": ("assets.delete_error_title",),
    "code.validate_ok_title": _pair("Проверка", "Validation"),
    "code.validate_ok_text": _pair(
        "Всё в порядке: структура и синтаксис корректны.",
        "All good: the structure and syntax are correct.",
    ),
    "code.validate_passed": _pair("Проверка пройдена.", "Validation passed."),
    "code.validate_errors_title": _pair("Найдены ошибки", "Errors found"),
    "code.validate_summary": _pair(
        "Проверка: ошибок {errors}, предупреждений {warnings}.",
        "Validation: {errors} errors, {warnings} warnings.",
    ),

    # -- first-run quick start (editor/tutorial.py) ----------------------
    "menu.tutorial": _pair("Быстрый старт (обучение)", "Quick start (tutorial)"),
    "settings.tutorial_button": _pair("Обучение", "Tutorial"),
    "settings.tutorial_hint": _pair(
        "Повторить короткое обучение по редактору",
        "Replay the short editor tutorial",
    ),
    "welcome.tutorial": _pair("Обучение", "Tutorial"),
    "welcome.tutorial_tip": _pair(
        "Повторить короткое обучение по редактору",
        "Replay the short editor tutorial",
    ),
    "tutorial.title": _pair("Быстрый старт", "Quick start"),
    "tutorial.subtitle": _pair(
        "Шесть интерактивных шагов — выполняйте действия по порядку",
        "Six hands-on steps — complete each action to move on",
    ),
    "tutorial.badge": _pair("ОБУЧЕНИЕ", "TUTORIAL"),
    "tutorial.outline": _pair("ШАГИ", "STEPS"),
    "tutorial.outline_hint": _pair(
        "Следующий шаг открывается после выполнения действия. Обучение можно закрыть в любой момент.",
        "The next step unlocks after you complete the action. You can close the tutorial at any time.",
    ),
    "tutorial.tip": _pair("СОВЕТ", "TIP"),
    "tutorial.step_of": _pair("ШАГ {step} ИЗ {total}", "STEP {step} OF {total}"),
    "tutorial.progress": _pair("Шаг {step} из {total}", "Step {step} of {total}"),
    "tutorial.keyboard_hint": _pair(
        "← → — шаги · Esc",
        "← → steps · Esc",
    ),
    "tutorial.back": _pair("Назад", "Back"),
    "tutorial.next": _pair("Далее", "Next"),
    "tutorial.skip": _pair("Пропустить", "Skip"),
    "tutorial.skip_tip": _pair(
        "Закрыть обучение — открыть его снова можно через «Помощь → Быстрый старт» или кнопку «Обучение».",
        "Close the tutorial — reopen it from Help → Quick start or the Tutorial button.",
    ),
    "tutorial.done": _pair("Готово", "Done"),
    "tutorial.action_heading": _pair("ВАШЕ ДЕЙСТВИЕ", "YOUR TURN"),
    "tutorial.locked_hint": _pair(
        "Выполните действие выше, чтобы продолжить",
        "Complete the action above to continue",
    ),

    # step 1 — choose a project type
    "tutorial.step1_choose_ai": _pair("Создать с ИИ", "Create with AI"),
    "tutorial.step1_choose_blank": _pair("Пустой проект", "Blank project"),
    "tutorial.step1_selected_ai": _pair(
        "Выбрано: проект с ИИ. Мастер спросит идею и тип — остальное соберёт движок.",
        "Selected: an AI project. The wizard asks for the idea and type — the engine builds the rest.",
    ),
    "tutorial.step1_selected_blank": _pair(
        "Выбрано: пустой проект. Подходит, если хотите начать с чистого листа.",
        "Selected: a blank project. A good choice when you want a clean start.",
    ),

    # step 2 — task and plan
    "tutorial.step2_placeholder": _pair(
        "Например: добавь меню и три уровня",
        "For example: add a menu and three levels",
    ),
    "tutorial.step2_submit": _pair("Поставить задачу", "Give the task"),
    "tutorial.step2_empty": _pair(
        "Напишите хотя бы пару слов — так агенту будет понятнее.",
        "Write at least a few words — it helps the agent understand.",
    ),
    "tutorial.step2_chip1": _pair("Добавь меню и три уровня", "Add a menu and three levels"),
    "tutorial.step2_chip2": _pair("Сделай экран статистики", "Build a statistics screen"),
    "tutorial.step2_chip3": _pair("Улучши графику и звук", "Improve the graphics and sound"),
    "tutorial.step2_plan_ready": _pair(
        "План готов — агент начнёт с первой задачи и будет отмечать прогресс.",
        "The plan is ready — the agent starts with the first task and tracks progress.",
    ),
    "tutorial.step2_plan1": _pair("Изучить проект и структуру", "Study the project and its structure"),
    "tutorial.step2_plan2": _pair("Собрать меню", "Build the menu"),
    "tutorial.step2_plan3": _pair("Добавить три уровня", "Add three levels"),
    "tutorial.step2_plan4": _pair("Проверить запуск", "Check the launch"),

    # step 3 — visit the workspaces in order
    "tutorial.section_hint": _pair(
        "Нажимайте разделы по порядку, как в настоящем проекте.",
        "Click the workspaces in order, just like in a real project.",
    ),
    "tutorial.section_overview": _pair(
        "Обзор: готовность, план, события и история версий.",
        "Overview: readiness, plan, events and version history.",
    ),
    "tutorial.section_agent": _pair(
        "ИИ-агент: задача словами, живой план и вызовы инструментов.",
        "AI agent: a task in words, a live plan and tool calls.",
    ),
    "tutorial.section_code": _pair(
        "Код: дерево файлов и полноценный редактор с сохранением.",
        "Code: the file tree and a full editor with saving.",
    ),
    "tutorial.section_assets": _pair(
        "Ассеты: спрайты, фоны, звуки и генерация изображений.",
        "Assets: sprites, backgrounds, sounds and image generation.",
    ),
    "tutorial.section_scene": _pair(
        "Сцена: визуальный холст с сеткой, объектами и инспектором.",
        "Scene: a visual canvas with a grid, objects and an inspector.",
    ),
    "tutorial.step3_done": _pair(
        "Все пять разделов освоены — теперь вы знаете, где что лежит.",
        "All five workspaces visited — you know where everything lives.",
    ),

    # step 4 — run
    "tutorial.step4_console": _pair(
        "$ python main.py\nЗапуск проекта…",
        "$ python main.py\nStarting the project…",
    ),
    "tutorial.step4_run": _pair("Запустить проект", "Run the project"),
    "tutorial.step4_ok": _pair(
        "Проект запущен, проверка пройдена: 0 ошибок. Так выглядит успешный запуск.",
        "The project started and validation passed: 0 errors. This is what a successful run looks like.",
    ),

    # step 5 — undo
    "tutorial.step5_changes": _pair(
        "Агент изменил 2 файла:\n• main.py — новая сцена\n• ui.py — кнопка меню",
        "The agent changed 2 files:\n• main.py — a new scene\n• ui.py — a menu button",
    ),
    "tutorial.step5_undo": _pair("Отменить изменения", "Undo the changes"),
    "tutorial.step5_ok": _pair(
        "Изменения отменены — проект вернулся к снимку перед запуском агента.",
        "The changes are undone — the project is back to the snapshot taken before the agent run.",
    ),

    # step 6 — export
    "tutorial.step6_folder": _pair("Папка Windows", "Windows folder"),
    "tutorial.step6_exe": _pair(".exe", ".exe"),
    "tutorial.step6_android": _pair("Android", "Android"),
    "tutorial.step6_export": _pair("Экспортировать", "Export"),
    "tutorial.step6_start": _pair("Создать проект с ИИ", "Create an AI project"),
    "tutorial.step6_ok": _pair(
        "Готово: {target}. Проект можно запускать без установленного редактора.",
        "Done: {target}. The project runs without the editor installed.",
    ),

    "tutorial.step1_short": _pair("Проект", "Project"),
    "tutorial.step1_title": _pair("Создайте проект", "Create a project"),
    "tutorial.step1_body": _pair(
        "На стартовом экране выберите «Новый проект с ИИ» — движок соберёт готовую "
        "основу и откроет её. Или начните с пустого проекта, если хотите полностью "
        "ручной контроль. Недавние проекты всегда под рукой в том же окне.",
        "On the start screen choose “New AI project” — the engine builds a ready "
        "foundation and opens it. Or start from a blank project for full manual "
        "control. Recent projects stay one click away in the same window.",
    ),
    "tutorial.step1_tip": _pair(
        "Первый экран — это ещё и список недавних проектов: вернуться к работе можно в один клик.",
        "The start screen doubles as your recent-projects list: one click to get back to work.",
    ),
    "tutorial.step2_short": _pair("ИИ-задача", "AI task"),
    "tutorial.step2_title": _pair("Опишите задачу словами", "Describe the task in words"),
    "tutorial.step2_body": _pair(
        "Откройте раздел «ИИ-агент» и напишите, что нужно сделать: «добавь меню и "
        "три уровня» или «сделай экран статистики». Агент сам составит план, "
        "изменит файлы, нарисует ассеты и проверит запуск. Прогресс и вызовы "
        "инструментов видны прямо в чате.",
        "Open “AI agent” and say what you need: “add a menu and three levels” or "
        "“build a statistics screen”. The agent plans the work, edits files, "
        "draws assets and checks the launch. Progress and tool calls are visible "
        "right in the chat.",
    ),
    "tutorial.step2_tip": _pair(
        "Чем конкретнее задача, тем лучше результат. Можно писать на русском или английском.",
        "The more specific the task, the better the result. Write in Russian or English.",
    ),
    "tutorial.step3_short": _pair("Разделы", "Workspaces"),
    "tutorial.step3_title": _pair("Пять рабочих пространств", "Five workspaces"),
    "tutorial.step3_body": _pair(
        "«Обзор» показывает состояние и историю. «ИИ-агент» — чат с планом. "
        "«Код» — полноценный редактор файлов. «Ассеты» — спрайты, фоны и звуки. "
        "«Сцена» — визуальный холст для размещения объектов. Переключайтесь "
        "горячими клавишами Ctrl+1…Ctrl+5.",
        "“Overview” shows status and history. “AI agent” is the planning chat. "
        "“Code” is a full file editor. “Assets” holds sprites, backgrounds and "
        "sounds. “Scene” is a visual canvas for placing objects. Switch with "
        "Ctrl+1…Ctrl+5.",
    ),
    "tutorial.step3_tip": _pair(
        "Черновики в редакторе кода сохраняются автоматически перед каждым запуском агента.",
        "Drafts in the code editor are saved automatically before every agent run.",
    ),
    "tutorial.step4_short": _pair("Запуск", "Run"),
    "tutorial.step4_title": _pair("Запустите и проверьте", "Run and check"),
    "tutorial.step4_body": _pair(
        "Кнопка «Запустить» (Ctrl+R) открывает проект в отдельном окне, а вывод "
        "появляется в консоли редактора. Агент сам вызывает проверку и пробный "
        "запуск перед тем, как объявить работу готовой, — но вы всегда можете "
        "запустить вручную и посмотреть результат своими глазами.",
        "The “Run” button (Ctrl+R) opens the project in its own window and its "
        "output appears in the editor console. The agent validates and test-runs "
        "the project before declaring the work done — but you can always run it "
        "manually and judge the result yourself.",
    ),
    "tutorial.step4_tip": _pair(
        "В игре F11 переключает полный экран, Esc — пауза. В приложении работают мышь и касания.",
        "In a game F11 toggles fullscreen and Esc pauses. In an app mouse and touch both work.",
    ),
    "tutorial.step5_short": _pair("Отмена", "Undo"),
    "tutorial.step5_title": _pair("Верните любой шаг назад", "Undo any step"),
    "tutorial.step5_body": _pair(
        "Перед каждым запуском агента движок делает снимок проекта. В карточке "
        "изменений есть кнопка «Отменить», а раздел «История версий» позволяет "
        "вернуться к любой более ранней точке. Восстановление тоже отменяемо, "
        "так что экспериментировать безопасно.",
        "Before every agent run the engine takes a project snapshot. The changes "
        "card has an Undo button, and “Version history” lets you return to any "
        "earlier point. A restore is undoable too, so experimenting is safe.",
    ),
    "tutorial.step5_tip": _pair(
        "Снимки хранятся в папке проекта, их можно открыть и скопировать без редактора.",
        "Snapshots live inside the project folder and can be opened or copied without the editor.",
    ),
    "tutorial.step6_short": _pair("Экспорт", "Export"),
    "tutorial.step6_title": _pair("Поделитесь результатом", "Share the result"),
    "tutorial.step6_body": _pair(
        "Раздел «Экспорт» собирает папку Windows, отдельный .exe или пакет для "
        "Android. Игра и приложение запускаются без установленного редактора — "
        "внутри проекта уже лежит движок. Обучение можно повторить в любой момент "
        "через «Помощь → Быстрый старт» или кнопку «Обучение» на стартовом экране.",
        "“Export” builds a Windows folder, a standalone .exe or an Android "
        "package. Games and apps run without the editor installed — the engine "
        "already ships inside the project. Replay this tutorial any time from "
        "Help → Quick start or the Tutorial button on the start screen.",
    ),
    "tutorial.step6_tip": _pair(
        "Перед экспортом полезно один раз пройти проект вручную — так видны мелочи, которых не видит проверка.",
        "Before exporting, play through the project once by hand — you will spot details that validation cannot.",
    ),
}
