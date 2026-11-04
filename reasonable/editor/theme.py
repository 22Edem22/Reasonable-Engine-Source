"""Visual language of the Reasonable Engine editor.

The interface follows the conventions of desktop engines (Unity, Godot,
Unreal): flat neutral panels, hairline borders, compact type, a single warm
accent and purpose-drawn line icons. Decorative gradients, oversized cards and
emoji glyphs are deliberately avoided so the window reads as a tool, not a
landing page.
"""

from __future__ import annotations

import functools

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QIcon,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QApplication

from reasonable.core.paths import BRAND_DIR, FONT_DIR


# ---------------------------------------------------------------------------
# Design tokens
# ---------------------------------------------------------------------------

COLORS = {
    "bg": "#1E1F22",
    "bg_deep": "#18191C",
    "surface": "#24262A",
    "surface_2": "#2B2D32",
    "surface_3": "#33363B",
    "border": "#35383D",
    "border_strong": "#454951",
    "text": "#D7DAE0",
    "text_strong": "#F0F2F5",
    "muted": "#A0A5AD",
    "dim": "#767B84",
    "accent": "#D97757",
    "accent_hover": "#E4896C",
    "accent_press": "#C4684A",
    "accent_soft": "#3A2A24",
    "success": "#83B292",
    "warning": "#C6A96B",
    "danger": "#C47F86",
}

RADIUS = 4
RADIUS_SMALL = 3


# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------

_FONTS_LOADED = False
_UI_FAMILY = "Segoe UI"


def load_fonts() -> None:
    global _FONTS_LOADED, _UI_FAMILY
    if _FONTS_LOADED:
        return
    _FONTS_LOADED = True
    path = FONT_DIR / "Inter-Variable.ttf"
    if not path.exists():
        return
    font_id = QFontDatabase.addApplicationFont(str(path))
    if font_id < 0:
        return
    families = QFontDatabase.applicationFontFamilies(font_id)
    if families:
        _UI_FAMILY = families[0]


def ui_font(size: int = 10, weight: int = 400) -> QFont:
    load_fonts()
    font = QFont(_UI_FAMILY, size)
    font.setWeight(QFont.Weight(weight))
    return font


def display_font(size: int = 18, weight: int = 700) -> QFont:
    # Headings use the same family as the rest of the interface: hierarchy is
    # built with size and weight instead of a second, decorative typeface.
    load_fonts()
    font = QFont(_UI_FAMILY, size)
    font.setWeight(QFont.Weight(weight))
    font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 100)
    return font


def section_font() -> QFont:
    """Uppercase tracking used for panel and group headers."""
    font = ui_font(8, 700)
    font.setCapitalization(QFont.Capitalization.AllUppercase)
    font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 108)
    return font


# ---------------------------------------------------------------------------
# Vector icons
# ---------------------------------------------------------------------------

_ICON_BOX = 16.0


def _path(*points: tuple[float, float]) -> QPainterPath:
    path = QPainterPath()
    path.moveTo(*points[0])
    for point in points[1:]:
        path.lineTo(*point)
    return path


