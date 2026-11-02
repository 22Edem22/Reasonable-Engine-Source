"""Asset browser and sprite/background generation."""

from __future__ import annotations

import random
import shutil
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from reasonable.ai.providers import IMAGE_PROVIDERS
from reasonable.core.paths import slugify
from reasonable.core.i18n import t
from reasonable.core.settings import Settings

from . import theme
from .widgets import Badge, Card, EmptyState, muted, title_label
from .workers import SpriteWorker

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
AUDIO_SUFFIXES = {".wav", ".ogg", ".mp3", ".flac"}


class GenerateImageDialog(QDialog):
    created = Signal(str)

    def __init__(self, project, settings: Settings, parent: QWidget | None = None, *, background: bool = False) -> None:
        super().__init__(parent)
        self.project = project
        self.settings = settings
        self.background = background
        self.worker: SpriteWorker | None = None
        self.result_path = ""
        self.setWindowTitle(t("assets.gen_title_bg") if background else t("assets.gen_title_sprite"))
        self.setMinimumSize(660, 780)
        self.resize(700, 820)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = title_label(t("assets.new_bg") if background else t("assets.new_sprite"), 16)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(Badge(t("assets.badge_ai_gen"), "default"))
        layout.addLayout(header)
        layout.addWidget(
            muted(
                t("assets.intro"),
                size=9,
            )
        )

        card = Card()
        form_top = QHBoxLayout()
        form_top.setSpacing(10)
        name_box = QVBoxLayout()
        name_box.setSpacing(5)
        name_box.addWidget(self._label(t("assets.filename_label")))
        self.name_edit = QLineEdit("sprite" if not background else "background")
        name_box.addWidget(self.name_edit)
        form_top.addLayout(name_box, 1)
        layout.addWidget(card)
        card.layout().addLayout(form_top)

        self.prompt = QTextEdit()
        self.prompt.setPlaceholderText(
            t("assets.prompt_example_sprite")
            if not background
            else t("assets.prompt_example_bg")
        )
        self.prompt.setMinimumHeight(110)
        card.layout().addWidget(self.prompt)

        options = QHBoxLayout()
        options.setSpacing(10)
        style_box = QVBoxLayout()
        style_box.setSpacing(4)
        style_box.addWidget(self._label(t("assets.style_label")))
        self.style_combo = QComboBox()
        for key, name in (("flat", t("assets.style_flat")), ("pixel", t("assets.style_pixel")), ("painterly", t("assets.style_painterly")), ("icon", t("assets.style_icon"))):
            self.style_combo.addItem(name, key)
        style_box.addWidget(self.style_combo)
        options.addLayout(style_box)
        card.layout().addLayout(options)

        size_row = QHBoxLayout()
        size_row.setSpacing(10)
        self.size_combo = QComboBox()
        for value in (128, 256, 512):
            self.size_combo.addItem(f"{value} × {value}", value)
        self.size_combo.setCurrentIndex(1)
        size_row.addLayout(self._field(t("assets.size_label"), self.size_combo))
        self.provider_combo = QComboBox()
        for provider in IMAGE_PROVIDERS:
            self.provider_combo.addItem(provider.name, provider.id)
        size_row.addLayout(self._field(t("assets.provider_label"), self.provider_combo))
        card.layout().addLayout(size_row)

        seed_row = QHBoxLayout()
        seed_row.setSpacing(8)
        self.seed_spin = QSpinBox()
        self.seed_spin.setRange(0, 2_147_483_647)
        self.seed_spin.setValue(random.randint(1, 999_999))
        seed_row.addLayout(self._field("Seed", self.seed_spin))
        randomize = QPushButton(t("assets.random_button"))
        randomize.setObjectName("ghost")
        randomize.clicked.connect(lambda: self.seed_spin.setValue(random.randint(1, 999_999)))
        seed_row.addWidget(randomize, 0, Qt.AlignmentFlag.AlignBottom)
        card.layout().addLayout(seed_row)

        self.provider_note = muted("", size=9)
        card.layout().addWidget(self.provider_note)

        layout.addWidget(card)

        self.preview = QLabel(t("assets.preview_placeholder"))
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(180)
        self.preview.setStyleSheet(
            "background: #12151A; border: 1px dashed #2A3038; border-radius: 8px; color: #6F7680;"
        )
        layout.addWidget(self.preview, 1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.status = muted("", size=9)
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton(t("common.close"))
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.generate_button = QPushButton(t("assets.generate_button"))
        self.generate_button.setObjectName("primary")
        self.generate_button.setMinimumWidth(160)
        self.generate_button.clicked.connect(self._generate)
        buttons.addWidget(self.generate_button)
        layout.addLayout(buttons)

        style = str((project.manifest.get("ai") or {}).get("image_style") or "flat")
        index = self.style_combo.findData(style)
        if index >= 0:
            self.style_combo.setCurrentIndex(index)
        self.provider_combo.currentIndexChanged.connect(self._provider_changed)
        self._provider_changed()

    def _label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("muted")
        label.setFont(theme.ui_font(9, 700))
        return label

    def _field(self, label: str, widget: QWidget) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(4)
        box.addWidget(self._label(label))
        box.addWidget(widget)
        return box

    def _provider_changed(self) -> None:
        provider = self.provider_combo.currentData()
        if provider == "procedural":
            self.provider_note.setText(t("assets.note_procedural"))
        else:
            self.provider_note.setText(t("assets.note_openai"))

    def _generate(self) -> None:
        prompt = self.prompt.toPlainText().strip()
        if len(prompt) < 3:
            QMessageBox.warning(self, t("assets.need_prompt_title"), t("assets.need_prompt_text"))
            return
        name = slugify(self.name_edit.text().strip() or prompt, "image")
        folder = "backgrounds" if self.background else "sprites"
        target = self.project.root / "assets" / folder / (name + ".png")
        counter = 2
        while target.exists():
            target = target.with_name(f"{name}-{counter}.png")
            counter += 1
        target.parent.mkdir(parents=True, exist_ok=True)

        config = self.settings.image_config()
        provider = self.provider_combo.currentData()
        config["provider"] = provider
        if provider == "procedural":
            config["base_url"] = ""
            config["api_key"] = ""
        self.generate_button.setEnabled(False)
        self.progress.show()
        self.status.setText(t("assets.status_generating"))
        self.worker = SpriteWorker(
            prompt,
            target,
            style=self.style_combo.currentData() or "flat",
            size=int(self.size_combo.currentData() or 256),
            image_config=config,
            seed=int(self.seed_spin.value()),
            background=self.background,
            width=int((self.project.window or {}).get("width", 1280)),
            height=int((self.project.window or {}).get("height", 720)),
        )
        self.worker.stage.connect(self.status.setText)
        self.worker.done.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _done(self, result: dict) -> None:
        self.generate_button.setEnabled(True)
        self.progress.hide()
        self.result_path = str(result.get("path") or "")
        self.status.setText(
            t(
                "assets.status_done",
                name=Path(self.result_path).name,
                provider=result.get("provider", ""),
                fallback=t("assets.status_done_fallback") if result.get("fallback") else "",
            )
        )
        pixmap = QPixmap(self.result_path)
        if not pixmap.isNull():
            self.preview.setPixmap(
                pixmap.scaled(
                    QSize(520, 260),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self.preview.setStyleSheet("background: #12151A; border: 1px solid #262B33; border-radius: 8px;")
        self.created.emit(self.result_path)
        self.generate_button.setText(t("assets.generate_again_button"))

    def _failed(self, message: str, _trace: str) -> None:
        self.generate_button.setEnabled(True)
        self.progress.hide()
        self.status.setText(t("assets.error_prefix") + message)
        QMessageBox.critical(self, t("assets.failed_title"), message)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.worker is not None and self.worker.isRunning():
            answer = QMessageBox.question(
                self,
                t("assets.close_running_title"),
                t("assets.close_running_text"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        event.accept()


class AssetsPage(QWidget):
    status_message = Signal(str)
    open_file_requested = Signal(str)

    def __init__(self, project, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self.settings = settings
        self.assets: list[Path] = []
        self.selected: Path | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addLayout(self._build_toolbar())

        splitter = QHBoxLayout()
        splitter.setSpacing(14)
        splitter.addWidget(self._build_grid(), 3)
        splitter.addWidget(self._build_preview(), 2)
        layout.addLayout(splitter, 1)
        self.refresh()

    def _build_toolbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        heading = QVBoxLayout()
        heading.setSpacing(0)
        heading.addWidget(title_label(t("assets.page_title"), 15))
        heading.addWidget(muted(t("assets.page_subtitle"), wrap=False, size=9))
        row.addLayout(heading)
        row.addStretch(1)
        import_button = QPushButton(t("assets.import_button"))
        import_button.clicked.connect(self._import)
        row.addWidget(import_button)
        folder_button = QPushButton(t("assets.open_folder_button"))
        folder_button.setObjectName("ghost")
        folder_button.clicked.connect(self._open_folder)
        row.addWidget(folder_button)
        bg_button = QPushButton(t("assets.background_button"))
        bg_button.setObjectName("teal")
        bg_button.clicked.connect(lambda: self._generate(background=True))
        row.addWidget(bg_button)
        sprite_button = QPushButton(t("assets.gen_sprite_button"))
        sprite_button.setObjectName("primary")
        sprite_button.clicked.connect(lambda: self._generate(background=False))
        row.addWidget(sprite_button)
        return row

    def _build_grid(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("cardSoft")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        top = QHBoxLayout()
        top.addWidget(title_label(t("assets.library_title"), 10))
        top.addStretch(1)
        self.count_badge = Badge("0", "default")
        top.addWidget(self.count_badge)
        layout.addLayout(top)
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText(t("assets.search_placeholder"))
        self.search.textChanged.connect(self._fill_grid)
        layout.addWidget(self.search)
        self.list = QListWidget()
        self.list.setObjectName("assetGrid")
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setIconSize(QSize(92, 92))
        self.list.setGridSize(QSize(132, 128))
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setMovement(QListWidget.Movement.Static)
        self.list.setWordWrap(True)
        self.list.setSpacing(5)
        self.list.currentItemChanged.connect(self._selected)
        self.list.itemDoubleClicked.connect(self._double_clicked)
        layout.addWidget(self.list, 1)
        return frame

    def _build_preview(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        head = QHBoxLayout()
        head.addWidget(title_label(t("assets.preview_title"), 11))
        head.addStretch(1)
        self.kind_badge = Badge("—", "default")
        head.addWidget(self.kind_badge)
        layout.addLayout(head)
        self.preview = QLabel(t("assets.choose_asset"))
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(260)
        self.preview.setStyleSheet(
            "background: #12151A;"
            "border: 1px solid #262B33; border-radius: 8px; color: #6F7680;"
        )
        layout.addWidget(self.preview, 1)
        self.name_label = QLabel("")
        self.name_label.setFont(theme.ui_font(10, 700))
        self.name_label.setWordWrap(True)
        layout.addWidget(self.name_label)
        self.meta_label = muted("", size=9)
        layout.addWidget(self.meta_label)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.delete_button = QPushButton(t("assets.delete_button"))
        self.delete_button.setObjectName("danger")
        self.delete_button.clicked.connect(self._delete)
        self.delete_button.setEnabled(False)
        buttons.addWidget(self.delete_button)
        self.edit_button = QPushButton(t("assets.edit_button"))
        self.edit_button.setObjectName("teal")
        self.edit_button.clicked.connect(self._open_in_editor)
        self.edit_button.setEnabled(False)
        buttons.addWidget(self.edit_button)
        layout.addLayout(buttons)
        return frame

    # ------------------------------------------------------------------
    def refresh(self, select: str | None = None) -> None:
        self.assets = []
        assets_dir = self.project.root / "assets"
        if assets_dir.is_dir():
            for path in sorted(assets_dir.rglob("*"), key=lambda p: p.name.lower()):
                if path.is_file() and path.suffix.lower() not in {".pyc", ".tmp"}:
                    self.assets.append(path)
        self.count_badge.setText(str(len(self.assets)))
        self._fill_grid()
        if select:
            for index in range(self.list.count()):
                item = self.list.item(index)
                if item.data(Qt.ItemDataRole.UserRole) == select:
                    self.list.setCurrentItem(item)
                    break

    def _fill_grid(self) -> None:
        query = self.search.text().strip().lower()
        self.list.clear()
        for path in self.assets:
            rel = self.project.rel(path)
            if query and query not in rel.lower():
                continue
            item = QListWidgetItem()
            item.setText(path.name)
            item.setData(Qt.ItemDataRole.UserRole, rel)
            item.setToolTip(rel)
            if path.suffix.lower() in IMAGE_SUFFIXES:
                pixmap = QPixmap(str(path))
                if not pixmap.isNull():
                    item.setIcon(QIcon(pixmap.scaled(92, 92, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)))
                else:
                    item.setIcon(self._icon_for(path))
            else:
                item.setIcon(self._icon_for(path))
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)
        else:
            self.selected = None
            self.preview.setText(t("assets.empty_list"))
            self.preview.setPixmap(QPixmap())
            self.name_label.setText("")
            self.meta_label.setText("")
            self.kind_badge.setText(t("assets.badge_empty"))
            self.edit_button.setEnabled(False)
            self.delete_button.setEnabled(False)

    def _icon_for(self, path: Path) -> QIcon:
        suffix = path.suffix.lower()
        if suffix in AUDIO_SUFFIXES:
            return QIcon(self._glyph_icon("AUD", "#A8AFB9"))
        if suffix in IMAGE_SUFFIXES:
            return QIcon(self._glyph_icon("IMG", "#A8AFB9"))
        if suffix == ".json":
            return QIcon(self._glyph_icon("JSON", "#A8AFB9"))
        return QIcon(self._glyph_icon("FILE", "#A8AFB9"))

    def _glyph_icon(self, glyph: str, color: str) -> QPixmap:
        pixmap = QPixmap(96, 96)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#1B1F25"))
        painter.drawRoundedRect(4, 4, 88, 88, 14, 14)
        font = QFont(theme.ui_font(22, 700))
        font.setPixelSize(20)
        painter.setFont(font)
        painter.setPen(QColor(color))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, glyph)
        painter.end()
        return pixmap

    def _selected(self, current: QListWidgetItem | None, _previous) -> None:
        if current is None:
            return
        rel = current.data(Qt.ItemDataRole.UserRole)
        if not rel:
            return
        path = self.project.root / rel
        self.selected = path
        self.name_label.setText(rel)
        suffix = path.suffix.lower()
        try:
            size_kb = path.stat().st_size / 1024
        except OSError:
            size_kb = 0
        self.kind_badge.setText(
            t("assets.badge_image")
            if suffix in IMAGE_SUFFIXES
            else (t("assets.badge_sound") if suffix in AUDIO_SUFFIXES else t("assets.badge_file"))
        )
        if suffix in IMAGE_SUFFIXES:
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                self.preview.setPixmap(
                    pixmap.scaled(
                        QSize(380, 300),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                self.meta_label.setText(
                    t(
                        "assets.meta_image",
                        width=pixmap.width(),
                        height=pixmap.height(),
                        size=f"{size_kb:.1f}",
                        suffix=suffix.lstrip(".").upper(),
                    )
                )
            else:
                self.preview.setText(t("assets.image_open_failed"))
                self.meta_label.setText(t("assets.meta_kb", size=f"{size_kb:.1f}"))
        elif suffix in AUDIO_SUFFIXES:
            self.preview.setPixmap(self._glyph_icon("AUD", "#A8AFB9").scaled(160, 160))
            self.meta_label.setText(t("assets.audio_file", size=f"{size_kb:.1f}"))
        else:
            self.preview.setText(suffix.upper() + t("assets.no_preview"))
            self.meta_label.setText(t("assets.meta_kb", size=f"{size_kb:.1f}"))
        self.edit_button.setEnabled(True)
        self.delete_button.setEnabled(True)

    # ------------------------------------------------------------------
    def _generate(self, *, background: bool) -> None:
        dialog = GenerateImageDialog(self.project, self.settings, self, background=background)
        dialog.created.connect(lambda path: self.refresh(select=self.project.rel(path)))
        dialog.exec()
        if dialog.result_path:
            self.refresh(select=self.project.rel(dialog.result_path))
            self.status_message.emit(t("assets.created_status", rel=self.project.rel(dialog.result_path)))
        self.refresh()

    def _import(self) -> None:
        files, _filter = QFileDialog.getOpenFileNames(
            self,
            t("assets.import_dialog_title"),
            str(self.project.root / "assets"),
            t("assets.import_filter"),
        )
        if not files:
            return
        target_dir = self.project.root / "assets" / "imported"
        target_dir.mkdir(parents=True, exist_ok=True)
        imported = []
        for file in files:
            source = Path(file)
            target = target_dir / source.name
            counter = 2
            while target.exists():
                target = target_dir / f"{source.stem}-{counter}{source.suffix}"
                counter += 1
            try:
                shutil.copy2(source, target)
                imported.append(self.project.rel(target))
            except OSError as exc:
                QMessageBox.warning(self, t("assets.import_error_title"), t("assets.import_error_text", name=source.name, error=exc))
        if imported:
            self.refresh(select=imported[-1])
            self.status_message.emit(t("assets.imported_status", count=len(imported)))

    def _open_folder(self) -> None:
        path = self.project.root / "assets"
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _double_clicked(self, item: QListWidgetItem) -> None:
        rel = item.data(Qt.ItemDataRole.UserRole)
        if rel:
            self.open_file_requested.emit(str(rel))

    def _open_in_editor(self) -> None:
        if self.selected is not None:
            self.open_file_requested.emit(self.project.rel(self.selected))

    def _delete(self) -> None:
        if self.selected is None:
            return
        rel = self.project.rel(self.selected)
        answer = QMessageBox.question(
            self,
            t("assets.delete_title"),
            t("assets.delete_text", rel=rel),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.selected.unlink()
        except OSError as exc:
            QMessageBox.critical(self, t("assets.delete_error_title"), str(exc))
            return
        self.status_message.emit(t("assets.deleted_status", rel=rel))
        self.refresh()
