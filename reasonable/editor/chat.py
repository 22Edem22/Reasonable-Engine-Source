"""Built-in AI agent chat with live plan/progress."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
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
from reasonable.ai.providers import config_status, short_provider_name
from reasonable.core import chatlog
from reasonable.core.i18n import t
from reasonable.core.progress import derived_percent, read_state
from reasonable.core.settings import Settings

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
            name = QLabel(t("chat.role_system"))
            name.setFont(theme.ui_font(9, 600))
            name.setStyleSheet("color: #C98A90;")
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
        # Set by ProjectPage so unsaved editor buffers reach disk before the
        # agent snapshot and tool calls see them.
        self.prepare_run: Callable[[], bool] | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self._build_header())
        layout.addWidget(self._build_stream(), 1)
        layout.addWidget(self._build_input())

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
        recent = [item for item in history if item.get("role") in ("user", "assistant", "error")]
        for item in recent[-40:]:
            role = str(item.get("role") or "assistant")
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            self._append(role, text)

    def _remember(self, role: str, text: str) -> None:
        """Persist a message the UI produced (the agent persists its own)."""
        if not text.strip():
            return
        try:
            chatlog.append_message(self.project.root, role, text)
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _build_header(self) -> QFrame:
        card = Card(padding=14)
        layout = QHBoxLayout()
        layout.setSpacing(10)
        avatar = Avatar(40)
        avatar.set_logo()
        layout.addWidget(avatar)
        titles = QVBoxLayout()
        titles.setSpacing(1)
        title = QLabel(t("chat.title"))
        title.setObjectName("title")
        title.setFont(theme.display_font(12, 700))
        titles.addWidget(title)
        config = self.settings.get_provider_config()
        provider_name = short_provider_name(config.get("name") or config.get("id") or t("chat.ai_fallback"))
        self.model_label = muted(
            f"{provider_name} · {config.get('model') or t('chat.model_none')}",
            size=9,
        )
        self.model_label.setToolTip(
            f"{config.get('name') or config.get('id') or t('chat.ai_fallback')} · "
            f"{config.get('model') or t('chat.model_none')}"
        )
        titles.addWidget(self.model_label)
        layout.addLayout(titles)
        layout.addStretch(1)
        self.usage_badge = Badge("", "default")
        self.usage_badge.hide()
        layout.addWidget(self.usage_badge)
        self.status_badge = Badge(t("chat.status_ready_badge"), "default")
        layout.addWidget(self.status_badge)
        self.stop_button = QPushButton(t("chat.stop_button"))
        self.stop_button.setObjectName("danger")
        self.stop_button.clicked.connect(self.stop_agent)
        self.stop_button.hide()
        layout.addWidget(self.stop_button)
        clear = QPushButton(t("chat.clear_button"))
        clear.setObjectName("ghost")
        clear.clicked.connect(self.clear_chat)
        layout.addWidget(clear)
        card.layout().addLayout(layout)
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
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.send()
                return True
        return super().eventFilter(obj, event)

    def _append(self, role: str, text: str) -> MessageBubble:
        bubble = MessageBubble(role, text)
        self.stream.insertWidget(self.stream.count() - 1, bubble)
        self._message_count += 1
        QTimer.singleShot(30, self._scroll_bottom)
        return bubble

    def _append_changes(self, files: list[dict], snapshot: dict | None, outcome: str = "") -> ChangesCard:
        card = ChangesCard(files, snapshot, outcome)
        card.file_requested.connect(self.file_open_requested)
        card.restore_requested.connect(self.restore_requested)
        card.history_requested.connect(self.history_requested)
        self.stream.insertWidget(self.stream.count() - 1, card)
        self._message_count += 1
        self._changes_card = card
        QTimer.singleShot(30, self._scroll_bottom)
        return card

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

    # ------------------------------------------------------------------
    def refresh_state(self) -> None:
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

    def _start(self, message: str | None) -> None:
        self.running = True
        self._last_assistant = ""
        self._last_error_text = ""
        self._current_snapshot = None
        self._changes_card = None
        self.send_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.stop_button.setText(t("chat.stop_button"))
        self.stop_button.show()
        self.status_badge.setText(t("chat.badge_working"))
        self.status_badge.set_tone("gold")
        self.progress.setRange(0, 0)
        self.step_label.setText(t("chat.studying"))
        self.worker = AgentWorker(self.project, self.settings, message)
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
            self._last_assistant = event.text
        elif kind == "tool_start":
            self.step_label.setText(t("chat.tool_label", name=event.data.get("tool", "")))
        elif kind == "tool_result":
            name = event.data.get("tool", "tool")
            result = event.data.get("result", "")
            success = event.data.get("success", True)
            icon = "✓" if success else "×"
            self._append("tool", f"{icon} {name}\n{result[:1200]}")
            if name in {"set_plan", "update_task", "report_progress", "finish"}:
                self.refresh_state()
        elif kind == "usage":
            usage = event.data.get("usage") or {}
            total = usage.get("total_tokens") or usage.get("total") or 0
            if total:
                self.usage_badge.setText(t("chat.token_count", count=f"{int(total):,}".replace(",", " ")))
                self.usage_badge.show()
        elif kind == "snapshot":
            snapshot = event.data.get("snapshot") or {}
            if snapshot:
                self._current_snapshot = snapshot
                self.step_label.setText(t("chat.snapshot_saved"))
                self.history_changed.emit()
        elif kind == "snapshot_error":
            self._append("system", event.text or t("chat.snapshot_failed"))
        elif kind == "changes":
            files = event.data.get("files") or []
            snapshot = event.data.get("snapshot") or self._current_snapshot
            if snapshot:
                self._current_snapshot = snapshot
            self._append_changes(files, snapshot, str(event.data.get("outcome") or ""))
            self.history_changed.emit()
        elif kind == "done":
            self._append("system", event.text or t("chat.done_short"))
        elif kind == "incomplete":
            self._append(
                "error",
                t("chat.incomplete_prefix") + (event.text or t("chat.incomplete_default")),
            )
        elif kind == "error":
            self._last_error_text = event.text
            self._append("error", event.text)
        elif kind == "cancelled":
            self._append("system", event.text)

    def _on_done(self, _text: str) -> None:
        self._finish(t("chat.badge_done"), t("chat.finish_done"))
        self.finished.emit()

    def _on_incomplete(self, reason: str) -> None:
        self._finish(t("chat.badge_incomplete"), reason or t("chat.finish_incomplete"))
        self.finished.emit()

    def _on_failed(self, message: str) -> None:
        self._finish(t("chat.badge_error"), t("chat.finish_failed", message=message))
        if message and message != self._last_error_text:
            self._append("error", message)
            self._remember("error", "⚠ " + message)
        self.finished.emit()

    def _on_cancelled(self) -> None:
        self._finish(t("chat.badge_stopped"), t("chat.finish_cancelled"))
        self.finished.emit()

    def _finish(self, badge: str, message: str) -> None:
        self.running = False
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
        while self.stream.count():
            item = self.stream.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._message_count = 0
        self._changes_card = None
        try:
            chatlog.clear_chat(self.project.root)
        except Exception:
            pass
        self._show_intro()
        self.refresh_state()

    def set_enabled(self, enabled: bool) -> None:
        self.input.setEnabled(enabled)
        self.send_button.setEnabled(enabled)

    def shutdown(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(1500)

    def _on_settings_clicked(self) -> None:
        self.settings_requested.emit()