def _draw_glyph(painter: QPainter, name: str, color: QColor) -> None:
    pen = QPen(color)
    pen.setWidthF(1.4)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    filled = QColor(color)

    if name == "back":
        painter.drawPath(_path((10.5, 3.5), (5.5, 8), (10.5, 12.5)))
        painter.drawLine(QPointF(5.5, 8), QPointF(13, 8))
    elif name == "forward":
        painter.drawPath(_path((5.5, 3.5), (10.5, 8), (5.5, 12.5)))
        painter.drawLine(QPointF(2.5, 8), QPointF(10.5, 8))
    elif name == "play":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(filled)
        painter.drawPath(_path((5.0, 3.2), (12.6, 8.0), (5.0, 12.8)))
    elif name == "stop":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(filled)
        painter.drawRoundedRect(QRectF(4.6, 4.6, 6.8, 6.8), 1.0, 1.0)
    elif name == "export":
        painter.drawLine(QPointF(8, 11.5), QPointF(8, 3.0))
        painter.drawPath(_path((4.8, 6.2), (8, 3.0), (11.2, 6.2)))
        painter.drawPath(_path((3.2, 9.6), (3.2, 13.0), (12.8, 13.0), (12.8, 9.6)))
    elif name == "import":
        painter.drawLine(QPointF(8, 2.5), QPointF(8, 10.5))
        painter.drawPath(_path((4.8, 7.4), (8, 10.6), (11.2, 7.4)))
        painter.drawPath(_path((3.2, 11.2), (3.2, 13.0), (12.8, 13.0), (12.8, 11.2)))
    elif name == "settings":
        for y, knob in ((4.0, 6.2), (8.0, 10.2), (12.0, 5.0)):
            painter.drawLine(QPointF(2.4, y), QPointF(13.6, y))
            painter.setBrush(QColor(COLORS["bg"]))
            painter.drawEllipse(QPointF(knob, y), 1.7, 1.7)
            painter.setBrush(Qt.BrushStyle.NoBrush)
    elif name == "history":
        painter.drawEllipse(QPointF(8, 8), 5.6, 5.6)
        painter.drawPath(_path((8, 4.9), (8, 8.1), (10.6, 9.6)))
    elif name == "folder":
        painter.drawPath(
            _path((2.2, 5.0), (6.2, 5.0), (7.5, 6.4), (13.8, 6.4), (13.8, 12.6), (2.2, 12.6), (2.2, 5.0))
        )
    elif name == "trash":
        painter.drawLine(QPointF(2.8, 4.4), QPointF(13.2, 4.4))
        painter.drawPath(_path((6.2, 4.4), (6.6, 2.6), (9.4, 2.6), (9.8, 4.4)))
        painter.drawPath(_path((4.4, 4.4), (5.0, 13.2), (11.0, 13.2), (11.6, 4.4)))
        painter.drawLine(QPointF(6.8, 6.6), QPointF(7.0, 11.2))
        painter.drawLine(QPointF(9.2, 6.6), QPointF(9.0, 11.2))
    elif name == "code":
        painter.drawPath(_path((6.0, 4.8), (2.6, 8.0), (6.0, 11.2)))
        painter.drawPath(_path((10.0, 4.8), (13.4, 8.0), (10.0, 11.2)))
    elif name == "image":
        painter.drawRoundedRect(QRectF(2.4, 3.4, 11.2, 9.2), 1.4, 1.4)
        painter.drawEllipse(QPointF(5.8, 6.6), 1.15, 1.15)
        painter.drawPath(_path((3.0, 11.2), (6.4, 8.0), (8.7, 10.0), (10.6, 8.6), (13.2, 11.2)))
    elif name == "sparkles":
        painter.drawPath(_path((6.4, 2.6), (7.4, 5.4), (10.2, 6.4), (7.4, 7.4), (6.4, 10.2), (5.4, 7.4), (2.6, 6.4), (5.4, 5.4), (6.4, 2.6)))
        painter.drawPath(_path((11.2, 9.6), (11.8, 11.2), (13.4, 11.8), (11.8, 12.4), (11.2, 14.0), (10.6, 12.4), (9.0, 11.8), (10.6, 11.2), (11.2, 9.6)))
    elif name == "plus":
        painter.drawLine(QPointF(8, 3.4), QPointF(8, 12.6))
        painter.drawLine(QPointF(3.4, 8), QPointF(12.6, 8))
    elif name == "minus":
        painter.drawLine(QPointF(3.4, 8), QPointF(12.6, 8))
    elif name == "close":
        painter.drawLine(QPointF(4.2, 4.2), QPointF(11.8, 11.8))
        painter.drawLine(QPointF(11.8, 4.2), QPointF(4.2, 11.8))
    elif name == "chevron-down":
        painter.drawPath(_path((4.4, 6.2), (8, 9.8), (11.6, 6.2)))
    elif name == "chevron-right":
        painter.drawPath(_path((6.2, 4.4), (9.8, 8), (6.2, 11.6)))
    elif name == "grid":
        painter.drawRoundedRect(QRectF(2.6, 2.6, 4.4, 4.4), 0.8, 0.8)
        painter.drawRoundedRect(QRectF(9.0, 2.6, 4.4, 4.4), 0.8, 0.8)
        painter.drawRoundedRect(QRectF(2.6, 9.0, 4.4, 4.4), 0.8, 0.8)
        painter.drawRoundedRect(QRectF(9.0, 9.0, 4.4, 4.4), 0.8, 0.8)
    elif name == "cube":
        painter.drawPath(_path((8.0, 2.4), (13.4, 5.2), (13.4, 10.8), (8.0, 13.6), (2.6, 10.8), (2.6, 5.2), (8.0, 2.4)))
        painter.drawPath(_path((2.6, 5.2), (8.0, 8.0), (13.4, 5.2)))
        painter.drawLine(QPointF(8, 8), QPointF(8, 13.6))
    elif name == "layers":
        painter.drawPath(_path((8.0, 2.6), (13.6, 5.6), (8.0, 8.6), (2.4, 5.6), (8.0, 2.6)))
        painter.drawPath(_path((2.4, 8.4), (8.0, 11.4), (13.6, 8.4)))
        painter.drawPath(_path((2.4, 11.0), (8.0, 14.0), (13.6, 11.0)))
    elif name == "save":
        painter.drawRoundedRect(QRectF(3.0, 3.0, 10.0, 10.0), 1.2, 1.2)
        painter.drawPath(_path((5.6, 3.2), (5.6, 6.6), (10.4, 6.6), (10.4, 3.2)))
        painter.drawRoundedRect(QRectF(5.2, 9.2, 5.6, 3.8), 0.8, 0.8)
    elif name in {"undo", "redo"}:
        path = QPainterPath()
        if name == "undo":
            painter.drawPath(_path((3.2, 6.2), (3.2, 9.4), (6.4, 9.4)))
            path.moveTo(3.2, 9.4)
            path.cubicTo(4.0, 5.2, 8.6, 3.6, 12.8, 6.2)
        else:
            painter.drawPath(_path((12.8, 6.2), (12.8, 9.4), (9.6, 9.4)))
            path.moveTo(12.8, 9.4)
            path.cubicTo(12.0, 5.2, 7.4, 3.6, 3.2, 6.2)
        painter.drawPath(path)
    elif name == "search":
        painter.drawEllipse(QPointF(7.0, 7.0), 4.0, 4.0)
        painter.drawLine(QPointF(10.0, 10.0), QPointF(13.4, 13.4))
    elif name == "eye":
        path = QPainterPath()
        path.moveTo(1.8, 8.0)
        path.cubicTo(4.2, 4.0, 11.8, 4.0, 14.2, 8.0)
        path.cubicTo(11.8, 12.0, 4.2, 12.0, 1.8, 8.0)
        painter.drawPath(path)
        painter.drawEllipse(QPointF(8.0, 8.0), 1.8, 1.8)
    elif name == "move":
        painter.drawLine(QPointF(8, 2.6), QPointF(8, 13.4))
        painter.drawLine(QPointF(2.6, 8), QPointF(13.4, 8))
        for tip, pair in (
            ((8, 2.6), ((6.4, 4.2), (9.6, 4.2))),
            ((8, 13.4), ((6.4, 11.8), (9.6, 11.8))),
            ((2.6, 8), ((4.2, 6.4), (4.2, 9.6))),
            ((13.4, 8), ((11.8, 6.4), (11.8, 9.6))),
        ):
            painter.drawPath(_path(tip, pair[0]))
            painter.drawPath(_path(tip, pair[1]))
    elif name in {"zoom-in", "zoom-out"}:
        painter.drawEllipse(QPointF(7.0, 7.0), 4.0, 4.0)
        painter.drawLine(QPointF(10.0, 10.0), QPointF(13.4, 13.4))
        painter.drawLine(QPointF(5.0, 7.0), QPointF(9.0, 7.0))
        if name == "zoom-in":
            painter.drawLine(QPointF(7.0, 5.0), QPointF(7.0, 9.0))
    elif name == "rotate":
        path = QPainterPath()
        path.arcMoveTo(QRectF(2.6, 2.6, 10.8, 10.8), 70)
        path.arcTo(QRectF(2.6, 2.6, 10.8, 10.8), 70, 280)
        painter.drawPath(path)
        painter.drawPath(_path((7.6, 2.0), (10.6, 3.6), (7.8, 5.4)))
    elif name == "pointer":
        painter.drawPath(_path((4.6, 2.6), (4.6, 12.2), (7.2, 9.8), (9.0, 13.2), (11.0, 12.2), (9.2, 8.8), (12.6, 8.4), (4.6, 2.6)))
    elif name == "text":
        painter.drawLine(QPointF(3.6, 3.4), QPointF(12.4, 3.4))
        painter.drawLine(QPointF(8, 3.4), QPointF(8, 12.8))
    elif name == "square":
        painter.drawRoundedRect(QRectF(2.8, 2.8, 10.4, 10.4), 1.0, 1.0)
    elif name == "circle":
        painter.drawEllipse(QPointF(8, 8), 5.2, 5.2)
    elif name == "camera":
        painter.drawRoundedRect(QRectF(2.2, 4.6, 11.6, 8.2), 1.4, 1.4)
        painter.drawEllipse(QPointF(8, 8.7), 2.2, 2.2)
        painter.drawLine(QPointF(5.8, 4.6), QPointF(6.6, 2.8))
        painter.drawLine(QPointF(6.6, 2.8), QPointF(9.4, 2.8))
        painter.drawLine(QPointF(9.4, 2.8), QPointF(10.2, 4.6))
    elif name == "monitor":
        painter.drawRoundedRect(QRectF(2.2, 3.0, 11.6, 8.0), 1.2, 1.2)
        painter.drawLine(QPointF(8, 11.0), QPointF(8, 13.2))
        painter.drawLine(QPointF(5.4, 13.2), QPointF(10.6, 13.2))
    elif name == "phone":
        painter.drawRoundedRect(QRectF(5.0, 1.8, 6.0, 12.4), 1.4, 1.4)
        painter.drawLine(QPointF(7.2, 3.8), QPointF(8.8, 3.8))
        painter.drawEllipse(QPointF(8.0, 12.2), 0.55, 0.55)
    elif name == "refresh":
        path = QPainterPath()
        path.arcMoveTo(QRectF(2.8, 2.8, 10.4, 10.4), 40)
        path.arcTo(QRectF(2.8, 2.8, 10.4, 10.4), 40, 280)
        painter.drawPath(path)
        painter.drawPath(_path((11.2, 1.8), (13.2, 4.2), (10.0, 5.2)))
    elif name == "check":
        painter.drawPath(_path((3.2, 8.4), (6.6, 11.6), (12.8, 4.6)))
    elif name == "bolt":
        painter.drawPath(_path((9.2, 1.6), (4.2, 9.0), (7.8, 9.0), (6.8, 14.4), (11.8, 7.0), (8.2, 7.0), (9.2, 1.6)))
    elif name == "dots":
        for x in (3.8, 8.0, 12.2):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(filled)
            painter.drawEllipse(QPointF(x, 8.0), 1.1, 1.1)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(pen)
    elif name == "help":
        painter.drawEllipse(QPointF(8.0, 8.0), 5.8, 5.8)
        path = QPainterPath()
        path.moveTo(6.0, 6.2)
        path.cubicTo(6.2, 3.6, 10.2, 3.4, 10.0, 6.0)
        path.cubicTo(9.9, 7.4, 8.2, 7.2, 8.0, 9.0)
        painter.drawPath(path)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(filled)
        painter.drawEllipse(QPointF(8.0, 11.4), 0.8, 0.8)


