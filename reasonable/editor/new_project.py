"""New-project wizard.

The wizard deliberately asks only what is needed to create the folder:

1. the idea, project type and agent mode;
2. the name and location, with a short summary.

Everything that benefits from context — window size and mode, notes, and the
first task for the AI agent — is configured after the project exists. This
keeps the first run short and avoids asking the user to write a brief before
they have seen anything.
"""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from reasonable.core.paths import slugify
from reasonable.core.project import (
    UI_LEVELS,
    UI_LEVEL_LABELS,
    choose_project_dir,
    default_manifest,
)
from reasonable.core.settings import Settings

from . import theme
from .widgets import Badge, Card, muted, title_label
from .workers import ScaffoldWorker


PROJECT_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9][A-Za-z0-9 _-]{0,58}$")


def default_projects_dir(settings: Settings | None = None) -> Path:
    """Folder for new projects: the configured one, or the engine's Projects."""
    if settings is not None:
        return settings.projects_dir()
    from reasonable.core.paths import ensure_projects_dir

    return ensure_projects_dir()


class StepPill(QLabel):
    def __init__(self, number: int, text: str, parent: QWidget | None = None) -> None:
        super().__init__(f"{number}  {text}", parent)
        self.number = number
        self.setFont(theme.ui_font(9, 700))
        self.set_state(False, False)

    def set_state(self, active: bool, complete: bool) -> None:
        if active:
            style = (
                "background: #241C19; color: #E0A08B;"
                "border: 1px solid #4A352D; border-radius: 6px;"
                "padding: 4px 10px;"
            )
        elif complete:
            style = (
                "background: #1B1F25; color: #B7BDC6;"
                "border: 1px solid #2B3038; border-radius: 6px;"
                "padding: 4px 10px;"
            )
        else:
            style = (
                "background: transparent; color: #6F7680;"
                "border: 1px solid #2A3038; border-radius: 6px; padding: 4px 10px;"
            )
        self.setStyleSheet(style)


