"""Project hub shown when no project is open.

The layout mirrors desktop engines: a compact title bar, a list of recent
projects and a narrow column with the first-run actions and the AI status.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from reasonable import branding
from reasonable.core.i18n import tagline as i18n_tagline, t
from reasonable.core.paths import DOCS_DIR
from reasonable.core.settings import Settings
from reasonable.version import VERSION_LABEL

from . import theme
from .widgets import Badge, Card, ProjectCard, muted, title_label


class WelcomePage(QWidget):
    new_project = Signal()
    new_blank_project = Signal()
    open_project = Signal()
    open_settings = Signal()
    configure_ai = Signal()
    open_recent = Signal(str)
    delete_project = Signal(str)
    open_tutorial = Signal()

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self._recent_cards: list[QWidget] = []

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        content = QWidget()
        content.setObjectName("root")
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(22, 14, 22, 16)
        layout.setSpacing(14)

        layout.addWidget(self._build_header())
        layout.addLayout(self._build_intro())
        layout.addLayout(self._build_body(), 1)
        layout.addLayout(self._build_footer())

        self.refresh()
        self._update_footer_compact()

    # ------------------------------------------------------------------
    def _build_header(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("topbar")
        bar.setFixedHeight(46)
        row = QHBoxLayout(bar)
        row.setContentsMargins(12, 6, 10, 6)
        row.setSpacing(9)

        logo = QLabel()
        logo.setPixmap(theme.logo_pixmap(22))
        row.addWidget(logo)

        name = QLabel("Reasonable Engine")
        name.setObjectName("title")
        name.setFont(theme.ui_font(10, 600))
        row.addWidget(name)

        sub = QLabel(t("welcome.version_line", version=VERSION_LABEL, tagline=i18n_tagline()))
        sub.setObjectName("dim")
        sub.setFont(theme.ui_font(8))
        row.addWidget(sub)
        row.addStretch(1)

        settings_button = QPushButton(t("welcome.settings"))
        settings_button.setObjectName("ghost")
        settings_button.setIcon(theme.icon("settings", 14))
        settings_button.setIconSize(QSize(14, 14))
        settings_button.clicked.connect(self.open_settings)
        row.addWidget(settings_button)
        return bar

    def _build_intro(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 4, 0, 2)
        row.setSpacing(16)

        left_host = QWidget()
        # The heading is two lines and the caption wraps to three. Without an
        # explicit minimum the outer stretch layout may compress this column
        # and clip the first line of both labels.
        left_host.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )
        left = QVBoxLayout(left_host)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(6)
        heading = QLabel(t("welcome.heading"))
        heading.setObjectName("title")
        heading.setFont(theme.display_font(15, 600))
        heading.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        heading.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        left.addWidget(heading)
        caption = muted(t("welcome.intro"), size=9)
        caption.setMaximumWidth(640)
        caption.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        left.addWidget(caption)
        # Keep both wrapped lines intact even when the page below asks for
        # space; the welcome content is scrollable, clipping is not accepted.
        left_host.setMinimumHeight(max(left_host.sizeHint().height(), 1))
        row.addWidget(left_host, 1)

        host = QWidget()
        host.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        buttons = QHBoxLayout(host)
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(8)

        self.create_button = QPushButton(t("welcome.create_ai"))
        self.create_button.setObjectName("primary")
        self.create_button.setMinimumHeight(28)
        self.create_button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.create_button.setIcon(theme.icon("sparkles", 14, "#1B110D"))
        self.create_button.setToolTip(t("welcome.create_ai_tip"))
        self.create_button.clicked.connect(self.new_project)
        buttons.addWidget(self.create_button)

        self.open_button = QPushButton(t("welcome.open_project"))
        self.open_button.setMinimumHeight(28)
        self.open_button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.open_button.setIcon(theme.icon("folder", 14))
        self.open_button.setToolTip(t("welcome.open_project_tip"))
        self.open_button.clicked.connect(self.open_project)
        buttons.addWidget(self.open_button)

        self.blank_button = QPushButton(t("welcome.blank_project"))
        self.blank_button.setObjectName("ghost")
        self.blank_button.setMinimumHeight(28)
        self.blank_button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.blank_button.setIcon(theme.icon("plus", 14))
        self.blank_button.setToolTip(t("welcome.blank_project_tip"))
        self.blank_button.clicked.connect(self.new_blank_project)
        buttons.addWidget(self.blank_button)

        row.addWidget(host, 0, Qt.AlignmentFlag.AlignVCenter)
        return row

    def _eyebrow(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("dim")
        label.setFont(theme.section_font())
        return label

    def _build_body(self) -> QHBoxLayout:
        body = QHBoxLayout()
        body.setSpacing(12)

        recent_card = Card(padding=12)
        recent_card.setMinimumHeight(240)
        header = QHBoxLayout()
        header.addWidget(title_label(t("welcome.recent_projects"), 9))
        header.addStretch(1)
        self.recent_count = Badge("0", "default")
        header.addWidget(self.recent_count)
        recent_card.layout().addLayout(header)
        recent_card.layout().addWidget(muted(t("welcome.recent_hint"), size=8))
        self.recent_box = QVBoxLayout()
        self.recent_box.setSpacing(5)
        recent_card.layout().addLayout(self.recent_box)
        recent_card.layout().addStretch(1)
        body.addWidget(recent_card, 3)

        right = QVBoxLayout()
        right.setSpacing(12)

        steps_card = Card(soft=True, padding=12)
        steps_card.layout().addWidget(self._eyebrow(t("welcome.what_next")))
        for number, title, text in (
            ("1", t("welcome.step1_title"), t("welcome.step1_text")),
            ("2", t("welcome.step2_title"), t("welcome.step2_text")),
            ("3", t("welcome.step3_title"), t("welcome.step3_text")),
        ):
            step = QHBoxLayout()
            step.setSpacing(8)
            marker = QLabel(number)
            marker.setObjectName("dim")
            marker.setFont(theme.ui_font(8, 700))
            marker.setFixedWidth(10)
            marker.setAlignment(Qt.AlignmentFlag.AlignTop)
            step.addWidget(marker)
            texts = QVBoxLayout()
            texts.setSpacing(0)
            label = QLabel(title)
            label.setFont(theme.ui_font(9, 600))
            texts.addWidget(label)
            texts.addWidget(muted(text, size=8))
            step.addLayout(texts, 1)
            steps_card.layout().addLayout(step)
        right.addWidget(steps_card)

        ai_card = Card(soft=True, padding=12)
        ai_header = QHBoxLayout()
        ai_header.addWidget(self._eyebrow(t("welcome.ai_helper")))
        ai_header.addStretch(1)
        self.ai_status = Badge(t("welcome.ai_checking"), "default")
        ai_header.addWidget(self.ai_status)
        ai_card.layout().addLayout(ai_header)
        self.ai_text = muted(t("welcome.ai_hint"), size=8)
        self.ai_text.setWordWrap(True)
        ai_card.layout().addWidget(self.ai_text)
        self.ai_button = QPushButton(t("welcome.configure_ai"))
        self.ai_button.setObjectName("teal")
        self.ai_button.clicked.connect(self.configure_ai)
        ai_card.layout().addWidget(self.ai_button)
        right.addWidget(ai_card)
        right.addStretch(1)
        body.addLayout(right, 2)
        return body

    def _build_footer(self) -> QHBoxLayout:
        row = QHBoxLayout()
        tutorial = QPushButton(t("welcome.tutorial"))
        tutorial.setObjectName("ghost")
        tutorial.setIcon(theme.icon("help", 13))
        tutorial.setToolTip(t("welcome.tutorial_tip"))
        tutorial.clicked.connect(self.open_tutorial)
        row.addWidget(tutorial)

        external = QPushButton(t("welcome.external_guide"))
        external.setObjectName("ghost")
        external.setIcon(theme.icon("code", 13))
        external.clicked.connect(self._open_external_guide)
        row.addWidget(external)

        hint = QLabel(t("welcome.footer_splash"))
        hint.setObjectName("dim")
        hint.setFont(theme.ui_font(8))
        row.addWidget(hint)
        row.addStretch(1)
        self._footer_path = str(self.settings.projects_dir())
        folder = QLabel(t("welcome.projects_folder", path=self._footer_path))
        folder.setObjectName("dim")
        folder.setFont(theme.ui_font(8))
        folder.setToolTip(t("welcome.projects_folder_tip"))
        row.addWidget(folder)
        self._footer_hint = hint
        self._footer_folder = folder
        return row

    def _update_footer_compact(self) -> None:
        """Keep the footer inside narrow windows instead of clipping it."""
        if not hasattr(self, "_footer_folder"):
            return
        compact = self.width() < 1250
        self._footer_hint.setVisible(not compact)
        path = str(self.settings.projects_dir())
        self._footer_path = path
        shown = Path(path).name if compact else path
        self._footer_folder.setText(t("welcome.projects_folder", path=shown))
        self._footer_folder.setToolTip(f"{t('welcome.projects_folder_tip')}\n{path}")

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_footer_compact()

    # ------------------------------------------------------------------
    def _open_external_guide(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        path = DOCS_DIR / "EXTERNAL_AGENTS.md"
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
            return
        QMessageBox.information(
            self,
            t("welcome.external_title"),
            t("welcome.external_text"),
        )

    def refresh(self) -> None:
        while self.recent_box.count():
            item = self.recent_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            elif item.layout() is not None:
                self._clear_layout(item.layout())

        recents = self.settings.recent_projects()
        self.recent_count.setText(str(len(recents)))
        if not recents:
            empty = QLabel(t("welcome.recent_empty"))
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setObjectName("muted")
            empty.setWordWrap(True)
            empty.setStyleSheet("padding: 26px 10px;")
            self.recent_box.addWidget(empty)
        else:
            grid = QGridLayout()
            grid.setSpacing(5)
            for index, entry in enumerate(recents[:8]):
                card = ProjectCard(
                    entry.get("name", t("welcome.default_project_name")),
                    entry.get("goal", ""),
                    entry.get("type", "game"),
                    entry.get("path", ""),
                )
                card.clicked.connect(lambda path=entry.get("path", ""): self.open_recent.emit(path))
                card.delete_requested.connect(
                    lambda path=entry.get("path", ""), name=entry.get("name", t("welcome.default_project_name")): self.delete_project.emit(path)
                )
                grid.addWidget(card, index // 2, index % 2)
            self.recent_box.addLayout(grid)

        config = self.settings.get_provider_config()
        name = config.get("name") or config.get("id") or t("welcome.ai_not_selected")
        model = config.get("model") or t("welcome.ai_model_unspecified")
        requires_key = config.get("requires_key") and not config.get("api_key")
        if requires_key:
            self.ai_status.setText(t("welcome.ai_need_key"))
            self.ai_status.set_tone("gold")
            self.ai_text.setText(
                f"{name} · {model}\n{t('welcome.ai_need_key_text')}"
            )
            self.ai_button.setText(t("welcome.ai_add_key"))
        else:
            self.ai_status.setText(t("welcome.ai_ready"))
            self.ai_status.set_tone("default")
            self.ai_text.setText(
                f"{name} · {model}\n"
                + t(
                    "welcome.ai_ready_text",
                    key_state=t("welcome.ai_key_saved") if config.get("api_key") else t("welcome.ai_no_key_needed"),
                )
            )
            self.ai_button.setText(t("welcome.ai_check_settings"))
        self._update_footer_compact()

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            elif item.layout() is not None:
                self._clear_layout(item.layout())
