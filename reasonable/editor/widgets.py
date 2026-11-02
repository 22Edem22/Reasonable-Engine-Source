"""Small reusable widgets for the editor UI."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from reasonable.core.i18n import t

from . import theme


class Card(QFrame):
    def __init__(self, parent: QWidget | None = None, *, soft: bool = False, padding: int = 18) -> None:
        super().__init__(parent)
        self.setObjectName("cardSoft" if soft else "card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(padding, padding, padding, padding)
        self._layout.setSpacing(12)

    def layout(self) -> QVBoxLayout:  # type: ignore[override]
        return self._layout

    def add(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self._layout.addWidget(widget, stretch)
        return widget


class HeroCard(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("hero")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(26, 24, 26, 24)
        self._layout.setSpacing(12)

    def layout(self) -> QVBoxLayout:  # type: ignore[override]
        return self._layout


class Badge(QLabel):
    def __init__(self, text: str = "", tone: str = "default", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName(
            {
                "accent": "pillAccent",
                "teal": "pillTeal",
                "gold": "pillGold",
            }.get(tone, "pill")
        )
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def set_tone(self, tone: str) -> None:
        self.setObjectName(
            {
                "accent": "pillAccent",
                "teal": "pillTeal",
                "gold": "pillGold",
            }.get(tone, "pill")
        )
        self.style().unpolish(self)
        self.style().polish(self)


def title_label(text: str, size: int = 20, parent: QWidget | None = None) -> QLabel:
    label = QLabel(text, parent)
    label.setObjectName("title")
    label.setFont(theme.display_font(size, 700))
    return label


class ElidedLabel(QLabel):
    """Label that shortens its text instead of forcing the layout wider."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full_text = str(text or "")
        self._refresh()

    def fullText(self) -> str:  # noqa: N802
        return self._full_text

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        width = max(20, self.width() - 2)
        super().setText(self.fontMetrics().elidedText(self._full_text, Qt.TextElideMode.ElideRight, width))


def body_label(text: str, *, color: str = "", wrap: bool = True, size: int = 10) -> QLabel:
    label = QLabel(text)
    if color == "muted":
        label.setObjectName("muted")
    elif color:
        label.setObjectName(color)
    label.setWordWrap(wrap)
    label.setFont(theme.ui_font(size))
    return label


def muted(text: str, *, wrap: bool = True, size: int = 10) -> QLabel:
    return body_label(text, color="muted", wrap=wrap, size=size)


def pill_button(text: str, *, accent: bool = False, parent: QWidget | None = None) -> QPushButton:
    button = QPushButton(text, parent)
    if accent:
        button.setObjectName("primary")
    return button


class EmptyState(QWidget):
    def __init__(self, icon: str, title: str, text: str, parent: QWidget | None = None, *, pixmap=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(8)
        symbol = QLabel()
        symbol.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if pixmap is not None:
            symbol.setPixmap(pixmap)
        else:
            symbol.setText(icon)
            symbol.setFont(QFont(theme.display_font(28).family(), 30))
            symbol.setStyleSheet("color: #4B515A;")
        layout.addWidget(symbol)
        heading = QLabel(title)
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading.setFont(theme.display_font(13, 700))
        heading.setStyleSheet("color: #B7BDC6;")
        layout.addWidget(heading)
        if text:
            caption = muted(text)
            caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
            caption.setMaximumWidth(360)
            layout.addWidget(caption)


class Avatar(QLabel):
    """Round avatar with the brand logo or generated initials."""

    def __init__(self, size: int = 36, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def set_logo(self) -> None:
        pixmap = theme.logo_pixmap(self._size)
        self.setPixmap(pixmap)

    def set_initials(self, text: str, color: str = "#A8AFB9") -> None:
        pixmap = QPixmap(self._size, self._size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        tint = QColor(color)
        painter.setBrush(QColor(tint.red(), tint.green(), tint.blue(), 46))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(0, 0, self._size, self._size)
        painter.setPen(tint)
        font = QFont(theme.display_font(10, 700))
        font.setPixelSize(max(12, self._size // 3))
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, text[:2].upper())
        painter.end()
        self.setPixmap(pixmap)


class Dot(QLabel):
    def __init__(self, color: str = "#8DB8A0", size: int = 8, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setStyleSheet(f"background: {color}; border-radius: {size // 2}px;")


class ProjectCard(QFrame):
    clicked = Signal()
    delete_requested = Signal()

    def __init__(self, name: str, goal: str, kind: str, path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("projectRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(8)
        heading = QLabel(name)
        heading.setObjectName("title")
        heading.setFont(theme.display_font(11, 600))
        top.addWidget(heading)
        top.addStretch(1)
        kind_label = QLabel(t("widgets.kind_game") if kind == "game" else t("widgets.kind_app"))
        kind_label.setObjectName("dim")
        kind_label.setFont(theme.ui_font(9))
        top.addWidget(kind_label)
        delete = QPushButton("×")
        delete.setObjectName("ghost")
        delete.setFixedSize(24, 24)
        delete.setToolTip(t("widgets.delete_project"))
        delete.setCursor(Qt.CursorShape.PointingHandCursor)
        delete.clicked.connect(self.delete_requested)
        top.addWidget(delete)
        layout.addLayout(top)
        if goal:
            text = muted(goal)
            text.setMaximumHeight(38)
            layout.addWidget(text)
        location = QLabel(path)
        location.setObjectName("dim")
        location.setFont(theme.ui_font(9))
        layout.addWidget(location)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class StatBox(QFrame):
    def __init__(self, label: str, value: str, hint: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("cardSoft")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 12, 15, 12)
        layout.setSpacing(3)
        caption = QLabel(label.upper())
        caption.setObjectName("dim")
        caption.setFont(theme.ui_font(8, 700))
        layout.addWidget(caption)
        self.value_label = QLabel(value)
        self.value_label.setFont(theme.display_font(18, 700))
        self.value_label.setStyleSheet("color: #F0F2F4;")
        layout.addWidget(self.value_label)
        self.hint_label = muted(hint, size=9)
        layout.addWidget(self.hint_label)

    def set_value(self, value: str, hint: str | None = None) -> None:
        self.value_label.setText(value)
        if hint is not None:
            self.hint_label.setText(hint)


class IconTile(QPushButton):
    """Square button used for compact actions."""

    def __init__(self, glyph: str, tooltip: str, parent: QWidget | None = None) -> None:
        super().__init__(glyph, parent)
        self.setObjectName("ghost")
        self.setToolTip(tooltip)
        self.setFixedSize(32, 32)
        self.setFont(theme.ui_font(12, 700))
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class Separator(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(1)
        self.setStyleSheet("background: #23272E;")


def clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())
