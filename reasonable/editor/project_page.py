"""The main project workspace: overview, agents, code and assets."""

from __future__ import annotations

import os
import re
import subprocess
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
from reasonable.core.i18n import t
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
from .scene_editor import SceneEditorPage
from .convert_dialog import ConvertDialog
from .export_dialog import ExportDialog
from .external import ExternalAgentPanel
from .history_dialog import HistoryDialog
from .project_settings import ProjectSettingsDialog
from .settings_dialog import SettingsDialog
from .widgets import Badge, Card, ElidedLabel, Separator, StatBox, muted, title_label

STATUS_TONES = {
    "running": "gold",
    "done": "teal",
    "error": "gold",
    "idle": "default",
}


def _status_label(status: str) -> str:
    """Localized status badge text ('running' → РАБОТАЕТ/RUNNING)."""
    text = t(f"projectpage.status_{status}")
    return text if not text.startswith("projectpage.") else status.upper()


def _tl(key: str, fallback: str, **values) -> str:
    """t() with a Russian-era fallback for dynamically built keys."""
    text = t(key, **values) if values else t(key)
    return fallback if text == key or not text else text


def project_icon_pixmap(path: Path | None, size: int = 52, name: str = "") -> QPixmap:
    pixmap = QPixmap(str(path)) if path and path.exists() else QPixmap()
    if pixmap.isNull():
        result = QPixmap(size, size)
        result.fill(Qt.GlobalColor.transparent)
        painter = QPainter(result)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#2E3137"))
        painter.drawRoundedRect(0, 0, size, size, 4, 4)
        letter = (name or "R").strip()[:1].upper() or "R"
        font = theme.ui_font(10, 700)
        font.setPixelSize(max(11, int(size * 0.52)))
        painter.setFont(font)
        painter.setPen(QColor("#D97757"))
        painter.drawText(result.rect(), Qt.AlignmentFlag.AlignCenter, letter)
        painter.end()
        return result
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


