"""Visual language of the Reasonable Engine editor.

The interface is deliberately quiet: graphite surfaces, one warm accent and
muted status colours. The brand logo supplies the character, while the UI
itself avoids gradients, glows and competing accent hues.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QApplication

from reasonable.core.paths import BRAND_DIR, FONT_DIR


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


# ---------------------------------------------------------------------------
# Stylesheet
# ---------------------------------------------------------------------------

QSS = """
* {
    outline: none;
}
QWidget {
    color: #E7E9EC;
    font-size: 13px;
}
QMainWindow, QWidget#root {
    background: #0F1115;
}
QWidget#sidebar {
    background: #13161B;
    border-right: 1px solid #24282F;
}
QWidget#topbar {
    background: #13161B;
    border-bottom: 1px solid #24282F;
}
QFrame#card, QWidget#card {
    background: #171A20;
    border: 1px solid #262B33;
    border-radius: 10px;
}
QFrame#cardSoft {
    background: #15181D;
    border: 1px solid #23272E;
    border-radius: 10px;
}
QFrame#projectRow {
    background: #15181D;
    border: 1px solid #242830;
    border-radius: 8px;
}
QFrame#projectRow:hover {
    background: #191D23;
    border-color: #303640;
}
QFrame#hero {
    background: transparent;
    border: none;
}
QLabel {
    background: transparent;
    padding-bottom: 2px;
}
QLabel#title {
    color: #F0F2F4;
    padding-bottom: 4px;
}
QLabel#muted {
    color: #9AA1AB;
}
QLabel#dim {
    color: #6F7680;
}
QLabel#accent {
    color: #D9917A;
}
QLabel#success {
    color: #8DB8A0;
}
QLabel#warning {
    color: #C9AD73;
}
QLabel#danger {
    color: #C98A90;
}
QLabel#pill, QLabel#pillAccent, QLabel#pillTeal, QLabel#pillGold {
    border-radius: 6px;
    padding: 2px 7px;
    font-size: 10px;
    font-weight: 600;
}
QLabel#pill {
    background: #1B1F25;
    color: #A8AFB9;
    border: 1px solid #2B3038;
}
QLabel#pillAccent {
    background: #241C19;
    color: #E0A08B;
    border: 1px solid #4A352D;
}
QLabel#pillTeal {
    background: #1A1F1D;
    color: #9BB5A6;
    border: 1px solid #2E3933;
}
QLabel#pillGold {
    background: #211F19;
    color: #C9B486;
    border: 1px solid #3B352A;
}
QPushButton {
    background: #191D23;
    color: #E7E9EC;
    border: 1px solid #2C323B;
    border-radius: 7px;
    padding: 7px 14px;
    font-weight: 600;
    min-height: 18px;
}
QPushButton:hover {
    background: #21252C;
    border-color: #3A414B;
}
QPushButton:pressed {
    background: #15181D;
}
QPushButton:disabled {
    color: #5E646D;
    background: #15181D;
    border-color: #23272E;
}
QPushButton#primary {
    background: #D97757;
    color: #1B110D;
    border: 1px solid #D97757;
    font-weight: 700;
}
QPushButton#primary:hover {
    background: #E2876B;
    border-color: #E2876B;
}
QPushButton#primary:pressed {
    background: #C4684A;
    border-color: #C4684A;
}
QPushButton#primary:disabled {
    background: #4A332B;
    border-color: #4A332B;
    color: #8C7971;
}
QPushButton#teal {
    background: #1A1E24;
    color: #C9CED6;
    border: 1px solid #343A44;
}
QPushButton#teal:hover {
    background: #22272F;
    border-color: #424A56;
}
QPushButton#ghost {
    background: transparent;
    border: 1px solid transparent;
    color: #A5ACB6;
    padding: 6px 10px;
}
QPushButton#ghost:hover {
    background: #1D2127;
    color: #F0F2F4;
}
QPushButton#danger {
    background: transparent;
    color: #D49AA0;
    border: 1px solid #4A3034;
}
QPushButton#danger:hover {
    background: #241A1C;
}
QPushButton#nav {
    background: transparent;
    border: none;
    border-left: 2px solid transparent;
    border-radius: 6px;
    color: #9AA1AB;
    text-align: left;
    padding: 8px 12px;
    font-weight: 500;
}
QPushButton#nav:hover {
    background: #1A1E24;
    color: #E7E9EC;
}
QPushButton#nav:checked {
    background: #1E2228;
    color: #F0F2F4;
    border-left: 2px solid #D97757;
}
QPushButton#choice {
    background: #14171C;
    border: 1px solid #2A3038;
    border-radius: 8px;
    color: #DCE0E5;
    text-align: left;
    padding: 13px 15px;
    font-weight: 600;
}
QPushButton#choice:hover {
    background: #1A1E24;
    border-color: #3A414B;
}
QPushButton#choice:checked {
    background: #1C2027;
    border: 1px solid #D97757;
    color: #FFFFFF;
}
QPushButton#choiceSmall {
    background: #15181D;
    border: 1px solid #2A3038;
    border-radius: 7px;
    color: #B7BDC6;
    padding: 7px 11px;
    font-weight: 500;
}
QPushButton#choiceSmall:hover {
    border-color: #3A414B;
    color: #F0F2F4;
}
QPushButton#choiceSmall:checked {
    background: #1E2228;
    border-color: #D97757;
    color: #FFFFFF;
}
QPushButton#suggestion {
    background: #15181D;
    border: 1px solid #2A3038;
    border-radius: 7px;
    color: #C1C7CF;
    text-align: left;
    padding: 8px 13px;
    font-weight: 500;
}
QPushButton#suggestion:hover {
    background: #1A1E24;
    border-color: #3A414B;
    color: #FFFFFF;
}
QTextEdit#promptBig {
    background: #12151A;
    border: 1px solid #2A3038;
    border-radius: 8px;
    padding: 12px;
    font-size: 14px;
    line-height: 1.45;
}
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: #12151A;
    color: #E7E9EC;
    border: 1px solid #2A3038;
    border-radius: 7px;
    padding: 7px 10px;
    selection-background-color: #3A332F;
    selection-color: #FFFFFF;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border: 1px solid #D97757;
    background: #15181D;
}
QLineEdit:disabled, QTextEdit:disabled, QComboBox:disabled {
    color: #656B74;
    background: #13161B;
    border-color: #23272E;
}
QLineEdit#search {
    background: #15181D;
    border-radius: 7px;
    padding-left: 12px;
}
QTextEdit#chatInput {
    background: #12151A;
    border-radius: 8px;
    padding: 9px 11px;
}
QComboBox::drop-down {
    border: none;
    width: 24px;
}
QComboBox QAbstractItemView {
    background: #171A20;
    border: 1px solid #303640;
    border-radius: 6px;
    padding: 4px;
    selection-background-color: #282D35;
    color: #E7E9EC;
}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    background: #1D2127;
    border: none;
    width: 18px;
}
QCheckBox {
    spacing: 8px;
    color: #C1C7CF;
}
QCheckBox::indicator {
    width: 17px;
    height: 17px;
    border-radius: 4px;
    border: 1px solid #3A414B;
    background: #12151A;
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
    spacing: 8px;
    color: #C1C7CF;
}
QRadioButton::indicator {
    width: 16px;
    height: 16px;
    border-radius: 8px;
    border: 1px solid #3A414B;
    background: #12151A;
}
QRadioButton::indicator:checked {
    background: #D97757;
    border: 4px solid #D97757;
}
QProgressBar {
    background: #1D2127;
    border: none;
    border-radius: 5px;
    text-align: center;
    color: transparent;
    height: 10px;
}
QProgressBar::chunk {
    border-radius: 5px;
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
    width: 8px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #353A43;
    border-radius: 4px;
    min-height: 28px;
}
QScrollBar::handle:vertical:hover {
    background: #474D57;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
    height: 0;
}
QScrollBar:horizontal {
    background: transparent;
    height: 8px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background: #353A43;
    border-radius: 4px;
    min-width: 28px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: none;
    width: 0;
}
QListWidget, QTreeWidget, QTableWidget {
    background: transparent;
    border: none;
    color: #D7DBE0;
    outline: none;
}
QListWidget::item, QTreeWidget::item {
    border-radius: 6px;
    padding: 6px 7px;
}
QListWidget::item:hover, QTreeWidget::item:hover {
    background: #1D2127;
}
QListWidget::item:selected, QTreeWidget::item:selected {
    background: #282D35;
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
    color: #9AA1AB;
    padding: 8px 13px;
    border-radius: 6px;
    font-weight: 500;
}
QTabBar::tab:hover {
    color: #E7E9EC;
}
QTabBar::tab:selected {
    background: #1F232A;
    color: #F0F2F4;
}
QMenu {
    background: #171A20;
    border: 1px solid #303640;
    border-radius: 8px;
    padding: 5px;
}
QMenuBar {
    background: #101216;
    color: #C1C7CF;
    border-bottom: 1px solid #23272E;
    padding: 2px 4px;
}
QMenuBar::item {
    background: transparent;
    padding: 6px 10px;
    border-radius: 5px;
}
QMenuBar::item:selected {
    background: #1D2127;
}
QMenuBar::item:pressed {
    background: #282D35;
}
QMenu::item {
    padding: 7px 26px 7px 12px;
    border-radius: 5px;
}
QMenu::item:selected {
    background: #282D35;
}
QMenu::separator {
    height: 1px;
    background: #23272E;
    margin: 5px 8px;
}
QToolTip {
    background: #1D2127;
    color: #E7E9EC;
    border: 1px solid #343A44;
    border-radius: 6px;
    padding: 5px 8px;
}
QDialog {
    background: #101216;
}
QSplitter::handle {
    background: #23272E;
}
QSplitter::handle:horizontal {
    width: 3px;
}
QSplitter::handle:vertical {
    height: 3px;
}
QSplitter::handle:hover {
    background: #D97757;
}
QStatusBar {
    background: #101216;
    color: #7D848E;
    border-top: 1px solid #23272E;
}
QPlainTextEdit#code {
    background: #101216;
    color: #D7DDE5;
    border: none;
    border-radius: 0;
    font-family: "Cascadia Code", "JetBrains Mono", "Consolas", monospace;
    font-size: 13px;
    selection-background-color: #303842;
    padding: 10px;
}
QFrame#editorHeader {
    background: #16191E;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
}
QListWidget#assetGrid {
    background: #12151A;
    border: 1px solid #262B33;
    border-radius: 8px;
}
QListWidget#eventsList::item {
    padding: 4px 5px;
    border-radius: 5px;
}
"""


def apply_theme(app: QApplication) -> None:
    load_fonts()
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#282D35"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    app.setPalette(palette)
    app.setFont(ui_font(10))
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
