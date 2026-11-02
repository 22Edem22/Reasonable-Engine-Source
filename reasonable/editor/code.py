"""Manual code editing: file tree, syntax highlighting and quick actions."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QRect, QRegularExpression, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QImage,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from reasonable.core.i18n import t
from reasonable.core.project import TEXT_SUFFIXES

from . import theme
from .widgets import Badge, Card, EmptyState, muted, title_label

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
BINARY_SUFFIXES = IMAGE_SUFFIXES | {".ico", ".ttf", ".otf", ".wav", ".mp3", ".ogg", ".zip", ".exe", ".apk"}


class LineNumberArea(QWidget):
    def __init__(self, editor: "CodeEditor") -> None:
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.editor.line_number_width(), 0)

    def paintEvent(self, event) -> None:  # noqa: N802
        self.editor.paint_line_numbers(event)


class CodeEditor(QPlainTextEdit):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("code")
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabStopDistance(36)
        self.setCursorWidth(2)
        font = QFont("Cascadia Code", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setFixedPitch(True)
        self.setFont(font)
        self.line_number_area = LineNumberArea(self)
        self.blockCountChanged.connect(self.update_line_number_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)
        self.update_line_number_width()
        self.highlight_current_line()

    def line_number_width(self) -> int:
        digits = max(2, len(str(max(1, self.blockCount()))))
        return 16 + self.fontMetrics().horizontalAdvance("9") * digits

    def update_line_number_width(self) -> None:
        self.setViewportMargins(self.line_number_width(), 0, 0, 0)

    def update_line_number_area(self, rect: QRect, dy: int) -> None:
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_line_number_width()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        contents = self.contentsRect()
        self.line_number_area.setGeometry(QRect(contents.left(), contents.top(), self.line_number_width(), contents.height()))

    def paint_line_numbers(self, event) -> None:
        painter = QPainter(self.line_number_area)
        painter.fillRect(event.rect(), QColor("#101216"))
        painter.setPen(QColor("#262B33"))
        painter.drawLine(self.line_number_area.width() - 1, event.rect().top(), self.line_number_area.width() - 1, event.rect().bottom())

        block = self.firstVisibleBlock()
        number = block.blockNumber() + 1
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())
        current = self.textCursor().blockNumber() + 1
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                if number == current:
                    painter.setPen(QColor("#D9917A"))
                    font = painter.font()
                    font.setBold(True)
                    painter.setFont(font)
                else:
                    painter.setPen(QColor("#4F555E"))
                    font = painter.font()
                    font.setBold(False)
                    painter.setFont(font)
                painter.drawText(
                    0,
                    top,
                    self.line_number_area.width() - 7,
                    self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight,
                    str(number),
                )
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            number += 1
        painter.end()

    def highlight_current_line(self) -> None:
        selection = QTextEdit.ExtraSelection()
        selection.format.setBackground(QColor("#171B21"))
        selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        self.setExtraSelections([selection])

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Tab and not event.modifiers():
            self.insertPlainText("    ")
            return
        super().keyPressEvent(event)


# ---------------------------------------------------------------------------
# Highlighters
# ---------------------------------------------------------------------------


def _format(color: str, *, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(color))
    if bold:
        fmt.setFontWeight(QFont.Weight.Bold)
    if italic:
        fmt.setFontItalic(True)
    return fmt


class PythonHighlighter(QSyntaxHighlighter):
    KEYWORDS = (
        "and", "as", "assert", "async", "await", "break", "class", "continue", "def", "del",
        "elif", "else", "except", "False", "finally", "for", "from", "global", "if", "import",
        "in", "is", "lambda", "None", "nonlocal", "not", "or", "pass", "raise", "return",
        "True", "try", "while", "with", "yield", "match", "case", "self",
    )
    BUILTINS = (
        "print", "len", "range", "str", "int", "float", "bool", "list", "dict", "set",
        "tuple", "open", "enumerate", "zip", "super", "isinstance", "getattr", "setattr",
        "min", "max", "sum", "abs", "round", "sorted", "any", "all", "type", "object",
    )

    def __init__(self, document: QTextDocument) -> None:
        super().__init__(document)
        self.rules: list[tuple[QRegularExpression, QTextCharFormat]] = []
        keyword = _format("#D9917A", bold=True)
        for word in self.KEYWORDS:
            self.rules.append((QRegularExpression(rf"\b{word}\b"), keyword))
        builtin = _format("#C9CED6")
        for word in self.BUILTINS:
            self.rules.append((QRegularExpression(rf"\b{word}\b"), builtin))
        self.rules += [
            (QRegularExpression(r"\b[A-Za-z_][A-Za-z0-9_]*(?=\()"), _format("#A8B9D4")),
            (QRegularExpression(r"\b[A-Z][A-Za-z0-9_]*\b"), _format("#D7C294")),
            (QRegularExpression(r"\b[0-9]+(\.[0-9]+)?\b"), _format("#A8C4B2")),
            (QRegularExpression(r"#[^\n]*"), _format("#6F7680", italic=True)),
            (QRegularExpression(r"@[A-Za-z_][A-Za-z0-9_.]*"), _format("#B8A8D4")),
            (QRegularExpression(r"\b(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)"), _format("#E0C08F", bold=True)),
            (QRegularExpression(r"\b(?:import|from)\s+([A-Za-z_][A-Za-z0-9_.]*)"), _format("#8FB0C9")),
            (QRegularExpression(r'"[^"\\]*(?:\\.[^"\\]*)*"'), _format("#A9C4A1")),
            (QRegularExpression(r"'[^'\\]*(?:\\.[^'\\]*)*'"), _format("#A9C4A1")),
        ]
        self.triple_single = _format("#A9C4A1")
        self.triple_double = _format("#A9C4A1")

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        for regex, fmt in self.rules:
            iterator = regex.globalMatch(text)
            while iterator.hasNext():
                match = iterator.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), fmt)

        self.setCurrentBlockState(0)
        self._multiline(text, '"""', self.triple_double, 1)
        self._multiline(text, "'''", self.triple_single, 2)

    def _multiline(self, text: str, delimiter: str, fmt: QTextCharFormat, state: int) -> None:
        start = 0
        if self.previousBlockState() != state:
            start = text.find(delimiter)
        while start >= 0:
            end = text.find(delimiter, start + len(delimiter))
            if end < 0:
                self.setCurrentBlockState(state)
                length = len(text) - start
            else:
                length = end - start + len(delimiter)
            self.setFormat(start, length, fmt)
            start = text.find(delimiter, start + length)


