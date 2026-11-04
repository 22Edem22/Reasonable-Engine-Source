"""An interactive, strictly sequential quick start for the editor.

The first launch opens this dialog automatically. Each of the six steps asks
the user to *do* something — pick a project type, write a task, visit the
workspaces in order, run a preview, undo a change and choose an export target.
The next step is unlocked only after the current action is complete, so the
tour always moves forward in the same order as a real project.

The tour can be replayed from the welcome page, the settings dialog or
``Help → Quick start`` and skipped at any moment; the flag lives in
``settings.json`` (``ui.tutorial_seen``).
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from reasonable.core.i18n import t
from reasonable.core.settings import Settings

from . import theme
from .widgets import Card, muted


class TutorialDialog(QDialog):
    """Hands-on six-step guide with locked sequential progression."""

    ICONS = ("sparkles", "bolt", "grid", "play", "history", "export")
    STEP_COUNT = 6
    SECTIONS = ("overview", "agent", "code", "assets", "scene")
    SECTION_ICONS = ("home", "sparkles", "code", "image", "grid")

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.index = 0
        self.max_reached = 0
        self.completed = [False] * self.STEP_COUNT
        self.launch_action = ""
        self._step_buttons: list[QPushButton] = []

        # Per-step interaction state.
        self.step1_choice = ""
        self.step2_task = ""
        self.step3_visited: list[int] = []
        self.step4_ran = False
        self.step5_undone = False
        self.step6_target = ""
        self.step6_exported = False
        self.task_edit: QLineEdit | None = None
        self.task_error_label: QLabel | None = None

        self.setWindowTitle(t("tutorial.title"))
        self.setModal(True)
        self.setMinimumSize(900, 620)
        self.resize(940, 650)
        self.setObjectName("tutorialDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(14)
        root.addLayout(self._build_header())

        body = QHBoxLayout()
        body.setSpacing(16)
        body.addWidget(self._build_outline(), 0)
        body.addWidget(self._build_page(), 1)
        root.addLayout(body, 1)
        root.addLayout(self._build_footer())

        self._render()

    # ------------------------------------------------------------------
    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(11)
        logo = QLabel()
        logo.setPixmap(theme.logo_pixmap(30))
        row.addWidget(logo)
        titles = QVBoxLayout()
        titles.setSpacing(1)
        heading = QLabel(t("tutorial.title"))
        heading.setObjectName("title")
        heading.setFont(theme.display_font(14, 700))
        titles.addWidget(heading)
        titles.addWidget(muted(t("tutorial.subtitle"), size=9))
        row.addLayout(titles, 1)
        badge = QLabel(t("tutorial.badge"))
        badge.setObjectName("badge")
        badge.setFont(theme.ui_font(8, 700))
        badge.setStyleSheet(
            "color: #D9B07E; background: #33271F; border: 1px solid #4A382A;"
            "border-radius: 9px; padding: 3px 9px;"
        )
        row.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)
        return row

    def _build_outline(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("card")
        panel.setFixedWidth(250)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(5)

        layout.addWidget(muted(t("tutorial.outline"), size=8))
        for index in range(self.STEP_COUNT):
            button = QPushButton()
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFont(theme.ui_font(9, 600))
            button.setIcon(theme.icon(self.ICONS[index], 14))
            button.setIconSize(QSize(14, 14))
            button.setMinimumHeight(38)
            button.setStyleSheet(
                "QPushButton { text-align: left; padding: 6px 9px; border-radius: 7px;"
                " color: #A5ACB6; background: transparent; border: 1px solid transparent; }"
                "QPushButton:hover { background: #262A31; color: #E7E9EC; }"
                "QPushButton:checked { background: #2C2622; color: #F0D6C4;"
                " border: 1px solid #4A382A; }"
                "QPushButton:disabled { color: #5F646D; }"
            )
            button.clicked.connect(lambda checked=False, i=index: self.go_to(i))
            layout.addWidget(button)
            self._step_buttons.append(button)
        layout.addStretch(1)
        layout.addWidget(muted(t("tutorial.outline_hint"), size=8))
        return panel

    def _build_page(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(12)
        icon_host = QFrame()
        icon_host.setFixedSize(52, 52)
        icon_host.setStyleSheet(
            "QFrame { background: #2C2622; border: 1px solid #4A382A; border-radius: 14px; }"
        )
        icon_layout = QVBoxLayout(icon_host)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_layout.addWidget(self.icon_label)
        top.addWidget(icon_host, 0, Qt.AlignmentFlag.AlignTop)

        titles = QVBoxLayout()
        titles.setSpacing(3)
        self.eyebrow = QLabel()
        self.eyebrow.setFont(theme.ui_font(8, 700))
        self.eyebrow.setStyleSheet("color: #C9AD73; background: transparent; border: none;")
        titles.addWidget(self.eyebrow)
        self.heading = QLabel()
        self.heading.setObjectName("title")
        self.heading.setFont(theme.display_font(17, 700))
        self.heading.setWordWrap(True)
        titles.addWidget(self.heading)
        top.addLayout(titles, 1)
        layout.addLayout(top)

        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setFont(theme.ui_font(10))
        self.body.setStyleSheet("color: #C6CBD2; background: transparent; border: none;")
        layout.addWidget(self.body)

        self.task_card = Card(soft=True, padding=12)
        self.task_layout = QVBoxLayout()
        self.task_layout.setContentsMargins(0, 0, 0, 0)
        self.task_layout.setSpacing(8)
        self.task_card.layout().addLayout(self.task_layout)
        layout.addWidget(self.task_card)

        self.tip = Card(soft=True, padding=12)
        tip_head = QHBoxLayout()
        tip_head.setSpacing(8)
        tip_icon = QLabel()
        tip_icon.setPixmap(theme.icon_pixmap("bolt", 14, "#D9B07E"))
        tip_head.addWidget(tip_icon)
        tip_title = QLabel(t("tutorial.tip"))
        tip_title.setFont(theme.ui_font(8, 700))
        tip_title.setStyleSheet("color: #D9B07E; background: transparent; border: none;")
        tip_head.addWidget(tip_title)
        tip_head.addStretch(1)
        self.tip.layout().addLayout(tip_head)
        self.tip_text = muted("", size=9)
        self.tip_text.setWordWrap(True)
        self.tip.layout().addWidget(self.tip_text)
        layout.addWidget(self.tip)
        layout.addStretch(1)

        self.progress_label = muted("", size=8)
        layout.addWidget(self.progress_label)
        return panel

    def _build_footer(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        self.skip_button = QPushButton(t("tutorial.skip"))
        self.skip_button.setObjectName("ghost")
        self.skip_button.setToolTip(t("tutorial.skip_tip"))
        self.skip_button.clicked.connect(self._finish)
        row.addWidget(self.skip_button)
        self.locked_hint = QLabel(t("tutorial.locked_hint"))
        self.locked_hint.setFont(theme.ui_font(8, 600))
        self.locked_hint.setStyleSheet("color: #D9B07E; background: transparent; border: none;")
        row.addWidget(self.locked_hint)
        row.addStretch(1)
        self.hint = muted(t("tutorial.keyboard_hint"), size=8, wrap=False)
        row.addWidget(self.hint)
        row.addSpacing(8)
        self.back_button = QPushButton(t("tutorial.back"))
        self.back_button.setIcon(theme.icon("back", 13))
        self.back_button.clicked.connect(self.back)
        row.addWidget(self.back_button)
        self.next_button = QPushButton(t("tutorial.next"))
        self.next_button.setObjectName("primary")
        self.next_button.setIcon(theme.icon("forward", 13, "#1B110D"))
        self.next_button.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.next_button.setMinimumWidth(150)
        self.next_button.clicked.connect(self.next)
        row.addWidget(self.next_button)
        return row

    # ------------------------------------------------------------------
    # Sequential navigation
    # ------------------------------------------------------------------
    def complete_current(self) -> None:
        self.completed[self.index] = True
        self._render()

    def go_to(self, index: int) -> None:
        """Only completed/visited steps can be reviewed; jumping ahead is blocked."""
        index = max(0, int(index))
        if index > self.max_reached:
            return
        self.index = min(self.STEP_COUNT - 1, index)
        self._render()

    def next(self) -> None:
        if not self.completed[self.index]:
            self.locked_hint.setVisible(True)
            return
        if self.index >= self.STEP_COUNT - 1:
            self._finish()
            return
        self.index += 1
        self.max_reached = max(self.max_reached, self.index)
        self._render()

    def back(self) -> None:
        if self.index > 0:
            self.go_to(self.index - 1)

    def _mark_seen(self) -> None:
        try:
            self.settings.mark_tutorial_seen()
        except Exception:
            pass

    def _finish(self) -> None:
        self._mark_seen()
        self.accept()

    def reject(self) -> None:  # noqa: D401 - closing the tour counts as skipping
        self._mark_seen()
        super().reject()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._mark_seen()
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def _render(self) -> None:
        number = self.index + 1
        self.icon_label.setPixmap(theme.icon_pixmap(self.ICONS[self.index], 26, "#D9B07E"))
        self.eyebrow.setText(t("tutorial.step_of", step=number, total=self.STEP_COUNT))
        self.heading.setText(t(f"tutorial.step{number}_title"))
        self.body.setText(t(f"tutorial.step{number}_body"))
        self.tip_text.setText(t(f"tutorial.step{number}_tip"))
        self.progress_label.setText(t("tutorial.progress", step=number, total=self.STEP_COUNT))
        self._render_task()
        self._render_outline()
        self._render_footer()

    def _render_outline(self) -> None:
        for index, button in enumerate(self._step_buttons):
            done = self.completed[index]
            label = t(f"tutorial.step{index + 1}_short")
            button.setText(f"✓  {label}" if done else label)
            button.setChecked(index == self.index)
            button.setEnabled(index <= self.max_reached)

    def _render_footer(self) -> None:
        done = self.completed[self.index]
        self.locked_hint.setVisible(not done)
        self.next_button.setEnabled(done)
        self.back_button.setEnabled(self.index > 0)
        last = self.index == self.STEP_COUNT - 1
        self.next_button.setText(t("tutorial.done") if last else t("tutorial.next"))
        self.next_button.setIcon(
            theme.icon("check" if last else "forward", 13, "#1B110D")
        )

    def _clear_task(self) -> None:
        while self.task_layout.count():
            item = self.task_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
            elif item.layout() is not None:
                self._clear_task_layout(item.layout())

    def _clear_task_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
            elif item.layout() is not None:
                self._clear_task_layout(item.layout())

    def _action_label(self, text: str | None = None) -> QLabel:
        label = QLabel(text or t("tutorial.action_heading"))
        label.setFont(theme.ui_font(8, 700))
        label.setStyleSheet("color: #8B929C; background: transparent; border: none;")
        return label

    def _feedback(self, text: str, color: str = "#8DB8A0") -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setFont(theme.ui_font(9, 600))
        label.setStyleSheet(f"color: {color}; background: transparent; border: none;")
        return label

    def _render_task(self) -> None:
        self._clear_task()
        self.task_layout.addWidget(self._action_label())
        builder = getattr(self, f"_task_step{self.index + 1}", None)
        if builder is not None:
            builder()

    # -- step 1: pick a project type -----------------------------------
    def _task_step1(self) -> None:
        row = QHBoxLayout()
        row.setSpacing(8)
        for key, label in (
            ("ai", t("tutorial.step1_choose_ai")),
            ("blank", t("tutorial.step1_choose_blank")),
        ):
            button = QPushButton(label)
            button.setMinimumHeight(38)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            selected = self.step1_choice == key
            button.setObjectName("primary" if selected else "choice")
            button.clicked.connect(lambda checked=False, value=key: self._choose_project(value))
            row.addWidget(button)
        row.addStretch(1)
        self.task_layout.addLayout(row)
        if self.step1_choice:
            self.task_layout.addWidget(
                self._feedback(t(f"tutorial.step1_selected_{self.step1_choice}"))
            )

    def _choose_project(self, key: str) -> None:
        self.step1_choice = key
        self.completed[0] = True
        self._render()

    # -- step 2: write a task and see the plan --------------------------
    def _task_step2(self) -> None:
        row = QHBoxLayout()
        row.setSpacing(8)
        self.task_edit = QLineEdit()
        self.task_edit.setPlaceholderText(t("tutorial.step2_placeholder"))
        self.task_edit.setText(self.step2_task)
        self.task_edit.setMinimumHeight(38)
        self.task_edit.returnPressed.connect(self._submit_task)
        row.addWidget(self.task_edit, 1)
        submit = QPushButton(t("tutorial.step2_submit"))
        submit.setObjectName("primary")
        submit.setMinimumHeight(38)
        submit.clicked.connect(self._submit_task)
        row.addWidget(submit)
        self.task_layout.addLayout(row)

        chips = QHBoxLayout()
        chips.setSpacing(6)
        for index in (1, 2, 3):
            chip = QPushButton(t(f"tutorial.step2_chip{index}"))
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setMinimumHeight(28)
            chip.setStyleSheet(
                "QPushButton { color: #A5ACB6; background: #1B1E24;"
                " border: 1px solid #2C323B; border-radius: 10px; padding: 4px 9px; }"
                "QPushButton:hover { color: #E7E9EC; background: #242830;"
                " border-color: #3A414B; }"
            )
            chip.clicked.connect(
                lambda checked=False, value=t(f"tutorial.step2_chip{index}"): self._fill_task(value)
            )
            chips.addWidget(chip)
        chips.addStretch(1)
        self.task_layout.addLayout(chips)

        self.task_error_label = QLabel("")
        self.task_error_label.setFont(theme.ui_font(8))
        self.task_error_label.setStyleSheet("color: #C98A90; background: transparent; border: none;")
        self.task_layout.addWidget(self.task_error_label)

        if self.step2_task:
            self.task_layout.addWidget(
                self._feedback(t("tutorial.step2_plan_ready"), "#D9B07E")
            )
            for index in range(1, 5):
                line = QHBoxLayout()
                line.setSpacing(7)
                check = QLabel("✓")
                check.setFixedWidth(14)
                check.setStyleSheet("color: #8DB8A0; font-weight: 900; background: transparent; border: none;")
                item = QLabel(t(f"tutorial.step2_plan{index}"))
                item.setFont(theme.ui_font(9))
                item.setStyleSheet("color: #C6CBD2; background: transparent; border: none;")
                line.addWidget(check)
                line.addWidget(item, 1)
                self.task_layout.addLayout(line)

    def _fill_task(self, text: str) -> None:
        if self.task_edit is not None:
            self.task_edit.setText(text)
            self.task_edit.setFocus()

    def _submit_task(self) -> None:
        text = self.task_edit.text().strip() if self.task_edit is not None else ""
        if len(text) < 3:
            if self.task_error_label is not None:
                self.task_error_label.setText(t("tutorial.step2_empty"))
            return
        self.step2_task = text
        self.completed[1] = True
        self._render()

    # -- step 3: visit the five workspaces in order ----------------------
    def _task_step3(self) -> None:
        row = QHBoxLayout()
        row.setSpacing(6)
        next_index = len(self.step3_visited)
        for index, key in enumerate(self.SECTIONS):
            visited = index < next_index
            label = t(f"projectpage.nav_{key}")
            button = QPushButton(f"✓ {label}" if visited else label)
            button.setMinimumHeight(34)
            button.setFont(theme.ui_font(8, 600))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setEnabled(index == next_index)
            if visited:
                button.setStyleSheet(
                    "QPushButton { color: #8DB8A0; background: #1D2621; border: 1px solid #2F4237;"
                    " border-radius: 7px; padding: 4px 8px; }"
                )
            elif index == next_index:
                button.setStyleSheet(
                    "QPushButton { color: #F0D6C4; background: #2C2622; border: 1px solid #4A382A;"
                    " border-radius: 7px; padding: 4px 8px; }"
                )
            button.clicked.connect(lambda checked=False, value=index: self._visit_section(value))
            row.addWidget(button)
        self.task_layout.addLayout(row)

        if self.step3_visited:
            key = self.SECTIONS[self.step3_visited[-1]]
            self.task_layout.addWidget(self._feedback(t(f"tutorial.section_{key}"), "#C6CBD2"))
        else:
            self.task_layout.addWidget(
                self._feedback(t("tutorial.section_hint"), "#8B929C")
            )
        if len(self.step3_visited) == len(self.SECTIONS):
            self.task_layout.addWidget(
                self._feedback(t("tutorial.step3_done"))
            )

    def _visit_section(self, index: int) -> None:
        if index != len(self.step3_visited) or index >= len(self.SECTIONS):
            return
        self.step3_visited.append(index)
        if len(self.step3_visited) == len(self.SECTIONS):
            self.completed[2] = True
        self._render()

    # -- step 4: run a preview ------------------------------------------
    def _task_step4(self) -> None:
        console = QLabel(t("tutorial.step4_console"))
        console.setWordWrap(True)
        console.setFont(theme.ui_font(9))
        console.setStyleSheet(
            "color: #B8BEC7; background: #12151A; border: 1px solid #20242B;"
            " border-radius: 8px; padding: 9px;"
        )
        self.task_layout.addWidget(console)
        row = QHBoxLayout()
        run = QPushButton(t("tutorial.step4_run"))
        run.setObjectName("primary")
        run.setMinimumHeight(36)
        run.setEnabled(not self.step4_ran)
        run.clicked.connect(self._run_preview)
        row.addWidget(run)
        row.addStretch(1)
        self.task_layout.addLayout(row)
        if self.step4_ran:
            self.task_layout.addWidget(self._feedback(t("tutorial.step4_ok")))

    def _run_preview(self) -> None:
        self.step4_ran = True
        self.completed[3] = True
        self._render()

    # -- step 5: undo a change ------------------------------------------
    def _task_step5(self) -> None:
        changes = QLabel(t("tutorial.step5_changes"))
        changes.setWordWrap(True)
        changes.setFont(theme.ui_font(9))
        changes.setStyleSheet(
            "color: #C6CBD2; background: #12151A; border: 1px solid #20242B;"
            " border-radius: 8px; padding: 9px;"
        )
        self.task_layout.addWidget(changes)
        row = QHBoxLayout()
        undo = QPushButton(t("tutorial.step5_undo"))
        undo.setObjectName("danger")
        undo.setMinimumHeight(36)
        undo.setEnabled(not self.step5_undone)
        undo.clicked.connect(self._undo_preview)
        row.addWidget(undo)
        row.addStretch(1)
        self.task_layout.addLayout(row)
        if self.step5_undone:
            self.task_layout.addWidget(self._feedback(t("tutorial.step5_ok")))

    def _undo_preview(self) -> None:
        self.step5_undone = True
        self.completed[4] = True
        self._render()

    # -- step 6: choose an export target --------------------------------
    def _task_step6(self) -> None:
        row = QHBoxLayout()
        row.setSpacing(6)
        for key in ("folder", "exe", "android"):
            button = QPushButton(t(f"tutorial.step6_{key}"))
            button.setMinimumHeight(34)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            selected = self.step6_target == key
            button.setObjectName("primary" if selected else "ghost")
            button.clicked.connect(lambda checked=False, value=key: self._choose_export(value))
            row.addWidget(button)
        self.task_layout.addLayout(row)

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(100 if self.step6_exported else 0)
        bar.setMaximumHeight(8)
        self.task_layout.addWidget(bar)

        actions = QHBoxLayout()
        go = QPushButton(t("tutorial.step6_export"))
        go.setObjectName("primary")
        go.setMinimumHeight(36)
        go.setEnabled(bool(self.step6_target) and not self.step6_exported)
        go.clicked.connect(self._export_preview)
        actions.addWidget(go)
        if self.step6_exported:
            start = QPushButton(t("tutorial.step6_start"))
            start.setObjectName("teal")
            start.setMinimumHeight(36)
            start.clicked.connect(self._launch_new_project)
            actions.addWidget(start)
        actions.addStretch(1)
        self.task_layout.addLayout(actions)

        if self.step6_exported:
            target = t(f"tutorial.step6_{self.step6_target}") if self.step6_target else ""
            self.task_layout.addWidget(
                self._feedback(t("tutorial.step6_ok", target=target))
            )

    def _choose_export(self, key: str) -> None:
        self.step6_target = key
        self._render()

    def _export_preview(self) -> None:
        if not self.step6_target:
            return
        self.step6_exported = True
        self.completed[5] = True
        self._render()

    def _launch_new_project(self) -> None:
        self.launch_action = "new_project"
        self._finish()

    # ------------------------------------------------------------------
    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Right, Qt.Key.Key_PageDown):
            self.next()
            return
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_PageUp):
            self.back()
            return
        if event.key() == Qt.Key.Key_Escape:
            self._finish()
            return
        super().keyPressEvent(event)


def show_tutorial(settings: Settings, parent: QWidget | None = None) -> str:
    """Always show the quick start; returns a requested follow-up action."""
    dialog = TutorialDialog(settings, parent)
    dialog.exec()
    return dialog.launch_action


def maybe_show_tutorial(settings: Settings, parent: QWidget | None = None) -> str:
    """Show the quick start on the first launch only.

    Returns ``""`` when the tour was already seen (or was simply finished) and
    ``"new_project"`` when the user asked to create a project right away.
    """
    if settings.tutorial_seen():
        return ""
    dialog = TutorialDialog(settings, parent)
    dialog.exec()
    return dialog.launch_action
