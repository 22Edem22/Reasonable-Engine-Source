"""AI and editor settings."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from reasonable.ai.providers import (
    FREE_API_SITES,
    IMAGE_PROVIDERS,
    PROVIDERS,
    ProviderPreset,
    get_image_provider,
    get_provider,
)
from reasonable.core import i18n
from reasonable.core.i18n import t
from reasonable.core.settings import Settings

from . import theme
from .widgets import Badge, Card, Separator, muted, title_label
from .workers import ProviderTestWorker, Worker

SITE_PROVIDER_MAP = {
    "OpenRouter": "openrouter",
    "Google AI Studio": "gemini",
    "Groq Cloud": "groq",
    "Cerebras": "cerebras",
    "GitHub Models": "github",
    "Mistral": "mistral",
    "Hugging Face": "huggingface",
    "Cloudflare Workers AI": "custom",
}


def _list_name(name: str) -> str:
    """Short, readable provider name for the narrow list column."""
    short = name.split(" (", 1)[0]
    short = short.replace(" La Plateforme", "").replace(" API", "")
    if short.startswith(("Свой ", "Custom ")) or short in ("Свой сервер", "Custom server"):
        short = t("settings.custom_server")
    return short


class SettingsDialog(QDialog):
    settings_saved = Signal()

    def __init__(
        self,
        settings: Settings,
        parent: QWidget | None = None,
        *,
        advanced: bool | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self._current_provider: str = settings.active_provider
        self._test_worker: ProviderTestWorker | None = None
        self._models_worker: Worker | None = None
        self._loading = False
        self._initial_language = self.settings.language()
        self.language_combos: list[QComboBox] = []
        if advanced is None:
            self._advanced = bool((settings.data.get("ui") or {}).get("advanced_settings", False))
        else:
            self._advanced = bool(advanced)

        self.setWindowTitle(t("settings.title"))
        self.setMinimumSize(1080, 680)
        self.resize(1180, 760)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(14)
        layout.addLayout(self._build_header())

        body = QHBoxLayout()
        body.setSpacing(16)
        self.sidebar = self._build_sidebar()
        body.addWidget(self.sidebar)
        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_providers_page())
        self.pages.addWidget(self._build_free_page())
        self.pages.addWidget(self._build_images_page())
        self.pages.addWidget(self._build_agent_page())
        self.simple_page = self._build_simple_page()
        self.mode_stack = QStackedWidget()
        self.mode_stack.addWidget(self.simple_page)
        self.mode_stack.addWidget(self.pages)
        body.addWidget(self.mode_stack, 1)
        layout.addLayout(body, 1)

        footer = QHBoxLayout()
        self.test_result = QLabel("")
        self.test_result.setObjectName("muted")
        footer.addWidget(self.test_result)
        footer.addStretch(1)
        cancel = QPushButton(t("common.cancel"))
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        save = QPushButton(t("settings.save"))
        save.setObjectName("primary")
        save.setMinimumWidth(180)
        save.clicked.connect(self._save)
        footer.addWidget(save)
        layout.addLayout(footer)

        self._load_provider(self._current_provider)
        self._load_image()
        self._load_agent()
        self._load_simple()
        self._apply_advanced(self._advanced)

    # ------------------------------------------------------------------
    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(theme.logo_pixmap(34))
        row.addWidget(logo)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        title = QLabel(t("settings.heading"))
        title.setObjectName("title")
        title.setFont(theme.display_font(14, 700))
        titles.addWidget(title)
        titles.addWidget(muted(t("settings.subtitle"), wrap=False, size=9))
        row.addLayout(titles)
        row.addStretch(1)
        self.advanced_toggle = QCheckBox(t("settings.advanced_toggle"))
        self.advanced_toggle.setToolTip(t("settings.advanced_tooltip"))
        self.advanced_toggle.setChecked(self._advanced)
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        row.addWidget(self.advanced_toggle)
        row.addWidget(Badge(t("settings.badge_local"), "default"))
        return row

    def _build_sidebar(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("cardSoft")
        frame.setFixedWidth(236)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)
        self.nav_buttons: list[QPushButton] = []
        for index, label in enumerate(
            (
                t("settings.nav_providers"),
                t("settings.nav_free"),
                t("settings.nav_images"),
                t("settings.nav_agent"),
            )
        ):
            button = QPushButton(label)
            button.setObjectName("nav")
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda checked=False, i=index: self._show_page(i))
            layout.addWidget(button)
            self.nav_buttons.append(button)
        self.nav_buttons[0].setChecked(True)
        layout.addStretch(1)

        info = Card(soft=True, padding=12)
        info.setFrameShape(QFrame.Shape.NoFrame)
        info.layout().addWidget(title_label(t("settings.no_key_title"), 10))
        info.layout().addWidget(
            muted(
                t("settings.no_key_text"),
                size=9,
            )
        )
        layout.addWidget(info)
        return frame

    def _show_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        for position, button in enumerate(self.nav_buttons):
            button.setChecked(position == index)

    # ------------------------------------------------------------------
    def _build_simple_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("root")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 6, 4)
        layout.setSpacing(12)
        scroll.setWidget(body)

        layout.addWidget(title_label(t("settings.simple_title"), 16))
        layout.addWidget(
            muted(
                t("settings.simple_intro"),
                size=9,
            )
        )

        ai_card = Card()
        ai_header = QHBoxLayout()
        ai_header.addWidget(title_label(t("welcome.ai_helper"), 11))
        ai_header.addStretch(1)
        self.simple_ai_status = Badge(t("welcome.ai_checking"), "default")
        ai_header.addWidget(self.simple_ai_status)
        ai_card.layout().addLayout(ai_header)
        self.simple_ai_text = muted("", size=9)
        self.simple_ai_text.setWordWrap(True)
        ai_card.layout().addWidget(self.simple_ai_text)
        ai_buttons = QHBoxLayout()
        ai_buttons.addStretch(1)
        ai_setup = QPushButton(t("settings.setup_provider"))
        ai_setup.setObjectName("teal")
        ai_setup.clicked.connect(lambda: self.advanced_toggle.setChecked(True))
        ai_buttons.addWidget(ai_setup)
        ai_card.layout().addLayout(ai_buttons)
        layout.addWidget(ai_card)

        layout.addWidget(self._language_card())

        projects = Card(soft=True)
        projects.layout().addWidget(title_label(t("settings.projects_title"), 11))
        projects.layout().addWidget(
            muted(t("settings.projects_hint"), size=9)
        )
        projects_row = QHBoxLayout()
        self.simple_projects_edit = QLineEdit()
        self.simple_projects_edit.setPlaceholderText(t("settings.projects_placeholder"))
        projects_row.addWidget(self.simple_projects_edit, 1)
        browse = QPushButton(t("common.browse"))
        browse.clicked.connect(self._browse_simple_projects_dir)
        projects_row.addWidget(browse)
        reset = QPushButton(t("settings.reset_default"))
        reset.setObjectName("ghost")
        reset.clicked.connect(lambda: self.simple_projects_edit.setText(""))
        projects_row.addWidget(reset)
        projects.layout().addLayout(projects_row)
        layout.addWidget(projects)

        preview = Card(soft=True)
        preview.layout().addWidget(title_label(t("settings.preview_title"), 11))
        preview.layout().addWidget(
            muted(
                t("settings.preview_hint"),
                size=9,
            )
        )
        layout.addWidget(preview)
        layout.addStretch(1)
        return scroll

    def _language_card(self) -> Card:
        """Card with the interface-language switcher (shown on both pages)."""
        card = Card(soft=True)
        card.layout().addWidget(title_label(t("settings.language_title"), 11))
        card.layout().addWidget(muted(t("settings.language_hint"), size=9))
        row = QHBoxLayout()
        combo = QComboBox()
        for code, label in (("ru", "Русский"), ("en", "English")):
            combo.addItem(label, code)
        index = combo.findData(self.settings.language())
        combo.setCurrentIndex(max(0, index))
        combo.currentIndexChanged.connect(lambda _index, box=combo: self._language_changed(box))
        self.language_combos.append(combo)
        row.addWidget(combo, 1)
        card.layout().addLayout(row)
        return card

    def _language_changed(self, box: QComboBox) -> None:
        code = box.currentData()
        for other in self.language_combos:
            if other is not box and other.currentData() != code:
                other.blockSignals(True)
                other.setCurrentIndex(max(0, other.findData(code)))
                other.blockSignals(False)
        self.settings.data.setdefault("ui", {})["language"] = code
        try:
            self.settings.save()
        except Exception:
            pass
        i18n.invalidate_cache()

    def _load_simple(self) -> None:
        self.simple_projects_edit.setText(str(self.settings.data.get("projects_dir") or ""))
        config = self.settings.get_provider_config()
        name = config.get("name") or config.get("id") or t("welcome.ai_not_selected")
        model = config.get("model") or t("welcome.ai_model_unspecified")
        if config.get("requires_key") and not config.get("api_key"):
            self.simple_ai_status.setText(t("welcome.ai_need_key"))
            self.simple_ai_status.set_tone("gold")
            self.simple_ai_text.setText(
                t(
                    "settings.simple_need_key",
                    name=name,
                    model=model,
                )
            )
        else:
            self.simple_ai_status.setText(t("welcome.ai_ready"))
            self.simple_ai_status.set_tone("default")
            key_state = t("welcome.ai_key_saved") if config.get("api_key") else t("welcome.ai_no_key_needed")
            self.simple_ai_text.setText(t("settings.simple_ready_line", name=name, model=model, key_state=key_state))

    def _toggle_advanced(self, checked: bool) -> None:
        self._advanced = bool(checked)
        self.settings.data.setdefault("ui", {})["advanced_settings"] = self._advanced
        try:
            self.settings.save()
        except Exception:
            pass
        self._apply_advanced(self._advanced)

    def _apply_advanced(self, checked: bool) -> None:
        self.sidebar.setVisible(checked)
        self.mode_stack.setCurrentIndex(1 if checked else 0)
        if self.advanced_toggle.isChecked() != checked:
            self.advanced_toggle.setChecked(checked)
        if checked:
            self.nav_buttons[0].setChecked(True)
            self.pages.setCurrentIndex(0)

    def _browse_simple_projects_dir(self) -> None:
        from reasonable.core.paths import ensure_projects_dir

        start = self.simple_projects_edit.text().strip() or str(ensure_projects_dir())
        folder = QFileDialog.getExistingDirectory(self, t("settings.folder_dialog"), start)
        if folder:
            self.simple_projects_edit.setText(folder)

    # ------------------------------------------------------------------
    def _build_providers_page(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        left = QFrame()
        left.setObjectName("cardSoft")
        left.setFixedWidth(238)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(10, 12, 10, 10)
        left_layout.setSpacing(6)
        left_layout.addWidget(title_label(t("settings.model_for_agent"), 11))
        left_layout.addWidget(muted(t("settings.pick_provider"), size=9))
        self.provider_list = QListWidget()
        self.provider_list.setSpacing(2)
        self.provider_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.provider_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._fill_provider_list()
        self.provider_list.currentItemChanged.connect(self._provider_selected)
        left_layout.addWidget(self.provider_list, 1)
        layout.addWidget(left)

        right = QScrollArea()
        right.setWidgetResizable(True)
        right.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("root")
        self.provider_detail = QVBoxLayout(body)
        self.provider_detail.setContentsMargins(0, 0, 6, 4)
        self.provider_detail.setSpacing(12)
        right.setWidget(body)
        layout.addWidget(right, 1)

        self.provider_card = Card()
        top = QHBoxLayout()
        self.provider_name = QLabel("—")
        self.provider_name.setObjectName("title")
        self.provider_name.setFont(theme.display_font(16, 700))
        top.addWidget(self.provider_name)
        top.addStretch(1)
        self.provider_key_badge = Badge("", "default")
        top.addWidget(self.provider_key_badge)
        self.provider_active_badge = Badge(t("settings.active_badge"), "accent")
        top.addWidget(self.provider_active_badge)
        self.provider_card.layout().addLayout(top)
        self.provider_description = muted("", size=10)
        self.provider_description.setWordWrap(True)
        self.provider_card.layout().addWidget(self.provider_description)
        self.provider_note = QLabel("")
        self.provider_note.setObjectName("warning")
        self.provider_note.setWordWrap(True)
        self.provider_note.setFont(theme.ui_font(9))
        self.provider_card.layout().addWidget(self.provider_note)
        self.provider_card.layout().addWidget(Separator())

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.base_edit = QLineEdit()
        self.base_edit.setPlaceholderText("https://api.example.com/v1")
        form.addRow(self._label("Base URL"), self.base_edit)

        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.setMinimumWidth(240)
        form.addRow(self._label(t("settings.label_model")), self.model_combo)

        key_row = QHBoxLayout()
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText(t("settings.key_placeholder"))
        key_row.addWidget(self.key_edit, 1)
        self.show_key = QPushButton(t("settings.show"))
        self.show_key.setObjectName("ghost")
        self.show_key.setCheckable(True)
        self.show_key.toggled.connect(self._toggle_key)
        key_row.addWidget(self.show_key)
        self.get_key = QPushButton(t("settings.get_key"))
        self.get_key.setObjectName("teal")
        self.get_key.clicked.connect(self._open_key_url)
        key_row.addWidget(self.get_key)
        form.addRow(self._label(t("settings.label_api_key")), key_row)
        self.provider_card.layout().addLayout(form)

        self.provider_links = QLabel("")
        self.provider_links.setOpenExternalLinks(True)
        self.provider_links.setFont(theme.ui_font(9))
        self.provider_card.layout().addWidget(self.provider_links)

        test_row = QHBoxLayout()
        self.models_button = QPushButton(t("settings.load_models"))
        self.models_button.clicked.connect(self._load_models)
        test_row.addWidget(self.models_button)
        self.test_button = QPushButton(t("settings.test_connection"))
        self.test_button.clicked.connect(self._test_provider)
        test_row.addWidget(self.test_button)
        self.test_status = QLabel("")
        self.test_status.setObjectName("muted")
        self.test_status.setWordWrap(True)
        test_row.addWidget(self.test_status, 1)
        self.provider_card.layout().addLayout(test_row)
        self.provider_detail.addWidget(self.provider_card)

        hint = Card(soft=True)
        hint.layout().addWidget(title_label(t("settings.how_it_works"), 11))
        hint.layout().addWidget(
            muted(
                t("settings.how_it_works_text"),
                size=9,
            )
        )
        self.provider_detail.addWidget(hint)
        self.provider_detail.addStretch(1)
        return page

    def _fill_provider_list(self) -> None:
        self.provider_list.clear()
        groups: dict[str, list[ProviderPreset]] = {}
        for provider in PROVIDERS:
            groups.setdefault(provider.group, []).append(provider)
        for group, items in groups.items():
            header = QListWidgetItem(group.upper())
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            font = QFont(theme.ui_font(8, 700))
            header.setFont(font)
            header.setForeground(QBrush(QColor("#6F7680")))
            self.provider_list.addItem(header)
            for provider in items:
                item = QListWidgetItem(_list_name(provider.name))
                item.setData(Qt.ItemDataRole.UserRole, provider.id)
                item.setToolTip(f"{provider.name}\n{provider.description}")
                self.provider_list.addItem(item)

    def _label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("muted")
        label.setFont(theme.ui_font(9, 700))
        return label

    # ------------------------------------------------------------------
    def _select_provider(self, provider_id: str) -> None:
        for index in range(self.provider_list.count()):
            item = self.provider_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == provider_id:
                self.provider_list.setCurrentItem(item)
                return

    def _store_current_provider(self) -> None:
        if self._loading or not self._current_provider:
            return
        preset = get_provider(self._current_provider)
        if preset.id == "custom" and not self.base_edit.text().strip():
            return
        self.settings.update_provider(
            preset.id,
            base_url=self.base_edit.text().strip(),
            model=self.model_combo.currentText().strip(),
            api_key=self.key_edit.text().strip(),
            kind=preset.kind,
        )

    def _provider_selected(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        if current is None:
            return
        provider_id = current.data(Qt.ItemDataRole.UserRole)
        if not provider_id:
            return
        if not self._loading and str(provider_id) == self._current_provider:
            return
        if previous is not None and previous.data(Qt.ItemDataRole.UserRole):
            self._store_current_provider()
        self._load_provider(str(provider_id))

    def _load_provider(self, provider_id: str) -> None:
        self._loading = True
        self._current_provider = provider_id
        preset = get_provider(provider_id)
        config = self.settings.get_provider_config(provider_id)

        self.provider_name.setText(preset.name)
        self.provider_active_badge.setVisible(self.settings.active_provider == preset.id)
        self.provider_description.setText(preset.description)
        self.provider_note.setText(preset.note)
        self.provider_note.setVisible(bool(preset.note))
        if preset.requires_key:
            self.provider_key_badge.setText(t("settings.key_required_badge"))
            self.provider_key_badge.set_tone("gold")
        else:
            self.provider_key_badge.setText(t("settings.no_key_badge"))
            self.provider_key_badge.set_tone("default")

        self.base_edit.setText(config.get("base_url", ""))
        self.model_combo.clear()
        hints = list(preset.models_hint) or [preset.default_model or "model"]
        self.model_combo.addItems(hints)
        model = config.get("model") or preset.default_model
        if model:
            self.model_combo.setCurrentText(model)
        self.key_edit.setText(config.get("api_key", ""))
        self.show_key.setChecked(False)
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.get_key.setVisible(bool(preset.key_url))
        self.test_status.setText("")
        self.test_result.setText("")

        links = []
        if preset.key_url:
            links.append(f'<a style="color:#D9917A" href="{preset.key_url}">{t("settings.get_api_key_link")}</a>')
        if preset.docs_url:
            links.append(f'<a style="color:#9AA1AB" href="{preset.docs_url}">{t("settings.docs_link")}</a>')
        self.provider_links.setText("  ·  ".join(links))
        self.provider_links.setVisible(bool(links))

        for index in range(self.provider_list.count()):
            item = self.provider_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == provider_id:
                self.provider_list.blockSignals(True)
                self.provider_list.setCurrentItem(item)
                self.provider_list.blockSignals(False)
                break
        self._loading = False

    def _toggle_key(self, visible: bool) -> None:
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password)
        self.show_key.setText(t("settings.hide") if visible else t("settings.show"))

    def _open_key_url(self) -> None:
        preset = get_provider(self._current_provider)
        if preset.key_url:
            QDesktopServices.openUrl(QUrl(preset.key_url))

    def _test_provider(self) -> None:
        preset = get_provider(self._current_provider)
        config = {
            "id": preset.id,
            "name": preset.name,
            "kind": preset.kind,
            "base_url": self.base_edit.text().strip(),
            "model": self.model_combo.currentText().strip(),
            "api_key": self.key_edit.text().strip(),
            "requires_key": preset.requires_key,
            "headers": dict(preset.headers),
        }
        if not config["base_url"]:
            self.test_status.setText(t("settings.specify_base_url"))
            return
        if preset.requires_key and not config["api_key"]:
            self.test_status.setText(t("settings.enter_api_key"))
            return
        self.test_button.setEnabled(False)
        self.test_status.setText(t("settings.testing"))
        self._test_worker = ProviderTestWorker(config)
        self._test_worker.done.connect(self._test_done)
        self._test_worker.failed.connect(self._test_failed)
        self._test_worker.start()

    def _test_done(self, ok: bool, message: str) -> None:
        self.test_button.setEnabled(True)
        self.test_status.setText((t("settings.success_prefix") if ok else "") + message[:300])
        self.test_result.setText(t("settings.connection_ok") if ok else message[:200])

    def _test_failed(self, message: str, _trace: str) -> None:
        self.test_button.setEnabled(True)
        self.test_status.setText(t("settings.error_prefix") + message[:400])
        self.test_result.setText(t("settings.connection_failed"))

    def _load_models(self) -> None:
        preset = get_provider(self._current_provider)
        config = {
            "id": preset.id,
            "name": preset.name,
            "kind": preset.kind,
            "base_url": self.base_edit.text().strip(),
            "model": self.model_combo.currentText().strip(),
            "api_key": self.key_edit.text().strip(),
            "requires_key": preset.requires_key,
            "headers": dict(preset.headers),
        }
        if not config["base_url"]:
            self.test_status.setText(t("settings.specify_base_url"))
            return
        if preset.requires_key and not config["api_key"]:
            self.test_status.setText(t("settings.enter_key_models"))
            return
        if self._models_worker is not None and self._models_worker.isRunning():
            return
        self.models_button.setEnabled(False)
        self.test_status.setText(t("settings.loading_models"))
        from reasonable.ai.client import fetch_models

        provider_id = self._current_provider
        self._models_worker = Worker(fetch_models, config)
        self._models_worker.done.connect(
            lambda models, pid=provider_id: self._models_done(models, pid)
        )
        self._models_worker.failed.connect(
            lambda message, _trace, pid=provider_id: self._models_failed(message, pid)
        )
        self._models_worker.start()

    def _models_done(self, models, provider_id: str) -> None:
        self.models_button.setEnabled(True)
        models = list(models or [])
        if provider_id != self._current_provider:
            return
        if not models:
            self.test_status.setText(t("settings.empty_model_list"))
            return
        current = self.model_combo.currentText().strip()
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItems(models[:500])
        self.model_combo.setCurrentText(current or models[0])
        self.model_combo.blockSignals(False)
        suffix = t("settings.shown_first_500") if len(models) > 500 else ""
        self.test_status.setText(t("settings.models_loaded", count=len(models)) + suffix)

    def _models_failed(self, message: str, provider_id: str) -> None:
        self.models_button.setEnabled(True)
        if provider_id != self._current_provider:
            return
        self.test_status.setText(
            t("settings.load_failed_prefix") + message[:300] + t("settings.load_failed_suffix")
        )

    # ------------------------------------------------------------------
    def _build_free_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("root")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 6, 4)
        layout.setSpacing(12)
        scroll.setWidget(body)

        layout.addWidget(title_label(t("settings.free_title"), 16))
        layout.addWidget(
            muted(
                t("settings.free_intro"),
                size=9,
            )
        )

        no_key = Card(soft=True)
        no_key.layout().addWidget(title_label(t("welcome.ai_no_key_needed"), 11))
        no_key.layout().addWidget(
            muted(
                t("settings.local_no_key_text"),
                size=9,
            )
        )
        layout.addWidget(no_key)

        for site in FREE_API_SITES:
            card = Card()
            top = QHBoxLayout()
            name = QLabel(site.name)
            name.setFont(theme.display_font(11, 700))
            top.addWidget(name)
            top.addStretch(1)
            top.addWidget(Badge(site.badge, "default"))
            card.layout().addLayout(top)
            models = QLabel(site.models)
            models.setObjectName("muted")
            models.setFont(theme.ui_font(9, 600))
            card.layout().addWidget(models)
            card.layout().addWidget(muted(site.note, size=9))
            buttons = QHBoxLayout()
            buttons.addStretch(1)
            provider_id = SITE_PROVIDER_MAP.get(site.name)
            if provider_id:
                use = QPushButton(t("settings.setup_provider_btn"))
                use.setObjectName("teal")
                use.clicked.connect(lambda checked=False, pid=provider_id: self._use_site_provider(pid))
                buttons.addWidget(use)
            open_button = QPushButton(t("settings.open_site"))
            open_button.clicked.connect(lambda checked=False, url=site.url: QDesktopServices.openUrl(QUrl(url)))
            buttons.addWidget(open_button)
            card.layout().addLayout(buttons)
            layout.addWidget(card)
        layout.addStretch(1)
        return scroll

    def _use_site_provider(self, provider_id: str) -> None:
        self._show_page(0)
        for index, button in enumerate(self.nav_buttons):
            button.setChecked(index == 0)
        self._select_provider(provider_id)

    # ------------------------------------------------------------------
    def _build_images_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("root")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 6, 4)
        layout.setSpacing(12)
        scroll.setWidget(body)

        layout.addWidget(title_label(t("settings.nav_images"), 16))
        layout.addWidget(
            muted(
                t("settings.images_intro"),
                size=9,
            )
        )

        card = Card()
        form = QFormLayout()
        form.setSpacing(10)
        self.image_provider = QComboBox()
        for provider in IMAGE_PROVIDERS:
            self.image_provider.addItem(provider.name, provider.id)
        self.image_provider.currentIndexChanged.connect(self._image_provider_changed)
        form.addRow(self._label(t("settings.label_provider")), self.image_provider)

        self.image_description = muted("", size=9)
        form.addRow(self._label(t("settings.label_description")), self.image_description)

        self.image_base = QLineEdit()
        form.addRow(self._label(t("settings.label_base_url")), self.image_base)

        self.image_model = QComboBox()
        self.image_model.setEditable(True)
        form.addRow(self._label(t("settings.label_model")), self.image_model)

        self.image_key = QLineEdit()
        self.image_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.image_key.setPlaceholderText(t("settings.key_placeholder"))
        form.addRow(self._label(t("settings.label_api_key")), self.image_key)

        self.image_fallback = QCheckBox(t("settings.fallback_checkbox"))
        form.addRow("", self.image_fallback)
        card.layout().addLayout(form)
        layout.addWidget(card)

        note = Card(soft=True)
        note.layout().addWidget(title_label(t("settings.tip_title"), 10))
        note.layout().addWidget(
            muted(
                t("settings.tip_text"),
                size=9,
            )
        )
        layout.addWidget(note)
        layout.addStretch(1)
        return scroll

    def _load_image(self) -> None:
        config = self.settings.image_config()
        index = self.image_provider.findData(config.get("provider", "procedural"))
        self.image_provider.setCurrentIndex(max(0, index))
        self._image_provider_changed()
        self.image_base.setText(config.get("base_url", ""))
        self.image_model.setCurrentText(config.get("model", ""))
        self.image_key.setText(str(config.get("api_key") or ""))
        self.image_fallback.setChecked(bool(config.get("fallback_to_procedural", True)))

    def _image_provider_changed(self) -> None:
        provider = get_image_provider(self.image_provider.currentData() or "procedural")
        self.image_description.setText(provider.description)
        self.image_base.setText(provider.base_url)
        self.image_model.clear()
        self.image_model.addItem(provider.default_model)
        self.image_model.setCurrentText(provider.default_model)
        self.image_key.setEnabled(provider.requires_key)

    # ------------------------------------------------------------------
    def _build_agent_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("root")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 6, 4)
        layout.setSpacing(12)
        scroll.setWidget(body)

        layout.addWidget(title_label(t("settings.nav_agent"), 16))
        layout.addWidget(self._language_card())
        card = Card()
        form = QFormLayout()
        form.setSpacing(12)
        self.temperature = QDoubleSpinBox()
        self.temperature.setRange(0.0, 1.6)
        self.temperature.setSingleStep(0.05)
        self.temperature.setDecimals(2)
        form.addRow(self._label(t("settings.label_temperature")), self.temperature)
        self.context_messages = QSpinBox()
        self.context_messages.setRange(12, 120)
        form.addRow(self._label(t("settings.label_context")), self.context_messages)
        card.layout().addLayout(form)
        layout.addWidget(card)

        projects = Card(soft=True)
        projects.layout().addWidget(title_label(t("settings.projects_title"), 11))
        projects.layout().addWidget(
            muted(
                t("settings.projects_hint2"),
                size=9,
            )
        )
        projects_row = QHBoxLayout()
        self.projects_dir_edit = QLineEdit()
        self.projects_dir_edit.setPlaceholderText(t("settings.projects_placeholder"))
        projects_row.addWidget(self.projects_dir_edit, 1)
        browse = QPushButton(t("common.browse"))
        browse.clicked.connect(self._browse_projects_dir)
        projects_row.addWidget(browse)
        reset = QPushButton(t("settings.reset_default"))
        reset.setObjectName("ghost")
        reset.clicked.connect(lambda: self.projects_dir_edit.setText(""))
        projects_row.addWidget(reset)
        projects.layout().addLayout(projects_row)
        layout.addWidget(projects)

        preview = Card(soft=True)
        preview.layout().addWidget(title_label(t("settings.preview_splash_title"), 11))
        preview.layout().addWidget(
            muted(
                t("settings.preview_hint"),
                size=9,
            )
        )
        layout.addWidget(preview)

        external = Card(soft=True)
        external.layout().addWidget(title_label(t("settings.external_title"), 11))
        external.layout().addWidget(
            muted(
                t("settings.external_text"),
                size=9,
            )
        )
        layout.addWidget(external)
        layout.addStretch(1)
        return scroll

    def _browse_projects_dir(self) -> None:
        from reasonable.core.paths import ensure_projects_dir

        start = self.projects_dir_edit.text().strip() or str(ensure_projects_dir())
        folder = QFileDialog.getExistingDirectory(self, t("settings.folder_dialog"), start)
        if folder:
            self.projects_dir_edit.setText(folder)

    def _load_agent(self) -> None:
        agent = self.settings.data.get("agent", {})
        self.temperature.setValue(float(agent.get("temperature", 0.65)))
        self.context_messages.setValue(int(agent.get("context_messages", 36)))
        self.projects_dir_edit.setText(str(self.settings.data.get("projects_dir") or ""))

    # ------------------------------------------------------------------
    def _save(self) -> None:
        language_changed = False
        if self.language_combos:
            chosen = self.language_combos[0].currentData()
            language_changed = chosen != self._initial_language
            self.settings.data.setdefault("ui", {})["language"] = chosen
        self._store_current_provider()
        self.settings.active_provider = self._current_provider
        self.settings.data.setdefault("agent", {}).update(
            {
                "temperature": float(self.temperature.value()),
                "context_messages": int(self.context_messages.value()),
            }
        )
        self.settings.data["projects_dir"] = (
            self.projects_dir_edit if self._advanced else self.simple_projects_edit
        ).text().strip()
        self.settings.data.setdefault("ui", {})["advanced_settings"] = self._advanced
        preset = get_image_provider(self.image_provider.currentData() or "procedural")
        self.settings.update_image(
            provider=preset.id,
            base_url=self.image_base.text().strip() or preset.base_url,
            model=self.image_model.currentText().strip() or preset.default_model,
            api_key=self.image_key.text().strip(),
            fallback_to_procedural=bool(self.image_fallback.isChecked()),
        )
        self.settings.save()
        i18n.invalidate_cache()
        self.settings_saved.emit()
        if language_changed:
            # Widgets built before the switch keep their old texts; new windows
            # and dialogs already open in the chosen language.
            QMessageBox.information(self, t("settings.language_title"), t("settings.restart_hint"))
        self.accept()

    def closeEvent(self, event) -> None:  # noqa: N802
        for worker in (self._test_worker, self._models_worker):
            if worker is not None and worker.isRunning():
                worker.terminate()
                worker.wait(2000)
        event.accept()