def _kill_process_tree(process: QProcess) -> None:
    """Stop the project and anything it spawned (launchers, Python workers)."""
    try:
        pid = int(process.processId() or 0)
    except (TypeError, ValueError):
        pid = 0
    if os.name == "nt" and pid:
        try:
            # Fire and forget: waiting for taskkill used to freeze the editor
            # for several seconds while the process tree shut down.
            subprocess.Popen(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            pass
    try:
        process.kill()
    except RuntimeError:
        pass


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
        self._stop_requested = False

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
        content_layout.setContentsMargins(14, 14, 14, 14)
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

        # The scene editor is a workspace of its own and is opened from the
        # sidebar button under the regular sections. It lives at the end of the
        # stack so section indexes stay stable.
        self.scene_page = SceneEditorPage(project, self)
        self.scene_page.status_message.connect(self.status_message)
        self.scene_page.run_requested.connect(self.run_project)
        self.stack.addWidget(self.scene_page)

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
            t("projectpage.run_result_idle_title"),
            t("projectpage.run_result_idle_detail"),
        )
        self._refresh_history_card(force=True)

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------
    def _build_header(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("topbar")
        frame.setFixedHeight(56)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(10, 8, 12, 8)
        layout.setSpacing(8)

        back = QPushButton()
        back.setObjectName("ghost")
        back.setFixedSize(28, 28)
        back.setIcon(theme.icon("back", 16))
        back.setToolTip(t("projectpage.back_tooltip"))
        back.clicked.connect(self._back)
        layout.addWidget(back)

        self.project_icon = QLabel()
        self.project_icon.setFixedSize(30, 30)
        self.project_icon.setPixmap(project_icon_pixmap(self.project.icon_path, 30, self.project.name))
        layout.addWidget(self.project_icon)

        titles = QVBoxLayout()
        titles.setSpacing(0)
        top = QHBoxLayout()
        top.setSpacing(6)
        self.name_label = QLabel(_shorten(self.project.name, 32))
        self.name_label.setObjectName("title")
        self.name_label.setFont(theme.ui_font(10, 600))
        self.name_label.setMinimumWidth(100)
        self.name_label.setMaximumWidth(360)
        top.addWidget(self.name_label)
        self.type_badge = Badge(
            {
                "game": t("projectpage.badge_game"),
                "app": t("projectpage.badge_app"),
                "site": t("projectpage.badge_site"),
                "other": t("projectpage.badge_other"),
            }.get(self.project.project_type, t("projectpage.badge_app")),
            "default",
        )
        top.addWidget(self.type_badge)
        self.mode_badge = Badge(t("projectpage.badge_mode_builtin") if self.project.mode == "builtin" else t("projectpage.badge_mode_external"), "default")
        top.addWidget(self.mode_badge)
        top.addStretch(1)
        titles.addLayout(top)
        self.goal_label_header = ElidedLabel(self.project.goal or t("projectpage.goal_missing"))
        self.goal_label_header.setObjectName("dim")
        self.goal_label_header.setFont(theme.ui_font(8))
        self.goal_label_header.setFixedHeight(self.goal_label_header.fontMetrics().height() + 2)
        titles.addWidget(self.goal_label_header)
        layout.addLayout(titles, 1)

        self.header_model = QLabel("")
        self.header_model.setObjectName("dim")
        self.header_model.setFont(theme.ui_font(8))
        self.header_model.setMaximumWidth(250)
        self.header_model.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.header_model)

        self.header_status = Badge(t("projectpage.status_idle"), "default")
        layout.addWidget(self.header_status)

        export = QPushButton(t("projectpage.export_btn"))
        export.setObjectName("ghost")
        export.setIcon(theme.icon("export", 15))
        export.setIconSize(QSize(15, 15))
        export.setToolTip(t("projectpage.export_tooltip"))
        export.clicked.connect(self._open_export)
        layout.addWidget(export)

        self.run_button = QPushButton(t("projectpage.run_btn"))
        self.run_button.setObjectName("primary")
        self.run_button.setIcon(theme.icon("play", 14, "#1B110D"))
        self.run_button.setIconSize(QSize(14, 14))
        self.run_button.setMinimumHeight(28)
        self.run_button.setMinimumWidth(108)
        self.run_button.clicked.connect(self._run_clicked)
        layout.addWidget(self.run_button)
        return frame

    # ------------------------------------------------------------------
    # Sidebar
    # ------------------------------------------------------------------
    def _build_sidebar(self) -> QWidget:
        frame = QWidget()
        frame.setObjectName("sidebar")
        frame.setFixedWidth(192)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 10, 8, 10)
        layout.setSpacing(1)

        label = QLabel(t("projectpage.sections_label"))
        label.setObjectName("dim")
        label.setFont(theme.section_font())
        layout.addWidget(label)
        layout.addSpacing(3)

        self.nav_buttons: list[QPushButton] = []
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        nav_icons = ("grid", "sparkles", "code", "image")
        for index, (text, icon_name) in enumerate(
            zip(
                (
                    t("projectpage.nav_overview"),
                    t("projectpage.nav_agent"),
                    t("projectpage.nav_code"),
                    t("projectpage.nav_assets"),
                ),
                nav_icons,
            )
        ):
            button = QPushButton(text)
            button.setObjectName("nav")
            button.setCheckable(True)
            button.setIcon(theme.icon(icon_name, 14))
            button.setIconSize(QSize(14, 14))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda checked=False, i=index: self._show_page(i))
            self.nav_group.addButton(button)
            self.nav_buttons.append(button)
            layout.addWidget(button)
        self.nav_buttons[0].setChecked(True)

        # Scene editor: a separate workspace, so it is not part of the four
        # section buttons above (their order is part of the editor contract).
        self.scene_button = QPushButton(t("projectpage.nav_scene"))
        self.scene_button.setObjectName("nav")
        self.scene_button.setCheckable(True)
        self.scene_button.setIcon(theme.icon("layers", 14))
        self.scene_button.setIconSize(QSize(14, 14))
        self.scene_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.scene_button.clicked.connect(self._show_scene)
        self.nav_group.addButton(self.scene_button)
        layout.addWidget(self.scene_button)
        layout.addSpacing(14)

        label = QLabel(t("projectpage.project_label"))
        label.setObjectName("dim")
        label.setFont(theme.section_font())
        layout.addWidget(label)
        self.side_meta = muted("", size=8)
        self.side_meta.setWordWrap(True)
        layout.addWidget(self.side_meta)
        layout.addSpacing(4)

        for text, icon_name, slot, tooltip in (
            (t("projectpage.project_settings_btn"), "settings", self._open_project_settings, ""),
            (t("projectpage.history_btn"), "history", self.open_history, t("projectpage.history_tooltip")),
            (t("projectpage.open_folder_btn"), "folder", self._open_folder, ""),
            (t("projectpage.convert_btn"), "import", self._open_convert, t("projectpage.convert_tooltip")),
        ):
            button = QPushButton(text)
            button.setObjectName("ghost")
            button.setIcon(theme.icon(icon_name, 14))
            button.setIconSize(QSize(14, 14))
            button.setStyleSheet("text-align: left; padding: 4px 7px;")
            if tooltip:
                button.setToolTip(tooltip)
            button.clicked.connect(slot)
            if icon_name == "import":
                self.convert_button = button
            elif icon_name == "history":
                self.history_sidebar = button
            layout.addWidget(button)

        delete = QPushButton(t("projectpage.delete_btn"))
        delete.setObjectName("danger")
        delete.setIcon(theme.icon("trash", 14, "#C47F86"))
        delete.setIconSize(QSize(14, 14))
        delete.setStyleSheet("text-align: left; padding: 4px 7px;")
        delete.setToolTip(t("projectpage.delete_tooltip"))
        delete.clicked.connect(self.delete_requested)
        layout.addWidget(delete)
        layout.addStretch(1)

        ai = Card(soft=True, padding=9)
        ai.layout().setSpacing(6)
        ai.layout().addWidget(title_label(t("projectpage.ai_project_title"), 9))
        self.side_ai = muted("", size=8)
        self.side_ai.setWordWrap(True)
        ai.layout().addWidget(self.side_ai)
        guide = QPushButton(t("projectpage.guide_btn"))
        guide.setObjectName("teal")
        guide.setStyleSheet("padding: 4px 8px;")
        guide.clicked.connect(self._open_guide)
        ai.layout().addWidget(guide)
        layout.addWidget(ai)

        version = QLabel(f"Reasonable Engine · {self.project.manifest.get('engine_version') or ''}")
        version.setObjectName("dim")
        version.setFont(theme.ui_font(7))
        layout.addWidget(version)
        return frame

    # ------------------------------------------------------------------
    # Overview
    # ------------------------------------------------------------------
    def _build_run_result_card(self) -> Card:
        card = Card(padding=12)
        top = QHBoxLayout()
        top.setSpacing(8)
        label = QLabel(t("projectpage.run_result_label"))
        label.setObjectName("title")
        label.setFont(theme.ui_font(10, 600))
        top.addWidget(label)
        self.run_result_badge = Badge(t("projectpage.badge_not_run"), "default")
        top.addWidget(self.run_result_badge)
        top.addStretch(1)
        self.run_result_when = muted("", size=8)
        top.addWidget(self.run_result_when)
        card.layout().addLayout(top)

        self.run_result_title = QLabel(t("projectpage.run_result_idle_title"))
        self.run_result_title.setFont(theme.ui_font(9, 600))
        self.run_result_title.setStyleSheet("color: #D7DAE0;")
        card.layout().addWidget(self.run_result_title)
        self.run_result_detail = muted(
            t("projectpage.run_result_idle_detail"),
            size=9,
        )
        self.run_result_detail.setWordWrap(True)
        card.layout().addWidget(self.run_result_detail)
        self.run_result_error = QLabel("")
        self.run_result_error.setWordWrap(True)
        self.run_result_error.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.run_result_error.setFont(theme.ui_font(8))
        self.run_result_error.setStyleSheet(
            "background: #2A1E20; color: #D7B0B4; border: 1px solid #4A3034; "
            "border-radius: 3px; padding: 6px;"
        )
        self.run_result_error.hide()
        card.layout().addWidget(self.run_result_error)

        actions = QHBoxLayout()
        actions.setSpacing(7)
        self.run_again_button = QPushButton(t("projectpage.run_again_btn"))
        self.run_again_button.setObjectName("primary")
        self.run_again_button.setIcon(theme.icon("play", 13, "#1B110D"))
        self.run_again_button.clicked.connect(self.run_project)
        actions.addWidget(self.run_again_button)
        self.fix_ai_button = QPushButton(t("projectpage.fix_ai_btn"))
        self.fix_ai_button.setObjectName("teal")
        self.fix_ai_button.setIcon(theme.icon("sparkles", 14))
        self.fix_ai_button.setToolTip(t("projectpage.fix_ai_tooltip"))
        self.fix_ai_button.clicked.connect(self._fix_failed_run_with_ai)
        actions.addWidget(self.fix_ai_button)
        self.rollback_button = QPushButton(t("projectpage.rollback_btn"))
        self.rollback_button.setObjectName("ghost")
        self.rollback_button.setIcon(theme.icon("undo", 14))
        self.rollback_button.setToolTip(t("projectpage.rollback_tooltip"))
        self.rollback_button.clicked.connect(self._rollback_last_run)
        actions.addWidget(self.rollback_button)
        actions.addStretch(1)
        self.run_history_button = QPushButton(t("projectpage.run_history_btn"))
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
            "success": t("projectpage.badge_success"),
            "failure": t("projectpage.badge_failure"),
            "running": t("projectpage.badge_running"),
            "idle": t("projectpage.badge_not_run"),
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
        running = state == "running"
        self.run_again_button.setText(
            t("projectpage.stop_btn") if running else t("projectpage.run_again_btn")
        )
        self.run_again_button.setIcon(
            theme.icon("stop" if running else "play", 13, "#C47F86" if running else "#1B110D")
        )
        self.run_again_button.setObjectName("danger" if running else "primary")
        self.run_again_button.style().unpolish(self.run_again_button)
        self.run_again_button.style().polish(self.run_again_button)
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
        layout.setContentsMargins(0, 0, 8, 4)
        layout.setSpacing(10)
        scroll.setWidget(host)

        self.run_result_card = self._build_run_result_card()
        layout.addWidget(self.run_result_card)

        hero = Card(padding=14)
        top = QHBoxLayout()
        title = QLabel(t("projectpage.progress_title"))
        title.setObjectName("title")
        title.setFont(theme.ui_font(10, 600))
        top.addWidget(title)
        top.addStretch(1)
        self.overview_status = Badge(t("projectpage.status_idle"), "default")
        top.addWidget(self.overview_status)
        hero.layout().addLayout(top)

        progress_row = QHBoxLayout()
        progress_row.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(3)
        self.percent_label = QLabel("0%")
        self.percent_label.setFont(theme.display_font(22, 700))
        self.percent_label.setStyleSheet("color: #F0F2F5;")
        left.addWidget(self.percent_label)
        self.stage_label = QLabel(t("progress.idle_stage"))
        self.stage_label.setFont(theme.ui_font(9, 600))
        self.stage_label.setStyleSheet("color: #B7BDC6;")
        left.addWidget(self.stage_label)
        self.message_label = muted("", size=9)
        self.message_label.setWordWrap(True)
        left.addWidget(self.message_label)
        progress_row.addLayout(left, 3)

        stats = QHBoxLayout()
        stats.setSpacing(8)
        self.tasks_stat = StatBox(t("projectpage.stat_tasks"), "0/0", t("projectpage.stat_tasks_hint"))
        self.files_stat = StatBox(t("projectpage.stat_files"), "0", t("projectpage.stat_files_hint"))
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
        self.hero_agent = QPushButton(t("projectpage.open_agent_btn"))
        self.hero_agent.setObjectName("primary")
        self.hero_agent.clicked.connect(self._open_agent)
        action_row.addWidget(self.hero_agent)
        code_button = QPushButton(t("projectpage.edit_code_btn"))
        code_button.clicked.connect(lambda: self._show_page(2))
        action_row.addWidget(code_button)
        sprite_button = QPushButton(t("projectpage.sprites_btn"))
        sprite_button.clicked.connect(lambda: self._show_page(3))
        action_row.addWidget(sprite_button)
        scene_button = QPushButton(t("projectpage.scene_btn"))
        scene_button.setToolTip(t("projectpage.scene_btn_tip"))
        scene_button.clicked.connect(self._show_scene)
        action_row.addWidget(scene_button)
        action_row.addStretch(1)
        self.last_activity_label = muted("", size=9)
        action_row.addWidget(self.last_activity_label)
        hero.layout().addLayout(action_row)
        layout.addWidget(hero)

        middle = QHBoxLayout()
        middle.setSpacing(13)
        tasks_card = Card()
        task_header = QHBoxLayout()
        task_header.addWidget(title_label(t("projectpage.plan_title"), 12))
        task_header.addStretch(1)
        tasks_card.layout().addLayout(task_header)
        self.tasks_card_hint = muted(t("projectpage.plan_hint"), size=8)
        tasks_card.layout().addWidget(self.tasks_card_hint)
        self.task_host = QVBoxLayout()
        self.task_host.setSpacing(5)
        tasks_card.layout().addLayout(self.task_host)
        tasks_card.layout().addStretch(1)
        middle.addWidget(tasks_card, 3)

        events_card = Card()
        events_header = QHBoxLayout()
        events_header.addWidget(title_label(t("projectpage.events_title"), 12))
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
        goal_top.addWidget(title_label(t("projectpage.goal_notes_title"), 11))
        goal_top.addStretch(1)
        edit_goal = QPushButton(t("projectpage.edit_btn"))
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
        files_header.addWidget(title_label(t("projectpage.recent_files_title"), 11))
        files_header.addStretch(1)
        refresh_files = QPushButton(t("projectpage.refresh_btn"))
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
        history_header.addWidget(title_label(t("projectpage.history_title"), 11))
        history_header.addStretch(1)
        self.history_count = Badge("0", "default")
        history_header.addWidget(self.history_count)
        history_card.layout().addLayout(history_header)
        self.history_latest = muted(t("projectpage.history_empty_initial"), size=9)
        self.history_latest.setWordWrap(True)
        history_card.layout().addWidget(self.history_latest)
        history_actions = QHBoxLayout()
        history_actions.setSpacing(7)
        history_open = QPushButton(t("projectpage.open_history_btn"))
        history_open.setObjectName("teal")
        history_open.clicked.connect(self.open_history)
        history_actions.addWidget(history_open)
        history_save = QPushButton(t("projectpage.snapshot_now_btn"))
        history_save.setObjectName("ghost")
        history_save.setToolTip(t("projectpage.snapshot_now_tooltip"))
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
        self.console_title = QLabel(t("projectpage.console_title"))
        self.console_title.setFont(theme.ui_font(9, 700))
        top.addWidget(self.console_title)
        top.addStretch(1)
        self.console_stop = QPushButton(t("projectpage.stop_btn"))
        self.console_stop.setObjectName("danger")
        self.console_stop.clicked.connect(self.stop_project)
        top.addWidget(self.console_stop)
        close = QPushButton("×")
        close.setObjectName("ghost")
        close.setFixedSize(24, 24)
        close.setToolTip(t("projectpage.hide_console_tooltip"))
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

    def _show_scene(self) -> None:
        self.stack.setCurrentWidget(self.scene_page)
        self.scene_button.setChecked(True)
        self.scene_page.viewport.setFocus()

    def _back(self) -> None:
        if self.process is not None and self.process.state() != QProcess.ProcessState.NotRunning:
            answer = QMessageBox.question(
                self,
                t("dialog.project_running_title"),
                t("projectpage.back_running_text"),
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
            QMessageBox.information(self, t("projectpage.guide_missing_title"), t("projectpage.guide_missing_text"))

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
            t("projectpage.restored_title"),
            t("projectpage.restored_detail"),
        )
        self.status_message.emit(t("projectpage.restored_status"))

    def _create_manual_snapshot(self) -> None:
        if not self._history_available():
            return
        if not self.code_page.save_all():
            return
        label, ok = QInputDialog.getText(
            self,
            t("projectpage.snapshot_dialog_title"),
            t("projectpage.snapshot_dialog_label"),
        )
        if not ok:
            return
        try:
            snapshot = create_snapshot(
                self.project,
                label=label.strip() or t("projectpage.manual_snapshot_label"),
                reason="manual",
            )
        except Exception as exc:
            QMessageBox.warning(self, t("projectpage.snapshot_failed_title"), str(exc))
            return
        self._refresh_history_card(force=True)
        self.status_message.emit(
            t("projectpage.snapshot_created_status", label=snapshot.get("label"))
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
            t("projectpage.restore_confirm_title"),
            t(
                "projectpage.restore_confirm_text",
                label=label,
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            result = restore_snapshot(self.project, snapshot_id, safety=True)
        except Exception as exc:
            QMessageBox.critical(self, t("projectpage.restore_failed_title"), str(exc))
            return
        self._history_restored(snapshot_id)
        self.status_message.emit(
            t(
                "projectpage.restored_files_status",
                label=label,
                restored=result.get("restored", 0),
                removed=result.get("removed", 0),
            )
        )

    def _rollback_last_run(self) -> None:
        try:
            snapshot = latest_snapshot(self.project, reason="agent") or latest_snapshot(self.project)
        except Exception:
            snapshot = None
        if not snapshot:
            QMessageBox.information(
                self,
                t("projectpage.no_snapshots_title"),
                t("projectpage.no_snapshots_text"),
            )
            return
        self._restore_snapshot(str(snapshot.get("id")))

    def _history_available(self) -> bool:
        """History writes project files, so never race a running built-in agent."""
        if self.chat is not None and self.chat.running:
            QMessageBox.information(
                self,
                t("progress.heartbeat"),
                t("projectpage.agent_running_text"),
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
            self.history_latest.setText(t("projectpage.history_empty"))
            return
        latest = snapshots[0]
        changed = len(latest.get("changed_files") or [])
        extra = t("history.changed_files", count=changed) if changed else ""
        self.history_latest.setText(
            f"{describe_snapshot(latest)}\n"
            + t("projectpage.history_files_line", time=human_time(latest.get("created_at")), count=latest.get("file_count", 0))
            + extra
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
        self.status_message.emit(t("projectpage.project_settings_saved"))

    def _open_global_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self, advanced=True)
        dialog.settings_saved.connect(self._ai_settings_saved)
        dialog.exec()

    def _ai_settings_saved(self) -> None:
        self.refresh_ai()
        self.status_message.emit(t("projectpage.ai_settings_saved"))

    def refresh_ai(self) -> None:
        self._update_header_model()
        self._update_side_ai()
        if self.chat is not None:
            self.chat.refresh_state()

    def _open_export(self) -> None:
        if not self.code_page.save_all():
            return
        dialog = ExportDialog(self.project, self)
        dialog.exported.connect(lambda result: self.status_message.emit(result.get("message", t("projectpage.export_done_default"))))
        dialog.exec()
        self._tick_refresh(force=True)

    def _open_convert(self) -> None:
        if not self.code_page.save_all():
            return
        dialog = ConvertDialog(self.project, self)
        dialog.converted.connect(self._converted_project)
        dialog.exec()

    def _converted_project(self, path: str) -> None:
        self.status_message.emit(t("projectpage.converted_status", path=path))
        self.converted.emit(path)

    def _update_header(self) -> None:
        from reasonable.core.project import UI_LEVEL_LABELS

        self.name_label.setText(_shorten(self.project.name, 32))
        self.goal_label_header.setText(self.project.goal or t("projectpage.goal_missing"))
        self.type_badge.setText(
            {
                "game": t("projectpage.badge_game"),
                "app": t("projectpage.badge_app"),
                "site": t("projectpage.badge_site"),
                "other": t("projectpage.badge_other"),
            }.get(self.project.project_type, t("projectpage.badge_app"))
        )
        self.mode_badge.setText(t("projectpage.badge_mode_builtin") if self.project.mode == "builtin" else t("projectpage.badge_mode_external"))
        self.project_icon.setPixmap(project_icon_pixmap(self.project.icon_path, 30, self.project.name))
        levels = ", ".join(_tl(f"project.ui_{level}", UI_LEVEL_LABELS.get(level, level)) for level in self.project.ui_levels)
        orientation = (
            t("projectpage.orientation_portrait")
            if self.project.manifest.get("orientation") == "portrait"
            else t("projectpage.orientation_landscape")
        )
        if self.project.project_type == "site":
            runtime_line = "Python · HTML/CSS/JS"
        elif self.project.project_type == "other":
            runtime_line = "Python"
        else:
            runtime_line = f"Python · {orientation}"
        self.side_meta.setText(
            f"{runtime_line}\n{t('projectpage.meta_ui_line', levels=levels)}"
            if self.project.project_type in {"game", "app"}
            else runtime_line
        )
        self._update_header_model()
        self._update_side_ai()
        self.hero_agent.setText(t("projectpage.open_agent_btn_full"))

    def _provider_label(self, config: dict) -> str:
        """Short provider name for the header and sidebar."""
        return short_provider_name(config.get("name") or config.get("id") or t("projectpage.fallback_ai"))

    def _model_text(self) -> str:
        config = self.settings.get_provider_config()
        name = self._provider_label(config)
        model = config.get("model") or t("projectpage.model_not_selected")
        return f"{name} · {model}"

    def _update_header_model(self) -> None:
        text = self._model_text()
        config = self.settings.get_provider_config()
        full = str(config.get("name") or config.get("id") or t("projectpage.fallback_ai"))
        self.header_model.setText(_shorten(text, 36))
        self.header_model.setToolTip(
            t(
                "projectpage.active_model_tooltip",
                full=full,
                model=config.get("model") or t("projectpage.model_not_selected"),
            )
        )

    def _update_side_ai(self) -> None:
        config = self.settings.get_provider_config()
        name = self._provider_label(config)
        model = config.get("model") or t("projectpage.model_not_selected")
        if self.project.mode == "external":
            access = t("projectpage.access_external")
        elif config.get("requires_key") and not config.get("api_key"):
            access = t("projectpage.access_need_key")
        elif config.get("api_key"):
            access = t("projectpage.access_key_saved")
        else:
            access = t("projectpage.access_no_key")
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
            return t("projectpage.hint_module_missing")
        if "importerror" in text:
            return t("projectpage.hint_import")
        if "syntaxerror" in text or "indentationerror" in text:
            return t("projectpage.hint_syntax")
        if "filenotfounderror" in text or "no such file" in text:
            return t("projectpage.hint_filenotfound")
        if "permissionerror" in text:
            return t("projectpage.hint_permission")
        if "pygame.error" in text:
            return t("projectpage.hint_pygame")
        if "typeerror" in text or "attributeerror" in text or "valueerror" in text or "keyerror" in text:
            return t("projectpage.hint_type")
        if "timeout" in text or "timed out" in text:
            return t("projectpage.hint_timeout")
        return t("projectpage.hint_generic")

    def _analyze_run(self, code: int, output: str) -> tuple[str, str, str, str]:
        """Turn a process result into a short, actionable UI message."""
        output = str(output or "").strip()
        if code == 0:
            return (
                "success",
                t("projectpage.success_title"),
                t("projectpage.success_detail"),
                "",
            )
        error_line = self._run_error_line(output)
        hint = self._run_error_hint(error_line)
        title = (
            t("projectpage.no_start_title")
            if "Traceback" in output
            else t("projectpage.exit_code_title", code=code)
        )
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
            t("projectpage.running_title"),
            t("projectpage.running_detail"),
            when=datetime.now().strftime("%H:%M"),
        )

    def _fix_failed_run_with_ai(self) -> None:
        if self.chat is None:
            QMessageBox.information(
                self,
                t("settings.external_title"),
                t("projectpage.external_agent_text"),
            )
            return
        error = (
            self._last_run_error
            or self.run_result_error.text()
            or t("projectpage.default_error")
        ).strip()
        prompt = t("projectpage.fix_prompt", error=error[:3000])
        self.chat.prefill_task(prompt)
        self.open_agent_page(focus=True)
        self.status_message.emit(t("projectpage.fix_prepared_status"))

    def run_project(self) -> None:
        if self.process is not None and self.process.state() != QProcess.ProcessState.NotRunning:
            self.status_message.emit(t("projectpage.already_running"))
            return
        if not self.code_page.save_all():
            return
        self.scene_page.flush()
        if not self.project.entry.exists():
            QMessageBox.warning(self, t("projectpage.no_entry_title"), t("projectpage.no_entry_text", name=self.project.entry.name))
            return
        env = QProcessEnvironment()
        for key, value in self.project.run_env().items():
            env.insert(key, value)
        env.insert("PYTHONUNBUFFERED", "1")
        self._process_output = ""
        self._last_run_code = None
        self._last_run_error = ""
        self._stop_requested = False
        self.console.clear()
        self.console_frame.show()
        self.console_title.setText(t("projectpage.console_title_splash"))
        self.console_stop.setEnabled(True)
        self.process = QProcess(self)
        self.process.setProcessEnvironment(env)
        self.process.setWorkingDirectory(str(self.project.root))
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read_process_output)
        self.process.finished.connect(self._process_finished)
        self.process.errorOccurred.connect(self._process_error)
        command = self.project.run_command(splash_wrapper=True)
        self.process.start(command[0], command[1:])
        if not self.process.waitForStarted(5000):
            self._append_console(t("projectpage.start_failed_console"))
            self._set_run_result(
                "failure",
                t("projectpage.start_failed_title"),
                t("projectpage.start_failed_detail"),
                t("projectpage.start_failed_error"),
                when=datetime.now().strftime("%H:%M"),
            )
            return
        self._append_console(t("projectpage.console_project", name=self.project.name, folder=self.project.root))
        self._update_run_button(True)
        self._set_running_result()
        self.status_message.emit(t("projectpage.run_started_status"))
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
        if self._stop_requested:
            self._stop_requested = False
            self.process = None
            self._apply_stopped_state()
            return
        self._append_console(t("projectpage.exit_console", code=code))
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
        self._update_run_button(False)
        self.console_stop.setEnabled(False)
        self.console_title.setText(
            t("projectpage.console_finished") if code == 0 else t("projectpage.console_finished_error", code=code)
        )
        try:
            record_event(
                self.project.root,
                "run",
                t("projectpage.event_success")
                if code == 0
                else t("projectpage.event_failed", code=code),
                {"returncode": int(code), "error": self._run_error_line(self._process_output)},
            )
        except Exception:
            pass
        self.status_message.emit(
            t("projectpage.finished_status") if code == 0 else t("projectpage.finished_status_code", code=code)
        )
        self._tick_refresh(force=True)

    def _process_error(self, error) -> None:
        if self._stop_requested:
            return
        self._append_console(t("projectpage.process_error_console", error=error))
        self._last_run_error = str(error)
        if self._last_run_code is None:
            self._set_run_result(
                "failure",
                t("projectpage.process_error_title"),
                t("projectpage.process_error_detail"),
                str(error),
                when=datetime.now().strftime("%H:%M"),
            )

    def _update_run_button(self, running: bool) -> None:
        self.run_button.setText(
            t("projectpage.stop_btn") if running else t("projectpage.run_btn")
        )
        self.run_button.setObjectName("danger" if running else "primary")
        self.run_button.setIcon(
            theme.icon(
                "stop" if running else "play",
                14,
                "#C47F86" if running else "#1B110D",
            )
        )
        self.run_button.style().unpolish(self.run_button)
        self.run_button.style().polish(self.run_button)

    def _apply_stopped_state(self) -> None:
        self._update_run_button(False)
        self.console_stop.setEnabled(False)
        self.console_title.setText(t("projectpage.console_stopped"))
        self._set_run_result(
            "idle",
            t("projectpage.stopped_title"),
            t("projectpage.stopped_detail"),
            when=datetime.now().strftime("%H:%M"),
        )
        self.status_message.emit(t("projectpage.stopped_status"))

    def stop_project(self) -> None:
        process = self.process
        if process is None or process.state() == QProcess.ProcessState.NotRunning:
            self.process = None
            self._apply_stopped_state()
            return
        self._stop_requested = True
        self._append_console(t("projectpage.stopping_console"))
        # QProcess.kill() only terminates the direct child. Launchers such as
        # Play.bat or a player executable may own the real game process, so on
        # Windows the whole tree is terminated by PID.
        _kill_process_tree(process)
        if not process.waitForFinished(800):
            process.terminate()
            if not process.waitForFinished(600):
                process.kill()
                process.waitForFinished(600)
        if self._stop_requested:
            self._stop_requested = False
            self.process = None
            self._apply_stopped_state()

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
        # Walking the project tree is the most expensive refresh step, so the
        # recent-files list is refreshed every ~6 s instead of every tick.
        if force or self._tick % 4 == 0:
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
        text, tone = _status_label(status), STATUS_TONES.get(status, "default")
        self.overview_status.setText(text)
        self.overview_status.set_tone(tone)
        self.header_status.setText(text)
        self.header_status.set_tone(tone)
        self.percent_label.setText(f"{percent}%")
        self.overview_progress.setValue(percent)
        stage = state.get("stage") or t("progress.idle_stage")
        self.stage_label.setText(stage)
        message = state.get("message") or ""
        self.message_label.setText(message)
        self.message_label.setVisible(bool(message))
        tasks = state.get("tasks") or []
        done = sum(1 for task in tasks if task.get("status") == "done")
        self.tasks_stat.set_value(f"{done}/{len(tasks)}", t("projectpage.stat_tasks_value"))
        self.last_activity_label.setText(t("projectpage.activity", time=human_time(state.get("last_event_at"))))
        if force or self._file_count == 0 or self._tick % 8 == 0:
            self._file_count = len(self.project.list_files(limit=2000))
        self.files_stat.set_value(str(self._file_count), t("projectpage.stat_files_value"))
        self.goal_label.setText(self.project.goal or t("projectpage.goal_missing_long"))
        notes = self.project.notes.strip()
        self.notes_label.setText(
            _shorten(notes, 420)
            if notes
            else t("projectpage.notes_empty")
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
            self.task_host.addWidget(muted(t("projectpage.plan_empty"), size=9))
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
            item.setToolTip(t("projectpage.files_tooltip"))
            self.recent_files.addItem(item)
        if not rows:
            self.recent_files.addItem(t("projectpage.files_empty"))

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
                    t("projectpage.agent_error_title"),
                    t("projectpage.agent_error_detail"),
                    self.chat.last_error or t("projectpage.agent_error_fallback"),
                    when=when,
                )
            elif outcome == "incomplete":
                self._set_run_result(
                    "idle",
                    t("projectpage.agent_incomplete_title"),
                    t("projectpage.agent_incomplete_detail"),
                    when=when,
                )
            else:
                self._set_run_result(
                    "idle",
                    t("projectpage.agent_done_title"),
                    t("projectpage.agent_done_detail"),
                    when=when,
                )
        self.status_message.emit(t("projectpage.agent_finished_status"))

    # ------------------------------------------------------------------
    def shutdown(self) -> None:
        self.timer.stop()
        self.scene_page.shutdown()
        if self.chat is not None:
            self.chat.shutdown()
        if self.external is not None:
            self.external.shutdown()
        self.stop_project()
