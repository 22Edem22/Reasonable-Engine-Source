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

from reasonable.core.paths import DOCS_DIR
from reasonable.core.settings import Settings
from reasonable.version import VERSION, VERSION_NAME

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
        sub = QLabel(f"{VERSION_NAME} · v{VERSION}")
        sub.setObjectName("dim")
        sub.setFont(theme.ui_font(9))
        names.addWidget(sub)
        row.addLayout(names)
        row.addStretch(1)

        settings_button = QPushButton("Настройки")
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
        eyebrow = QLabel("РЕДАКТОР ИГР И ПРИЛОЖЕНИЙ")
        eyebrow.setObjectName("dim")
        eyebrow.setFont(theme.ui_font(8, 700))
        left.addWidget(eyebrow)

        heading = QLabel("Создайте игру\nиз одной идеи")
        heading.setObjectName("title")
        heading.setFont(theme.display_font(25, 700))
        heading.setWordWrap(True)
        left.addWidget(heading)

        caption = muted(
            "Три пути — без анкеты и без обязательной настройки ИИ. Создайте проект "
            "с агентом, откройте готовый или начните с пустого файла вручную. "
            "Провайдера и модель спросим только тогда, когда они действительно понадобятся.",
            size=10,
        )
        caption.setMaximumWidth(660)
        caption.setMinimumHeight(72)
        left.addWidget(caption)

        buttons = QHBoxLayout()
        buttons.setSpacing(9)
        self.create_button = QPushButton("Создать с ИИ")
        self.create_button.setObjectName("primary")
        self.create_button.setMinimumHeight(42)
        self.create_button.setMinimumWidth(150)
        self.create_button.setFont(theme.ui_font(10, 700))
        self.create_button.setToolTip("Опишите идею — агент соберёт игру или приложение.")
        self.create_button.clicked.connect(self.new_project)
        buttons.addWidget(self.create_button)

        self.open_button = QPushButton("Открыть проект")
        self.open_button.setMinimumHeight(42)
        self.open_button.setMinimumWidth(150)
        self.open_button.setFont(theme.ui_font(10, 700))
        self.open_button.setToolTip("Выбрать существующую папку проекта.")
        self.open_button.clicked.connect(self.open_project)
        buttons.addWidget(self.open_button)

        self.blank_button = QPushButton("Пустой проект")
        self.blank_button.setObjectName("ghost")
        self.blank_button.setMinimumHeight(42)
        self.blank_button.setMinimumWidth(150)
        self.blank_button.setFont(theme.ui_font(10, 700))
        self.blank_button.setToolTip("Минимальный main.py и сразу редактор кода.")
        self.blank_button.clicked.connect(self.new_blank_project)
        buttons.addWidget(self.blank_button)
        buttons.addStretch(1)
        left.addLayout(buttons)

        links = QHBoxLayout()
        links.setSpacing(9)
        external = QPushButton("Как подключить внешнего агента")
        external.setObjectName("ghost")
        external.clicked.connect(self._open_external_guide)
        links.addWidget(external)
        links.addStretch(1)
        left.addLayout(links)
        left.addStretch(1)
        layout.addLayout(left, 3)

        steps = QVBoxLayout()
        steps.setSpacing(9)
        steps.addWidget(self._eyebrow("ЧТО БУДЕТ ДАЛЬШЕ"))
        for number, title, text in (
            ("1", "Сразу к результату", "Проект создаётся без выбора провайдера и длинной анкеты."),
            ("2", "Прозрачный агент", "Видно, какие файлы он меняет, что получилось и что сломалось."),
            ("3", "История и откат", "Перед каждым запуском агента сохраняется рабочая версия."),
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
        header.addWidget(title_label("Недавние проекты", 12))
        header.addStretch(1)
        self.recent_count = Badge("0", "default")
        header.addWidget(self.recent_count)
        recent_card.layout().addLayout(header)
        recent_card.layout().addWidget(
            muted("Продолжите с того места, где остановились.", size=9)
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
        ai_header.addWidget(title_label("ИИ-помощник", 11))
        ai_header.addStretch(1)
        self.ai_status = Badge("Проверка", "default")
        ai_header.addWidget(self.ai_status)
        ai_card.layout().addLayout(ai_header)
        self.ai_text = muted(
            "Провайдер и модель понадобятся только для встроенного агента. "
            "Можно создать проект и сначала посмотреть его.",
            size=9,
        )
        self.ai_text.setWordWrap(True)
        ai_card.layout().addWidget(self.ai_text)
        self.ai_button = QPushButton("Настроить ИИ")
        self.ai_button.setObjectName("teal")
        self.ai_button.clicked.connect(self.configure_ai)
        ai_card.layout().addWidget(self.ai_button)
        right.addWidget(ai_card)
        right.addStretch(1)
        body.addLayout(right, 2)
        return body

    def _build_footer(self) -> QHBoxLayout:
        row = QHBoxLayout()
        hint = QLabel("Заставка Reasonable Engine всегда играет перед запуском проекта.")
        hint.setObjectName("dim")
        hint.setFont(theme.ui_font(9))
        row.addWidget(hint)
        row.addStretch(1)
        folder = QLabel(f"Проекты: {self.settings.projects_dir()}")
        folder.setObjectName("dim")
        folder.setFont(theme.ui_font(9))
        folder.setToolTip("Папка по умолчанию для новых проектов. Меняется в настройках.")
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
            "Внешний агент",
            "Выберите «Внешний агент» при создании проекта. Редактор создаст "
            "AGENT_GUIDE.md, skills/, re.bat и покажет прогресс агента в разделе «ИИ-агент».",
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
            empty = QLabel("Пока пусто. Создайте первый проект — это займёт минуту.")
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
                    entry.get("name", "Проект"),
                    entry.get("goal", ""),
                    entry.get("type", "game"),
                    entry.get("path", ""),
                )
                card.clicked.connect(lambda path=entry.get("path", ""): self.open_recent.emit(path))
                card.delete_requested.connect(
                    lambda path=entry.get("path", ""), name=entry.get("name", "Проект"): self.delete_project.emit(path)
                )
                grid.addWidget(card, index // 2, index % 2)
            self.recent_box.addLayout(grid)

        config = self.settings.get_provider_config()
        name = config.get("name") or config.get("id") or "Не выбран"
        model = config.get("model") or "модель не указана"
        requires_key = config.get("requires_key") and not config.get("api_key")
        if requires_key:
            self.ai_status.setText("Нужен ключ")
            self.ai_status.set_tone("gold")
            self.ai_text.setText(
                f"{name} · {model}\n"
                "Встроенный агент попросит ключ, когда вы впервые попросите его изменить проект. "
                "Создание проекта и ручная работа доступны без него."
            )
            self.ai_button.setText("Добавить ключ")
        else:
            self.ai_status.setText("Готов")
            self.ai_status.set_tone("default")
            self.ai_text.setText(
                f"{name} · {model}\n"
                f"{'Ключ сохранён' if config.get('api_key') else 'Работает без ключа'}. "
                "Настройка не обязательна: её можно открыть из проекта, когда понадобится."
            )
            self.ai_button.setText("Проверить настройки")

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            elif item.layout() is not None:
                self._clear_layout(item.layout())
