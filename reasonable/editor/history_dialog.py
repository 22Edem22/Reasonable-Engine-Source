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
    REASON_LABELS,
    create_snapshot,
    delete_snapshot,
    describe_snapshot,
    list_snapshots,
    restore_snapshot,
    snapshot_files,
)
from reasonable.core.paths import human_time

from . import theme
from .widgets import Badge, Card, muted, title_label

ACTION_LABELS = {
    "create": "создан",
    "edit": "изменён",
    "delete": "удалён",
    "generate": "сгенерирован",
}


class HistoryDialog(QDialog):
    restored = Signal(str)
    snapshot_created = Signal(object)

    def __init__(self, project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self.snapshots: list[dict] = []
        self._current: dict | None = None

        self.setWindowTitle("История версий — Reasonable Engine")
        self.setMinimumSize(880, 640)
        self.resize(960, 720)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(12)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = QLabel("История версий")
        title.setObjectName("title")
        title.setFont(theme.display_font(17, 700))
        titles.addWidget(title)
        titles.addWidget(
            muted(
                "Перед каждым запуском ИИ-агента сохраняется полная рабочая версия. "
                "Любую из них можно вернуть — текущее состояние тоже сохранится.",
                size=9,
            )
        )
        header.addLayout(titles, 1)
        create = QPushButton("＋  Создать снимок")
        create.setObjectName("primary")
        create.clicked.connect(self._create)
        header.addWidget(create)
        layout.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(14)

        left = QVBoxLayout()
        left.setSpacing(6)
        left.addWidget(title_label("Версии", 11))
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
            "Снимков пока нет. Они появятся автоматически перед первым запуском агента "
            "или по кнопке «Создать снимок».",
            size=9,
        )
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_layout.addWidget(self.empty)
        self.detail_layout.addStretch(1)

        footer = QHBoxLayout()
        self.status = muted("", size=9)
        footer.addWidget(self.status, 1)
        close = QPushButton("Закрыть")
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
            suffix = f" · {changed} файл(ов)" if changed else ""
            item = QListWidgetItem(
                f"{human_time(snapshot.get('created_at'))}  ·  {describe_snapshot(snapshot)}{suffix}"
            )
            item.setToolTip(
                f"{snapshot.get('label')}\n"
                f"{snapshot.get('created_at')}\n"
                f"Файлов: {snapshot.get('file_count', 0)} · {snapshot.get('reason')}"
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
        self.status.setText(f"Сохранено версий: {len(self.snapshots)}")

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
                muted("Выберите версию слева, чтобы увидеть файлы и вернуть её.", size=9)
            )
            self.detail_layout.addStretch(1)
            return

        card = Card()
        top = QHBoxLayout()
        name = QLabel(str(snapshot.get("label") or "Снимок"))
        name.setObjectName("title")
        name.setFont(theme.display_font(13, 700))
        name.setWordWrap(True)
        top.addWidget(name, 1)
        reason = str(snapshot.get("reason") or "manual")
        top.addWidget(Badge(REASON_LABELS.get(reason, "Снимок"), "default"))
        card.layout().addLayout(top)
        card.layout().addWidget(
            muted(
                f"{human_time(snapshot.get('created_at'))} · файлов: {snapshot.get('file_count', 0)} · "
                f"{round(int(snapshot.get('bytes') or 0) / 1024)} КБ",
                size=9,
            )
        )
        outcome = str(snapshot.get("outcome") or "")
        if outcome:
            labels = {
                "done": "Агент завершил работу",
                "incomplete": "Агент не завершил работу",
                "cancelled": "Работа остановлена",
                "error": "Ошибка агента",
                "stopped": "Агент остановился",
            }
            card.layout().addWidget(
                muted(f"Результат запуска: {labels.get(outcome, outcome)}", size=9)
            )
        self.detail_layout.addWidget(card)

        changed = snapshot.get("changed_files") or []
        if changed:
            changed_card = Card(soft=True)
            changed_card.layout().addWidget(title_label("Файлы, изменённые после снимка", 11))
            for row in changed[:40]:
                path = str(row.get("path") or "")
                action = str(row.get("action") or "edit")
                label = QLabel(f"{path}  ·  {ACTION_LABELS.get(action, action)}")
                label.setWordWrap(True)
                label.setFont(theme.ui_font(9))
                label.setStyleSheet("color: #C1C7CF;")
                changed_card.layout().addWidget(label)
            self.detail_layout.addWidget(changed_card)

        files = snapshot_files(self.project, str(snapshot.get("id")), limit=120)
        files_card = Card(soft=True)
        files_card.layout().addWidget(title_label("Содержимое снимка", 11))
        preview = QLabel("\n".join(files) if files else "В снимке нет файлов.")
        preview.setWordWrap(True)
        preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        preview.setFont(theme.ui_font(9))
        preview.setStyleSheet("color: #9AA1AB;")
        files_card.layout().addWidget(preview)
        self.detail_layout.addWidget(files_card)

        actions = QHBoxLayout()
        restore = QPushButton("↶  Вернуть эту версию")
        restore.setObjectName("primary")
        restore.clicked.connect(self._restore)
        actions.addWidget(restore)
        folder = QPushButton("Открыть папку снимка")
        folder.setObjectName("ghost")
        folder.clicked.connect(self._open_folder)
        actions.addWidget(folder)
        actions.addStretch(1)
        delete = QPushButton("Удалить снимок")
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
                label="Ручной снимок рабочей версии",
                reason="manual",
            )
        except Exception as exc:
            QMessageBox.warning(self, "Не удалось создать снимок", str(exc))
            return
        self.snapshot_created.emit(snapshot)
        self.refresh(select_id=str(snapshot.get("id")))
        self.status.setText("Снимок создан. Теперь его можно вернуть в любой момент.")

    def _restore(self) -> None:
        if self._current is None:
            return
        snapshot = self._current
        answer = QMessageBox.question(
            self,
            "Вернуть версию",
            f"Вернуть версию «{snapshot.get('label')}»?\n\n"
            "Файлы проекта будут заменены содержимым снимка. Текущее состояние "
            "сначала сохранится отдельным снимком, поэтому действие можно отменить.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            result = restore_snapshot(self.project, str(snapshot.get("id")), safety=True)
        except Exception as exc:
            QMessageBox.critical(self, "Не удалось вернуть версию", str(exc))
            return
        self.refresh(select_id=str(snapshot.get("id")))
        self.status.setText(
            f"Версия возвращена: файлов восстановлено {result.get('restored', 0)}, "
            f"удалено {result.get('removed', 0)}. Текущее состояние сохранено отдельно."
        )
        self.restored.emit(str(snapshot.get("id")))

    def _delete(self) -> None:
        if self._current is None:
            return
        snapshot = self._current
        answer = QMessageBox.question(
            self,
            "Удалить снимок",
            f"Удалить снимок «{snapshot.get('label')}»? Это освободит место, но вернуть "
            "эту версию будет уже нельзя.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if delete_snapshot(self.project, str(snapshot.get("id"))):
            self.refresh()
            self.status.setText("Снимок удалён.")

    def _open_folder(self) -> None:
        if self._current is None:
            return
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        path = Path(str(self._current.get("path") or ""))
        if path.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
