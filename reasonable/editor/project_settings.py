"""Edit the project manifest from the editor."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .widgets import Badge, Card, muted, title_label


class ProjectSettingsDialog(QDialog):
    saved = Signal()

    def __init__(self, project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self.setWindowTitle("Настройки проекта")
        self.setMinimumSize(720, 640)
        self.resize(780, 820)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(12)
        header = QHBoxLayout()
        title = QLabel("Настройки проекта")
        title.setObjectName("title")
        title.setFont(theme.display_font(16, 700))
        header.addWidget(title)
        header.addStretch(1)
        self.advanced_check = QCheckBox("Расширенные параметры")
        self.advanced_check.setToolTip("Окно, ориентация и параметры Android.")
        header.addWidget(self.advanced_check)
        header.addWidget(Badge("ИГРА" if project.project_type == "game" else "ПРИЛОЖЕНИЕ", "default"))
        header.addWidget(Badge("WINDOWS" if project.platform == "windows" else "ANDROID", "default"))
        header.addWidget(Badge("ВСТРОЕННЫЙ" if project.mode == "builtin" else "ВНЕШНИЙ", "default"))
        layout.addLayout(header)
        layout.addWidget(muted(
            "Меняйте название, цель и заметки в любой момент. Окно, ориентация и Android — "
            "под переключателем «Расширенные параметры». Папка проекта остаётся на месте.",
            size=9,
        ))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("root")
        self.body_layout = QVBoxLayout(body)
        self.body_layout.setContentsMargins(4, 4, 12, 8)
        self.body_layout.setSpacing(12)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)

        card = Card()
        form = QFormLayout()
        form.setSpacing(10)
        self.name_edit = QLineEdit(project.name)
        self.name_edit.setCursorPosition(0)
        form.addRow("Название", self.name_edit)
        self.author_edit = QLineEdit(str(project.manifest.get("author") or ""))
        self.author_edit.setCursorPosition(0)
        form.addRow("Автор", self.author_edit)
        self.goal_edit = QLineEdit(project.goal)
        self.goal_edit.setMinimumHeight(38)
        self.goal_edit.setCursorPosition(0)
        form.addRow("Главная цель", self.goal_edit)

        self.notes_edit = QTextEdit()
        self.notes_edit.setPlainText(project.notes)
        self.notes_edit.setMinimumHeight(140)
        self.notes_edit.setPlaceholderText(
            "Необязательные требования и пожелания. Первую задачу агенту пишите в разделе «ИИ-агент»."
        )
        form.addRow("Заметки и требования", self.notes_edit)
        card.layout().addLayout(form)
        self.body_layout.addWidget(card)

        window_card = Card(soft=True)
        window_form = QFormLayout()
        window_form.setSpacing(10)
        self.window_mode_combo = QComboBox()
        self.window_mode_combo.addItem("Окно", "windowed")
        self.window_mode_combo.addItem("Полноэкранный", "fullscreen")
        self.window_mode_combo.setCurrentIndex(1 if project.fullscreen else 0)
        window_form.addRow("Режим запуска", self.window_mode_combo)
        self.width_spin = QSpinBox()
        self.width_spin.setRange(320, 3840)
        self.width_spin.setValue(int(project.window.get("width", 1280)))
        window_form.addRow("Базовая ширина", self.width_spin)
        self.height_spin = QSpinBox()
        self.height_spin.setRange(240, 2160)
        self.height_spin.setValue(int(project.window.get("height", 720)))
        window_form.addRow("Базовая высота", self.height_spin)
        self.resizable_check = QCheckBox("Разрешить менять размер окна")
        self.resizable_check.setChecked(project.resizable)
        window_form.addRow("", self.resizable_check)
        self.orientation_combo = QComboBox()
        self.orientation_combo.addItem("Альбомная", "landscape")
        self.orientation_combo.addItem("Портретная", "portrait")
        current = str(project.manifest.get("orientation") or "landscape")
        self.orientation_combo.setCurrentIndex(1 if current == "portrait" else 0)
        window_form.addRow("Ориентация", self.orientation_combo)
        self.version_edit = QLineEdit(str((project.manifest.get("android") or {}).get("version") or "1.0.0"))
        self.version_edit.setCursorPosition(0)
        window_form.addRow("Версия Android", self.version_edit)
        window_card.layout().addLayout(window_form)
        window_card.layout().addWidget(
            muted(
                "Параметры окна читаются из project.json при запуске. F11 переключает "
                "полный экран, RE_FULLSCREEN=1 запускает сразу на весь экран. Android-ориентация "
                "применяется при следующем экспорте. Платформа проекта меняется через "
                "«Конвертировать…» — создаётся новый проект, эта папка остаётся как есть.",
                size=8,
            )
        )
        self.body_layout.addWidget(window_card)
        self.window_card = window_card
        window_card.hide()
        self.advanced_check.toggled.connect(window_card.setVisible)
        self.body_layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        save = QPushButton("Сохранить")
        save.setObjectName("primary")
        save.setMinimumWidth(140)
        save.clicked.connect(self._save)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def _save(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Название", "Название проекта не может быть пустым.")
            return
        width = int(self.width_spin.value())
        height = int(self.height_spin.value())
        self.project.manifest["name"] = name
        self.project.manifest["author"] = self.author_edit.text().strip()
        self.project.manifest["goal"] = self.goal_edit.text().strip()
        self.project.manifest["notes"] = self.notes_edit.toPlainText().strip()
        self.project.manifest.pop("prompts", None)
        window = self.project.manifest.setdefault("window", {})
        window["width"] = width
        window["height"] = height
        window["title"] = name
        window["mode"] = self.window_mode_combo.currentData() or "windowed"
        window["resizable"] = bool(self.resizable_check.isChecked())
        orientation = self.orientation_combo.currentData() or "landscape"
        self.project.manifest["orientation"] = orientation
        android = self.project.manifest.setdefault("android", {})
        android["orientation"] = orientation
        android["version"] = self.version_edit.text().strip() or "1.0.0"
        try:
            self.project.save()
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка сохранения", str(exc))
            return
        try:
            from reasonable.ai.external import generate_agent_pack

            generate_agent_pack(self.project)
        except Exception:
            pass
        self.saved.emit()
        self.accept()