class JsonHighlighter(QSyntaxHighlighter):
    def __init__(self, document: QTextDocument) -> None:
        super().__init__(document)
        self.rules = [
            (QRegularExpression(r'"[^"\\]*(?:\\.[^"\\]*)*"(?=\s*:)'), _format("#A8B9D4")),
            (QRegularExpression(r'"[^"\\]*(?:\\.[^"\\]*)*"'), _format("#A9C4A1")),
            (QRegularExpression(r"\b(?:true|false|null)\b"), _format("#D9917A", bold=True)),
            (QRegularExpression(r"-?\b[0-9]+(?:\.[0-9]+)?\b"), _format("#A8C4B2")),
        ]

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        for regex, fmt in self.rules:
            iterator = regex.globalMatch(text)
            while iterator.hasNext():
                match = iterator.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), fmt)


# ---------------------------------------------------------------------------
# Code page
# ---------------------------------------------------------------------------


class CodePage(QWidget):
    run_requested = Signal()
    status_message = Signal(str)

    def __init__(self, project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self.current_path = ""
        self.current_saved_text = ""
        self.highlighter = None
        self._image_label: QLabel | None = None
        self._disk_mtime = 0.0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addLayout(self._build_toolbar())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_tree_panel())
        splitter.addWidget(self._build_editor_panel())
        splitter.setSizes([270, 860])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

        self.watch_timer = QTimer(self)
        self.watch_timer.setInterval(2200)
        self.watch_timer.timeout.connect(self._check_disk)
        self.watch_timer.start()

        self.refresh_tree()
        entry = project.rel(project.entry)
        if (project.root / entry).exists():
            # Use a child timer, not QTimer.singleShot: if the project page is
            # closed quickly, a global singleShot would call into deleted widgets.
            self._initial_open_timer = QTimer(self)
            self._initial_open_timer.setSingleShot(True)
            self._initial_open_timer.timeout.connect(lambda: self.open_file(entry))
            self._initial_open_timer.start(60)

    # ------------------------------------------------------------------
    def _build_toolbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        heading = QVBoxLayout()
        heading.setSpacing(0)
        heading.addWidget(title_label(t("code.page_title"), 15))
        heading.addWidget(muted(t("code.page_subtitle"), size=9))
        row.addLayout(heading)
        row.addStretch(1)
        validate = QPushButton(t("code.validate_button"))
        validate.clicked.connect(self.validate_project)
        row.addWidget(validate)
        self.run_button = QPushButton("▶  " + t("code.run_button"))
        self.run_button.setObjectName("primary")
        self.run_button.clicked.connect(self._run)
        row.addWidget(self.run_button)
        return row

    def _build_tree_panel(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("cardSoft")
        frame.setMinimumWidth(220)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        top = QHBoxLayout()
        top.addWidget(title_label(t("code.files_title"), 10))
        top.addStretch(1)
        refresh = QPushButton(t("code.refresh_button"))
        refresh.setObjectName("ghost")
        refresh.setToolTip(t("code.refresh_tip"))
        refresh.clicked.connect(self.refresh_tree)
        top.addWidget(refresh)
        layout.addLayout(top)

        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText(t("code.search_placeholder"))
        self.search.textChanged.connect(self._filter_tree)
        layout.addWidget(self.search)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.setIconSize(QSize(17, 17))
        self.tree.setAnimated(True)
        self.tree.itemClicked.connect(self._tree_clicked)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        layout.addWidget(self.tree, 1)

        buttons = QHBoxLayout()
        new_file = QPushButton(t("code.new_file_button"))
        new_file.setObjectName("ghost")
        new_file.clicked.connect(self.new_file)
        buttons.addWidget(new_file)
        new_folder = QPushButton(t("code.new_folder_button"))
        new_folder.setObjectName("ghost")
        new_folder.clicked.connect(self.new_folder)
        buttons.addWidget(new_folder)
        layout.addLayout(buttons)
        return frame

    def _build_editor_panel(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("editorHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 9, 12, 9)
        header_layout.setSpacing(8)
        self.file_label = QLabel(t("code.no_file_selected"))
        self.file_label.setFont(theme.ui_font(10, 700))
        header_layout.addWidget(self.file_label)
        self.dirty_badge = Badge(t("code.badge_modified"), "gold")
        self.dirty_badge.hide()
        header_layout.addWidget(self.dirty_badge)
        header_layout.addStretch(1)
        self.save_button = QPushButton(t("code.save_button"))
        self.save_button.setObjectName("teal")
        self.save_button.setMinimumWidth(104)
        self.save_button.setShortcut(QKeySequence.StandardKey.Save)
        self.save_button.clicked.connect(self.save_file)
        header_layout.addWidget(self.save_button)
        layout.addWidget(header)

        self.stack = QStackedWidget()
        self.placeholder = EmptyState(
            "{}",
            t("code.empty_title"),
            t("code.empty_text"),
        )
        self.stack.addWidget(self.placeholder)
        self.editor = CodeEditor()
        self.editor.textChanged.connect(self._text_changed)
        self.editor.cursorPositionChanged.connect(self._cursor_moved)
        self.stack.addWidget(self.editor)
        self.image_view = self._build_image_view()
        self.stack.addWidget(self.image_view)
        layout.addWidget(self.stack, 1)

        self.status = QLabel(t("code.status_ready"))
        self.status.setObjectName("dim")
        self.status.setFont(theme.ui_font(9))
        self.status.setStyleSheet("padding: 5px 12px; background: #101216; border-bottom-left-radius: 10px; border-bottom-right-radius: 10px;")
        layout.addWidget(self.status)
        return frame

    def _build_image_view(self) -> QWidget:
        widget = QWidget()
        widget.setObjectName("root")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        self.image_caption = QLabel("")
        self.image_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_caption.setObjectName("muted")
        layout.addWidget(self.image_caption)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_holder = QLabel()
        self._image_holder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll.setWidget(self._image_holder)
        layout.addWidget(scroll, 1)
        return widget

    # ------------------------------------------------------------------
    def _icon_canvas(self) -> tuple[QPixmap, QPainter]:
        pixmap = QPixmap(32, 32)
        pixmap.setDevicePixelRatio(2.0)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        return pixmap, painter

    def _folder_icon(self) -> QIcon:
        pixmap, painter = self._icon_canvas()
        painter.setPen(QPen(QColor("#7D848E"), 2))
        painter.setBrush(QColor("#232830"))
        painter.drawRoundedRect(3, 8, 26, 20, 4, 4)
        painter.end()
        return QIcon(pixmap)

    def _file_icon(self) -> QIcon:
        pixmap, painter = self._icon_canvas()
        painter.setPen(QPen(QColor("#7D848E"), 2))
        painter.setBrush(QColor("#1C2027"))
        painter.drawRoundedRect(7, 2, 18, 28, 4, 4)
        painter.setPen(QPen(QColor("#8B929C"), 2))
        for y in (10, 15, 20):
            painter.drawLine(11, y, 21, y)
        painter.end()
        return QIcon(pixmap)

    def _icon_for(self, path: str, is_dir: bool) -> QIcon:
        return self._folder_icon() if is_dir else self._file_icon()

    def refresh_tree(self) -> None:
        expanded = set()
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item.isExpanded():
                expanded.add(item.data(0, Qt.ItemDataRole.UserRole))
        selected = self.current_path
        self.tree.clear()
        root = QTreeWidgetItem([t("code.tree_root")])
        root.setIcon(0, self._icon_for("", True))
        root.setData(0, Qt.ItemDataRole.UserRole, "")
        root.setFont(0, theme.ui_font(9, 700))
        self.tree.addTopLevelItem(root)

        dirs: dict[str, QTreeWidgetItem] = {"": root}
        rows = self.project.list_tree()
        for row in rows:
            rel = row["path"]
            parts = rel.split("/")
            parent = ""
            for index, part in enumerate(parts):
                path = "/".join(parts[: index + 1])
                is_last = index == len(parts) - 1
                if path in dirs:
                    parent = path
                    continue
                item = QTreeWidgetItem([part])
                item.setData(0, Qt.ItemDataRole.UserRole, path)
                item.setData(0, Qt.ItemDataRole.UserRole + 1, row["is_dir"] if is_last else True)
                item.setIcon(0, self._icon_for(path, row["is_dir"] if is_last else True))
                item.setToolTip(0, path)
                dirs[path] = item
                dirs[parent].addChild(item)
                parent = path

        root.setExpanded(True)
        for folder in ("assets", "progress", "skills"):
            item = dirs.get(folder)
            if item is not None:
                item.setExpanded(True)
        for path in expanded:
            item = dirs.get(path)
            if item is not None:
                item.setExpanded(True)
        if selected:
            self._select_path(selected)
        self._filter_tree(self.search.text())

    def _select_path(self, path: str) -> None:
        stack = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            item = stack.pop()
            if item.data(0, Qt.ItemDataRole.UserRole) == path:
                self.tree.setCurrentItem(item)
                return
            stack.extend(item.child(i) for i in range(item.childCount()))

    def _filter_tree(self, text: str) -> None:
        query = text.strip().lower()

        def visit(item: QTreeWidgetItem) -> bool:
            visible = query in item.text(0).lower() or not query
            child_visible = False
            for index in range(item.childCount()):
                child_visible = visit(item.child(index)) or child_visible
            shown = visible or child_visible
            item.setHidden(not shown)
            if query and child_visible:
                item.setExpanded(True)
            return shown

        for index in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(index))

    def _tree_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not path:
            return
        is_dir = bool(item.data(0, Qt.ItemDataRole.UserRole + 1))
        if is_dir:
            item.setExpanded(not item.isExpanded())
            return
        self.open_file(path)

    # ------------------------------------------------------------------
    def open_file(self, path: str) -> None:
        if path == self.current_path and self.current_path:
            return
        if not self._maybe_save():
            return
        absolute = self.project.root / path
        if not absolute.exists():
            self.status_message.emit(t("code.file_not_found", path=path))
            return
        self.current_path = path
        self.file_label.setText(path)
        self.dirty_badge.hide()
        suffix = absolute.suffix.lower()
        if suffix in IMAGE_SUFFIXES:
            self._show_image(absolute)
            return
        if suffix in BINARY_SUFFIXES:
            self.stack.setCurrentIndex(0)
            self.status.setText(t("code.binary_file"))
            return
        try:
            text = absolute.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            QMessageBox.critical(self, t("code.read_error_title"), str(exc))
            return
        self.stack.setCurrentIndex(1)
        self.editor.blockSignals(True)
        self.editor.setPlainText(text)
        self.editor.blockSignals(False)
        self.current_saved_text = text
        self._disk_mtime = absolute.stat().st_mtime
        self._install_highlighter(suffix)
        self.editor.document().setModified(False)
        self.dirty_badge.hide()
        self._select_path(path)
        self._update_status()

    def _install_highlighter(self, suffix: str) -> None:
        if self.highlighter is not None:
            self.highlighter.setDocument(None)
            self.highlighter = None
        if suffix == ".py":
            self.highlighter = PythonHighlighter(self.editor.document())
        elif suffix == ".json":
            self.highlighter = JsonHighlighter(self.editor.document())

    def _show_image(self, absolute: Path) -> None:
        pixmap = QPixmap(str(absolute))
        if pixmap.isNull():
            self.stack.setCurrentIndex(0)
            self.status.setText(t("code.image_open_failed"))
            return
        self.stack.setCurrentIndex(2)
        self._source_image = pixmap
        self._resize_image()
        self.image_caption.setText(
            t(
                "code.image_caption",
                path=self.current_path,
                width=pixmap.width(),
                height=pixmap.height(),
                kb=absolute.stat().st_size // 1024,
            )
        )
        self._update_status()

    def _resize_image(self) -> None:
        if not hasattr(self, "_source_image"):
            return
        area = self.stack.currentWidget()
        target = self._image_holder.parentWidget().size()
        scaled = self._source_image.scaled(
            max(100, target.width() - 60),
            max(100, target.height() - 80),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._image_holder.setPixmap(scaled)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.stack.currentIndex() == 2:
            self._resize_image()

    # ------------------------------------------------------------------
    def _text_changed(self) -> None:
        dirty = self.editor.toPlainText() != self.current_saved_text
        self.dirty_badge.setVisible(dirty)
        self.editor.document().setModified(dirty)
        self._update_status()

    def _cursor_moved(self) -> None:
        self._update_status()

    def _update_status(self) -> None:
        cursor = self.editor.textCursor()
        if self.stack.currentIndex() == 1:
            self.status.setText(
                t(
                    "code.cursor_status",
                    line=cursor.blockNumber() + 1,
                    column=cursor.columnNumber() + 1,
                    count=len(self.editor.toPlainText()),
                )
            )
        elif self.stack.currentIndex() == 2:
            self.status.setText(t("code.image_preview_status"))
        elif self.current_path:
            self.status.setText(self.current_path)

    def is_dirty(self) -> bool:
        return self.stack.currentIndex() == 1 and self.editor.toPlainText() != self.current_saved_text

    def _maybe_save(self) -> bool:
        if not self.is_dirty():
            return True
        answer = QMessageBox.question(
            self,
            t("code.unsaved_title"),
            t("code.unsaved_text", path=self.current_path),
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            return self.save_file()
        return True

    def save_file(self) -> bool:
        if not self.current_path or self.stack.currentIndex() != 1:
            return False
        try:
            self.project.write_text(self.current_path, self.editor.toPlainText())
            self.current_saved_text = self.editor.toPlainText()
            self._disk_mtime = (self.project.root / self.current_path).stat().st_mtime
            self.dirty_badge.hide()
            self.status_message.emit(t("code.saved_status", path=self.current_path))
            self._update_status()
            return True
        except Exception as exc:
            QMessageBox.critical(self, t("code.save_error_title"), str(exc))
            return False

    def _check_disk(self) -> None:
        if not self.current_path or self.is_dirty():
            return
        path = self.project.root / self.current_path
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return
        if mtime > self._disk_mtime + 0.5:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return
            if text != self.current_saved_text and self.stack.currentIndex() == 1:
                cursor = self.editor.textCursor().position()
                self.editor.blockSignals(True)
                self.editor.setPlainText(text)
                self.editor.blockSignals(False)
                self.current_saved_text = text
                self._disk_mtime = mtime
                self.editor.moveCursor(QTextCursor.MoveOperation.Start)
                self.status_message.emit(t("code.agent_updated_file", path=self.current_path))

    # ------------------------------------------------------------------
    def new_file(self) -> None:
        name, ok = QInputDialog.getText(self, t("code.new_file_title"), t("code.new_file_label"), text="new_file.py")
        if not ok or not name.strip():
            return
        relative = name.strip().replace("\\", "/")
        try:
            path = self.project.ensure_inside(relative)
            if path.exists():
                QMessageBox.warning(self, t("code.file_exists_title"), t("code.file_exists_text"))
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
        except Exception as exc:
            QMessageBox.critical(self, t("code.create_file_error"), str(exc))
            return
        self.refresh_tree()
        self.open_file(relative)

    def new_folder(self) -> None:
        name, ok = QInputDialog.getText(self, t("code.new_folder_title"), t("code.new_file_label"), text="assets/new")
        if not ok or not name.strip():
            return
        try:
            path = self.project.ensure_inside(name.strip())
            path.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            QMessageBox.critical(self, t("code.create_folder_error"), str(exc))
            return
        self.refresh_tree()

    def _tree_menu(self, position) -> None:
        item = self.tree.itemAt(position)
        if item is None:
            return
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not path:
            return
        menu = QMenu(self)
        open_action = menu.addAction(t("code.menu_open"))
        rename_action = menu.addAction(t("code.menu_rename"))
        delete_action = menu.addAction(t("code.menu_delete"))
        selected = menu.exec(self.tree.viewport().mapToGlobal(position))
        if selected == open_action:
            self.open_file(path)
        elif selected == rename_action:
            self._rename(path, bool(item.data(0, Qt.ItemDataRole.UserRole + 1)))
        elif selected == delete_action:
            self._delete(path)

    def _rename(self, path: str, is_dir: bool) -> None:
        new_name, ok = QInputDialog.getText(self, t("code.rename_title"), t("code.rename_label"), text=path)
        if not ok or not new_name.strip() or new_name.strip() == path:
            return
        try:
            source = self.project.ensure_inside(path)
            target = self.project.ensure_inside(new_name.strip())
            if target.exists():
                QMessageBox.warning(self, t("code.rename_exists_title"), t("code.rename_exists_text"))
                return
            target.parent.mkdir(parents=True, exist_ok=True)
            source.rename(target)
        except Exception as exc:
            QMessageBox.critical(self, t("code.rename_error_title"), str(exc))
            return
        if self.current_path == path or self.current_path.startswith(path + "/"):
            self.current_path = ""
            self.stack.setCurrentIndex(0)
            self.file_label.setText(t("code.no_file_selected"))
        self.refresh_tree()

    def _delete(self, path: str) -> None:
        answer = QMessageBox.question(
            self,
            t("code.menu_delete"),
            t("code.delete_text", path=path),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.project.delete_path(path)
        except Exception as exc:
            QMessageBox.critical(self, t("code.delete_error_title"), str(exc))
            return
        if self.current_path == path:
            self.current_path = ""
            self.stack.setCurrentIndex(0)
            self.file_label.setText(t("code.no_file_selected"))
        self.refresh_tree()

    # ------------------------------------------------------------------
    def validate_project(self) -> None:
        issues = self.project.validate()
        errors = [issue for issue in issues if issue.level == "error"]
        warnings = [issue for issue in issues if issue.level == "warning"]
        if not errors and not warnings:
            QMessageBox.information(self, t("code.validate_ok_title"), t("code.validate_ok_text"))
            self.status_message.emit(t("code.validate_passed"))
            return
        lines = []
        for issue in issues:
            icon = {"error": "✗", "warning": "!", "ok": "✓"}.get(issue.level, "·")
            suffix = f"  [{issue.path}]" if issue.path else ""
            lines.append(f"{icon} {issue.message}{suffix}")
        text = "\n".join(lines)
        if errors:
            QMessageBox.warning(self, t("code.validate_errors_title"), text)
        else:
            QMessageBox.information(self, t("code.validate_ok_title"), text)
        self.status_message.emit(t("code.validate_summary", errors=len(errors), warnings=len(warnings)))

    def _run(self) -> None:
        if not self._maybe_save():
            return
        self.run_requested.emit()

    def save_all(self) -> bool:
        return self._maybe_save()