@functools.lru_cache(maxsize=256)
def icon(name: str, size: int = 16, color: str | None = None) -> QIcon:
    """Return a cached line icon drawn with the active accent palette."""
    tint = QColor(color or COLORS["muted"])
    scale = 2
    pixmap = QPixmap(int(size * scale), int(size * scale))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.scale(scale * size / _ICON_BOX, scale * size / _ICON_BOX)
    _draw_glyph(painter, name, tint)
    painter.end()
    pixmap.setDevicePixelRatio(scale)
    return QIcon(pixmap)


def icon_pixmap(name: str, size: int = 16, color: str | None = None) -> QPixmap:
    return icon(name, size, color).pixmap(QSize(size, size))


# ---------------------------------------------------------------------------
# Stylesheet
# ---------------------------------------------------------------------------

QSS = """
* {
    outline: none;
}
QWidget {
    color: #D7DAE0;
}
QMainWindow, QWidget#root {
    background: #1E1F22;
}
QWidget#sidebar {
    background: #202226;
    border-right: 1px solid #303338;
}
QWidget#topbar {
    background: #24262A;
    border-bottom: 1px solid #303338;
}
QFrame#card, QWidget#card {
    background: #24262A;
    border: 1px solid #34373C;
    border-radius: 4px;
}
QFrame#cardSoft {
    background: #212328;
    border: 1px solid #303338;
    border-radius: 4px;
}
QFrame#projectRow {
    background: #25272C;
    border: 1px solid #34373C;
    border-radius: 4px;
}
QFrame#projectRow:hover {
    background: #2B2E33;
    border-color: #464A51;
}
QFrame#hero {
    background: transparent;
    border: none;
}
QLabel {
    background: transparent;
    padding: 0;
}
QLabel#title {
    color: #F0F2F5;
}
QLabel#muted {
    color: #A0A5AD;
}
QLabel#dim {
    color: #767B84;
}
QLabel#accent {
    color: #D97757;
}
QLabel#success {
    color: #83B292;
}
QLabel#warning {
    color: #C6A96B;
}
QLabel#danger {
    color: #C47F86;
}
QLabel#pill, QLabel#pillAccent, QLabel#pillTeal, QLabel#pillGold {
    border-radius: 3px;
    padding: 1px 6px;
    font-size: 10px;
    font-weight: 600;
}
QLabel#pill {
    background: #2B2E33;
    color: #A0A5AD;
    border: 1px solid #3A3D43;
}
QLabel#pillAccent {
    background: #33251F;
    color: #E0A08B;
    border: 1px solid #513830;
}
QLabel#pillTeal {
    background: #242C27;
    color: #93B2A0;
    border: 1px solid #33423A;
}
QLabel#pillGold {
    background: #2E2A20;
    color: #C9B486;
    border: 1px solid #453E2E;
}
QPushButton {
    background: #2B2E33;
    color: #DDE0E5;
    border: 1px solid #3C4046;
    border-radius: 3px;
    padding: 5px 12px;
    font-weight: 600;
    font-size: 12px;
    min-height: 16px;
}
QPushButton:hover {
    background: #33363C;
    border-color: #4C515A;
}
QPushButton:pressed {
    background: #26282D;
}
QPushButton:disabled {
    color: #62666E;
    background: #232529;
    border-color: #2F3237;
}
QPushButton#primary {
    background: #D97757;
    color: #1B110D;
    border: 1px solid #E18A6C;
    font-weight: 700;
}
QPushButton#primary:hover {
    background: #E4896C;
    border-color: #EE9B7F;
}
QPushButton#primary:pressed {
    background: #C4684A;
    border-color: #C4684A;
}
QPushButton#primary:disabled {
    background: #43312A;
    border-color: #43312A;
    color: #8C7971;
}
QPushButton#teal {
    background: #2B2E33;
    color: #DDE0E5;
    border: 1px solid #3C4046;
}
QPushButton#teal:hover {
    background: #33363C;
    border-color: #4C515A;
}
QPushButton#ghost {
    background: transparent;
    border: 1px solid transparent;
    color: #A8ADB4;
    padding: 4px 8px;
    font-weight: 500;
}
QPushButton#ghost:hover {
    background: #2C2F34;
    border-color: #3A3D43;
    color: #F0F2F5;
}
QPushButton#danger {
    background: transparent;
    color: #C47F86;
    border: 1px solid #453034;
}
QPushButton#danger:hover {
    background: #2E2225;
    border-color: #5A3D42;
}
QPushButton#nav {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 3px;
    color: #A0A5AD;
    text-align: left;
    padding: 6px 9px;
    font-weight: 500;
}
QPushButton#nav:hover {
    background: #282B30;
    color: #DDE0E5;
}
QPushButton#nav:checked {
    background: #2F3238;
    color: #F0F2F5;
    border: 1px solid #3E424A;
}
QPushButton#choice {
    background: #232529;
    border: 1px solid #34373C;
    border-radius: 4px;
    color: #D7DAE0;
    text-align: left;
    padding: 10px 12px;
    font-weight: 600;
}
QPushButton#choice:hover {
    background: #2A2D32;
    border-color: #464A51;
}
QPushButton#choice:checked {
    background: #2E3137;
    border: 1px solid #D97757;
    color: #FFFFFF;
}
QPushButton#choiceSmall {
    background: #26282D;
    border: 1px solid #34373C;
    border-radius: 3px;
    color: #B8BDC5;
    padding: 4px 9px;
    font-weight: 500;
}
QPushButton#choiceSmall:hover {
    border-color: #4C515A;
    color: #F0F2F5;
}
QPushButton#choiceSmall:checked {
    background: #2F3238;
    border-color: #D97757;
    color: #FFFFFF;
}
QPushButton#suggestion {
    background: #26282D;
    border: 1px solid #34373C;
    border-radius: 3px;
    color: #BEC3CA;
    text-align: left;
    padding: 6px 10px;
    font-weight: 500;
}
QPushButton#suggestion:hover {
    background: #2D3035;
    border-color: #4C515A;
    color: #FFFFFF;
}
QTextEdit#promptBig {
    background: #1B1D21;
    border: 1px solid #34373C;
    border-radius: 3px;
    padding: 9px;
    font-size: 12px;
    line-height: 1.4;
}
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: #1B1D21;
    color: #D7DAE0;
    border: 1px solid #34373C;
    border-radius: 3px;
    padding: 5px 8px;
    font-size: 12px;
    selection-background-color: #4A3B34;
    selection-color: #FFFFFF;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border: 1px solid #D97757;
    background: #1E2024;
}
QLineEdit:disabled, QTextEdit:disabled, QComboBox:disabled {
    color: #62666E;
    background: #212328;
    border-color: #2F3237;
}
QLineEdit#search {
    background: #1B1D21;
    border-radius: 3px;
    padding-left: 9px;
}
QTextEdit#chatInput {
    background: #1B1D21;
    border-radius: 3px;
    padding: 7px 9px;
}
QComboBox::drop-down {
    border: none;
    width: 20px;
}
QComboBox QAbstractItemView {
    background: #26282D;
    border: 1px solid #3E424A;
    border-radius: 3px;
    padding: 3px;
    selection-background-color: #35383E;
    color: #D7DAE0;
}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    background: #2B2E33;
    border: none;
    width: 16px;
}
QCheckBox {
    spacing: 7px;
    color: #BEC3CA;
}
QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border-radius: 2px;
    border: 1px solid #454951;
    background: #1B1D21;
}
QCheckBox::indicator:checked {
    background: #D97757;
    border-color: #D97757;
    image: none;
}
QCheckBox::indicator:hover {
    border-color: #D97757;
}
QRadioButton {
    spacing: 7px;
    color: #BEC3CA;
}
QRadioButton::indicator {
    width: 13px;
    height: 13px;
    border-radius: 6px;
    border: 1px solid #454951;
    background: #1B1D21;
}
QRadioButton::indicator:checked {
    background: #D97757;
    border: 3px solid #D97757;
}
QProgressBar {
    background: #2A2D32;
    border: none;
    border-radius: 2px;
    text-align: center;
    color: transparent;
    height: 6px;
    max-height: 6px;
}
QProgressBar::chunk {
    border-radius: 2px;
    background: #D97757;
}
QScrollArea {
    background: transparent;
    border: none;
}
QScrollArea > QWidget > QWidget {
    background: transparent;
}
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #3C4046;
    border-radius: 2px;
    min-height: 24px;
    margin: 2px;
}
QScrollBar::handle:vertical:hover {
    background: #4E535C;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
    height: 0;
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: #3C4046;
    border-radius: 2px;
    min-width: 24px;
    margin: 2px;
}
QScrollBar::handle:horizontal:hover {
    background: #4E535C;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: none;
    width: 0;
}
QListWidget, QTreeWidget, QTableWidget {
    background: transparent;
    border: none;
    color: #CDD1D7;
    outline: none;
}
QListWidget::item, QTreeWidget::item {
    border-radius: 2px;
    padding: 3px 5px;
}
QListWidget::item:hover, QTreeWidget::item:hover {
    background: #2A2D32;
}
QListWidget::item:selected, QTreeWidget::item:selected {
    background: #35383E;
    color: #FFFFFF;
}
QTreeWidget::branch {
    background: transparent;
}
QTabWidget::pane {
    border: none;
}
QTabBar::tab {
    background: transparent;
    color: #A0A5AD;
    padding: 6px 12px;
    border-radius: 3px;
    font-weight: 500;
}
QTabBar::tab:hover {
    color: #DDE0E5;
}
QTabBar::tab:selected {
    background: #2F3238;
    color: #F0F2F5;
}
QMenu {
    background: #26282D;
    border: 1px solid #3E424A;
    border-radius: 3px;
    padding: 4px;
}
QMenuBar {
    background: #202226;
    color: #BEC3CA;
    border-bottom: 1px solid #303338;
    padding: 1px 3px;
}
QMenuBar::item {
    background: transparent;
    padding: 5px 9px;
    border-radius: 3px;
}
QMenuBar::item:selected {
    background: #2B2E33;
}
QMenuBar::item:pressed {
    background: #35383E;
}
QMenu::item {
    padding: 6px 24px 6px 11px;
    border-radius: 3px;
}
QMenu::item:selected {
    background: #35383E;
}
QMenu::separator {
    height: 1px;
    background: #34373C;
    margin: 4px 8px;
}
QToolTip {
    background: #2B2E33;
    color: #D7DAE0;
    border: 1px solid #454951;
    border-radius: 3px;
    padding: 4px 7px;
}
QDialog {
    background: #1E1F22;
}
QSplitter::handle {
    background: #303338;
}
QSplitter::handle:horizontal {
    width: 1px;
}
QSplitter::handle:vertical {
    height: 1px;
}
QSplitter::handle:hover {
    background: #D97757;
}
QStatusBar {
    background: #202226;
    color: #767B84;
    border-top: 1px solid #303338;
}
QStatusBar::item {
    border: none;
}
QPlainTextEdit#code {
    background: #1B1D21;
    color: #D7DDE5;
    border: none;
    border-radius: 0;
    font-family: "Cascadia Code", "JetBrains Mono", "Consolas", monospace;
    font-size: 12px;
    selection-background-color: #34404C;
    padding: 8px;
}
QFrame#editorHeader {
    background: #232529;
    border-bottom: 1px solid #303338;
    border-top-left-radius: 3px;
    border-top-right-radius: 3px;
}
QListWidget#assetGrid {
    background: #1B1D21;
    border: 1px solid #34373C;
    border-radius: 3px;
}
QListWidget#eventsList::item {
    padding: 2px 4px;
    border-radius: 2px;
}
QListWidget#historyList {
    background: #1B1D21;
    border: 1px solid #34373C;
    border-radius: 3px;
}
QComboBox#chatSelect {
    background: #26282D;
    border: 1px solid #3A3D43;
    border-radius: 3px;
    padding: 3px 8px;
}
QFrame#toolCall, QFrame#toolCallGroup {
    background: #212328;
    border: 1px solid #303338;
    border-radius: 3px;
}
QPushButton#toolCallHeader, QPushButton#toolCallGroupHeader {
    background: transparent;
    border: none;
    color: #A8ADB4;
    text-align: left;
    padding: 4px 6px;
    font-weight: 500;
}
QPushButton#toolCallHeader:hover, QPushButton#toolCallGroupHeader:hover {
    background: #292C31;
    color: #DDE0E5;
}
QPlainTextEdit#toolCallDetails {
    background: #1B1D21;
    border: 1px solid #303338;
    border-radius: 3px;
    font-family: "Cascadia Code", "Consolas", monospace;
    font-size: 11px;
    color: #A8B2BE;
}
"""


def apply_theme(app: QApplication) -> None:
    load_fonts()
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor(COLORS["bg"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(COLORS["bg_deep"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(COLORS["surface_2"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#35383E"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    app.setPalette(palette)
    app.setFont(ui_font(9))
    app.setWindowIcon(QIcon(str(BRAND_DIR / "logo_256.png")))


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------


def logo_pixmap(size: int = 64) -> QPixmap:
    path = BRAND_DIR / "logo_512.png"
    pixmap = QPixmap(str(path)) if path.exists() else QPixmap()
    if pixmap.isNull():
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
    return pixmap.scaled(
        QSize(size, size),
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
