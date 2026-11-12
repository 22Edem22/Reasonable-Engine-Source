"""Register a folder that already contains code as a Reasonable Engine project.

Opening a folder normally requires ``project.json``. For an existing project
made outside the editor, this dialog asks what the project is, then the caller
writes a manifest without touching the user's files.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from reasonable.core.i18n import t
from reasonable.core.project import default_manifest
from reasonable.version import VERSION_LABEL

from . import theme
from .widgets import Card, muted


class ImportProjectDialog(QDialog):
    """Ask for the manifest fields of an existing folder."""

    def __init__(self, folder: str | Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.folder = Path(folder).resolve()
        self.manifest: dict | None = None
        self.setWindowTitle(t("importproj.title"))
        self.setMinimumSize(720, 620)
        self.resize(760, 660)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(12)

        title = QLabel(t("importproj.title"))
        title.setObjectName("title")
        title.setFont(theme.display_font(16, 700))
        layout.addWidget(title)
        intro = muted(t("importproj.intro"), size=9)
        intro.setWordWrap(True)
        layout.addWidget(intro)

        folder_label = QLabel(str(self.folder))
        folder_label.setObjectName("dim")
        folder_label.setWordWrap(True)
        folder_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(folder_label)

        card = Card()
        form = QFormLayout()
        form.setSpacing(10)
        self.name_edit = QLineEdit(self.folder.name)
        self.name_edit.setMinimumHeight(34)
        form.addRow(t("common.name"), self.name_edit)

        self.entry_edit = QLineEdit(self._detect_entry())
        self.entry_edit.setMinimumHeight(34)
        self.entry_edit.setToolTip(t("importproj.entry_tip"))
        form.addRow(t("importproj.entry"), self.entry_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItem(t("importproj.type_game"), "game")
        self.type_combo.addItem(t("importproj.type_app"), "app")
        self.type_combo.addItem(t("importproj.type_site"), "site")
        self.type_combo.addItem(t("importproj.type_other"), "other")
        form.addRow(t("importproj.type"), self.type_combo)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem(t("importproj.mode_builtin"), "builtin")
        self.mode_combo.addItem(t("importproj.mode_external"), "external")
        form.addRow(t("importproj.mode"), self.mode_combo)

        self.goal_edit = QLineEdit()
        self.goal_edit.setMinimumHeight(34)
        self.goal_edit.setPlaceholderText(t("newproj.goal_placeholder"))
        form.addRow(t("projset.goal"), self.goal_edit)

        self.notes_edit = QTextEdit()
        self.notes_edit.setMinimumHeight(110)
        self.notes_edit.setPlaceholderText(t("projset.notes_placeholder"))
        form.addRow(t("projset.notes"), self.notes_edit)
        card.layout().addLayout(form)
        layout.addWidget(card, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton(t("common.cancel"))
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        create = QPushButton(t("importproj.create"))
        create.setObjectName("primary")
        create.setMinimumWidth(220)
        create.clicked.connect(self._accept)
        buttons.addWidget(create)
        layout.addLayout(buttons)

    def _detect_entry(self) -> str:
        if (self.folder / "main.py").is_file():
            return "main.py"
        skip = {"setup.py", "conftest.py", "run_editor.py"}
        candidates = sorted(
            path.name
            for path in self.folder.glob("*.py")
            if path.is_file() and path.name not in skip
        )
        return candidates[0] if candidates else "main.py"

    def _accept(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, t("common.name"), t("importproj.name_required"))
            return
        entry = self.entry_edit.text().strip().replace("\\", "/") or "main.py"
        entry_path = Path(entry)
        if entry_path.is_absolute() or ".." in entry_path.parts:
            QMessageBox.warning(self, t("importproj.entry"), t("importproj.entry_invalid"))
            return
        manifest = default_manifest(
            name,
            project_type=str(self.type_combo.currentData() or "game"),
            mode=str(self.mode_combo.currentData() or "builtin"),
            goal=self.goal_edit.text().strip(),
            notes=self.notes_edit.toPlainText().strip(),
            template="blank",
        )
        manifest["entry"] = entry
        manifest["engine_version"] = VERSION_LABEL
        self.manifest = manifest
        self.accept()
