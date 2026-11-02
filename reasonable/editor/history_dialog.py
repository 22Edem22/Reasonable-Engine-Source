"""Version history dialog: inspect, compare and restore project snapshots."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from reasonable.core.history import (
    create_snapshot,
    delete_snapshot,
    describe_snapshot,
    list_snapshots,
    reason_label,
    restore_snapshot,
    snapshot_files,
)
from reasonable.core.i18n import t
from reasonable.core.paths import human_time

from . import theme
from .widgets import Badge, Card, muted, title_label

ACTION_KEYS = {
    "create": "historydlg.action_create",
    "edit": "historydlg.action_edit",
    "delete": "historydlg.action_delete",
    "generate": "historydlg.action_generate",
}


def _action_label(action: str) -> str:
    key = ACTION_KEYS.get(action)
    return t(key) if key else action


class HistoryDialog(QDialog):
    restored = Signal(str)
    snapshot_created = Signal(object)

    def __init__(self, project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self.snapshots: list[dict] = []
        self._current: dict | None = None

        self.setWindowTitle(t("historydlg.title"))
        self.setMinimumSize(880, 640)
        self.resize(960, 720)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(12)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = QLabel(t("historydlg.heading"))
        title.setObjectName("title")
        title.setFont(theme.display_font(17, 700))
        titles.addWidget(title)
        titles.addWidget(
            muted(
                t("historydlg.subtitle"),
                size=9,
            )
        )
        header.addLayout(titles, 1)
        create = QPushButton(t("historydlg.create_button"))
        create.setObjectName("primary")
        create.clicked.connect(self._create)
        header.addWidget(create)
        layout.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(14)

        left = QVBoxLayout()
        left.setSpacing(6)
        left.addWidget(title_label(t("historydlg.versions_label"), 11))
        self.list = QListWidget()
        self.list.setObjectName("historyList")
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.currentItemChanged.connect(self._selected)
        left.addWidget(self.list, 1)
        body.addLayout(left, 2)

        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right_host = QWidget()
        right_host.setObjectName("root")
        self.detail_layout = QVBoxLayout(right_host)
        self.detail_layout.setContentsMargins(0, 0, 6, 4)
        self.detail_layout.setSpacing(12)
        right_scroll.setWidget(right_host)
        body.addWidget(right_scroll, 3)
        layout.addLayout(body, 1)

        self.empty = muted(
            t("historydlg.empty_hint"),
            size=9,
        )
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_layout.addWidget(self.empty)
        self.detail_layout.addStretch(1)

        footer = QHBoxLayout()
        self.status = muted("", size=9)
        footer.addWidget(self.status, 1)
        close = QPushButton(t("common.close"))
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        layout.addLayout(footer)

        self.refresh()

    # ------------------------------------------------------------------
    def refresh(self, select_id: str | None = None) -> None:
        self.snapshots = list_snapshots(self.project)
        self.list.blockSignals(True)
        self.list.clear()
        for snapshot in self.snapshots:
            changed = len(snapshot.get("changed_files") or [])
            suffix = t("historydlg.changed_suffix", count=changed) if changed else ""
            item = QListWidgetItem(
                f"{human_time(snapshot.get('created_at'))}  ·  {describe_snapshot(snapshot)}{suffix}"
            )
            item.setToolTip(
                f"{snapshot.get('label')}\n"
                f"{snapshot.get('created_at')}\n"
                f"{t('historydlg.files_count_tooltip', count=snapshot.get('file_count', 0))}"
                f" · {snapshot.get('reason')}"
            )
            item.setData(Qt.ItemDataRole.UserRole, snapshot.get("id"))
            self.list.addItem(item)
        self.list.blockSignals(False)
        if self.list.count():
            target = 0
            if select_id:
                for index in range(self.list.count()):
                    if self.list.item(index).data(Qt.ItemDataRole.UserRole) == select_id:
                        target = index
                        break
            self.list.setCurrentRow(target)
        else:
            self._current = None
            self._render(None)
        self.status.setText(t("historydlg.saved_versions", count=len(self.snapshots)))

    def _selected(self, current: QListWidgetItem | None, _previous) -> None:
        if current is None:
            self._current = None
            self._render(None)
            return
        snapshot_id = current.data(Qt.ItemDataRole.UserRole)
        self._current = next(
            (snapshot for snapshot in self.snapshots if snapshot.get("id") == snapshot_id),
            None,
        )
        self._render(self._current)

    def _clear_details(self) -> None:
        while self.detail_layout.count():
            item = self.detail_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            elif item.layout() is not None:
                self._clear_layout(item.layout())

    @classmethod
    def _clear_layout(cls, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            elif item.layout() is not None:
                cls._clear_layout(item.layout())

    def _render(self, snapshot: dict | None) -> None:
        self._clear_details()
        if snapshot is None:
            self.detail_layout.addWidget(
                muted(t("historydlg.select_hint"), size=9)
            )
            self.detail_layout.addStretch(1)
            return

        card = Card()
        top = QHBoxLayout()
        name = QLabel(str(snapshot.get("label") or t("history.snapshot")))
        name.setObjectName("title")
        name.setFont(theme.display_font(13, 700))
        name.setWordWrap(True)
        top.addWidget(name, 1)
        reason = str(snapshot.get("reason") or "manual")
        top.addWidget(Badge(reason_label(reason), "default"))
        card.layout().addLayout(top)
        card.layout().addWidget(
            muted(
                t(
                    "historydlg.size_line",
                    time=human_time(snapshot.get("created_at")),
                    count=snapshot.get("file_count", 0),
                    kb=round(int(snapshot.get("bytes") or 0) / 1024),
                ),
                size=9,
            )
        )
        outcome = str(snapshot.get("outcome") or "")
        if outcome:
            labels = {
                "done": t("historydlg.outcome_done"),
                "incomplete": t("historydlg.outcome_incomplete"),
                "cancelled": t("historydlg.outcome_cancelled"),
                "error": t("historydlg.outcome_error"),
                "stopped": t("historydlg.outcome_stopped"),
            }
            card.layout().addWidget(
                muted(t("historydlg.outcome_line", outcome=labels.get(outcome, outcome)), size=9)
            )
        self.detail_layout.addWidget(card)

        changed = snapshot.get("changed_files") or []
        if changed:
            changed_card = Card(soft=True)
            changed_card.layout().addWidget(title_label(t("historydlg.changed_after_title"), 11))
            for row in changed[:40]:
                path = str(row.get("path") or "")
                action = str(row.get("action") or "edit")
                label = QLabel(f"{path}  ·  {_action_label(action)}")
                label.setWordWrap(True)
                label.setFont(theme.ui_font(9))
                label.setStyleSheet("color: #C1C7CF;")
                changed_card.layout().addWidget(label)
            self.detail_layout.addWidget(changed_card)

        files = snapshot_files(self.project, str(snapshot.get("id")), limit=120)
        files_card = Card(soft=True)
        files_card.layout().addWidget(title_label(t("historydlg.snapshot_contents"), 11))
        preview = QLabel("\n".join(files) if files else t("history.snapshot_empty"))
        preview.setWordWrap(True)
        preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        preview.setFont(theme.ui_font(9))
        preview.setStyleSheet("color: #9AA1AB;")
        files_card.layout().addWidget(preview)
        self.detail_layout.addWidget(files_card)

        actions = QHBoxLayout()
        restore = QPushButton(t("historydlg.restore_button"))
        restore.setObjectName("primary")
        restore.clicked.connect(self._restore)
        actions.addWidget(restore)
        folder = QPushButton(t("historydlg.open_folder_button"))
        folder.setObjectName("ghost")
        folder.clicked.connect(self._open_folder)
        actions.addWidget(folder)
        actions.addStretch(1)
        delete = QPushButton(t("historydlg.delete_button"))
        delete.setObjectName("danger")
        delete.clicked.connect(self._delete)
        actions.addWidget(delete)
        self.detail_layout.addLayout(actions)
        self.detail_layout.addStretch(1)

    # ------------------------------------------------------------------
    def _create(self) -> None:
        try:
            snapshot = create_snapshot(
                self.project,
                label=t("historydlg.manual_snapshot_label"),
                reason="manual",
            )
        except Exception as exc:
            QMessageBox.warning(self, t("historydlg.create_failed_title"), str(exc))
            return
        self.snapshot_created.emit(snapshot)
        self.refresh(select_id=str(snapshot.get("id")))
        self.status.setText(t("historydlg.created_status"))

    def _restore(self) -> None:
        if self._current is None:
            return
        snapshot = self._current
        answer = QMessageBox.question(
            self,
            t("historydlg.restore_title"),
            t("historydlg.restore_text", label=snapshot.get("label")),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            result = restore_snapshot(self.project, str(snapshot.get("id")), safety=True)
        except Exception as exc:
            QMessageBox.critical(self, t("historydlg.restore_failed_title"), str(exc))
            return
        self.refresh(select_id=str(snapshot.get("id")))
        self.status.setText(
            t(
                "historydlg.restored_status",
                restored=result.get("restored", 0),
                removed=result.get("removed", 0),
            )
        )
        self.restored.emit(str(snapshot.get("id")))

    def _delete(self) -> None:
        if self._current is None:
            return
        snapshot = self._current
        answer = QMessageBox.question(
            self,
            t("historydlg.delete_button"),
            t("historydlg.delete_text", label=snapshot.get("label")),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if delete_snapshot(self.project, str(snapshot.get("id"))):
            self.refresh()
            self.status.setText(t("historydlg.deleted_status"))

    def _open_folder(self) -> None:
        if self._current is None:
            return
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        path = Path(str(self._current.get("path") or ""))
        if path.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
