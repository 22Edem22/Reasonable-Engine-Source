"""The main project workspace: overview, agents, code and assets."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPainter, QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from reasonable.ai.providers import short_provider_name
from reasonable.core.history import (
    create_snapshot,
    describe_snapshot,
    get_snapshot,
    latest_snapshot,
    list_snapshots,
    restore_snapshot,
)
from reasonable.core.paths import human_time
from reasonable.core.progress import (
    derived_percent,
    read_events,
    read_state,
    record_event,
    scan_recent_files,
)
from reasonable.core.settings import Settings

from . import theme
from .assets import AssetsPage
from .chat import ChatPanel
from .code import CodePage
from .convert_dialog import ConvertDialog
from .export_dialog import ExportDialog
from .external import ExternalAgentPanel
from .history_dialog import HistoryDialog
from .project_settings import ProjectSettingsDialog
from .settings_dialog import SettingsDialog
from .widgets import Badge, Card, ElidedLabel, Separator, StatBox, muted, title_label

STATUS_MAP = {
    "running": ("РАБОТАЕТ", "gold"),
    "done": ("ГОТОВО", "teal"),
    "error": ("ОШИБКА", "gold"),
    "idle": ("ОЖИДАНИЕ", "default"),
}


def project_icon_pixmap(path: Path | None, size: int = 52) -> QPixmap:
    pixmap = QPixmap(str(path)) if path and path.exists() else QPixmap()
    if pixmap.isNull():
        return theme.logo_pixmap(size)
    pixmap = pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
    result = QPixmap(size, size)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    from PySide6.QtGui import QPainterPath

    clip = QPainterPath()
    clip.addRoundedRect(0, 0, size, size, size * 0.26, size * 0.26)
    painter.setClipPath(clip)
    painter.drawPixmap((size - pixmap.width()) // 2, (size - pixmap.height()) // 2, pixmap)
    painter.end()
    return result


def _shorten(text: str, limit: int = 90) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class ProjectPage(QWidget):
    back_requested = Signal()
    status_message = Signal(str)
    converted = Signal(str)
    delete_requested = Signal()

    def __init__(self, project, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self.settings = settings
        self.process: QProcess | None = None
        self._state_signature = None
        self._events_signature = None
        self._files_signature = None
        self._tasks_signature = None
        self._history_signature = None
        self._file_count = 0
        self._tick = 0
        self._process_output = ""
        self._last_run_code: int | None = None
        self._last_run_error = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_sidebar())
        content = QWidget()
        content.setObjectName("root")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(18, 14, 18, 14)
        content_layout.setSpacing(10)

        self.stack = QStackedWidget()
        self.overview = self._build_overview()
        self.stack.addWidget(self.overview)
        self.chat: ChatPanel | None = None
        self.external: ExternalAgentPanel | None = None
        if project.mode == "builtin":
            self.chat = ChatPanel(project, settings, self)
            self.chat.finished.connect(self._agent_finished)
            self.chat.settings_requested.connect(self._open_global_settings)
            self.chat.file_open_requested.connect(self._open_in_code)
            self.chat.restore_requested.connect(self._restore_snapshot)
            self.chat.history_requested.connect(self.open_history)
            self.chat.history_changed.connect(lambda: self._refresh_history_card(force=True))
            self.agent_page = self.chat
        else:
            self.external = ExternalAgentPanel(project, self)
            self.external.status_message.connect(self.status_message)
            self.agent_page = self.external
        self.stack.addWidget(self.agent_page)
        self.code_page = CodePage(project, self)
        self.code_page.status_message.connect(self.status_message)
        self.code_page.run_requested.connect(self.run_project)
        if self.chat is not None:
            self.chat.prepare_run = self.code_page.save_all
        self.stack.addWidget(self.code_page)
        self.assets_page = AssetsPage(project, settings, self)
        self.assets_page.status_message.connect(self.status_message)
        self.assets_page.open_file_requested.connect(self._open_in_code)
        self.stack.addWidget(self.assets_page)

        content_layout.addWidget(self.stack, 1)
        content_layout.addWidget(self._build_console())
        body.addWidget(content, 1)
        root.addLayout(body, 1)

        self.timer = QTimer(self)
        self.timer.setInterval(1500)
        self.timer.timeout.connect(self._tick_refresh)
        self.timer.start()
        self._tick_refresh(force=True)
        self._update_header()
        self._show_page(0, initial=True)
        self._set_run_result(
            "idle",
            "Проверьте проект в предпросмотре",
            "Быстрый цикл: запустите проект, посмотрите результат, исправьте код или "
            "попросите ИИ — и запустите снова.",
        )
        self._refresh_history_card(force=True)

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------
    def _build_header(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("topbar")
        frame.setFixedHeight(78)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(16, 10, 18, 10)
        layout.setSpacing(10)

        back = QPushButton("←")
        back.setObjectName("ghost")
        back.setFixedSize(34, 34)
        back.setToolTip("Ко всем проектам")
        back.clicked.connect(self._back)
        layout.addWidget(back)

        self.project_icon = QLabel()
        self.project_icon.setFixedSize(48, 48)
        self.project_icon.setPixmap(project_icon_pixmap(self.project.icon_path, 48))
        layout.addWidget(self.project_icon)

        titles = QVBoxLayout()
        titles.setSpacing(1)
        top = QHBoxLayout()
        top.setSpacing(7)
        self.name_label = QLabel(_shorten(self.project.name, 32))
        self.name_label.setObjectName("title")
        self.name_label.setFont(theme.display_font(13, 700))
        self.name_label.setMinimumWidth(100)
        self.name_label.setMaximumWidth(360)
        top.addWidget(self.name_label)
        self.type_badge = Badge("ИГРА" if self.project.project_type == "game" else "ПРИЛОЖЕНИЕ", "default")
        top.addWidget(self.type_badge)
        self.platform_badge = Badge("WINDOWS" if self.project.platform == "windows" else "ANDROID", "default")
        top.addWidget(self.platform_badge)
        self.mode_badge = Badge("ВСТРОЕННЫЙ ИИ" if self.project.mode == "builtin" else "ВНЕШНИЙ АГЕНТ", "default")
        top.addWidget(self.mode_badge)
        top.addStretch(1)
        titles.addLayout(top)
        self.goal_label_header = ElidedLabel(self.project.goal or "Цель пока не описана")
        self.goal_label_header.setObjectName("muted")
        self.goal_label_header.setFont(theme.ui_font(9))
        self.goal_label_header.setFixedHeight(self.goal_label_header.fontMetrics().height() + 8)
        titles.addWidget(self.goal_label_header)
        layout.addLayout(titles, 1)

        self.header_model = QLabel("")
        self.header_model.setObjectName("muted")
        self.header_model.setFont(theme.ui_font(8))
        self.header_model.setMaximumWidth(230)
        self.header_model.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.header_model)

        self.header_status = Badge("ОЖИДАНИЕ", "default")
        layout.addWidget(self.header_status)

        export = QPushButton("⤴  Экспорт")
        export.setObjectName("teal")
        export.setMinimumWidth(120)
        export.setStyleSheet("font-size: 13px; font-weight: 700; padding: 8px 14px;")
        export.setToolTip("Собрать проект в exe / APK / портативную папку (по умолчанию на Рабочий стол)")
        export.clicked.connect(self._open_export)
        layout.insertWidget(1, export)

        self.run_button = QPushButton("▶  Запустить")
        self.run_button.setObjectName("primary")
        self.run_button.setMinimumWidth(132)
        self.run_button.clicked.connect(self._run_clicked)
        layout.addWidget(self.run_button)
        return frame

    # ------------------------------------------------------------------
    # Sidebar
    # ------------------------------------------------------------------
    def _build_sidebar(self) -> QWidget:
        frame = QWidget()
        frame.setObjectName("sidebar")
        frame.setFixedWidth(224)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 16, 14, 16)
        layout.setSpacing(5)

        label = QLabel("РАЗДЕЛЫ")
        label.setObjectName("dim")
        label.setFont(theme.ui_font(8, 700))
        layout.addWidget(label)
        layout.addSpacing(2)

        self.nav_buttons: list[QPushButton] = []
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        for index, text in enumerate(
            (
                "Обзор",
                "ИИ-агент",
                "Код",
                "Ассеты",
            )
        ):
            button = QPushButton(text)
            button.setObjectName("nav")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda checked=False, i=index: self._show_page(i))
            self.nav_group.addButton(button)
            self.nav_buttons.append(button)
            layout.addWidget(button)
        self.nav_buttons[0].setChecked(True)
        layout.addSpacing(12)

        label = QLabel("ПРОЕКТ")
        label.setObjectName("dim")
        label.setFont(theme.ui_font(8, 700))
        layout.addWidget(label)
        self.side_meta = muted("", size=9)
        self.side_meta.setWordWrap(True)
        layout.addWidget(self.side_meta)
        layout.addSpacing(6)
        edit = QPushButton("Настройки проекта")
        edit.setObjectName("ghost")
        edit.clicked.connect(self._open_project_settings)
        layout.addWidget(edit)
        self.history_sidebar = QPushButton("История версий")
        self.history_sidebar.setObjectName("ghost")
        self.history_sidebar.setToolTip("Снимки проекта и возврат к рабочей версии")
        self.history_sidebar.clicked.connect(self.open_history)
        layout.addWidget(self.history_sidebar)
        folder = QPushButton("Открыть папку")
        folder.setObjectName("ghost")
        folder.clicked.connect(self._open_folder)
        layout.addWidget(folder)
        convert = QPushButton("Конвертировать…")
        convert.setObjectName("ghost")
        convert.setToolTip("Создать новый проект для другой платформы или с другими настройками")
        convert.clicked.connect(self._open_convert)
        self.convert_button = convert
        layout.addWidget(convert)
        delete = QPushButton("Удалить проект")
        delete.setObjectName("danger")
        delete.setToolTip("Убрать проект из списка или удалить его папку с диска")
        delete.clicked.connect(self.delete_requested)
        layout.addWidget(delete)
        layout.addStretch(1)

        ai = Card(soft=True, padding=12)
        ai.layout().addWidget(title_label("ИИ проекта", 10))
        self.side_ai = muted("", size=8)
        self.side_ai.setWordWrap(True)
        ai.layout().addWidget(self.side_ai)
        guide = QPushButton("Инструкции агента")
        guide.setObjectName("teal")
        guide.clicked.connect(self._open_guide)
        ai.layout().addWidget(guide)
        layout.addWidget(ai)

        version = QLabel(f"Reasonable Engine · {self.project.manifest.get('engine_version') or ''}")
        version.setObjectName("dim")
        version.setFont(theme.ui_font(8))
        layout.addWidget(version)
        return frame

    # ------------------------------------------------------------------
    # Overview
    # ------------------------------------------------------------------
    def _build_run_result_card(self) -> Card:
        card = Card(padding=16)
        top = QHBoxLayout()
        top.setSpacing(9)
        label = QLabel("Результат запуска")
        label.setObjectName("title")
        label.setFont(theme.display_font(12, 700))
        top.addWidget(label)
        self.run_result_badge = Badge("НЕ ЗАПУСКАЛСЯ", "default")
        top.addWidget(self.run_result_badge)
        top.addStretch(1)
        self.run_result_when = muted("", size=8)
        top.addWidget(self.run_result_when)
        card.layout().addLayout(top)

        self.run_result_title = QLabel("Проверьте проект в предпросмотре")
        self.run_result_title.setFont(theme.ui_font(10, 700))
        self.run_result_title.setStyleSheet("color: #E7E9EC;")
        card.layout().addWidget(self.run_result_title)
        self.run_result_detail = muted(
            "Быстрый цикл: запустите проект, посмотрите результат, исправьте код или "
            "попросите ИИ — и запустите снова.",
            size=9,
        )
        self.run_result_detail.setWordWrap(True)
        card.layout().addWidget(self.run_result_detail)
        self.run_result_error = QLabel("")
        self.run_result_error.setWordWrap(True)
        self.run_result_error.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.run_result_error.setFont(theme.ui_font(9))
        self.run_result_error.setStyleSheet(
            "background: #20191B; color: #D7B0B4; border: 1px solid #4A3034; "
            "border-radius: 7px; padding: 8px;"
        )
        self.run_result_error.hide()
        card.layout().addWidget(self.run_result_error)

        actions = QHBoxLayout()
        actions.setSpacing(7)
        self.run_again_button = QPushButton("▶  Запустить снова")
        self.run_again_button.setObjectName("primary")
        self.run_again_button.clicked.connect(self.run_project)
        actions.addWidget(self.run_again_button)
        self.fix_ai_button = QPushButton("✎  Исправить с ИИ")
        self.fix_ai_button.setObjectName("teal")
        self.fix_ai_button.setToolTip("Подготовить задачу агенту с текстом ошибки и открыть ИИ-агента")
        self.fix_ai_button.clicked.connect(self._fix_failed_run_with_ai)
        actions.addWidget(self.fix_ai_button)
        self.rollback_button = QPushButton("↶  Вернуть рабочую версию")
        self.rollback_button.setObjectName("ghost")
        self.rollback_button.setToolTip("Восстановить последний снимок проекта")
        self.rollback_button.clicked.connect(self._rollback_last_run)
        actions.addWidget(self.rollback_button)
        actions.addStretch(1)
        self.run_history_button = QPushButton("История")
        self.run_history_button.setObjectName("ghost")
        self.run_history_button.clicked.connect(self.open_history)
        actions.addWidget(self.run_history_button)
        card.layout().addLayout(actions)
        self.fix_ai_button.hide()
        self.rollback_button.hide()
        return card

    def _set_run_result(
        self,
        state: str,
        title: str,
        detail: str = "",
        error: str = "",
        *,
        when: str = "",
    ) -> None:
        tones = {"success": "teal", "failure": "gold", "running": "gold", "idle": "default"}
        labels = {
            "success": "УСПЕШНО",
            "failure": "ОШИБКА",
            "running": "ЗАПУЩЕН",
            "idle": "НЕ ЗАПУСКАЛСЯ",
        }
        self.run_result_badge.setText(labels.get(state, state.upper()))
        self.run_result_badge.set_tone(tones.get(state, "default"))
        self.run_result_title.setText(title)
        self.run_result_detail.setText(detail)
        self.run_result_detail.setVisible(bool(detail))
        self.run_result_error.setText(error)
        self.run_result_error.setVisible(bool(error))
        self.run_result_when.setText(when)
        self.fix_ai_button.setVisible(state == "failure")
        self.rollback_button.setVisible(state == "failure" and self._has_restorable_snapshot())
        self.run_again_button.setText("▶  Запустить снова" if state != "running" else "■  Остановить")
        if state == "running":
            try:
                self.run_again_button.clicked.disconnect()
            except (RuntimeError, TypeError):
                pass
            self.run_again_button.clicked.connect(self.stop_project)
        else:
            try:
                self.run_again_button.clicked.disconnect()
            except (RuntimeError, TypeError):
                pass
            self.run_again_button.clicked.connect(self.run_project)

    def _has_restorable_snapshot(self) -> bool:
        try:
            return latest_snapshot(self.project) is not None
        except Exception:
            return False

    def _build_overview(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = QWidget()
        host.setObjectName("root")
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 10, 4)
        layout.setSpacing(13)
        scroll.setWidget(host)

        self.run_result_card = self._build_run_result_card()
        layout.addWidget(self.run_result_card)

        hero = Card(padding=20)
        top = QHBoxLayout()
        title = QLabel("Прогресс разработки")
        title.setObjectName("title")
        title.setFont(theme.display_font(14, 700))
        top.addWidget(title)
        top.addStretch(1)
        self.overview_status = Badge("ОЖИДАНИЕ", "default")
        top.addWidget(self.overview_status)
        hero.layout().addLayout(top)

        progress_row = QHBoxLayout()
        progress_row.setSpacing(18)
        left = QVBoxLayout()
        left.setSpacing(4)
        self.percent_label = QLabel("0%")
        self.percent_label.setFont(theme.display_font(34, 700))
        self.percent_label.setStyleSheet("color: #FFFFFF; padding-bottom: 8px;")
        left.addWidget(self.percent_label)
        self.stage_label = QLabel("Ожидание")
        self.stage_label.setFont(theme.ui_font(11, 700))
        self.stage_label.setStyleSheet("color: #B7BDC6;")
        left.addWidget(self.stage_label)
        self.message_label = muted("", size=9)
        self.message_label.setWordWrap(True)
        left.addWidget(self.message_label)
        progress_row.addLayout(left, 3)

        stats = QHBoxLayout()
        stats.setSpacing(8)
        self.tasks_stat = StatBox("Задачи", "0/0", "план работ")
        self.files_stat = StatBox("Файлы", "0", "в проекте")
        stats.addWidget(self.tasks_stat)
        stats.addWidget(self.files_stat)
        progress_row.addLayout(stats, 2)
        hero.layout().addLayout(progress_row)

        self.overview_progress = QProgressBar()
        self.overview_progress.setRange(0, 100)
        self.overview_progress.setValue(0)
        hero.layout().addWidget(self.overview_progress)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.hero_agent = QPushButton("Открыть агента")
        self.hero_agent.setObjectName("primary")
        self.hero_agent.clicked.connect(self._open_agent)
        action_row.addWidget(self.hero_agent)
        code_button = QPushButton("Редактировать код")
        code_button.clicked.connect(lambda: self._show_page(2))
        action_row.addWidget(code_button)
        sprite_button = QPushButton("Спрайты")
        sprite_button.clicked.connect(lambda: self._show_page(3))
        action_row.addWidget(sprite_button)
        action_row.addStretch(1)
        self.last_activity_label = muted("", size=9)
        action_row.addWidget(self.last_activity_label)
        hero.layout().addLayout(action_row)
        layout.addWidget(hero)

        middle = QHBoxLayout()
        middle.setSpacing(13)
        tasks_card = Card()
        task_header = QHBoxLayout()
        task_header.addWidget(title_label("План работ", 12))
        task_header.addStretch(1)
        tasks_card.layout().addLayout(task_header)
        self.tasks_card_hint = muted("План ведёт ИИ-агент. Здесь он показывается для чтения.", size=8)
        tasks_card.layout().addWidget(self.tasks_card_hint)
        self.task_host = QVBoxLayout()
        self.task_host.setSpacing(5)
        tasks_card.layout().addLayout(self.task_host)
        tasks_card.layout().addStretch(1)
        middle.addWidget(tasks_card, 3)

        events_card = Card()
        events_header = QHBoxLayout()
        events_header.addWidget(title_label("События", 12))
        events_header.addStretch(1)
        self.events_count = Badge("0", "default")
        events_header.addWidget(self.events_count)
        events_card.layout().addLayout(events_header)
        self.events_list = QListWidget()
        self.events_list.setObjectName("eventsList")
        self.events_list.setMaximumHeight(260)
        self.events_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.events_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        events_card.layout().addWidget(self.events_list)
        middle.addWidget(events_card, 2)
        layout.addLayout(middle)

        bottom = QHBoxLayout()
        bottom.setSpacing(13)
        goal_card = Card(soft=True)
        goal_top = QHBoxLayout()
        goal_top.addWidget(title_label("Цель и заметки", 11))
        goal_top.addStretch(1)
        edit_goal = QPushButton("Изменить")
        edit_goal.setObjectName("ghost")
        edit_goal.clicked.connect(self._open_project_settings)
        goal_top.addWidget(edit_goal)
        goal_card.layout().addLayout(goal_top)
        self.goal_label = QLabel("")
        self.goal_label.setWordWrap(True)
        self.goal_label.setFont(theme.ui_font(10, 600))
        self.goal_label.setStyleSheet("color: #D7DBE0;")
        goal_card.layout().addWidget(self.goal_label)
        self.notes_label = muted("", size=9)
        self.notes_label.setWordWrap(True)
        goal_card.layout().addWidget(self.notes_label)
        bottom.addWidget(goal_card, 3)

        files_card = Card(soft=True)
        files_header = QHBoxLayout()
        files_header.addWidget(title_label("Недавние файлы", 11))
        files_header.addStretch(1)
        refresh_files = QPushButton("Обновить")
        refresh_files.setObjectName("ghost")
        refresh_files.clicked.connect(lambda: self._refresh_files(force=True))
        files_header.addWidget(refresh_files)
        files_card.layout().addLayout(files_header)
        self.recent_files = QListWidget()
        self.recent_files.setMaximumHeight(190)
        self.recent_files.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.recent_files.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.recent_files.itemDoubleClicked.connect(self._open_recent_file)
        files_card.layout().addWidget(self.recent_files)
        bottom.addWidget(files_card, 2)

        history_card = Card(soft=True)
        history_header = QHBoxLayout()
        history_header.addWidget(title_label("История версий", 11))
        history_header.addStretch(1)
        self.history_count = Badge("0", "default")
        history_header.addWidget(self.history_count)
        history_card.layout().addLayout(history_header)
        self.history_latest = muted("Снимки появятся перед первым запуском агента.", size=9)
        self.history_latest.setWordWrap(True)
        history_card.layout().addWidget(self.history_latest)
        history_actions = QHBoxLayout()
        history_actions.setSpacing(7)
        history_open = QPushButton("Открыть историю")
        history_open.setObjectName("teal")
        history_open.clicked.connect(self.open_history)
        history_actions.addWidget(history_open)
        history_save = QPushButton("Снимок сейчас")
        history_save.setObjectName("ghost")
        history_save.setToolTip("Сохранить текущее состояние как версию, к которой можно вернуться")
        history_save.clicked.connect(self._create_manual_snapshot)
        history_actions.addWidget(history_save)
        history_actions.addStretch(1)
        history_card.layout().addLayout(history_actions)
        bottom.addWidget(history_card, 2)

        layout.addLayout(bottom)
        layout.addStretch(1)
        return scroll

    # ------------------------------------------------------------------
    # Console
    # ------------------------------------------------------------------
    def _build_console(self) -> QFrame:
        self.console_frame = QFrame()
        self.console_frame.setObjectName("card")
        self.console_frame.setMaximumHeight(190)
        self.console_frame.hide()
        layout = QVBoxLayout(self.console_frame)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(5)
        top = QHBoxLayout()
        self.console_title = QLabel("Запуск проекта")
        self.console_title.setFont(theme.ui_font(9, 700))
        top.addWidget(self.console_title)
        top.addStretch(1)
        self.console_stop = QPushButton("Остановить")
        self.console_stop.setObjectName("danger")
        self.console_stop.clicked.connect(self.stop_project)
        top.addWidget(self.console_stop)
        close = QPushButton("×")
        close.setObjectName("ghost")
        close.setFixedSize(24, 24)
        close.setToolTip("Скрыть консоль")
        close.clicked.connect(self._hide_console)
        top.addWidget(close)
        layout.addLayout(top)
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(600)
        self.console.setFont(QFont("Cascadia Code", 8))
        self.console.setStyleSheet(
            "background: #101216; color: #B7BDC6; border: 1px solid #262B33; border-radius: 7px; padding: 6px;"
        )
        layout.addWidget(self.console)
        return self.console_frame

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def _show_page(self, index: int, initial: bool = False) -> None:
        self.stack.setCurrentIndex(index)
        if 0 <= index < len(self.nav_buttons):
            self.nav_buttons[index].setChecked(True)
        if index == 1:
            if self.chat is not None:
                self.chat.refresh_state()
            elif self.external is not None:
                self.external.refresh(force=True)
        if index == 2 and not initial:
            self.code_page.refresh_tree()
        if index == 3:
            self.assets_page.refresh()

    def _back(self) -> None:
        if self.process is not None and self.process.state() != QProcess.ProcessState.NotRunning:
            answer = QMessageBox.question(
                self,
                "Проект запущен",
                "Проект ещё запущен. Остановить его и вернуться к списку?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            self.stop_project()
        if not self.code_page.save_all():
            return
        self.shutdown()
        self.back_requested.emit()

    def _open_in_code(self, path: str) -> None:
        self._show_page(2)
        self.code_page.open_file(path)

    def _open_recent_file(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self._open_in_code(str(path))

    def _open_agent(self) -> None:
        self.open_agent_page()

    def open_agent_page(self, *, focus: bool = True) -> None:
        self._show_page(1)
        if not focus:
            return
        if self.chat is not None:
            QTimer.singleShot(0, self.chat.focus_input)
        elif self.external is not None:
            QTimer.singleShot(0, self.external.focus_task)

    def _open_guide(self) -> None:
        path = self.project.root / "AGENT_GUIDE.md"
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        else:
            QMessageBox.information(self, "Инструкция", "AGENT_GUIDE.md ещё не создан.")

    def _open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.project.root)))

    # ------------------------------------------------------------------
    # Version history / rollback
    # ------------------------------------------------------------------
    def open_history(self) -> None:
        if not self._history_available():
            return
        if not self.code_page.save_all():
            return
        dialog = HistoryDialog(self.project, self)
        dialog.restored.connect(self._history_restored)
        dialog.snapshot_created.connect(lambda _snapshot: self._refresh_history_card(force=True))
        dialog.exec()
        self._refresh_history_card(force=True)

    def _history_restored(self, _snapshot_id: str) -> None:
        self.code_page.refresh_tree()
        try:
            self.code_page._check_disk()
        except Exception:
            pass
        self.assets_page.refresh()
        if self.chat is not None:
            self.chat.refresh_state()
        self._tick_refresh(force=True)
        self._refresh_history_card(force=True)
        self._set_run_result(
            "idle",
            "Версия восстановлена",
            "Файлы проекта возвращены к выбранному снимку. Запустите проект, чтобы проверить результат.",
        )
        self.status_message.emit("Версия проекта восстановлена. Предыдущее состояние сохранено в истории.")

    def _create_manual_snapshot(self) -> None:
        if not self._history_available():
            return
        if not self.code_page.save_all():
            return
        label, ok = QInputDialog.getText(
            self,
            "Снимок версии",
            "Название версии (необязательно):",
        )
        if not ok:
            return
        try:
            snapshot = create_snapshot(
                self.project,
                label=label.strip() or "Ручной снимок рабочей версии",
                reason="manual",
            )
        except Exception as exc:
            QMessageBox.warning(self, "Не удалось создать снимок", str(exc))
            return
        self._refresh_history_card(force=True)
        self.status_message.emit(
            f"Снимок «{snapshot.get('label')}» создан. Его можно вернуть из истории."
        )

    def _restore_snapshot(self, snapshot_id: str) -> None:
        if not self._history_available():
            return
        if not self.code_page.save_all():
            return
        snapshot = get_snapshot(self.project, snapshot_id)
        label = str(snapshot.get("label") if snapshot else snapshot_id)
        answer = QMessageBox.question(
            self,
            "Отменить изменения",
            f"Вернуть версию «{label}»?\n\n"
            "Текущее состояние сначала сохранится отдельным снимком, поэтому "
            "восстановление тоже можно отменить.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            result = restore_snapshot(self.project, snapshot_id, safety=True)
        except Exception as exc:
            QMessageBox.critical(self, "Не удалось вернуть версию", str(exc))
            return
        self._history_restored(snapshot_id)
        self.status_message.emit(
            f"Версия «{label}» восстановлена: файлов {result.get('restored', 0)}, "
            f"удалено {result.get('removed', 0)}."
        )

    def _rollback_last_run(self) -> None:
        try:
            snapshot = latest_snapshot(self.project, reason="agent") or latest_snapshot(self.project)
        except Exception:
            snapshot = None
        if not snapshot:
            QMessageBox.information(
                self,
                "Нет снимков",
                "Пока нет сохранённых версий. Они создаются автоматически перед запуском агента.",
            )
            return
        self._restore_snapshot(str(snapshot.get("id")))

    def _history_available(self) -> bool:
        """History writes project files, so never race a running built-in agent."""
        if self.chat is not None and self.chat.running:
            QMessageBox.information(
                self,
                "Агент работает",
                "Дождитесь завершения агента или остановите его — затем можно "
                "создавать снимки и возвращать версии.",
            )
            return False
        return True

    def _refresh_history_card(self, force: bool = False) -> None:
        if not hasattr(self, "history_latest"):
            return
        try:
            snapshots = list_snapshots(self.project)
        except Exception:
            snapshots = []
        signature = tuple(
            (snapshot.get("id"), snapshot.get("created_at"), snapshot.get("outcome"))
            for snapshot in snapshots[:6]
        )
        if not force and signature == self._history_signature:
            return
        self._history_signature = signature
        self.history_count.setText(str(len(snapshots)))
        if not snapshots:
            self.history_latest.setText(
                "Снимков пока нет. Перед каждым запуском ИИ-агента рабочая версия "
                "сохраняется автоматически."
            )
            return
        latest = snapshots[0]
        changed = len(latest.get("changed_files") or [])
        extra = f" · изменено {changed} файл(ов)" if changed else ""
        self.history_latest.setText(
            f"{describe_snapshot(latest)}\n"
            f"{human_time(latest.get('created_at'))} · файлов {latest.get('file_count', 0)}{extra}"
        )

    # ------------------------------------------------------------------
    # Settings / export
    # ------------------------------------------------------------------
    def _open_project_settings(self) -> None:
        dialog = ProjectSettingsDialog(self.project, self)
        dialog.saved.connect(self._project_settings_saved)
        dialog.exec()

    def _project_settings_saved(self) -> None:
        self._update_header()
        self._tick_refresh(force=True)
        self.code_page.refresh_tree()
        self.status_message.emit("Настройки проекта сохранены.")

    def _open_global_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self, advanced=True)
        dialog.settings_saved.connect(self._ai_settings_saved)
        dialog.exec()

    def _ai_settings_saved(self) -> None:
        self.refresh_ai()
        self.status_message.emit("Настройки ИИ сохранены.")

    def refresh_ai(self) -> None:
        self._update_header_model()
        self._update_side_ai()
        if self.chat is not None:
            self.chat.refresh_state()

    def _open_export(self) -> None:
        if not self.code_page.save_all():
            return
        dialog = ExportDialog(self.project, self)
        dialog.exported.connect(lambda result: self.status_message.emit(result.get("message", "Экспорт завершён.")))
        dialog.exec()
        self._tick_refresh(force=True)

    def _open_convert(self) -> None:
        if not self.code_page.save_all():
            return
        dialog = ConvertDialog(self.project, self)
        dialog.converted.connect(self._converted_project)
        dialog.exec()

    def _converted_project(self, path: str) -> None:
        self.status_message.emit(f"Новый проект создан: {path}")
        self.converted.emit(path)

    def _update_header(self) -> None:
        from reasonable.core.project import UI_LEVEL_LABELS

        self.name_label.setText(_shorten(self.project.name, 32))
        self.goal_label_header.setText(self.project.goal or "Цель пока не описана")
        self.type_badge.setText("ИГРА" if self.project.project_type == "game" else "ПРИЛОЖЕНИЕ")
        self.platform_badge.setText("WINDOWS" if self.project.platform == "windows" else "ANDROID")
        self.mode_badge.setText("ВСТРОЕННЫЙ ИИ" if self.project.mode == "builtin" else "ВНЕШНИЙ АГЕНТ")
        self.project_icon.setPixmap(project_icon_pixmap(self.project.icon_path, 48))
        levels = ", ".join(UI_LEVEL_LABELS.get(level, level) for level in self.project.ui_levels)
        self.side_meta.setText(
            f"{'Windows' if self.project.platform == 'windows' else 'Android'} · "
            f"{'портрет' if self.project.manifest.get('orientation') == 'portrait' else 'альбом'}\n"
            f"Интерфейс: {levels}\n"
            f"{'Python/pygame' if self.project.project_type == 'game' else 'Python/pygame UI'} · "
            "окно настроит агент"
        )
        self._update_header_model()
        self._update_side_ai()
        self.hero_agent.setText("Открыть ИИ-агента")

    def _provider_label(self, config: dict) -> str:
        """Short provider name for the header and sidebar."""
        return short_provider_name(config.get("name") or config.get("id") or "ИИ")

    def _model_text(self) -> str:
        config = self.settings.get_provider_config()
        name = self._provider_label(config)
        model = config.get("model") or "модель не выбрана"
        return f"{name} · {model}"

    def _update_header_model(self) -> None:
        text = self._model_text()
        config = self.settings.get_provider_config()
        full = str(config.get("name") or config.get("id") or "ИИ")
        self.header_model.setText(_shorten(text, 46))
        self.header_model.setToolTip(f"Активная модель: {full} · {config.get('model') or 'модель не выбрана'}")

    def _update_side_ai(self) -> None:
        config = self.settings.get_provider_config()
        name = self._provider_label(config)
        model = config.get("model") or "модель не выбрана"
        if self.project.mode == "external":
            access = "внешний агент · API не требуется"
        elif config.get("requires_key") and not config.get("api_key"):
            access = "нужен API-ключ"
        elif config.get("api_key"):
            access = "ключ сохранён"
        else:
            access = "работает без ключа"
        self.side_ai.setText(f"{name}\n{model}\n{access}")

    # ------------------------------------------------------------------
    # Run process
    # ------------------------------------------------------------------
    def _run_clicked(self) -> None:
        if self.process is not None and self.process.state() != QProcess.ProcessState.NotRunning:
            self.stop_project()
        else:
            self.run_project()

    @staticmethod
    def _run_error_line(output: str) -> str:
        lines = [line.strip() for line in str(output or "").splitlines() if line.strip()]
        for line in reversed(lines):
            if re.match(r"^[A-Za-z_][\w.]*(?:Error|Exception|Interrupt|Exit):\s", line):
                return line
            if line.startswith(("ModuleNotFoundError:", "ImportError:", "SyntaxError:", "IndentationError:")):
                return line
        return lines[-1] if lines else ""

    @staticmethod
    def _run_error_hint(error_line: str) -> str:
        text = error_line.lower()
        if "modulenotfounderror" in text or "no module named" in text:
            return "Не установлена нужная библиотека. Установите её или попросите агента убрать зависимость."
        if "importerror" in text:
            return "Ошибка импорта: модуль есть, но импортируется неверное имя или не хватает зависимости."
        if "syntaxerror" in text or "indentationerror" in text:
            return "В коде синтаксическая ошибка — файл нужно исправить и сохранить."
        if "filenotfounderror" in text or "no such file" in text:
            return "Код обращается к файлу, которого нет в проекте. Проверьте путь к ассету."
        if "permissionerror" in text:
            return "Не хватает прав на файл или папку. Закройте занявший файл и попробуйте снова."
        if "pygame.error" in text:
            return "Ошибка pygame: окно, звук или поверхность созданы неправильно для этого окружения."
        if "typeerror" in text or "attributeerror" in text or "valueerror" in text or "keyerror" in text:
            return "Ошибка в данных или вызове функции. Агент может найти точное место по трассировке."
        if "timeout" in text or "timed out" in text:
            return "Проект не завершился вовремя — проверьте бесконечные циклы или ожидание ввода."
        return "Проект завершился с ошибкой. Полный вывод и трассировка остаются в консоли ниже."

    def _analyze_run(self, code: int, output: str) -> tuple[str, str, str, str]:
        """Turn a process result into a short, actionable UI message."""
        output = str(output or "").strip()
        if code == 0:
            return (
                "success",
                "Проект запустился и завершился без ошибок",
                "Предпросмотр работает. Можно менять код или попросить ИИ о следующем шаге.",
                "",
            )
        error_line = self._run_error_line(output)
        hint = self._run_error_hint(error_line)
        title = "Проект не запустился" if "Traceback" in output else f"Проект завершился с кодом {code}"
        detail = hint
        if error_line:
            detail = f"{hint}\n{error_line}"
        excerpt = ""
        if "Traceback" in output:
            tail = output.split("Traceback", 1)[-1]
            excerpt = ("Traceback" + tail)[-3500:].strip()
        elif output:
            excerpt = "\n".join(output.splitlines()[-14:])
        return "failure", title, detail, excerpt

    def _set_running_result(self) -> None:
        self._set_run_result(
            "running",
            "Проект запущен в предпросмотре",
            "Посмотрите окно проекта. Ошибки появятся здесь сразу после завершения процесса.",
            when=datetime.now().strftime("%H:%M"),
        )

    def _fix_failed_run_with_ai(self) -> None:
        if self.chat is None:
            QMessageBox.information(
                self,
                "Внешний агент",
                "Этот проект работает с внешним агентом. Скопируйте ошибку из консоли "
                "в задачу для Claude Code, Codex, Cursor или другого агента.",
            )
            return
        error = (self._last_run_error or self.run_result_error.text() or "Проект завершился с ошибкой.").strip()
        prompt = (
            "Проект не запускается. Найди причину, исправь файлы и проверь запуск.\n\n"
            f"Ошибка запуска:\n{error[:3000]}\n\n"
            "Сначала прочитай нужные файлы, затем измени только необходимое. "
            "В конце вызови validate_project и run_project."
        )
        self.chat.prefill_task(prompt)
        self.open_agent_page(focus=True)
        self.status_message.emit("Задача с текстом ошибки подготовлена в ИИ-агенте.")

    def run_project(self) -> None:
        if self.process is not None and self.process.state() != QProcess.ProcessState.NotRunning:
            self.status_message.emit("Проект уже запущен.")
            return
        if not self.code_page.save_all():
            return
        if not self.project.entry.exists():
            QMessageBox.warning(self, "Нет точки входа", f"Файл {self.project.entry.name} не найден.")
            return
        env = QProcessEnvironment()
        for key, value in self.project.run_env().items():
            env.insert(key, value)
        env.insert("PYTHONUNBUFFERED", "1")
        self._process_output = ""
        self._last_run_code = None
        self._last_run_error = ""
        self.console.clear()
        self.console_frame.show()
        self.console_title.setText("Запуск проекта · заставка Reasonable Engine")
        self.console_stop.setEnabled(True)
        self.process = QProcess(self)
        self.process.setProcessEnvironment(env)
        self.process.setWorkingDirectory(str(self.project.root))
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read_process_output)
        self.process.finished.connect(self._process_finished)
        self.process.errorOccurred.connect(self._process_error)
        command = self.project.run_command()
        self.process.start(command[0], command[1:])
        if not self.process.waitForStarted(5000):
            self._append_console("Не удалось запустить процесс.\n")
            self._set_run_result(
                "failure",
                "Не удалось запустить процесс",
                "Python или папка проекта недоступны. Проверьте установку Python в настройках.",
                "Процесс не стартовал за 5 секунд.",
                when=datetime.now().strftime("%H:%M"),
            )
            return
        self._append_console(f"Проект: {self.project.name}\nПапка: {self.project.root}\n")
        self.run_button.setText("■  Остановить")
        self.run_button.setObjectName("danger")
        self.run_button.style().unpolish(self.run_button)
        self.run_button.style().polish(self.run_button)
        self._set_running_result()
        self.status_message.emit("Проект запущен. Заставка ~3 секунды, затем игра/приложение.")
        self._show_page(0)

    def _read_process_output(self) -> None:
        if self.process is None:
            return
        data = bytes(self.process.readAllStandardOutput()).decode("utf-8", "replace")
        if data:
            self._process_output += data
            self._append_console(data)

    def _append_console(self, text: str) -> None:
        self.console.moveCursor(QTextCursor.MoveOperation.End)
        self.console.insertPlainText(text)
        bar = self.console.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _process_finished(self, code: int, _status) -> None:
        self._append_console(f"\nПроцесс завершён с кодом {code}.\n")
        self._last_run_code = int(code)
        state, title, detail, error = self._analyze_run(int(code), self._process_output)
        self._last_run_error = error or detail
        self._set_run_result(
            state,
            title,
            detail,
            error,
            when=datetime.now().strftime("%H:%M"),
        )
        self.run_button.setText("▶  Запустить")
        self.run_button.setObjectName("primary")
        self.run_button.style().unpolish(self.run_button)
        self.run_button.style().polish(self.run_button)
        self.console_stop.setEnabled(False)
        self.console_title.setText("Проект завершён" if code == 0 else f"Проект завершён с ошибкой ({code})")
        try:
            record_event(
                self.project.root,
                "run",
                "Проект запустился без ошибок" if code == 0 else f"Проект завершился с ошибкой (код {code})",
                {"returncode": int(code), "error": self._run_error_line(self._process_output)},
            )
        except Exception:
            pass
        self.status_message.emit("Проект завершён." if code == 0 else f"Проект завершился с кодом {code}.")
        self._tick_refresh(force=True)

    def _process_error(self, error) -> None:
        self._append_console(f"\nОшибка процесса: {error}\n")
        self._last_run_error = str(error)
        if self._last_run_code is None:
            self._set_run_result(
                "failure",
                "Ошибка запуска процесса",
                "Процесс не смог стартовать. Проверьте путь к Python и папку проекта.",
                str(error),
                when=datetime.now().strftime("%H:%M"),
            )

    def stop_project(self) -> None:
        if self.process is not None and self.process.state() != QProcess.ProcessState.NotRunning:
            self._append_console("\nОстанавливаю проект…\n")
            self.process.kill()
        self.run_button.setText("▶  Запустить")
        self.run_button.setObjectName("primary")
        self.run_button.style().unpolish(self.run_button)
        self.run_button.style().polish(self.run_button)
        if self._last_run_code is None:
            self._set_run_result(
                "idle",
                "Запуск остановлен",
                "Проект остановлен до завершения. Запустите снова, когда будете готовы.",
                when=datetime.now().strftime("%H:%M"),
            )

    def _hide_console(self) -> None:
        self.console_frame.hide()

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------
    def _tick_refresh(self, force: bool = False) -> None:
        self._tick += 1
        state = read_state(self.project.root)
        self._refresh_state(state, force)
        self._refresh_tasks(state, force)
        self._refresh_events(force)
        self._refresh_files(force)
        if force or self._tick % 6 == 0:
            self._refresh_history_card(force=force)

    def _refresh_state(self, state: dict, force: bool) -> None:
        signature = (
            state.get("percent"),
            state.get("stage"),
            state.get("message"),
            state.get("status"),
            state.get("last_event_at"),
            len(state.get("tasks") or []),
        )
        if not force and signature == self._state_signature:
            return
        self._state_signature = signature
        percent = int(round(derived_percent(state)))
        status = str(state.get("status") or "idle")
        text, tone = STATUS_MAP.get(status, ("ОЖИДАНИЕ", "default"))
        self.overview_status.setText(text)
        self.overview_status.set_tone(tone)
        self.header_status.setText(text)
        self.header_status.set_tone(tone)
        self.percent_label.setText(f"{percent}%")
        self.overview_progress.setValue(percent)
        stage = state.get("stage") or "Ожидание"
        self.stage_label.setText(stage)
        message = state.get("message") or ""
        self.message_label.setText(message)
        self.message_label.setVisible(bool(message))
        tasks = state.get("tasks") or []
        done = sum(1 for task in tasks if task.get("status") == "done")
        self.tasks_stat.set_value(f"{done}/{len(tasks)}", "задач выполнено")
        self.last_activity_label.setText(f"Активность: {human_time(state.get('last_event_at'))}")
        if force or self._file_count == 0 or self._tick % 6 == 0:
            self._file_count = len(self.project.list_files(limit=2000))
        self.files_stat.set_value(str(self._file_count), "файлов в проекте")
        self.goal_label.setText(self.project.goal or "Цель не описана. Добавьте её в настройках проекта.")
        notes = self.project.notes.strip()
        self.notes_label.setText(
            _shorten(notes, 420)
            if notes
            else "Заметок пока нет. Их можно добавить в настройках проекта или попросить агента."
        )

    def _refresh_tasks(self, state: dict, force: bool) -> None:
        tasks = state.get("tasks") or []
        signature = tuple((task.get("id"), task.get("title"), task.get("status")) for task in tasks)
        if not force and signature == self._tasks_signature:
            return
        self._tasks_signature = signature
        while self.task_host.count():
            item = self.task_host.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not tasks:
            self.task_host.addWidget(muted("План пока пуст. Агент создаст его при запуске.", size=9))
            return
        for task in tasks:
            row = QFrame()
            row.setStyleSheet("background: transparent;")
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 2, 0, 2)
            layout.setSpacing(8)
            status = task.get("status", "pending")
            icon, color = {
                "done": ("✓", "#8DB8A0"),
                "in_progress": (">", "#C9AD73"),
                "skipped": ("–", "#6F7680"),
            }.get(status, ("·", "#6F7680"))
            marker = QLabel(icon)
            marker.setFixedSize(26, 26)
            marker.setAlignment(Qt.AlignmentFlag.AlignCenter)
            marker.setStyleSheet(f"color: {color}; font-weight: 900; font-size: 14px; background: transparent;")
            layout.addWidget(marker)
            title = QLabel(str(task.get("title", "")))
            title.setWordWrap(True)
            title.setFont(theme.ui_font(9))
            if status == "done":
                title.setStyleSheet("color: #7D848E; text-decoration: line-through;")
            elif status == "in_progress":
                title.setStyleSheet("color: #D7C294; font-weight: 600;")
            elif status == "skipped":
                title.setStyleSheet("color: #6F7680;")
            else:
                title.setStyleSheet("color: #C1C7CF;")
            layout.addWidget(title, 1)
            task_id = QLabel(str(task.get("id", "")))
            task_id.setObjectName("dim")
            task_id.setFont(theme.ui_font(8))
            layout.addWidget(task_id)
            self.task_host.addWidget(row)

    def _refresh_events(self, force: bool) -> None:
        events = read_events(self.project.root, limit=30)
        signature = tuple((event.get("ts"), event.get("type"), event.get("message")) for event in events[-30:])
        if not force and signature == self._events_signature:
            return
        self._events_signature = signature
        self.events_list.clear()
        for event in reversed(events[-30:]):
            stamp = str(event.get("ts", ""))[11:19]
            kind = str(event.get("type", "event"))
            message = str(event.get("message", ""))
            item = QListWidgetItem(f"{stamp}  {kind}  ·  {message}")
            item.setToolTip(message)
            color = {
                "error": "#C98A90",
                "done": "#8DB8A0",
                "task": "#C9AD73",
            }.get(kind, "#A8AFB9")
            item.setForeground(QColor(color))
            self.events_list.addItem(item)
        self.events_count.setText(str(len(events)))

    def _refresh_files(self, force: bool) -> None:
        rows = scan_recent_files(self.project.root, limit=8)
        signature = tuple((row["path"], round(row["mtime"])) for row in rows)
        if not force and signature == self._files_signature:
            return
        self._files_signature = signature
        self.recent_files.clear()
        for row in rows:
            stamp = datetime.fromtimestamp(row["mtime"]).strftime("%H:%M")
            item = QListWidgetItem(f"{stamp}   {row['path']}")
            item.setData(Qt.ItemDataRole.UserRole, row["path"])
            item.setToolTip("Двойной клик — открыть в редакторе")
            self.recent_files.addItem(item)
        if not rows:
            self.recent_files.addItem("Пока нет изменённых файлов.")

    # ------------------------------------------------------------------
    def _agent_finished(self) -> None:
        self._tick_refresh(force=True)
        self._refresh_history_card(force=True)
        self.code_page.refresh_tree()
        self.assets_page.refresh()
        if self.process is None or self.process.state() == QProcess.ProcessState.NotRunning:
            outcome = self.chat.last_outcome if self.chat is not None else ""
            when = datetime.now().strftime("%H:%M")
            if outcome == "error":
                self._set_run_result(
                    "failure",
                    "Агент не смог завершить работу",
                    "Подробности — в чате агента. Проверьте ключ, модель и сеть, "
                    "затем запустите задачу снова.",
                    self.chat.last_error or "Ошибка ИИ-агента.",
                    when=when,
                )
            elif outcome == "incomplete":
                self._set_run_result(
                    "idle",
                    "Агент не завершил работу",
                    "Агент остановился до проверки и запуска. Запустите проект, "
                    "чтобы увидеть результат, или продолжите задачу в чате.",
                    when=when,
                )
            else:
                self._set_run_result(
                    "idle",
                    "Агент изменил проект — проверьте предпросмотр",
                    "Запустите проект, чтобы увидеть результат. Если стало хуже, верните версию из истории.",
                    when=when,
                )
        self.status_message.emit("Агент завершил работу. Прогресс обновлён.")

    # ------------------------------------------------------------------
    def shutdown(self) -> None:
        self.timer.stop()
        if self.chat is not None:
            self.chat.shutdown()
        if self.external is not None:
            self.external.shutdown()
        self.stop_project()
