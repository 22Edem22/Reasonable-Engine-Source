"""Welcome screen: recent projects, first steps and AI status."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
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
        layout.setContentsMargins(40, 24, 40, 28)
        layout.setSpacing(24)

        layout.addLayout(self._build_header())
        layout.addWidget(self._build_intro())
        layout.addLayout(self._build_body())
        layout.addStretch(1)
        layout.addLayout(self._build_footer())

        self.refresh()

    # ------------------------------------------------------------------
    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(11)
        logo = QLabel()
        logo.setPixmap(theme.logo_pixmap(32))
        row.addWidget(logo)

        names = QVBoxLayout()
        names.setSpacing(0)
        name = QLabel("Reasonable Engine")
        name.setObjectName("title")
        name.setFont(theme.display_font(13, 700))
        names.addWidget(name)
        sub = QLabel(t("welcome.version_line", version=VERSION_LABEL, tagline=i18n_tagline()))
        sub.setObjectName("dim")
        sub.setFont(theme.ui_font(9))
        names.addWidget(sub)
        row.addLayout(names)
        row.addStretch(1)

        settings_button = QPushButton(t("welcome.settings"))
        settings_button.setObjectName("ghost")
        settings_button.clicked.connect(self.open_settings)
        row.addWidget(settings_button)
        return row

    def _build_intro(self) -> QWidget:
        section = QWidget()
        layout = QHBoxLayout(section)
        layout.setContentsMargins(0, 8, 0, 4)
        layout.setSpacing(52)

        left = QVBoxLayout()
        left.setSpacing(11)
        eyebrow = QLabel(t("welcome.eyebrow"))
        eyebrow.setObjectName("dim")
        eyebrow.setFont(theme.ui_font(8, 700))
        left.addWidget(eyebrow)

        heading = QLabel(t("welcome.heading"))
        heading.setObjectName("title")
        heading.setFont(theme.display_font(25, 700))
        heading.setWordWrap(True)
        left.addWidget(heading)

        caption = muted(
            t("welcome.intro"),
            size=10,
        )
        caption.setMaximumWidth(660)
        caption.setMinimumHeight(72)
        left.addWidget(caption)

        buttons = QHBoxLayout()
        buttons.setSpacing(9)
        self.create_button = QPushButton(t("welcome.create_ai"))
        self.create_button.setObjectName("primary")
        self.create_button.setMinimumHeight(42)
        self.create_button.setMinimumWidth(150)
        self.create_button.setFont(theme.ui_font(10, 700))
        self.create_button.setToolTip(t("welcome.create_ai_tip"))
        self.create_button.clicked.connect(self.new_project)
        buttons.addWidget(self.create_button)

        self.open_button = QPushButton(t("welcome.open_project"))
        self.open_button.setMinimumHeight(42)
        self.open_button.setMinimumWidth(150)
        self.open_button.setFont(theme.ui_font(10, 700))
        self.open_button.setToolTip(t("welcome.open_project_tip"))
        self.open_button.clicked.connect(self.open_project)
        buttons.addWidget(self.open_button)

        self.blank_button = QPushButton(t("welcome.blank_project"))
        self.blank_button.setObjectName("ghost")
        self.blank_button.setMinimumHeight(42)
        self.blank_button.setMinimumWidth(150)
        self.blank_button.setFont(theme.ui_font(10, 700))
        self.blank_button.setToolTip(t("welcome.blank_project_tip"))
        self.blank_button.clicked.connect(self.new_blank_project)
        buttons.addWidget(self.blank_button)
        buttons.addStretch(1)
        left.addLayout(buttons)

        links = QHBoxLayout()
        links.setSpacing(9)
        external = QPushButton(t("welcome.external_guide"))
        external.setObjectName("ghost")
        external.clicked.connect(self._open_external_guide)
        links.addWidget(external)
        links.addStretch(1)
        left.addLayout(links)
        left.addStretch(1)
        layout.addLayout(left, 3)

        steps = QVBoxLayout()
        steps.setSpacing(9)
        steps.addWidget(self._eyebrow(t("welcome.what_next")))
        for number, title, text in (
            ("1", t("welcome.step1_title"), t("welcome.step1_text")),
            ("2", t("welcome.step2_title"), t("welcome.step2_text")),
            ("3", t("welcome.step3_title"), t("welcome.step3_text")),
        ):
            row = QHBoxLayout()
            row.setSpacing(11)
            marker = QLabel(number)
            marker.setObjectName("dim")
            marker.setFont(theme.ui_font(9, 700))
            marker.setFixedWidth(14)
            marker.setAlignment(Qt.AlignmentFlag.AlignTop)
            row.addWidget(marker)
            texts = QVBoxLayout()
            texts.setSpacing(1)
            label = QLabel(title)
            label.setFont(theme.ui_font(10, 600))
            texts.addWidget(label)
            texts.addWidget(muted(text, size=9))
            row.addLayout(texts, 1)
            steps.addLayout(row)
        steps.addStretch(1)
        layout.addLayout(steps, 2)
        return section

    def _eyebrow(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("dim")
        label.setFont(theme.ui_font(8, 700))
        return label

    def _build_body(self) -> QHBoxLayout:
        body = QHBoxLayout()
        body.setSpacing(16)

        recent_card = Card()
        recent_card.setMinimumHeight(230)
        header = QHBoxLayout()
        header.addWidget(title_label(t("welcome.recent_projects"), 12))
        header.addStretch(1)
        self.recent_count = Badge("0", "default")
        header.addWidget(self.recent_count)
        recent_card.layout().addLayout(header)
        recent_card.layout().addWidget(
            muted(t("welcome.recent_hint"), size=9)
        )
        self.recent_box = QVBoxLayout()
        self.recent_box.setSpacing(9)
        recent_card.layout().addLayout(self.recent_box)
        recent_card.layout().addStretch(1)
        body.addWidget(recent_card, 3)

        right = QVBoxLayout()
        right.setSpacing(16)
        ai_card = Card(soft=True)
        ai_header = QHBoxLayout()
        ai_header.addWidget(title_label(t("welcome.ai_helper"), 11))
        ai_header.addStretch(1)
        self.ai_status = Badge(t("welcome.ai_checking"), "default")
        ai_header.addWidget(self.ai_status)
        ai_card.layout().addLayout(ai_header)
        self.ai_text = muted(
            t("welcome.ai_hint"),
            size=9,
        )
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
        hint = QLabel(t("welcome.footer_splash"))
        hint.setObjectName("dim")
        hint.setFont(theme.ui_font(9))
        row.addWidget(hint)
        row.addStretch(1)
        folder = QLabel(t("welcome.projects_folder", path=self.settings.projects_dir()))
        folder.setObjectName("dim")
        folder.setFont(theme.ui_font(9))
        folder.setToolTip(t("welcome.projects_folder_tip"))
        row.addWidget(folder)
        return row

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
            empty.setStyleSheet("padding: 34px 12px;")
            self.recent_box.addWidget(empty)
        else:
            grid = QGridLayout()
            grid.setSpacing(9)
            for index, entry in enumerate(recents[:4]):
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

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            elif item.layout() is not None:
                self._clear_layout(item.layout())
