"""Built-in AI agent chat with live plan/progress."""

from __future__ import annotations

import json
from typing import Callable

from PySide6.QtCore import QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap, QPolygon, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from reasonable.ai.agent import AgentEvent
from reasonable.ai.prompts import build_improvement_prompt
from reasonable.ai.providers import config_status, short_provider_name
from reasonable.core import chatlog
from reasonable.core.agent_errors import AUTO_CONTINUE_KINDS
from reasonable.core.i18n import current_language, t
from reasonable.core.progress import derived_percent, read_state
from reasonable.core.settings import Settings
from reasonable.core.usage import add_usage, format_duration, format_tokens, load_usage

from . import theme
from .widgets import Avatar, Badge, Card, muted, title_label
from .workers import AgentWorker


class MessageBubble(QFrame):
    def __init__(self, role: str, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.role = role
        self.full_text = text
        self.expanded = False
        self.setObjectName("cardSoft")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        if role == "user":
            self.setStyleSheet(
                "QFrame { background: #1B1E24; border: 1px solid #2C323B;"
                "border-radius: 9px; }"
            )
        elif role == "assistant":
            self.setStyleSheet("QFrame { background: #171A20; border: 1px solid #262B33; border-radius: 9px; }")
        elif role == "error":
            self.setStyleSheet(
                "QFrame { background: #20191B; border: 1px solid #4A3034;"
                "border-radius: 9px; }"
            )
        elif role == "tool":
            self.setStyleSheet("QFrame { background: #14171C; border: 1px solid #242830; border-radius: 8px; }")
        else:
            self.setStyleSheet("QFrame { background: #171A20; border: 1px solid #262B33; border-radius: 9px; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(13, 10, 13, 11)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(7)
        if role == "user":
            avatar = Avatar(22)
            avatar.set_initials(t("chat.role_user"), "#A8AFB9")
            header.addWidget(avatar)
            name = QLabel(t("chat.role_user"))
            name.setFont(theme.ui_font(9, 600))
            name.setStyleSheet("color: #A8AFB9;")
        elif role == "assistant":
            avatar = Avatar(22)
            avatar.set_logo()
            header.addWidget(avatar)
            name = QLabel("Reasonable Agent")
            name.setFont(theme.ui_font(9, 600))
            name.setStyleSheet("color: #E7E9EC;")
        elif role == "tool":
            avatar = QLabel("T")
            avatar.setFixedWidth(18)
            avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
            avatar.setStyleSheet("color: #8B929C; font-weight: 600;")
            header.addWidget(avatar)
            name = QLabel(t("chat.role_tool"))
            name.setFont(theme.ui_font(8, 600))
            name.setStyleSheet("color: #8B929C;")
        else:
            role_key = "chat.role_error" if role == "error" else "chat.role_system"
            name = QLabel(t(role_key))
            name.setFont(theme.ui_font(9, 600))
            name.setStyleSheet("color: #C98A90;" if role == "error" else "color: #8B929C;")
        header.addWidget(name)
        header.addStretch(1)
        layout.addLayout(header)

        self.body = QLabel(text)
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.body.setFont(theme.ui_font(10))
        self.body.setStyleSheet("color: #D7DBE0; background: transparent; border: none;")
        layout.addWidget(self.body)

        self.more_button: QToolButton | None = None
        if role == "tool" and len(text) > 360:
            self.body.setText(text[:360] + "…")
            self.more_button = QToolButton()
            self.more_button.setText(t("chat.show_full"))
            self.more_button.setObjectName("ghost")
            self.more_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.more_button.clicked.connect(self._toggle)
            layout.addWidget(self.more_button, 0, Qt.AlignmentFlag.AlignLeft)

    def _toggle(self) -> None:
        self.expanded = not self.expanded
        if self.expanded:
            self.body.setText(self.full_text)
            if self.more_button:
                self.more_button.setText(t("chat.collapse"))
        else:
            self.body.setText(self.full_text[:360] + "…")
            if self.more_button:
                self.more_button.setText(t("chat.show_full"))


class AgentErrorBubble(MessageBubble):
    """An error bubble with a manual (and optional automatic) continue action."""

    continue_requested = Signal()
    auto_continue_changed = Signal(bool)

    def __init__(
        self,
        text: str,
        error_kind: str,
        auto_enabled: bool = False,
        *,
        analysis: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("error", text, parent)
        self.error_kind = error_kind
        self.analysis = bool(analysis)
        self.auto_check: QCheckBox | None = None
        self._hint: QLabel | None = None
        if error_kind not in AUTO_CONTINUE_KINDS:
            return

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.continue_button = QPushButton(t("chat.continue_button"))
        self.continue_button.setObjectName("primary")
        self.continue_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.continue_button.clicked.connect(lambda: self.continue_requested.emit())
        actions.addWidget(self.continue_button)

        self.auto_check = QCheckBox(t("chat.auto_continue_check"))
        self.auto_check.setChecked(bool(auto_enabled))
        self.auto_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self.auto_check.setToolTip(
            f"{t('chat.auto_continue_check_tip')}\n{t(f'errors.kind_{error_kind}')}"
        )
        self.auto_check.toggled.connect(self._auto_toggled)
        actions.addWidget(self.auto_check)
        actions.addStretch(1)
        self.layout().addLayout(actions)

        self._hint = muted("", size=8)
        self._hint.setStyleSheet("background: transparent; border: none; color: #9AA1AB;")
        self.layout().addWidget(self._hint)
        self._refresh_hint()

    def _auto_toggled(self, checked: bool) -> None:
        self._refresh_hint()
        self.auto_continue_changed.emit(bool(checked))

    def _refresh_hint(self) -> None:
        if self._hint is None or self.auto_check is None:
            return
        key = (
            "chat.auto_continue_hint_on"
            if self.auto_check.isChecked()
            else "chat.auto_continue_hint"
        )
        self._hint.setText(t(key))


_TOOL_LABEL_KEYS = {
    "list_files": "chat.tool_list_files",
    "read_file": "chat.tool_read_file",
    "write_file": "chat.tool_write_file",
    "edit_file": "chat.tool_edit_file",
    "delete_path": "chat.tool_delete_path",
    "search_text": "chat.tool_search_text",
    "run_command": "chat.tool_run_command",
    "run_project": "chat.tool_run_project",
    "validate_project": "chat.tool_validate_project",
    "generate_sprite": "chat.tool_generate_sprite",
    "draw_sprite": "chat.tool_draw_sprite",
    "generate_background": "chat.tool_generate_background",
    "inspect_image": "chat.tool_inspect_image",
    "set_plan": "chat.tool_set_plan",
    "update_task": "chat.tool_update_task",
    "report_progress": "chat.tool_report_progress",
    "get_progress": "chat.tool_get_progress",
    "finish": "chat.tool_finish",
}

_TASK_STATUS_KEYS = {
    "pending": "chat.task_status_pending",
    "in_progress": "chat.task_status_in_progress",
    "done": "chat.task_status_done",
    "skipped": "chat.task_status_skipped",
}

_FILE_TOOLS = {
    "list_files",
    "read_file",
    "write_file",
    "edit_file",
    "delete_path",
    "generate_sprite",
    "draw_sprite",
    "generate_background",
    "inspect_image",
}

_RESULT_LIMIT = 6000


def _tool_label(name: str) -> str:
    key = _TOOL_LABEL_KEYS.get(name)
    if key:
        return t(key)
    return name or t("chat.tool_unknown")


def _shorten(value: object, limit: int = 160) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def _chevron_icon(expanded: bool) -> QIcon:
    """Draw a small triangle so the control never depends on font glyphs."""
    pixmap = QPixmap(14, 14)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#8B929C"))
    if expanded:
        painter.drawPolygon(QPolygon([QPoint(2, 5), QPoint(12, 5), QPoint(7, 10)]))
    else:
        painter.drawPolygon(QPolygon([QPoint(5, 2), QPoint(5, 12), QPoint(10, 7)]))
    painter.end()
    return QIcon(pixmap)


def _tool_summary(name: str, arguments: dict | None) -> str:
    """One compact, human-readable line describing what the call does."""
    args = arguments or {}
    if name in _FILE_TOOLS:
        return _shorten(args.get("path"), 180)
    if name == "search_text":
        query = _shorten(args.get("query"), 100)
        return f"«{query}»" if query else ""
    if name == "run_command":
        return _shorten(args.get("command"), 180)
    if name == "set_plan":
        tasks = args.get("tasks") or []
        count = len(tasks) if isinstance(tasks, list) else 0
        return t("chat.tool_task_count", count=count)
    if name == "update_task":
        task = _shorten(args.get("task"), 70)
        status_key = _TASK_STATUS_KEYS.get(str(args.get("status") or ""))
        status = t(status_key) if status_key else ""
        return " · ".join(part for part in (task, status) if part)
    if name == "report_progress":
        percent = args.get("percent")
        try:
            percent_text = f"{float(percent):g}%"
        except (TypeError, ValueError):
            percent_text = _shorten(percent, 20)
        stage = _shorten(args.get("stage"), 80)
        return " · ".join(part for part in (percent_text, stage) if part)
    if name == "finish":
        return _shorten(args.get("message"), 160)
    return ""


def _clip_result(text: str) -> str:
    text = (text or "").strip()
    if len(text) <= _RESULT_LIMIT:
        return text
    return text[:_RESULT_LIMIT].rstrip() + "\n" + t("chat.tool_truncated")


def _format_matches(matches: list) -> str:
    rows: list[str] = []
    for item in matches:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "")
        line = item.get("line")
        snippet = _shorten(item.get("text"), 240)
        location = f"{path}:{line}" if line else path
        rows.append(f"{location}  {snippet}".rstrip())
    return "\n".join(rows) if rows else t("chat.tool_no_matches")


def _format_issues(issues: list) -> str:
    rows: list[str] = []
    for item in issues:
        if not isinstance(item, dict):
            continue
        level = str(item.get("level") or "")
        message = str(item.get("message") or "").strip()
        path = str(item.get("path") or "")
        marker = "×" if level == "error" else "·"
        row = f"{marker} {message}".rstrip()
        if path:
            row += f"  ({path})"
        rows.append(row)
    return "\n".join(rows) if rows else t("chat.tool_no_issues")


def _format_tool_result(raw: str) -> str:
    """Turn the tool's JSON payload into readable (not raw) output."""
    text = (raw or "").strip()
    if not text:
        return t("chat.tool_no_output")
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return _clip_result(text)
    if not isinstance(data, dict):
        return _clip_result(json.dumps(data, ensure_ascii=False, indent=2))
    if data.get("ok") is False:
        return _clip_result(str(data.get("error") or text))

    parts: list[str] = []
    message = data.get("message")
    if isinstance(message, str) and message.strip():
        parts.append(message.strip())
    output = data.get("output")
    if isinstance(output, str) and output.strip():
        parts.append(output.rstrip())
    content = data.get("content")
    if isinstance(content, str) and content.strip():
        parts.append(content.rstrip())
    entries = data.get("entries")
    if isinstance(entries, list):
        parts.append("\n".join(str(item) for item in entries) if entries else t("chat.tool_no_output"))
    matches = data.get("matches")
    if isinstance(matches, list):
        parts.append(_format_matches(matches))
    issues = data.get("issues")
    if isinstance(issues, list):
        parts.append(_format_issues(issues))

    if not parts:
        ignored = {"ok", "readiness"}
        for key, value in data.items():
            if key in ignored or value is None:
                continue
            if isinstance(value, (dict, list)):
                parts.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
            else:
                parts.append(f"{key}: {value}")
    return _clip_result("\n\n".join(part for part in parts if str(part).strip()))


class ToolCallCard(QFrame):
    """One compact, collapsible tool call in the agent conversation."""

    def __init__(self, name: str, arguments: dict | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.name = name
        self.arguments = dict(arguments or {})
        self.full_text = ""
        self.success = True
        self._status = "•"
        self._summary = _tool_summary(name, self.arguments)
        self.setObjectName("toolCall")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.setStyleSheet(
            "QFrame#toolCall { background: #12151A; border: 1px solid #20242B; border-radius: 6px; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.header = QPushButton()
        self.header.setObjectName("toolCallHeader")
        self.header.setCheckable(True)
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.setFont(theme.ui_font(9, 600))
        self.header.setIcon(_chevron_icon(False))
        self.header.setIconSize(QSize(14, 14))
        self.header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.header.setStyleSheet(
            "QPushButton#toolCallHeader { background: transparent; border: none;"
            " text-align: left; padding: 3px 8px; color: #A5ACB6; }"
            "QPushButton#toolCallHeader:hover { background: #1B1F25; border-radius: 5px;"
            " color: #E7E9EC; }"
        )
        self.header.toggled.connect(self._toggle)
        layout.addWidget(self.header)

        self.details = QLabel()
        self.details.setObjectName("toolCallDetails")
        self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        self.details.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.details.setFont(theme.ui_font(9))
        self.details.setStyleSheet(
            "QLabel#toolCallDetails { background: transparent; border: none;"
            " color: #B8BEC7; padding: 0 10px 7px 24px; }"
        )
        self.details.hide()
        layout.addWidget(self.details)

        self._refresh_header()

    def finish(self, result: str, success: bool) -> None:
        self.success = bool(success)
        self._status = "✓" if self.success else "×"
        self.full_text = _format_tool_result(result)
        if self.header.isChecked():
            self.details.setText(self.full_text)
        self._refresh_header()

    def stop(self) -> None:
        if self._status != "•":
            return
        self._status = "–"
        self.full_text = t("chat.tool_stopped")
        if self.header.isChecked():
            self.details.setText(self.full_text)
        self._refresh_header()

    def _toggle(self, checked: bool) -> None:
        if checked:
            self.details.setText(self.full_text or t("chat.tool_running"))
            self.details.show()
        else:
            self.details.hide()
        self._refresh_header()

    def _refresh_header(self) -> None:
        expanded = self.header.isChecked()
        self.header.setIcon(_chevron_icon(expanded))
        text = f"{self._status}  {_tool_label(self.name)}"
        if self._summary:
            text += f"  ·  {self._summary}"
        self.header.setText(text)
        tooltip = _tool_label(self.name)
        if self._summary:
            tooltip += f" · {self._summary}"
        tooltip += f"\n{t('chat.tool_toggle_hint')}"
        self.header.setToolTip(tooltip)


class ToolCallGroup(QFrame):
    """A run of consecutive tool calls that can also be collapsed together."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("toolCallGroup")
        self.setStyleSheet("QFrame#toolCallGroup { background: transparent; border: none; }")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.header = QPushButton()
        self.header.setObjectName("toolCallGroupHeader")
        self.header.setCheckable(True)
        # Tool calls are noise most of the time. Start every group collapsed
        # and let the user expand it when they need the details.
        self.header.setChecked(False)
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.setFont(theme.ui_font(8, 600))
        self.header.setIcon(_chevron_icon(False))
        self.header.setIconSize(QSize(12, 12))
        self.header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.header.setStyleSheet(
            "QPushButton#toolCallGroupHeader { background: transparent; border: none;"
            " text-align: left; padding: 1px 4px; color: #7D848E; }"
            "QPushButton#toolCallGroupHeader:hover { color: #E7E9EC; }"
        )
        self.header.setToolTip(t("chat.tool_group_hint"))
        self.header.toggled.connect(self._toggle)
        layout.addWidget(self.header)

        self.body = QWidget()
        self.rows = QVBoxLayout(self.body)
        self.rows.setContentsMargins(10, 0, 0, 0)
        self.rows.setSpacing(2)
        self.body.setVisible(False)
        layout.addWidget(self.body)
        self.count = 0
        self._refresh_header()

    def add_call(self, card: ToolCallCard) -> None:
        self.rows.addWidget(card)
        self.count += 1
        self._refresh_header()

    def _toggle(self, checked: bool) -> None:
        self.body.setVisible(checked)
        self._refresh_header()

    def _refresh_header(self) -> None:
        self.header.setIcon(_chevron_icon(self.header.isChecked()))
        self.header.setText(f"{t('chat.tool_group')} · {self.count}")


class ChangesCard(Card):
    """Audit trail shown after an agent run: what changed and how to undo it."""

    file_requested = Signal(str)
    restore_requested = Signal(str)
    history_requested = Signal()

    ACTION_ICONS = {
        "create": "＋",
        "edit": "✎",
        "delete": "−",
        "generate": "✦",
    }
    ACTION_KEYS = {
        "create": "chat.action_create",
        "edit": "chat.action_edit",
        "delete": "chat.action_delete",
        "generate": "chat.action_generate",
    }

    def __init__(self, files: list[dict], snapshot: dict | None, outcome: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent, soft=True, padding=13)
        self.files = list(files or [])
        self.snapshot = snapshot or {}
        self.outcome = outcome
        self.setObjectName("cardSoft")

        top = QHBoxLayout()
        top.setSpacing(8)
        heading = QLabel(t("chat.changes_heading"))
        heading.setFont(theme.ui_font(10, 700))
        heading.setStyleSheet("color: #E7E9EC; background: transparent; border: none;")
        top.addWidget(heading)
        top.addStretch(1)
        tone = "teal" if outcome == "done" else "gold"
        count = Badge(t("chat.file_count", count=len(self.files)), tone)
        top.addWidget(count)
        self.layout().addLayout(top)

        if not self.files:
            self.layout().addWidget(
                muted(t("chat.no_changes"), size=9)
            )
        else:
            rows = QVBoxLayout()
            rows.setContentsMargins(0, 0, 0, 0)
            rows.setSpacing(2)
            for item in self.files[:14]:
                path = str(item.get("path") or "")
                action = str(item.get("action") or "edit")
                icon = self.ACTION_ICONS.get(action, "·")
                label = t(self.ACTION_KEYS.get(action, "chat.action_edit"))
                button = QPushButton(f"{icon}  {path}")
                button.setObjectName("ghost")
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                button.setToolTip(f"{label}: {path}\n{t('chat.open_in_code')}")
                button.setStyleSheet(
                    "QPushButton { text-align: left; padding: 4px 6px; border-radius: 5px; }"
                    "QPushButton:hover { background: #20242B; }"
                )
                if action == "delete":
                    button.setEnabled(False)
                else:
                    button.clicked.connect(lambda checked=False, value=path: self.file_requested.emit(value))
                rows.addWidget(button)
            if len(self.files) > 14:
                rows.addWidget(muted(t("chat.more_files", count=len(self.files) - 14), size=8))
            self.layout().addLayout(rows)

        snapshot_id = str(self.snapshot.get("id") or "")
        if snapshot_id:
            note = muted(
                t(
                    "chat.snapshot_note",
                    label=self.snapshot.get("label") or t("history.snapshot"),
                ),
                size=8,
            )
            note.setWordWrap(True)
            self.layout().addWidget(note)

        actions = QHBoxLayout()
        actions.setSpacing(7)
        if snapshot_id:
            undo = QPushButton(t("chat.undo_button"))
            undo.setObjectName("danger")
            undo.setToolTip(t("chat.undo_tip"))
            undo.clicked.connect(lambda: self.restore_requested.emit(snapshot_id))
            actions.addWidget(undo)
        history = QPushButton(t("chat.history_button"))
        history.setObjectName("ghost")
        history.clicked.connect(self.history_requested)
        actions.addWidget(history)
        actions.addStretch(1)
        self.layout().addLayout(actions)


class ChatPanel(QWidget):
    finished = Signal()
    settings_requested = Signal()
    file_open_requested = Signal(str)
    restore_requested = Signal(str)
    history_requested = Signal()
    history_changed = Signal()

    def __init__(self, project, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self.settings = settings
        self.worker: AgentWorker | None = None
        self.running = False
        self._last_assistant = ""
        self._last_error_text = ""
        self._message_count = 0
        self._plan_signature: tuple | None = None
        self._current_snapshot: dict | None = None
        self._changes_card: ChangesCard | None = None
        self._tool_group: ToolCallGroup | None = None
        self._active_tool_card: ToolCallCard | None = None
        self._last_error_kind = "other"
        self._auto_continue_kind = ""
        self._auto_continue_attempts = 0
        self._auto_sending = False
        self._analysis_run = False
        self._run_chat_id: str | None = None
        self.usage = load_usage(self.project.root)
        # Set by ProjectPage so unsaved editor buffers reach disk before the
        # agent snapshot and tool calls see them.
        self.prepare_run: Callable[[], bool] | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self._build_header())
        layout.addWidget(self._build_stream(), 1)
        layout.addWidget(self._build_input())

        self._refresh_chat_list()
        self._update_usage_label()
        self.refresh_state()
        self._restore_history()

    # ------------------------------------------------------------------
    def _restore_history(self) -> None:
        """Show the conversation saved in the project across sessions.

        The agent itself stores every user task and its final answer in
        ``.reasonable/chat.json``; here we render the last messages as bubbles
        so the user (and the next session) sees the full story.
        """
        try:
            history = chatlog.load_chat(self.project.root)
        except Exception:
            return
        recent = [
            item
            for item in history
            if item.get("role") in ("user", "assistant", "system", "error")
            and not item.get("hidden")
        ]
        for item in recent[-40:]:
            role = str(item.get("role") or "assistant")
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            self._append(role, text)

    def _remember(
        self,
        role: str,
        text: str,
        *,
        chat_id: str | None = None,
        hidden: bool = False,
    ) -> None:
        """Persist a message exactly as the user sees it.

        The editor is the source of truth for the visible conversation: the
        user's task is stored the moment it is sent, every assistant reply is
        stored as it arrives and errors are stored too. The agent therefore
        runs with ``persist_messages=False`` in the editor, which prevents
        double writes and keeps the on-disk order identical to the screen.
        """
        if not str(text or "").strip():
            return
        try:
            chatlog.append_message(
                self.project.root,
                role,
                text,
                chat_id=chat_id or self._run_chat_id,
                hidden=hidden,
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _clear_stream(self) -> None:
        while self.stream.count():
            item = self.stream.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _reload_chat(self) -> None:
        """Show the active conversation from scratch."""
        self._clear_stream()
        self._changes_card = None
        self._message_count = 0
        self._last_assistant = ""
        self._last_error_text = ""
        self._last_error_kind = "other"
        self._auto_continue_kind = ""
        self._auto_continue_attempts = 0
        self._analysis_run = False
        self._run_chat_id = None
        self._tool_group = None
        self._active_tool_card = None
        self._show_intro()
        self._restore_history()
        self.refresh_state()

    def _refresh_chat_list(self) -> None:
        if not hasattr(self, "chat_combo"):
            return
        try:
            chats = chatlog.list_chats(self.project.root)
            active = chatlog.active_chat_id(self.project.root)
        except Exception:
            return
        self.chat_combo.blockSignals(True)
        self.chat_combo.clear()
        for index, chat in enumerate(chats):
            title = str(chat.get("title") or "").strip() or t("chat.untitled_chat")
            self.chat_combo.addItem(title, chat.get("id"))
            self.chat_combo.setItemData(index, title, Qt.ItemDataRole.ToolTipRole)
        active_index = self.chat_combo.findData(active)
        if active_index >= 0:
            self.chat_combo.setCurrentIndex(active_index)
        self.chat_combo.blockSignals(False)
        self._set_chat_controls_enabled(not self.running)

    def _set_chat_controls_enabled(self, enabled: bool) -> None:
        self.chat_combo.setEnabled(enabled)
        self.new_chat_button.setEnabled(enabled)
        self.delete_chat_button.setEnabled(enabled and self.chat_combo.count() > 1)
        self.improve_button.setEnabled(enabled)
        self.clear_button.setEnabled(enabled)

    def _chat_changed(self, index: int) -> None:
        if self.running:
            return
        chat_id = self.chat_combo.itemData(index)
        if not chat_id:
            return
        try:
            if str(chat_id) == chatlog.active_chat_id(self.project.root):
                return
            chatlog.set_active_chat(self.project.root, str(chat_id))
        except Exception:
            return
        self._reload_chat()

    def new_chat(self) -> None:
        if self.running:
            return
        try:
            chatlog.create_chat(self.project.root)
        except Exception:
            return
        self._refresh_chat_list()
        self._reload_chat()
        self.focus_input()

    def delete_chat(self) -> None:
        if self.running:
            return
        try:
            chats = chatlog.list_chats(self.project.root)
            if len(chats) <= 1:
                return
            active = chatlog.active_chat_id(self.project.root)
            title = next(
                (str(chat.get("title") or "").strip() for chat in chats if chat.get("id") == active),
                "",
            ) or t("chat.untitled_chat")
            answer = QMessageBox.question(
                self,
                t("chat.delete_chat_title"),
                t("chat.delete_chat_text", title=title),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            chatlog.delete_chat(self.project.root, active)
        except Exception:
            return
        self._refresh_chat_list()
        self._reload_chat()

    def improve_project(self) -> None:
        """Create a hidden review chat and start a read-only analysis run."""
        if self.running:
            return
        if not self._ready_to_run():
            return
        if self.prepare_run is not None and not self.prepare_run():
            return
        try:
            chat = chatlog.create_chat(
                self.project.root,
                title=t("chat.improve_chat_title"),
            )
        except Exception:
            return
        self._refresh_chat_list()
        self._reload_chat()
        prompt = build_improvement_prompt(self.project, current_language())
        self._start(
            prompt,
            chat_id=str(chat.get("id") or ""),
            hidden=True,
            analysis=True,
            reply_language=current_language(),
        )

    # ------------------------------------------------------------------
    def _build_header(self) -> QFrame:
        card = Card(padding=14)
        layout = QHBoxLayout()
        layout.setSpacing(9)
        avatar = Avatar(30)
        avatar.set_logo()
        layout.addWidget(avatar)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        title = QLabel(t("chat.title"))
        title.setObjectName("title")
        title.setFont(theme.ui_font(10, 600))
        titles.addWidget(title)
        config = self.settings.get_provider_config()
        provider_name = short_provider_name(config.get("name") or config.get("id") or t("chat.ai_fallback"))
        self.model_label = muted(
            f"{provider_name} · {config.get('model') or t('chat.model_none')}",
            size=8,
            wrap=False,
        )
        self.model_label.setMaximumWidth(380)
        self.model_label.setToolTip(
            f"{config.get('name') or config.get('id') or t('chat.ai_fallback')} · "
            f"{config.get('model') or t('chat.model_none')}"
        )
        titles.addWidget(self.model_label)
        self.usage_label = muted("", size=8)
        self.usage_label.hide()
        titles.addWidget(self.usage_label)
        layout.addLayout(titles)
        layout.addStretch(1)
        self.status_badge = Badge(t("chat.status_ready_badge"), "default")
        layout.addWidget(self.status_badge)
        self.stop_button = QPushButton(t("chat.stop_button"))
        self.stop_button.setObjectName("danger")
        self.stop_button.clicked.connect(self.stop_agent)
        self.stop_button.hide()
        layout.addWidget(self.stop_button)
        self.clear_button = QPushButton(t("chat.clear_button"))
        self.clear_button.setObjectName("ghost")
        self.clear_button.clicked.connect(self.clear_chat)
        layout.addWidget(self.clear_button)
        card.layout().addLayout(layout)

        chat_row = QHBoxLayout()
        chat_row.setSpacing(7)
        chat_row.addWidget(muted(t("chat.chat_label"), size=9))
        self.chat_combo = QComboBox()
        self.chat_combo.setObjectName("chatSelect")
        self.chat_combo.setMinimumWidth(220)
        self.chat_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.chat_combo.setToolTip(t("chat.chat_select_tip"))
        self.chat_combo.currentIndexChanged.connect(self._chat_changed)
        chat_row.addWidget(self.chat_combo, 1)

        self.new_chat_button = QPushButton()
        self.new_chat_button.setObjectName("ghost")
        self.new_chat_button.setFixedSize(28, 26)
        self.new_chat_button.setIcon(theme.icon("plus", 14))
        self.new_chat_button.setToolTip(t("chat.new_chat_tip"))
        self.new_chat_button.clicked.connect(self.new_chat)
        chat_row.addWidget(self.new_chat_button)

        self.delete_chat_button = QPushButton()
        self.delete_chat_button.setObjectName("ghost")
        self.delete_chat_button.setFixedSize(28, 26)
        self.delete_chat_button.setIcon(theme.icon("trash", 14))
        self.delete_chat_button.setToolTip(t("chat.delete_chat_tip"))
        self.delete_chat_button.clicked.connect(self.delete_chat)
        chat_row.addWidget(self.delete_chat_button)

        self.improve_button = QPushButton(t("chat.improve_button"))
        self.improve_button.setObjectName("teal")
        self.improve_button.setToolTip(t("chat.improve_tip"))
        self.improve_button.clicked.connect(self.improve_project)
        chat_row.addWidget(self.improve_button)
        card.layout().addLayout(chat_row)

        self.step_label = muted("", size=9)
        card.layout().addWidget(self.step_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setMaximumHeight(10)
        card.layout().addWidget(self.progress)
        return card

    def _build_stream(self) -> QWidget:
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.stream_host = QWidget()
        self.stream_host.setObjectName("root")
        self.stream = QVBoxLayout(self.stream_host)
        self.stream.setContentsMargins(4, 4, 10, 4)
        self.stream.setSpacing(9)
        self.scroll.setWidget(self.stream_host)
        self._show_intro()
        return self.scroll

    def _show_intro(self) -> None:
        intro = Card()
        top = QHBoxLayout()
        avatar = Avatar(46)
        avatar.set_logo()
        top.addWidget(avatar)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        heading = QLabel(t("chat.intro_heading"))
        heading.setObjectName("title")
        heading.setFont(theme.display_font(14, 700))
        titles.addWidget(heading)
        titles.addWidget(muted(t("chat.intro_text"), size=9))
        top.addLayout(titles, 1)
        intro.layout().addLayout(top)
        self.stream.addWidget(intro)

        suggestions = (
            (t("chat.suggest_vertical_slice"), t("chat.suggest_vertical_slice_prompt")),
            (t("chat.suggest_visual"), t("chat.suggest_visual_prompt")),
            (t("chat.suggest_menu"), t("chat.suggest_menu_prompt")),
            (t("chat.suggest_fix"), t("chat.suggest_fix_prompt")),
        )
        suggestions_grid = QGridLayout()
        suggestions_grid.setContentsMargins(0, 0, 0, 0)
        suggestions_grid.setHorizontalSpacing(7)
        suggestions_grid.setVerticalSpacing(7)
        for index, (label, prompt) in enumerate(suggestions):
            button = QPushButton(label)
            button.setObjectName("suggestion")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda checked=False, text=prompt: self.send(text))
            suggestions_grid.addWidget(button, 0, index)
        self.stream.addLayout(suggestions_grid)
        self.stream.addWidget(self._build_plan_card())
        self.stream.addStretch(1)

    def _build_plan_card(self) -> Card:
        card = Card(soft=True, padding=12)
        card.layout().setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(8)
        label = QLabel(t("chat.plan_heading"))
        label.setFont(theme.ui_font(10, 700))
        label.setStyleSheet("color: #E7E9EC; background: transparent; border: none;")
        head.addWidget(label)
        head.addStretch(1)
        self._plan_count = QLabel("0/0")
        self._plan_count.setObjectName("dim")
        self._plan_count.setFont(theme.ui_font(8, 600))
        head.addWidget(self._plan_count)
        card.layout().addLayout(head)

        self._plan_hint = muted(t("chat.plan_hint"), size=9)
        self._plan_hint.setWordWrap(True)
        card.layout().addWidget(self._plan_hint)

        self._plan_host = QWidget()
        self._plan_host.setObjectName("root")
        self._plan_rows = QVBoxLayout(self._plan_host)
        self._plan_rows.setContentsMargins(0, 0, 0, 0)
        self._plan_rows.setSpacing(4)
        self._plan_host.hide()
        card.layout().addWidget(self._plan_host)
        self._plan_signature = None
        return card

    def _render_plan(self, tasks: list[dict]) -> None:
        signature = tuple(
            (str(task.get("id", "")), str(task.get("title", "")), str(task.get("status", "")))
            for task in tasks
        )
        if signature == self._plan_signature:
            return
        self._plan_signature = signature
        while self._plan_rows.count():
            item = self._plan_rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        done = sum(1 for task in tasks if task.get("status") == "done")
        self._plan_count.setText(f"{done}/{len(tasks)}")
        if not tasks:
            self._plan_hint.show()
            self._plan_host.hide()
            return
        self._plan_hint.hide()
        self._plan_host.show()
        visible = tasks[:6]
        for task in visible:
            row = QFrame()
            row.setStyleSheet("background: transparent;")
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(7)
            status = task.get("status", "pending")
            icon, color = {
                "done": ("✓", "#8DB8A0"),
                "in_progress": ("›", "#C9AD73"),
                "skipped": ("–", "#6F7680"),
            }.get(status, ("·", "#6F7680"))
            marker = QLabel(icon)
            marker.setFixedWidth(14)
            marker.setAlignment(Qt.AlignmentFlag.AlignCenter)
            marker.setStyleSheet(f"color: {color}; font-weight: 900; background: transparent; border: none;")
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
            self._plan_rows.addWidget(row)
        if len(tasks) > len(visible):
            self._plan_rows.addWidget(muted(t("chat.plan_more_tasks", count=len(tasks) - len(visible)), size=8))

    def _build_input(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(7)
        self.input = QTextEdit()
        self.input.setObjectName("chatInput")
        self.input.setPlaceholderText(t("chat.input_placeholder"))
        self.input.setMaximumHeight(104)
        self.input.setMinimumHeight(64)
        self.input.installEventFilter(self)
        layout.addWidget(self.input)

        bottom = QHBoxLayout()
        hint = muted(t("chat.input_hint"), size=8)
        bottom.addWidget(hint)
        bottom.addStretch(1)
        self.send_button = QPushButton(t("chat.send_button"))
        self.send_button.setObjectName("primary")
        self.send_button.setMinimumWidth(150)
        self.send_button.clicked.connect(lambda: self.send())
        bottom.addWidget(self.send_button)
        layout.addLayout(bottom)
        return frame

    # ------------------------------------------------------------------
    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QKeyEvent

        if obj is self.input and event.type() == QEvent.Type.KeyPress:
            assert isinstance(event, QKeyEvent)
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                # Enter sends; Ctrl+Enter is the explicit newline gesture. Let
                # the editor handle the modified key normally.
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    cursor = self.input.textCursor()
                    cursor.insertText("\n")
                    self.input.setTextCursor(cursor)
                    return True
                self.send()
                return True
        return super().eventFilter(obj, event)

    def _append(self, role: str, text: str) -> MessageBubble:
        self._tool_group = None
        bubble = MessageBubble(role, text)
        self.stream.insertWidget(self.stream.count() - 1, bubble)
        self._message_count += 1
        QTimer.singleShot(30, self._scroll_bottom)
        return bubble

    def _append_tool_start(self, name: str, arguments: dict | None) -> ToolCallCard:
        if self._tool_group is None:
            self._tool_group = ToolCallGroup()
            self.stream.insertWidget(self.stream.count() - 1, self._tool_group)
            self._message_count += 1
        card = ToolCallCard(name, arguments)
        self._tool_group.add_call(card)
        self._active_tool_card = card
        QTimer.singleShot(30, self._scroll_bottom)
        return card

    def _append_changes(self, files: list[dict], snapshot: dict | None, outcome: str = "") -> ChangesCard:
        self._tool_group = None
        card = ChangesCard(files, snapshot, outcome)
        card.file_requested.connect(self.file_open_requested)
        card.restore_requested.connect(self.restore_requested)
        card.history_requested.connect(self.history_requested)
        self.stream.insertWidget(self.stream.count() - 1, card)
        self._message_count += 1
        self._changes_card = card
        QTimer.singleShot(30, self._scroll_bottom)
        return card

    def _append_error(self, text: str, error_kind: str, *, analysis: bool = False) -> AgentErrorBubble:
        self._tool_group = None
        bubble = AgentErrorBubble(
            text,
            error_kind,
            self.settings.is_auto_continue_enabled(error_kind),
            analysis=analysis,
        )
        bubble.continue_requested.connect(
            lambda kind=analysis: self._continue_after_error(kind)
        )
        bubble.auto_continue_changed.connect(
            lambda checked, kind=error_kind: self._set_auto_continue(kind, checked)
        )
        self.stream.insertWidget(self.stream.count() - 1, bubble)
        self._message_count += 1
        QTimer.singleShot(30, self._scroll_bottom)
        return bubble

    def _continue_after_error(self, analysis: bool = False) -> None:
        self._auto_continue_kind = ""
        prompt = t("chat.continue_prompt")
        if analysis:
            if self.running:
                return
            if self.prepare_run is not None and not self.prepare_run():
                return
            self._start(
                prompt,
                hidden=True,
                analysis=True,
                reply_language=current_language(),
            )
            return
        self.send(prompt)

    def _set_auto_continue(self, kind: str, enabled: bool) -> None:
        self.settings.set_auto_continue(kind, enabled)
        self.settings.save()

    def prefill_task(self, text: str) -> None:
        """Put an agent task in the composer without sending it automatically."""
        if not text.strip():
            return
        self.input.setPlainText(text.strip())
        self.input.setEnabled(True)
        self.send_button.setEnabled(True)
        self.focus_input()
        self.step_label.setText(t("chat.prefill_note"))

    def last_changes(self) -> list[dict]:
        if self._changes_card is None:
            return []
        return list(self._changes_card.files)

    def last_snapshot(self) -> dict | None:
        return self._current_snapshot

    @property
    def last_outcome(self) -> str:
        """Outcome of the most recent run (``done``, ``error``, ``incomplete``…)."""
        if self._changes_card is not None:
            return self._changes_card.outcome
        return "error" if self._last_error_text else ""

    @property
    def last_error(self) -> str:
        return self._last_error_text

    def _scroll_bottom(self) -> None:
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _update_usage_label(self) -> None:
        tokens = int(self.usage.get("total_tokens") or 0)
        seconds = float(self.usage.get("seconds") or 0.0)
        if tokens <= 0 and seconds <= 0:
            self.usage_label.hide()
            return
        duration = format_duration(seconds)
        cached = int(self.usage.get("cached_tokens") or 0)
        if cached > 0:
            self.usage_label.setText(
                t(
                    "chat.usage_total_cached",
                    tokens=format_tokens(tokens),
                    cached=format_tokens(cached),
                    time=duration,
                )
            )
        else:
            self.usage_label.setText(
                t(
                    "chat.usage_total",
                    tokens=format_tokens(tokens),
                    time=duration,
                )
            )
        self.usage_label.setToolTip(
            t(
                "chat.usage_tooltip",
                requests=int(self.usage.get("requests") or 0),
                prompt=format_tokens(int(self.usage.get("prompt_tokens") or 0)),
                cached=format_tokens(int(self.usage.get("cached_tokens") or 0)),
                cache_write=format_tokens(int(self.usage.get("cache_write_tokens") or 0)),
                completion=format_tokens(int(self.usage.get("completion_tokens") or 0)),
                time=duration,
            )
        )
        self.usage_label.show()

    # ------------------------------------------------------------------
    def refresh_state(self) -> None:
        self._update_usage_label()
        state = read_state(self.project.root)
        tasks = state.get("tasks") or []
        self._render_plan(tasks)
        if self.running:
            return
        done = sum(1 for task in tasks if task.get("status") == "done")
        status = state.get("status")
        if status == "done":
            self.status_badge.setText(t("chat.badge_done"))
            self.status_badge.set_tone("default")
        elif status == "error":
            self.status_badge.setText(t("chat.badge_error"))
            self.status_badge.set_tone("gold")
        else:
            self.status_badge.setText(t("chat.status_ready_badge"))
            self.status_badge.set_tone("default")
        self.progress.setValue(int(round(derived_percent(state))))
        stage = state.get("stage") or ""
        if tasks:
            self.step_label.setText(t("chat.step_tasks", stage=stage, done=done, total=len(tasks)))
        else:
            self.step_label.setText(stage)
        config = self.settings.get_provider_config()
        provider_name = short_provider_name(config.get("name") or config.get("id") or t("chat.ai_fallback"))
        self.model_label.setText(
            f"{provider_name} · {config.get('model') or t('chat.model_none')}"
        )
        self.model_label.setToolTip(
            f"{config.get('name') or config.get('id') or t('chat.ai_fallback')} · "
            f"{config.get('model') or t('chat.model_none')}"
        )

    def _ready_to_run(self) -> bool:
        config = self.settings.get_provider_config()
        ok, reason = config_status(config)
        if not ok:
            QMessageBox.warning(
                self,
                t("chat.not_configured_title"),
                t("chat.not_configured_text", reason=reason),
            )
            self.settings_requested.emit()
            return False
        return True

    def send(self, text: str | None = None) -> None:
        if self.running:
            return
        if text is None:
            text = self.input.toPlainText().strip()
        if not text:
            return
        if not self._auto_sending:
            self._auto_continue_attempts = 0
        if not self._ready_to_run():
            return
        if self.prepare_run is not None and not self.prepare_run():
            return
        self.input.clear()
        self._append("user", text)
        self._start(text)

    def focus_input(self) -> None:
        if self.input.isEnabled():
            self.input.setFocus()
            self.input.moveCursor(QTextCursor.MoveOperation.End)

    def _start(
        self,
        message: str | None,
        *,
        chat_id: str | None = None,
        hidden: bool = False,
        analysis: bool = False,
        reply_language: str | None = None,
    ) -> None:
        self.running = True
        self._analysis_run = bool(analysis)
        self._last_assistant = ""
        self._last_error_text = ""
        self._last_error_kind = "other"
        self._auto_continue_kind = ""
        self._current_snapshot = None
        self._changes_card = None
        self._tool_group = None
        self._active_tool_card = None
        self._run_chat_id = chat_id or chatlog.active_chat_id(self.project.root)
        # Store the task before the run starts: even if the app is closed in
        # the middle of a long generation, the conversation keeps its order
        # (user turn first, then every reply that actually appeared).
        if message and message.strip():
            self._remember("user", message, hidden=hidden)
        self.send_button.setEnabled(False)
        self._set_chat_controls_enabled(False)
        self.stop_button.setEnabled(True)
        self.stop_button.setText(t("chat.stop_button"))
        self.stop_button.show()
        self.status_badge.setText(t("chat.badge_working"))
        self.status_badge.set_tone("gold")
        self.progress.setRange(0, 0)
        self.step_label.setText(t("chat.improve_working") if analysis else t("chat.studying"))
        self.worker = AgentWorker(
            self.project,
            self.settings,
            message,
            chat_id=self._run_chat_id,
            hidden_message=hidden,
            analysis=analysis,
            reply_language=reply_language,
            persist_messages=False,
        )
        self.worker.event.connect(self._on_event)
        self.worker.done.connect(self._on_done)
        self.worker.incomplete.connect(self._on_incomplete)
        self.worker.failed.connect(self._on_failed)
        self.worker.cancelled.connect(self._on_cancelled)
        self.worker.start()

    def _on_event(self, event: AgentEvent) -> None:
        kind = event.kind
        if kind == "status":
            self.step_label.setText(event.text)
        elif kind == "step":
            step = event.data.get("step", "")
            total = event.data.get("max_steps") or 0
            if total:
                self.step_label.setText(t("chat.step_progress_total", step=step, total=total))
            else:
                self.step_label.setText(t("chat.step_progress", step=step))
        elif kind == "assistant":
            if not event.text.strip():
                return
            self._append("assistant", event.text)
            self._remember("assistant", event.text)
            self._last_assistant = event.text
        elif kind == "tool_start":
            name = event.data.get("tool", "")
            self.step_label.setText(t("chat.tool_label", name=_tool_label(name)))
            if not self._analysis_run:
                self._append_tool_start(name, event.data.get("arguments") or {})
        elif kind == "tool_result":
            name = event.data.get("tool", "tool")
            result = event.data.get("result", "")
            success = event.data.get("success", True)
            if self._analysis_run:
                if name in {"set_plan", "update_task", "report_progress", "finish"}:
                    self.refresh_state()
                return
            card = self._active_tool_card
            if card is None or card.name != name:
                card = self._append_tool_start(name, {})
            self._active_tool_card = None
            card.finish(result, success)
            if name in {"set_plan", "update_task", "report_progress", "finish"}:
                self.refresh_state()
        elif kind == "usage":
            usage = event.data.get("usage") or {}
            self.usage = add_usage(
                self.project.root,
                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                completion_tokens=int(usage.get("completion_tokens") or 0),
                total_tokens=int(usage.get("total_tokens") or 0),
                cached_tokens=int(usage.get("cached_tokens") or 0),
                cache_write_tokens=int(usage.get("cache_write_tokens") or 0),
                seconds=float(usage.get("seconds") or 0.0),
                requests=1,
            )
            self._update_usage_label()
        elif kind == "snapshot":
            snapshot = event.data.get("snapshot") or {}
            if snapshot:
                self._current_snapshot = snapshot
                self.step_label.setText(t("chat.snapshot_saved"))
                self.history_changed.emit()
        elif kind == "snapshot_error":
            text = event.text or t("chat.snapshot_failed")
            self._append("system", text)
            self._remember("system", text)
        elif kind == "changes":
            files = event.data.get("files") or []
            snapshot = event.data.get("snapshot") or self._current_snapshot
            if snapshot:
                self._current_snapshot = snapshot
            self._append_changes(files, snapshot, str(event.data.get("outcome") or ""))
            self.history_changed.emit()
        elif kind == "done":
            if not self._analysis_run:
                self._append("system", event.text or t("chat.done_short"))
        elif kind == "incomplete":
            text = t("chat.incomplete_prefix") + (
                event.text or t("chat.incomplete_default")
            )
            self._append("error", text)
            self._remember("error", text)
        elif kind == "error":
            self._last_error_text = event.text
            self._last_error_kind = str(event.data.get("error_kind") or "other")
            self._append_error(event.text, self._last_error_kind, analysis=self._analysis_run)
            self._remember("error", event.text)
            self._auto_continue_kind = (
                self._last_error_kind
                if self.settings.is_auto_continue_enabled(self._last_error_kind)
                else ""
            )
        elif kind == "supervisor":
            if event.data.get("complete"):
                self.step_label.setText(event.text)
            else:
                missing = event.data.get("missing") or []
                text = event.text or t("chat.supervisor_found")
                if missing:
                    text += "\n" + "\n".join(f"• {item}" for item in missing)
                self._append("system", text)
                self._remember("system", text)
        elif kind == "cancelled":
            self._append("system", event.text)
            self._remember("system", event.text)

    def _on_done(self, text: str) -> None:
        self._auto_continue_attempts = 0
        # The final answer sometimes arrives through ``finish`` instead of a
        # streamed assistant turn. Store it so the next session shows the same
        # reply the user saw at the end of the run (duplicates are ignored by
        # the chat history layer).
        if text and text.strip():
            self._remember("assistant", text)
            self._last_assistant = text
        self._finish(t("chat.badge_done"), t("chat.finish_done"))
        self.finished.emit()

    def _on_incomplete(self, reason: str) -> None:
        self._auto_continue_attempts = 0
        self._finish(t("chat.badge_incomplete"), reason or t("chat.finish_incomplete"))
        self.finished.emit()

    def _on_failed(self, message: str) -> None:
        was_analysis = self._analysis_run
        self._finish(t("chat.badge_error"), t("chat.finish_failed", message=message))
        if message and message != self._last_error_text:
            self._last_error_kind = "other"
            self._append_error(message, "other")
            self._remember("error", message)
        self.finished.emit()
        self._schedule_auto_continue(analysis=was_analysis)

    def _on_cancelled(self) -> None:
        self._auto_continue_attempts = 0
        self._finish(t("chat.badge_stopped"), t("chat.finish_cancelled"))
        self.finished.emit()

    def _schedule_auto_continue(self, *, analysis: bool = False) -> None:
        """Send the "Continue" prompt once the failed worker has fully stopped."""
        kind = self._auto_continue_kind
        self._auto_continue_kind = ""
        if not kind or not self.settings.is_auto_continue_enabled(kind):
            return
        # Unlimited auto-continue: a long server outage must not require the
        # user to press "Continue" by hand. The delay only backs off so a
        # persistent error does not hammer the provider, it never stops.
        attempt = self._auto_continue_attempts
        self._auto_continue_attempts += 1
        delay_ms = min(8000, 80 * (2 ** min(attempt, 6)))
        prompt = t("chat.continue_prompt")

        def run_auto() -> None:
            if self.running:
                return
            if analysis:
                if self.prepare_run is not None and not self.prepare_run():
                    return
                self._start(
                    prompt,
                    hidden=True,
                    analysis=True,
                    reply_language=current_language(),
                )
                return
            self._auto_sending = True
            try:
                self.send(prompt)
            finally:
                self._auto_sending = False

        QTimer.singleShot(delay_ms, run_auto)

    def _finish(self, badge: str, message: str) -> None:
        self.running = False
        if self._active_tool_card is not None:
            self._active_tool_card.stop()
            self._active_tool_card = None
        self._analysis_run = False
        self.send_button.setEnabled(True)
        self.stop_button.hide()
        self.status_badge.setText(badge)
        self.status_badge.set_tone("default" if badge == t("chat.badge_done") else "gold")
        self.step_label.setText(message)
        self.step_label.setToolTip(message)
        state = read_state(self.project.root)
        self.progress.setRange(0, 100)
        self.progress.setValue(int(round(derived_percent(state))))
        self._render_plan(state.get("tasks") or [])
        self._refresh_chat_list()

    def stop_agent(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.stop()
            self.stop_button.setEnabled(False)
            self.stop_button.setText(t("chat.stopping"))
            self.step_label.setText(t("chat.stopping_step"))

    def clear_chat(self) -> None:
        if self.running:
            QMessageBox.information(self, t("chat.agent_running_title"), t("chat.agent_running_text"))
            return
        try:
            chatlog.clear_chat(self.project.root)
        except Exception:
            pass
        self._refresh_chat_list()
        self._reload_chat()

    def set_enabled(self, enabled: bool) -> None:
        self.input.setEnabled(enabled)
        self.send_button.setEnabled(enabled)
        self._set_chat_controls_enabled(enabled and not self.running)

    def shutdown(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(1500)

    def _on_settings_clicked(self) -> None:
        self.settings_requested.emit()
