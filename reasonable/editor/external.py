"""External-agent control room.

The editor never launches Claude Code or Cursor itself: both are separate apps.
Instead this panel prepares a complete agent pack and watches the shared
``progress/`` files, so the user sees the external agent's work live.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from reasonable.core.paths import human_time
from reasonable.core.progress import (
    activity_is_live,
    read_events,
    read_state,
    scan_recent_files,
)

from . import theme
from .widgets import Badge, Card, Separator, muted, title_label


AGENT_PROMPT = """Ты работаешь над проектом «{name}» в папке:
{root}

1. Прочитай AGENT_GUIDE.md, AGENTS.md и AGENT_TASKS.md.
2. Изучи project.json, main.py, assets/ и progress/state.json.
3. Составь план и обновляй его командами:
   re.bat plan "задача 1" "задача 2" ...
4. В начале задачи: re.bat task <id> in_progress
   В конце: re.bat task <id> done
5. Сообщай о прогрессе: re.bat progress <0-100> "что готово" --stage "этап"
   и re.bat event "короткое сообщение".
6. Проверяй запуск: re.bat validate и re.bat run --headless
7. В конце выполни re.bat done "краткий итог" — только после того, как файлы проекта
   действительно изменены, validate пройден и проект запускается.

Работай самостоятельно, меняй файлы проекта, генерируй ассеты при необходимости.
Установка библиотеки через pip — это не выполненная задача: после неё продолжай
писать код, проверять и доводить проект до рабочего состояния.
Не трогай папку _engine — это встроенная копия движка."""


class ExternalAgentPanel(QWidget):
    settings_requested = Signal()
    status_message = Signal(str)

    def __init__(self, project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self._events_signature = None
        self._tasks_signature = None
        self._state_signature = None
        self._files_signature = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(self._build_instructions(), 3)
        body.addWidget(self._build_live(), 2)
        layout.addLayout(body, 1)

        self.timer = QTimer(self)
        self.timer.setInterval(1600)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh(force=True)

    # ------------------------------------------------------------------
    def _build_header(self) -> QFrame:
        card = Card(padding=14)
        row = QHBoxLayout()
        row.setSpacing(12)
        icon = QLabel()
        icon.setFixedSize(40, 40)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setPixmap(theme.logo_pixmap(38))
        icon.setStyleSheet("background: #1B1F25; border: 1px solid #2B3038; border-radius: 8px;")
        row.addWidget(icon)
        titles = QVBoxLayout()
        titles.setSpacing(1)
        title = QLabel("ИИ-агент")
        title.setObjectName("title")
        title.setFont(theme.display_font(12, 700))
        titles.addWidget(title)
        titles.addWidget(
            muted("Внешний режим · Claude Code / Codex / Cursor / Cline — прогресс виден здесь", size=9)
        )
        row.addLayout(titles)
        row.addStretch(1)
        self.status_badge = Badge("ОЖИДАНИЕ", "default")
        row.addWidget(self.status_badge)
        self.activity_label = muted("", size=9)
        row.addWidget(self.activity_label)
        pack_button = QPushButton("Обновить пакет агента")
        pack_button.setObjectName("teal")
        pack_button.clicked.connect(self._regenerate_pack)
        row.addWidget(pack_button)
        folder_button = QPushButton("Открыть папку")
        folder_button.clicked.connect(self._open_folder)
        row.addWidget(folder_button)
        card.layout().addLayout(row)
        return card

    def _build_instructions(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = QWidget()
        host.setObjectName("root")
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 6, 4)
        layout.setSpacing(12)
        scroll.setWidget(host)

        card = Card()
        card.layout().addWidget(title_label("Как подключить агента", 13))
        steps = (
            ("1", "Откройте папку проекта", "В Claude Code, Codex CLI, Cursor, Cline или другом агенте выберите папку проекта."),
            ("2", "Дайте агенту инструкцию", "Скопируйте промпт ниже или попросите прочитать AGENT_GUIDE.md."),
            ("3", "Следите за прогрессом", "Агент отмечает задачи и события через re.bat — панель обновляется сама."),
        )
        for number, title, text in steps:
            row = QHBoxLayout()
            row.setSpacing(10)
            bubble = QLabel(number)
            bubble.setFixedSize(26, 26)
            bubble.setAlignment(Qt.AlignmentFlag.AlignCenter)
            bubble.setStyleSheet(
                "background: #1B1F25; color: #A8AFB9;"
                "border: 1px solid #2B3038; border-radius: 13px; font-weight: 600;"
            )
            row.addWidget(bubble, 0, Qt.AlignmentFlag.AlignTop)
            texts = QVBoxLayout()
            texts.setSpacing(1)
            heading = QLabel(title)
            heading.setFont(theme.ui_font(10, 700))
            texts.addWidget(heading)
            texts.addWidget(muted(text, size=9))
            row.addLayout(texts, 1)
            card.layout().addLayout(row)
        layout.addWidget(card)

        prompt_card = Card(soft=True)
        top = QHBoxLayout()
        top.addWidget(title_label("Промпт для внешнего агента", 11))
        top.addStretch(1)
        copy_prompt = QPushButton("Скопировать промпт")
        copy_prompt.setObjectName("primary")
        copy_prompt.clicked.connect(self._copy_prompt)
        top.addWidget(copy_prompt)
        prompt_card.layout().addLayout(top)
        prompt_card.layout().addWidget(
            muted(
                "Напишите задачу своими словами. Ниже показан полный текст, который "
                "получит агент: путь к проекту, обязательный рабочий цикл и ваша задача. "
                "Кнопка копирует именно его.",
                size=9,
            )
        )

        task_label = QLabel("Ваша задача")
        task_label.setFont(theme.ui_font(9, 700))
        prompt_card.layout().addWidget(task_label)
        self.first_task_edit = QTextEdit()
        self.first_task_edit.setObjectName("promptBig")
        self.first_task_edit.setMinimumHeight(92)
        self.first_task_edit.setMaximumHeight(140)
        self.first_task_edit.setPlaceholderText(
            "Например: собери меню, первый уровень и экран паузы, затем проверь запуск."
        )
        self.first_task_edit.textChanged.connect(self._update_prompt_preview)
        prompt_card.layout().addWidget(self.first_task_edit)

        preview_row = QHBoxLayout()
        preview_label = QLabel("Полный промпт")
        preview_label.setFont(theme.ui_font(9, 700))
        preview_row.addWidget(preview_label)
        preview_row.addStretch(1)
        copy_task = QPushButton("Скопировать только задачу")
        copy_task.setObjectName("ghost")
        copy_task.clicked.connect(self._copy_task_only)
        preview_row.addWidget(copy_task)
        prompt_card.layout().addLayout(preview_row)

        self.prompt_preview = QTextEdit()
        self.prompt_preview.setReadOnly(True)
        self.prompt_preview.setMinimumHeight(170)
        self.prompt_preview.setMaximumHeight(220)
        self.prompt_preview.setStyleSheet(
            "background: #12151A; color: #C9CED6; border: 1px solid #262B33;"
            "border-radius: 7px; padding: 8px;"
        )
        prompt_card.layout().addWidget(self.prompt_preview)
        self.prompt_hint = muted("", size=8)
        prompt_card.layout().addWidget(self.prompt_hint)
        self._update_prompt_preview()
        layout.addWidget(prompt_card)

        commands = Card(soft=True)
        commands.layout().addWidget(title_label("Команды прогресса", 11))
        for title, command in (
            ("Показать состояние", "re.bat status"),
            ("Новый план", 're.bat plan "Экран меню" "Уровни" "Проверка"'),
            ("Начать задачу", "re.bat task t1 in_progress"),
            ("Завершить задачу", "re.bat task t1 done"),
            ("Процент и этап", 're.bat progress 40 "Готов экран меню" --stage "UI"'),
            ("Событие", 're.bat event "Добавил анимацию кнопок"'),
            ("Завершить проект", 're.bat done "Проект готов"'),
        ):
            row = QHBoxLayout()
            row.setSpacing(8)
            label = QLabel(title)
            label.setObjectName("muted")
            label.setFont(theme.ui_font(9))
            label.setFixedWidth(130)
            row.addWidget(label)
            code = QLabel(command)
            code.setFont(theme.ui_font(9))
            code.setWordWrap(True)
            code.setMinimumWidth(0)
            code.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            code.setStyleSheet(
                "background: #12151A; color: #C9CED6; border: 1px solid #262B33;"
                "border-radius: 6px; padding: 5px 8px;"
            )
            row.addWidget(code, 1)
            copy = QPushButton("Копировать")
            copy.setObjectName("ghost")
            copy.setFixedHeight(26)
            copy.setToolTip("Скопировать команду")
            copy.clicked.connect(lambda checked=False, value=command: self._copy(value))
            row.addWidget(copy)
            commands.layout().addLayout(row)
        layout.addWidget(commands)

        files = Card(soft=True)
        files.layout().addWidget(title_label("Созданные инструкции", 11))
        for name, text in (
            ("AGENT_GUIDE.md", "Полное руководство: API движка, структура, правила и команды."),
            ("EXTERNAL_AGENT.md", "Короткая инструкция для подключения любого агента."),
            ("AGENTS.md / CLAUDE.md", "Автозагружаемые правила для Codex, Claude Code и других."),
            (".cursor/rules", "Правила для Cursor."),
            (".github/copilot-instructions.md", "Инструкции для GitHub Copilot."),
            ("skills/*", "Навыки: игровой цикл, UI, спрайты, прогресс, экспорт."),
            ("AGENT_TASKS.md", "Чек-лист задач, который агент отмечает."),
        ):
            row = QHBoxLayout()
            name_label = QLabel(name)
            name_label.setFont(theme.ui_font(9, 700))
            name_label.setFixedWidth(210)
            row.addWidget(name_label)
            row.addWidget(muted(text, size=9), 1)
            files.layout().addLayout(row)
        layout.addWidget(files)
        layout.addStretch(1)
        return scroll

    def _build_live(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = QWidget()
        host.setObjectName("root")
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 6, 4)
        layout.setSpacing(12)
        scroll.setWidget(host)

        state_card = Card()
        top = QHBoxLayout()
        top.addWidget(title_label("Живой прогресс", 13))
        top.addStretch(1)
        self.mode_badge = Badge("ВНЕШНИЙ РЕЖИМ", "default")
        top.addWidget(self.mode_badge)
        state_card.layout().addLayout(top)
        self.stage_label = muted("Ожидание внешнего агента", size=10)
        self.stage_label.setWordWrap(True)
        state_card.layout().addWidget(self.stage_label)
        self.percent_label = QLabel("0%")
        self.percent_label.setFont(theme.display_font(20, 700))
        self.percent_label.setStyleSheet("padding-bottom: 5px;")
        state_card.layout().addWidget(self.percent_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        state_card.layout().addWidget(self.progress)
        self.last_label = muted("", size=9)
        state_card.layout().addWidget(self.last_label)
        state_card.layout().addWidget(Separator())
        self.task_host = QVBoxLayout()
        self.task_host.setSpacing(5)
        state_card.layout().addLayout(self.task_host)
        layout.addWidget(state_card)

        events_card = Card(soft=True)
        events_card.layout().addWidget(title_label("Лента событий", 11))
        self.events_list = QListWidget()
        self.events_list.setObjectName("eventsList")
        self.events_list.setMaximumHeight(260)
        events_card.layout().addWidget(self.events_list)
        layout.addWidget(events_card)

        files_card = Card(soft=True)
        files_card.layout().addWidget(title_label("Недавние файлы", 11))
        self.files_list = QListWidget()
        self.files_list.setMaximumHeight(180)
        files_card.layout().addWidget(self.files_list)
        layout.addWidget(files_card)

        open_guide = QPushButton("Открыть AGENT_GUIDE.md")
        open_guide.setObjectName("teal")
        open_guide.clicked.connect(lambda: self._open_file(self.project.root / "AGENT_GUIDE.md"))
        layout.addWidget(open_guide)
        layout.addStretch(1)
        return scroll

    # ------------------------------------------------------------------
    def focus_task(self) -> None:
        self.first_task_edit.setFocus()
        self.first_task_edit.moveCursor(QTextCursor.MoveOperation.End)

    def _compose_prompt(self, task: str) -> str:
        prompt = AGENT_PROMPT.format(name=self.project.name, root=self.project.root).rstrip()
        task = task.strip()
        if task:
            prompt += "\n\nПЕРВАЯ ЗАДАЧА:\n" + task + "\n"
        else:
            prompt += (
                "\n\nПЕРВАЯ ЗАДАЧА:\n"
                "Изучи проект, предложи план и начни с самого важного шага.\n"
            )
        return prompt

    def _update_prompt_preview(self) -> None:
        if not hasattr(self, "prompt_preview"):
            return
        task = self.first_task_edit.toPlainText().strip()
        self.prompt_preview.setPlainText(self._compose_prompt(task))
        if task:
            self.prompt_hint.setText(f"Задача добавлена в промпт · {len(task)} символов")
        else:
            self.prompt_hint.setText(
                "Пока задача не написана — в промпте будет просьба изучить проект и предложить план."
            )

    def _copy_prompt(self) -> None:
        task = self.first_task_edit.toPlainText().strip()
        if not task:
            answer = QMessageBox.question(
                self,
                "Задача не описана",
                "Скопировать промпт без конкретной задачи? Агент просто изучит проект "
                "и предложит план.\n\nЛучше сначала написать задачу.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.first_task_edit.setFocus()
                return
        self._copy(self._compose_prompt(task))

    def _copy_task_only(self) -> None:
        task = self.first_task_edit.toPlainText().strip()
        if not task:
            QMessageBox.information(
                self,
                "Задача не описана",
                "Напишите задачу в поле выше, чтобы скопировать только её.",
            )
            self.first_task_edit.setFocus()
            return
        self._copy(task)

    def _copy(self, text: str) -> None:
        QApplication.clipboard().setText(text)
        self.status_message.emit("Скопировано в буфер обмена.")
        self.status_badge.setText("СКОПИРОВАНО")
        self.status_badge.set_tone("teal")
        QTimer.singleShot(1600, self.refresh)

    def _open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.project.root)))

    def _open_file(self, path: Path) -> None:
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        else:
            self.status_message.emit(f"Файл ещё не создан: {path.name}")

    def _regenerate_pack(self) -> None:
        from reasonable.ai.external import generate_agent_pack

        try:
            paths = generate_agent_pack(self.project)
        except Exception as exc:
            self.status_message.emit(f"Не удалось обновить пакет: {exc}")
            return
        self.status_message.emit(f"Пакет агента обновлён: {len(paths)} файлов.")
        self.status_badge.setText("ПАКЕТ ОБНОВЛЁН")
        self.status_badge.set_tone("teal")
        QTimer.singleShot(1800, self.refresh)

    # ------------------------------------------------------------------
    def refresh(self, force: bool = False) -> None:
        state = read_state(self.project.root)
        self._render_state(state, force)
        self._render_tasks(state, force)
        self._render_events()
        self._render_files()

        live = activity_is_live(self.project.root, window_seconds=300)
        status = state.get("status", "idle")
        if live and status == "running":
            self.status_badge.setText("АГЕНТ РАБОТАЕТ")
            self.status_badge.set_tone("gold")
        elif status == "done":
            self.status_badge.setText("ЗАВЕРШЕНО")
            self.status_badge.set_tone("teal")
        elif status == "error":
            self.status_badge.setText("ОШИБКА")
            self.status_badge.set_tone("gold")
        else:
            self.status_badge.setText("ОЖИДАНИЕ")
            self.status_badge.set_tone("default")
        self.activity_label.setText(
            ("активность: " + human_time(state.get("last_event_at"))) if state.get("last_event_at") else ""
        )

    def _render_state(self, state: dict, force: bool = False) -> None:
        signature = (
            state.get("percent"),
            state.get("stage"),
            state.get("message"),
            state.get("status"),
            state.get("last_event_at"),
        )
        if not force and signature == self._state_signature:
            return
        self._state_signature = signature
        percent = int(float(state.get("percent", 0) or 0))
        self.progress.setValue(percent)
        self.percent_label.setText(f"{percent}%")
        stage = state.get("stage") or "Ожидание"
        message = state.get("message") or ""
        self.stage_label.setText(f"{stage}\n{message}" if message and message != stage else stage)
        self.last_label.setText(f"Последняя активность: {human_time(state.get('last_event_at'))}")

    def _render_tasks(self, state: dict, force: bool = False) -> None:
        tasks = state.get("tasks") or []
        signature = tuple((task.get("id"), task.get("status"), task.get("title")) for task in tasks)
        if not force and signature == self._tasks_signature:
            return
        self._tasks_signature = signature
        while self.task_host.count():
            item = self.task_host.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not tasks:
            self.task_host.addWidget(muted("Агент ещё не создал план.", size=9))
            return
        for task in tasks:
            row = QHBoxLayout()
            status = task.get("status", "pending")
            icon, color = {
                "done": ("✓", "#8DB8A0"),
                "in_progress": (">", "#C9AD73"),
                "skipped": ("–", "#6F7680"),
            }.get(status, ("·", "#6F7680"))
            marker = QLabel(icon)
            marker.setFixedWidth(16)
            marker.setStyleSheet(f"color: {color}; font-weight: 800;")
            row.addWidget(marker)
            title = QLabel(task.get("title", ""))
            title.setWordWrap(True)
            title.setFont(theme.ui_font(9))
            if status == "done":
                title.setStyleSheet("color: #7D848E; text-decoration: line-through;")
            elif status == "in_progress":
                title.setStyleSheet("color: #D7C294;")
            else:
                title.setStyleSheet("color: #C1C7CF;")
            row.addWidget(title, 1)
            self.task_host.addLayout(row)

    def _render_events(self) -> None:
        events = read_events(self.project.root, limit=28)
        signature = tuple((event.get("ts"), event.get("type"), event.get("message")) for event in events[-28:])
        if signature == self._events_signature:
            return
        self._events_signature = signature
        self.events_list.clear()
        for event in reversed(events[-28:]):
            stamp = str(event.get("ts", ""))[11:19]
            kind = str(event.get("type", "event"))
            message = str(event.get("message", ""))
            item = QListWidgetItem(f"{stamp}  {kind:9s}  {message}")
            item.setToolTip(message)
            color = {
                "error": "#C98A90",
                "done": "#8DB8A0",
                "task": "#C9AD73",
            }.get(kind, "#A8AFB9")
            item.setForeground(QColor(color))
            self.events_list.addItem(item)

    def _render_files(self) -> None:
        rows = scan_recent_files(self.project.root, limit=8)
        signature = tuple((row["path"], round(row["mtime"])) for row in rows)
        if signature == self._files_signature:
            return
        self._files_signature = signature
        self.files_list.clear()
        for row in rows:
            item = QListWidgetItem(f"{human_time_from_mtime(row['mtime'])}   {row['path']}")
            item.setToolTip(row["path"])
            self.files_list.addItem(item)
        if not rows:
            self.files_list.addItem("Пока нет изменённых файлов.")

    def shutdown(self) -> None:
        self.timer.stop()


def human_time_from_mtime(value: float) -> str:
    from datetime import datetime

    try:
        return datetime.fromtimestamp(value).strftime("%H:%M:%S")
    except (OSError, ValueError):
        return "--:--:--"
