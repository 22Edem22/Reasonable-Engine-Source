"""Create a converted copy of a project (Windows <-> Android and variants)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from reasonable.core.convert import PLATFORM_NAMES, conversion_plan

from . import theme
from .widgets import Badge, Card, muted, title_label
from .workers import ConvertWorker


class ConvertDialog(QDialog):
    """Copy the project and apply platform/settings changes to the copy."""

    converted = Signal(str)

    def __init__(self, project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self.worker: ConvertWorker | None = None
        self.result: dict | None = None
        self.target = "android" if project.platform == "windows" else "windows"
        self._running = False
        self._plan: dict | None = None

        self.setWindowTitle("Конвертировать проект — Reasonable Engine")
        self.setMinimumSize(840, 700)
        self.resize(880, 790)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(12)
        root.addLayout(self._build_header())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("root")
        self.body_layout = QVBoxLayout(body)
        self.body_layout.setContentsMargins(4, 4, 12, 8)
        self.body_layout.setSpacing(12)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        self.body_layout.addWidget(self._build_platform_card())
        self.body_layout.addWidget(self._build_target_card())
        self.body_layout.addWidget(self._build_options_card())
        self.body_layout.addWidget(self._build_preview_card())
        self.body_layout.addWidget(self._build_limits_card())
        self.body_layout.addStretch(1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        root.addWidget(self.progress)
        self.status = muted("", size=9)
        root.addWidget(self.status)

        self.result_card = Card(soft=True)
        self.result_card.hide()
        result_title = title_label("Новый проект готов", 11)
        self.result_card.layout().addWidget(result_title)
        self.result_text = muted("", size=9)
        self.result_text.setWordWrap(True)
        self.result_card.layout().addWidget(self.result_text)
        result_buttons = QHBoxLayout()
        self.open_folder = QPushButton("Открыть папку")
        self.open_folder.setObjectName("ghost")
        self.open_folder.clicked.connect(self._open_folder)
        result_buttons.addWidget(self.open_folder)
        result_buttons.addStretch(1)
        self.open_new = QPushButton("Открыть новый проект")
        self.open_new.setObjectName("teal")
        self.open_new.clicked.connect(self._open_new)
        result_buttons.addWidget(self.open_new)
        self.result_card.layout().addLayout(result_buttons)
        root.addWidget(self.result_card)

        footer = QHBoxLayout()
        close = QPushButton("Закрыть")
        close.clicked.connect(self.reject)
        footer.addWidget(close)
        footer.addStretch(1)
        self.convert_button = QPushButton("Создать новый проект")
        self.convert_button.setObjectName("primary")
        self.convert_button.setMinimumWidth(200)
        self.convert_button.clicked.connect(self._start)
        footer.addWidget(self.convert_button)
        root.addLayout(footer)

        for key, button in self.platform_buttons.items():
            button.toggled.connect(
                lambda checked=False, key=key: checked and self._select_platform(key)
            )
        self.name_edit.textChanged.connect(self._refresh_preview)
        self.folder_edit.textChanged.connect(self._refresh_preview)
        self.orientation_combo.currentIndexChanged.connect(self._refresh_preview)
        self.agent_combo.currentIndexChanged.connect(self._refresh_preview)
        self.reset_check.toggled.connect(self._refresh_preview)

        self.platform_buttons[self.target].setChecked(True)
        self._select_platform(self.target)
        self._refresh_preview()

    # ------------------------------------------------------------------
    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(theme.logo_pixmap(32))
        row.addWidget(logo)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        title = QLabel("Конвертировать проект")
        title.setObjectName("title")
        title.setFont(theme.display_font(15, 700))
        titles.addWidget(title)
        titles.addWidget(
            muted(
                "Создаётся отдельная папка. Исходный проект остаётся без изменений.",
                wrap=False,
                size=9,
            )
        )
        row.addLayout(titles)
        row.addStretch(1)
        row.addWidget(Badge(self.project.name, "default"))
        row.addWidget(
            Badge(
                "WINDOWS" if self.project.platform == "windows" else "ANDROID",
                "default",
            )
        )
        return row

    def _build_platform_card(self) -> Card:
        card = Card()
        top = QHBoxLayout()
        top.addWidget(title_label("Новая платформа", 11))
        top.addStretch(1)
        top.addWidget(
            muted(
                f"Сейчас: {PLATFORM_NAMES[self.project.platform]}",
                wrap=False,
                size=8,
            )
        )
        card.layout().addLayout(top)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.platform_group = QButtonGroup(self)
        self.platform_buttons: dict[str, QPushButton] = {}
        for key, text, hint in (
            ("windows", "WINDOWS", "Папка, Play.bat и опционально .exe"),
            ("android", "ANDROID", "buildozer-пакет, касания и портрет/альбом"),
        ):
            button = QPushButton(f"{text}\n{hint}")
            button.setObjectName("choice")
            button.setCheckable(True)
            button.setMinimumHeight(68)
            button.setFont(theme.ui_font(9, 700))
            self.platform_group.addButton(button)
            self.platform_buttons[key] = button
            row.addWidget(button)
        card.layout().addLayout(row)
        self.platform_hint = muted("", size=9)
        self.platform_hint.setWordWrap(True)
        card.layout().addWidget(self.platform_hint)
        return card

    def _build_target_card(self) -> Card:
        card = Card(soft=True)
        card.layout().addWidget(title_label("Название и папка", 10))
        form = QFormLayout()
        form.setSpacing(9)
        self.name_edit = QLineEdit(self.project.name)
        self.name_edit.setPlaceholderText("Название нового проекта")
        form.addRow("Название", self.name_edit)
        folder_row = QHBoxLayout()
        self.folder_edit = QLineEdit(str(self.project.root.parent))
        folder_row.addWidget(self.folder_edit, 1)
        browse = QPushButton("Выбрать…")
        browse.clicked.connect(self._browse)
        folder_row.addWidget(browse)
        form.addRow("Папка", folder_row)
        card.layout().addLayout(form)
        card.layout().addWidget(
            muted(
                "В выбранной папке появится новая подпапка. Если имя занято, добавится суффикс -2.",
                size=8,
            )
        )
        return card

    def _build_options_card(self) -> Card:
        card = Card()
        card.layout().addWidget(title_label("Что ещё можно изменить", 10))
        form = QFormLayout()
        form.setSpacing(9)

        self.orientation_combo = QComboBox()
        for label, value in (
            ("Как в проекте", None),
            ("Альбомная", "landscape"),
            ("Портретная", "portrait"),
        ):
            self.orientation_combo.addItem(label, value)
        form.addRow("Ориентация", self.orientation_combo)

        self.agent_combo = QComboBox()
        for label, value in (
            ("Как в проекте", None),
            ("Встроенный ИИ", "builtin"),
            ("Внешний агент", "external"),
        ):
            self.agent_combo.addItem(label, value)
        form.addRow("Режим агента", self.agent_combo)

        self.level_checks: dict[str, QCheckBox] = {}
        from reasonable.core.project import UI_LEVELS, UI_LEVEL_LABELS

        levels_row = QHBoxLayout()
        levels_row.setSpacing(8)
        current_levels = set(self.project.ui_levels)
        for level in UI_LEVELS:
            check = QCheckBox(UI_LEVEL_LABELS[level])
            check.setChecked(level in current_levels)
            check.toggled.connect(self._levels_changed)
            self.level_checks[level] = check
            levels_row.addWidget(check)
        levels_row.addStretch(1)
        form.addRow("Уровень интерфейса", levels_row)

        card.layout().addLayout(form)
        self.reset_check = QCheckBox("Сбросить план, прогресс и ленту событий в новом проекте")
        card.layout().addWidget(self.reset_check)
        card.layout().addWidget(
            muted(
                "Окно, разрешение и ориентацию агент подберёт сам — здесь это не настраивается. "
                "Код и ассеты не переписываются: после создания попросите агента адаптировать "
                "компоновку под новую платформу. APK собирается через buildozer на Linux/WSL2.",
                size=8,
            )
        )
        return card

    def _build_preview_card(self) -> Card:
        card = Card(soft=True)
        top = QHBoxLayout()
        top.addWidget(title_label("Предпросмотр", 10))
        top.addStretch(1)
        self.preview_badge = Badge("—", "default")
        top.addWidget(self.preview_badge)
        card.layout().addLayout(top)
        self.preview_text = muted("", size=9)
        self.preview_text.setWordWrap(True)
        card.layout().addWidget(self.preview_text)
        self.preview_path = QLabel("")
        self.preview_path.setObjectName("muted")
        self.preview_path.setFont(theme.ui_font(8))
        self.preview_path.setWordWrap(True)
        card.layout().addWidget(self.preview_path)
        return card

    def _build_limits_card(self) -> Card:
        card = Card(soft=True, padding=13)
        card.layout().addWidget(title_label("Что важно знать", 10))
        card.layout().addWidget(
            muted(
                "Платформа — главная ось конвертации. Ориентация, агент, окно и разрешение "
                "применяются к копии сразу. Код и ассеты не переписываются: после создания "
                "попросите агента адаптировать компоновку, управление и safe margins под Android. "
                "APK по-прежнему собирается через buildozer на Linux/WSL2.",
                size=9,
            )
        )
        return card

    # ------------------------------------------------------------------
    def _target_options(self) -> dict:
        resolution = self.resolution_combo.currentData()
        width = height = None
        if isinstance(resolution, tuple):
            width, height = resolution
        elif resolution == "custom":
            width = int(self.width_spin.value())
            height = int(self.height_spin.value())
        name = self.name_edit.text().strip()
        return {
            "name": name or None,
            "output": self.folder_edit.text().strip() or None,
            "orientation": self.orientation_combo.currentData(),
            "mode": self.agent_combo.currentData(),
            "window_mode": self.window_combo.currentData(),
            "resizable": self.resizable_combo.currentData(),
            "width": width,
            "height": height,
            "reset_progress": bool(self.reset_check.isChecked()),
        }

    def _select_platform(self, target: str | None) -> None:
        if target not in PLATFORM_NAMES:
            return
        self.target = target
        self.platform_buttons[target].setChecked(True)
        self.result_card.hide()
        same = target == self.project.platform
        if target == "android":
            self.platform_hint.setText(
                "Android: проект получит android-ориентацию и пакет. "
                "Проверьте касания и размеры элементов; APK собирается на Linux/WSL2."
            )
        else:
            self.platform_hint.setText(
                "Windows: проект будет ориентирован на окно Windows, папку и .exe. "
                "Ориентация портрет тоже поддерживается, если она нужна приложению."
            )
        if same:
            self.platform_hint.setText(
                self.platform_hint.text()
                + " Платформа не меняется — это будет новая версия проекта."
            )
        self._refresh_preview()

    def _resolution_changed(self, _index: int) -> None:
        self.custom_size.setVisible(self.resolution_combo.currentData() == "custom")
        self._refresh_preview()

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Куда сохранить новый проект",
            self.folder_edit.text() or str(self.project.root.parent),
        )
        if folder:
            self.folder_edit.setText(folder)

    def _refresh_preview(self) -> None:
        if not hasattr(self, "preview_text") or self._running:
            return
        try:
            plan = conversion_plan(self.project, self.target, **self._target_options())
        except Exception as exc:
            self._plan = None
            self.preview_badge.setText("Ошибка")
            self.preview_badge.set_tone("gold")
            self.preview_text.setText(str(exc))
            self.preview_path.setText("")
            self.convert_button.setEnabled(False)
            return
        self._plan = plan
        if plan["has_changes"]:
            self.preview_badge.setText("ГОТОВО")
            self.preview_badge.set_tone("default")
            self.preview_text.setText("\n".join(f"· {change}" for change in plan["changes"]))
        else:
            self.preview_badge.setText("БЕЗ ИЗМЕНЕНИЙ")
            self.preview_badge.set_tone("gold")
            self.preview_text.setText(
                "Измените платформу, имя, ориентацию, окно, агент или прогресс — "
                "точную копию можно создать только с хотя бы одним отличием."
            )
        self.preview_path.setText(f"Новый проект: {plan['target_root']}")
        self.convert_button.setEnabled(plan["has_changes"] and not self._running)

    # ------------------------------------------------------------------
    def _start(self) -> None:
        if self._running:
            return
        self._refresh_preview()
        if self._plan is None or not self._plan.get("has_changes"):
            return
        options = self._target_options()
        self._running = True
        self.result_card.hide()
        self.progress.show()
        self.status.setText("Копирую проект…")
        self.convert_button.setEnabled(False)
        self.convert_button.setText("Конвертирую…")
        self.worker = ConvertWorker(self.project, self.target, options)
        self.worker.stage.connect(self.status.setText)
        self.worker.done.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _done(self, result: dict) -> None:
        self._running = False
        self.result = result
        self.progress.hide()
        self.status.setText(result.get("message", "Новый проект создан."))
        self.convert_button.setText("Создать ещё одну копию")
        self.convert_button.setEnabled(True)
        self.result_card.show()
        lines = [str(result.get("path", ""))]
        for change in result.get("changes") or []:
            lines.append("· " + change)
        lines.append("Исходный проект не изменён.")
        self.result_text.setText("\n".join(lines))

    def _failed(self, message: str, trace: str) -> None:
        self._running = False
        self.progress.hide()
        self.convert_button.setText("Создать новый проект")
        self.convert_button.setEnabled(True)
        self.status.setText("Ошибка: " + message)
        box = QMessageBox(self)
        box.setWindowTitle("Конвертация не удалась")
        box.setIcon(QMessageBox.Icon.Critical)
        box.setText(message)
        box.setDetailedText(trace)
        box.exec()

    def _open_folder(self) -> None:
        if not self.result:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(str(self.result["path"])))))

    def _open_new(self) -> None:
        if not self.result:
            return
        path = str(self.result.get("path") or "")
        if not path:
            return
        self.accept()
        self.converted.emit(path)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.worker is not None and self.worker.isRunning():
            answer = QMessageBox.question(
                self,
                "Конвертация",
                "Конвертация ещё выполняется. Закрыть окно?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        event.accept()