class NewProjectDialog(QDialog):
    project_created = Signal(object)
    settings_requested = Signal()

    def __init__(
        self,
        settings: Settings,
        parent: QWidget | None = None,
        *,
        starter: str = "game",
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.starter = starter if starter in {"game", "app", "blank"} else "game"
        self.project = None
        self.worker: ScaffoldWorker | None = None
        self._creating = False
        self._name_touched = False

        self.setWindowTitle("Новый проект — Reasonable Engine")
        self.setMinimumSize(980, 740)
        self.resize(1000, 770)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 20, 26, 20)
        root.setSpacing(16)
        root.addLayout(self._build_header())

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_goal_page())
        self.stack.addWidget(self._build_finish_page())
        self.stack.addWidget(self._build_progress_page())
        root.addWidget(self.stack, 1)

        footer = QHBoxLayout()
        self.cancel_button = QPushButton("Отмена")
        self.cancel_button.setObjectName("ghost")
        self.cancel_button.clicked.connect(self.reject)
        footer.addWidget(self.cancel_button)
        footer.addStretch(1)
        self.back_button = QPushButton("Назад")
        self.back_button.clicked.connect(self._back)
        footer.addWidget(self.back_button)
        self.next_button = QPushButton("Далее")
        self.next_button.setObjectName("primary")
        self.next_button.setMinimumWidth(150)
        self.next_button.clicked.connect(self._next)
        footer.addWidget(self.next_button)
        root.addLayout(footer)

        self._update_steps()
        self._update_ai_card()
        self._sync_footer()
        self._apply_starter()
        if self.starter == "blank":
            self.next_button.setFocus()
        else:
            self.goal_edit.setFocus()

        for button in self.type_buttons.values():
            button.toggled.connect(lambda _checked: self._refresh_summary())
        for button in self.mode_buttons.values():
            button.toggled.connect(lambda _checked: self._refresh_summary())
        self.folder_edit.textChanged.connect(self._refresh_summary)
        self.name_edit.textChanged.connect(self._refresh_summary)

    # ------------------------------------------------------------------
    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(theme.logo_pixmap(30))
        row.addWidget(logo)
        heading = QLabel("Новый проект")
        heading.setObjectName("title")
        heading.setFont(theme.display_font(13, 700))
        row.addWidget(heading)
        row.addSpacing(18)
        self.step_pills = [StepPill(1, "Идея"), StepPill(2, "Название")]
        for pill in self.step_pills:
            row.addWidget(pill)
        row.addStretch(1)
        return row

    def _page_shell(self, title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 4, 0, 0)
        outer.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("root")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(10, 10, 22, 16)
        layout.setSpacing(14)
        header = QLabel(title)
        header.setObjectName("title")
        header.setFont(theme.display_font(21, 700))
        header.setStyleSheet("padding-bottom: 8px;")
        layout.addWidget(header)
        sub = muted(subtitle, size=10)
        sub.setMaximumWidth(760)
        sub.setWordWrap(True)
        layout.addWidget(sub)
        layout.addSpacing(6)
        page._header = header  # type: ignore[attr-defined]
        page._sub = sub  # type: ignore[attr-defined]
        scroll.setWidget(body)
        outer.addWidget(scroll)
        return page, layout

    # ------------------------------------------------------------------
    def _build_goal_page(self) -> QWidget:
        page, layout = self._page_shell(
            "С чего начинается проект?",
            "Одно короткое предложение — главная идея. Детали, окно и первую задачу "
            "агенту добавим после создания, когда проект уже будет перед глазами.",
        )
        goal_label = QLabel("Главная цель")
        goal_label.setFont(theme.ui_font(10, 700))
        layout.addWidget(goal_label)
        self.goal_label = goal_label

        self.goal_edit = QLineEdit()
        self.goal_edit.setPlaceholderText("Например: 2D-платформер, где кот собирает звёзды и убегает от слизней")
        self.goal_edit.setMinimumHeight(48)
        self.goal_edit.setFont(theme.ui_font(12))
        self.goal_edit.textChanged.connect(self._goal_changed)
        layout.addWidget(self.goal_edit)
        self.goal_hint = muted("Коротко и по делу: жанр + герой + главное действие.", size=9)
        layout.addWidget(self.goal_hint)

        layout.addSpacing(8)
        self.type_section = self._section("Что создаём")
        layout.addWidget(self.type_section)
        type_row = QHBoxLayout()
        type_row.setSpacing(12)
        self.type_row = type_row
        self.type_group = QButtonGroup(self)
        self.type_buttons: dict[str, QPushButton] = {}
        for key, text, hint in (
            ("game", "ИГРА", "Уровни, персонажи, очки, геймплей"),
            ("app", "ПРИЛОЖЕНИЕ", "Экраны, списки, формы, ИИ-панели"),
        ):
            button = QPushButton(f"{text}\n{hint}")
            button.setObjectName("choice")
            button.setCheckable(True)
            button.setMinimumHeight(74)
            button.setFont(theme.ui_font(10, 700))
            self.type_group.addButton(button)
            self.type_buttons[key] = button
            type_row.addWidget(button)
        self.type_buttons["game"].setChecked(True)
        layout.addLayout(type_row)

        layout.addSpacing(8)
        self.levels_section = self._section("Уровень интерфейса")
        layout.addWidget(self.levels_section)
        self.level_checks: dict[str, QCheckBox] = {}
        levels_hints = {
            "simple": "Обычные окна, кнопки и списки. Для утилит и программ Windows",
            "standard": "Готовые виджеты движка: тёмная тема, панели, списки, прокрутка",
            "advanced": "Своя графика, частицы, анимации. Для игр",
        }
        for level in UI_LEVELS:
            check = QCheckBox(f"{UI_LEVEL_LABELS[level]} — {levels_hints[level]}")
            check.setStyleSheet("font-size: 10px;")
            check.toggled.connect(self._levels_changed)
            self.level_checks[level] = check
            layout.addWidget(check)
        self.levels_hint = muted(
            "Можно выбрать несколько: в проект лягут только нужные инструменты и навыки.",
            size=9,
        )
        self.levels_hint.setWordWrap(True)
        layout.addWidget(self.levels_hint)
        self._levels_touched = False
        self._apply_level_defaults()
        for button in self.type_buttons.values():
            button.toggled.connect(self._apply_level_defaults_from_type)

        layout.addSpacing(8)
        self.mode_section = self._section("Кто будет собирать проект")
        layout.addWidget(self.mode_section)
        mode_row = QHBoxLayout()
        mode_row.setSpacing(12)
        self.mode_row = mode_row
        self.mode_group = QButtonGroup(self)
        self.mode_buttons: dict[str, QPushButton] = {}
        for key, text, hint in (
            ("builtin", "ВСТРОЕННЫЙ ИИ", "Агент работает прямо в редакторе"),
            ("external", "ВНЕШНИЙ АГЕНТ", "Claude Code, Codex, Cursor, Cline…"),
        ):
            button = QPushButton(f"{text}\n{hint}")
            button.setObjectName("choice")
            button.setCheckable(True)
            button.setMinimumHeight(74)
            button.setFont(theme.ui_font(10, 700))
            self.mode_group.addButton(button)
            self.mode_buttons[key] = button
            mode_row.addWidget(button)
        self.mode_buttons["builtin"].setChecked(True)
        layout.addLayout(mode_row)
        self.mode_hint = muted(
            "Встроенный агент сразу читает проект, меняет файлы, рисует спрайты и показывает прогресс.",
            size=9,
        )
        self.mode_hint.setWordWrap(True)
        layout.addWidget(self.mode_hint)
        for button in self.mode_buttons.values():
            button.toggled.connect(self._mode_changed)

        layout.addSpacing(8)
        after = Card(soft=True, padding=13)
        after.layout().addWidget(title_label("Что будет дальше", 10))
        after.layout().addWidget(
            muted(
                "После создания откроется проект и раздел «ИИ-агент». Там вы напишете "
                "первую задачу и сможете менять окно, заметки, код и ассеты.",
                size=9,
            )
        )
        layout.addWidget(after)
        self.after_card = after

        self.blank_card = Card(soft=True, padding=14)
        self.blank_card.layout().addWidget(title_label("Минимальный шаблон", 10))
        self.blank_card.layout().addWidget(
            muted(
                "Будет создан короткий main.py с пустым окном, project.json, папка assets "
                "и инструкции для агента. Никакая игра и никакие вопросы про ИИ не создаются: "
                "вы сразу попадёте в редактор кода и сможете писать сами или позвать агента.",
                size=9,
            )
        )
        self.blank_card.hide()
        layout.addWidget(self.blank_card)
        layout.addStretch(1)
        return page

    def _build_finish_page(self) -> QWidget:
        page, layout = self._page_shell(
            "Название и место",
            "Последний штрих. Укажите имя проекта и папку — остальное Reasonable Engine сделает сам.",
        )

        name_box = QVBoxLayout()
        name_box.setSpacing(5)
        name_box.addWidget(self._small_label("Название проекта (на английском)"))
        self.name_edit = QLineEdit()
        self.name_edit.setMinimumHeight(42)
        self.name_edit.setPlaceholderText("My Great Project")
        self.name_edit.textEdited.connect(self._name_edited)
        name_box.addWidget(self.name_edit)
        self.name_hint = muted(
            "Латиницей, например «Task Manager». Используется для папки и файлов проекта.",
            size=9,
        )
        self.name_hint.setWordWrap(True)
        name_box.addWidget(self.name_hint)
        layout.addLayout(name_box)

        folder_box = QVBoxLayout()
        folder_box.setSpacing(5)
        folder_box.addWidget(self._small_label("Папка"))
        folder_row = QHBoxLayout()
        self.folder_edit = QLineEdit(str(default_projects_dir(self.settings)))
        self.folder_edit.setMinimumHeight(42)
        folder_row.addWidget(self.folder_edit, 1)
        browse = QPushButton("Выбрать…")
        browse.clicked.connect(self._browse)
        folder_row.addWidget(browse)
        folder_box.addLayout(folder_row)
        self.folder_hint = muted("", size=9)
        self.folder_hint.setWordWrap(True)
        folder_box.addWidget(self.folder_hint)
        layout.addLayout(folder_box)

        layout.addSpacing(4)
        self.ai_card = Card(soft=True)
        ai_top = QHBoxLayout()
        ai_top.addWidget(title_label("ИИ для проекта", 11))
        ai_top.addStretch(1)
        self.ai_badge = Badge("Проверка", "default")
        ai_top.addWidget(self.ai_badge)
        self.ai_card.layout().addLayout(ai_top)
        self.ai_text = muted("", size=9)
        self.ai_text.setWordWrap(True)
        self.ai_card.layout().addWidget(self.ai_text)
        ai_buttons = QHBoxLayout()
        ai_buttons.addStretch(1)
        ai_configure = QPushButton("Настроить ИИ")
        ai_configure.setObjectName("teal")
        ai_configure.clicked.connect(self.settings_requested)
        ai_buttons.addWidget(ai_configure)
        self.ai_card.layout().addLayout(ai_buttons)
        layout.addWidget(self.ai_card)

        layout.addWidget(self._small_label("Сводка"))
        self.summary_card = Card(soft=True)
        self.summary_label = muted("", size=9)
        self.summary_label.setWordWrap(True)
        self.summary_card.layout().addWidget(self.summary_label)
        layout.addWidget(self.summary_card)

        note = Card(soft=True, padding=13)
        note.layout().addWidget(title_label("Первая задача — после создания", 10))
        note.layout().addWidget(
            muted(
                "Мастер не просит писать техническое задание заранее. После создания "
                "откроется раздел «ИИ-агент», где вы опишете первую задачу обычными словами.",
                size=9,
            )
        )
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def _build_progress_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("root")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 20, 10, 10)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(14)
        self.progress_logo = QLabel()
        self.progress_logo.setPixmap(theme.logo_pixmap(64))
        self.progress_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.progress_logo)
        self.progress_title = QLabel("Собираю проект")
        self.progress_title.setObjectName("title")
        self.progress_title.setFont(theme.display_font(21, 700))
        self.progress_title.setStyleSheet("padding-bottom: 8px;")
        self.progress_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.progress_title)
        self.progress_stage = muted("Готовлю папки и файлы…", size=10)
        self.progress_stage.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.progress_stage)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setMaximumWidth(430)
        self.progress_bar.setMinimumHeight(12)
        layout.addWidget(self.progress_bar, 0, Qt.AlignmentFlag.AlignCenter)
        self.progress_detail = muted("", size=9)
        self.progress_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_detail.setWordWrap(True)
        self.progress_detail.setMaximumWidth(600)
        layout.addWidget(self.progress_detail)
        self.progress_buttons = QHBoxLayout()
        self.progress_buttons.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.open_project_button = QPushButton("Открыть проект")
        self.open_project_button.setObjectName("primary")
        self.open_project_button.clicked.connect(self._finish_open)
        self.open_project_button.hide()
        self.progress_buttons.addWidget(self.open_project_button)
        self.close_button = QPushButton("Закрыть")
        self.close_button.clicked.connect(self.reject)
        self.close_button.hide()
        self.progress_buttons.addWidget(self.close_button)
        layout.addLayout(self.progress_buttons)
        return page

    # ------------------------------------------------------------------
    def _section(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setFont(theme.ui_font(11, 700))
        return label

    def _small_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setFont(theme.ui_font(9, 700))
        label.setStyleSheet("color: #9AA1AB;")
        return label

    def _goal_changed(self, text: str) -> None:
        if not self._name_touched:
            from reasonable.core.paths import to_latin

            name = re.sub(r"\s+", " ", to_latin(text)).strip()
            name = re.sub(r"[^A-Za-z0-9 _-]+", "", name)[:58].strip()
            self.name_edit.setText(name)
        self._update_finish_hint()

    def _name_edited(self, _text: str) -> None:
        self._name_touched = True

    # ------------------------------------------------------------------
    # UI level selection
    def _levels_changed(self, _checked: bool) -> None:
        self._levels_touched = True
        self._refresh_summary()

    def _apply_level_defaults_from_type(self, _checked: bool) -> None:
        self._apply_level_defaults()

    def _apply_level_defaults(self) -> None:
        """Reset the checkboxes to sensible defaults for the chosen type."""
        if self.starter == "blank":
            defaults = ["standard"]
        elif self.project_type() == "game":
            defaults = ["advanced", "standard"]
        else:
            defaults = ["standard"]
        for level, check in self.level_checks.items():
            check.blockSignals(True)
            check.setChecked(level in defaults)
            check.blockSignals(False)
        self._levels_touched = False

    def selected_ui_levels(self) -> list[str]:
        return [level for level in UI_LEVELS if self.level_checks[level].isChecked()]

    def _mode_changed(self, _checked: bool) -> None:
        if self.mode() == "external":
            self.mode_hint.setText(
                "Внешний агент: редактор подготовит AGENT_GUIDE.md, навыки, re.bat и будет "
                "показывать его прогресс в реальном времени. Работает с Claude Code, Codex, Cursor, Cline и другими."
            )
        else:
            self.mode_hint.setText(
                "Встроенный агент: работает сразу в редакторе, меняет файлы, рисует спрайты и "
                "показывает план и прогресс. Нужен настроенный провайдер ИИ."
            )
        if hasattr(self, "ai_text"):
            self._refresh_summary()

    def _apply_starter(self) -> None:
        """Blank projects skip the idea and agent questions entirely."""
        if self.starter != "blank":
            return
        page = self.stack.widget(0)
        header = getattr(page, "_header", None)
        sub = getattr(page, "_sub", None)
        if header is not None:
            header.setText("Пустой проект")
        if sub is not None:
            sub.setText(
                "Сразу к результату: создаём минимальный проект без игры и без вопросов "
                "про ИИ. Вы начнёте с пустого main.py, который уже запускается."
            )
        for widget in (
            self.goal_label,
            self.goal_edit,
            self.goal_hint,
            self.type_section,
            self.mode_section,
            self.mode_hint,
            self.after_card,
            self.levels_section,
            self.levels_hint,
            *self.level_checks.values(),
        ):
            widget.hide()
        for button in (*self.type_buttons.values(), *self.mode_buttons.values()):
            button.hide()
        self.blank_card.show()
        self.step_pills[0].setText("1  Пустой проект")
        self.ai_card.hide()
        self.goal_edit.setPlaceholderText("")
        self.name_edit.setPlaceholderText("Мой проект")
        self.stack.widget(1)._header.setText("Название и место")

    # ------------------------------------------------------------------
    def project_type(self) -> str:
        for key, button in self.type_buttons.items():
            if button.isChecked():
                return key
        return "game"

    def mode(self) -> str:
        for key, button in self.mode_buttons.items():
            if button.isChecked():
                return key
        return "builtin"

    def _update_steps(self) -> None:
        index = self.stack.currentIndex()
        for position, pill in enumerate(self.step_pills):
            pill.set_state(position == index, position < index or index >= len(self.step_pills))

    def _back(self) -> None:
        if self._creating:
            return
        if self.stack.currentIndex() == 0:
            return
        self.stack.setCurrentIndex(self.stack.currentIndex() - 1)
        self._update_steps()
        self._sync_footer()
        if self.stack.currentIndex() == 1:
            self._refresh_summary()

    def _next(self) -> None:
        index = self.stack.currentIndex()
        if index == 0:
            if self.starter != "blank" and len(self.goal_edit.text().strip()) < 3:
                QMessageBox.warning(self, "Нужна цель", "Опишите главную цель проекта хотя бы тремя символами.")
                self.goal_edit.setFocus()
                return
            self.stack.setCurrentIndex(1)
            self.name_edit.setFocus()
            self.name_edit.selectAll()
            self._refresh_summary()
        elif index == 1:
            self._create_project()
            return
        self._update_steps()
        self._sync_footer()

    def _sync_footer(self) -> None:
        index = self.stack.currentIndex()
        self.back_button.setVisible(0 < index < 2)
        self.cancel_button.setVisible(not self._creating)
        self.next_button.setText("Создать проект" if index == 1 else "Далее")

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Куда сохранить проект",
            self.folder_edit.text() or str(Path.home()),
        )
        if folder:
            self.folder_edit.setText(folder)
            self._update_finish_hint()

    def _update_finish_hint(self) -> None:
        if not hasattr(self, "folder_edit"):
            return
        name = self.name_edit.text().strip()
        folder = self.folder_edit.text().strip()
        if name and folder:
            from reasonable.core.paths import slugify

            target = Path(folder) / slugify(name, "project")
            self.folder_hint.setText(f"Проект появится здесь: {target}")
        else:
            self.folder_hint.setText("")

    def _update_ai_card(self) -> None:
        config = self.settings.get_provider_config()
        name = config.get("name") or config.get("id") or "Не выбран"
        model = config.get("model") or "не указана"
        needs_key = bool(config.get("requires_key") and not config.get("api_key"))
        if self.mode() == "external":
            self.ai_badge.setText("Не требуется")
            self.ai_badge.set_tone("default")
            self.ai_text.setText(
                f"{name} · {model}\nВнешний режим не использует API редактора. Если захотите "
                "включить встроенного агента позже, ключ можно добавить в настройках."
            )
        elif needs_key:
            self.ai_badge.setText("Нужен ключ")
            self.ai_badge.set_tone("gold")
            self.ai_text.setText(
                f"{name} · {model}\nДля этой модели нужен API-ключ. Проект можно создать сейчас, "
                "но агент запустится только после настройки."
            )
        else:
            self.ai_badge.setText("Готов")
            self.ai_badge.set_tone("default")
            self.ai_text.setText(f"{name} · {model}\n{config.get('base_url') or 'Локальный провайдер'}")

        kind = "Игра" if self.project_type() == "game" else "Приложение"
        mode = "встроенный ИИ" if self.mode() == "builtin" else "внешний агент"
        if self.starter == "blank":
            self.summary_label.setText(
                "Пустой проект · минимальный main.py\n"
                "Без игры и без вопросов про ИИ\n"
                "После создания откроется раздел «Код»\n"
                f"Папка: {self.folder_edit.text().strip() or '—'}"
            )
            return
        self.summary_label.setText(
            f"{kind} · {mode}\n"
            "Окно: 1280 × 720 · можно менять размер\n"
            "Режим окна и заметки — после создания\n"
            f"Папка: {self.folder_edit.text().strip() or '—'}"
        )

    def refresh_ai(self) -> None:
        self._update_ai_card()

    def _refresh_summary(self) -> None:
        if not hasattr(self, "summary_label"):
            return
        self._update_finish_hint()
        self._update_ai_card()

    # ------------------------------------------------------------------
    def _create_project(self) -> None:
        name = self.name_edit.text().strip() or self.goal_edit.text().strip()[:58] or "Новый проект"
        parent = Path(self.folder_edit.text().strip() or str(default_projects_dir(self.settings)))
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.critical(self, "Не удалось создать папку", str(exc))
            return
        # Remember the chosen parent so the next project starts in the same place.
        self.settings.set_projects_dir(parent)
        manifest = default_manifest(
            name,
            project_type=self.project_type(),
            mode=self.mode(),
            goal=self.goal_edit.text().strip(),
            notes="",
            width=1280,
            height=720,
            window_mode="windowed",
            resizable=True,
            orientation="landscape",
            template="blank" if self.starter == "blank" else None,
        )
        manifest["ai"]["image_style"] = "flat"
        manifest["preview"] = {"skip_splash": False}
        root = choose_project_dir(parent, name)
        self._creating = True
        self.back_button.hide()
        self.next_button.hide()
        self.cancel_button.hide()
        self.stack.setCurrentIndex(2)
        self._update_steps()
        self.progress_detail.setText(f"{name}\n{root}")
        self.worker = ScaffoldWorker(root, manifest)
        self.worker.stage.connect(self.progress_stage.setText)
        self.worker.done.connect(self._creation_done)
        self.worker.failed.connect(self._creation_failed)
        self.worker.start()

    def _creation_done(self, project) -> None:
        self._creating = False
        self.project = project
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1)
        self.progress_title.setText("Проект готов!")
        if self.starter == "blank":
            self.progress_stage.setText(f"{project.name} · пустой проект")
            self.progress_detail.setText(
                "Созданы минимальный main.py, project.json, папка assets и инструкции для агента.\n"
                "Сейчас откроется раздел «Код» — можно писать самому или позвать ИИ-агента."
            )
        else:
            mode_text = "встроенный ИИ" if project.mode == "builtin" else "внешний агент"
            self.progress_stage.setText(f"{project.name} · {mode_text}")
            self.progress_detail.setText(
                "Созданы main.py, project.json, иконка, фон, стартовые спрайты, "
                "progress/ и инструкции для агента.\n"
                "Первая задача пишется в разделе «ИИ-агент» — уже после создания."
            )
        self.progress_logo.setPixmap(theme.logo_pixmap(64))
        self.open_project_button.show()
        self.close_button.show()
        self.cancel_button.show()
        self.cancel_button.setText("Закрыть")
        self.cancel_button.clicked.disconnect()
        self.cancel_button.clicked.connect(self.reject)
        self.project_created.emit(project)

    def _creation_failed(self, message: str, trace: str) -> None:
        self._creating = False
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_title.setText("Не удалось создать проект")
        self.progress_stage.setText(message)
        self.progress_detail.setText(trace[-1500:])
        self.cancel_button.show()
        self.cancel_button.setText("Закрыть")
        self.back_button.show()

    def _finish_open(self) -> None:
        self.accept()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.worker is not None and self.worker.isRunning():
            answer = QMessageBox.question(
                self,
                "Создание проекта",
                "Проект ещё создаётся. Закрыть окно? Это может оставить неполные файлы.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        event.accept()

    def result_project(self):
        return self.project
