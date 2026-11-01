"""Editor main window and application bootstrap."""

from __future__ import annotations

import ctypes
import logging
import shutil
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QProcess, Qt
from PySide6.QtGui import QAction, QIcon, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QStatusBar,
    QWidget,
)

from reasonable import branding
from reasonable.core.logging_setup import configure_logging
from reasonable.core.paths import BRAND_DIR
from reasonable.core.project import Project
from reasonable.core.settings import Settings
from reasonable.version import VERSION, VERSION_NAME

from . import theme
from .new_project import NewProjectDialog
from .project_page import ProjectPage
from .settings_dialog import SettingsDialog
from .welcome import WelcomePage

LOGGER = logging.getLogger("reasonable.editor")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = Settings()
        self.current_page: ProjectPage | None = None
        self.setWindowTitle(f"{branding.APP_NAME} — {branding.TAGLINE_RU}")
        self.setMinimumSize(1120, 750)
        self.resize(1380, 900)
        icon_path = BRAND_DIR / "logo.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        else:
            self.setWindowIcon(QIcon(str(BRAND_DIR / "logo_256.png")))

        self.stack = QStackedWidget()
        self.welcome = WelcomePage(self.settings)
        self.welcome.new_project.connect(self.new_project)
        self.welcome.new_blank_project.connect(lambda: self.new_project(starter="blank"))
        self.welcome.open_project.connect(self.choose_project)
        self.welcome.open_settings.connect(self.open_settings)
        self.welcome.configure_ai.connect(self.open_ai_settings)
        self.welcome.open_recent.connect(self.open_project)
        self.welcome.delete_project.connect(self.delete_project)
        self.stack.addWidget(self.welcome)
        self.setCentralWidget(self.stack)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage(f"Reasonable Engine {VERSION_NAME} ({VERSION}) готова к работе.")

        self._build_menus()
        self._update_actions()

    # ------------------------------------------------------------------
    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("Файл")
        self.new_action = QAction("Новый проект с ИИ…", self)
        self.new_action.setShortcut(QKeySequence.StandardKey.New)
        self.new_action.triggered.connect(self.new_project)
        file_menu.addAction(self.new_action)

        self.blank_action = QAction("Пустой проект вручную…", self)
        self.blank_action.setShortcut(QKeySequence("Ctrl+Shift+N"))
        self.blank_action.triggered.connect(lambda: self.new_project(starter="blank"))
        file_menu.addAction(self.blank_action)

        self.open_action = QAction("Открыть проект…", self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.triggered.connect(self.choose_project)
        file_menu.addAction(self.open_action)

        self.recent_menu = file_menu.addMenu("Недавние проекты")
        self.recent_menu.aboutToShow.connect(self._fill_recent_menu)

        file_menu.addSeparator()
        self.settings_action = QAction("Настройки…", self)
        self.settings_action.setShortcut(QKeySequence("Ctrl+,"))
        self.settings_action.triggered.connect(self.open_settings)
        file_menu.addAction(self.settings_action)
        file_menu.addSeparator()
        quit_action = QAction("Выход", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        project_menu = self.menuBar().addMenu("Проект")
        self.run_action = QAction("Запустить проект", self)
        self.run_action.setShortcut(QKeySequence("Ctrl+R"))
        self.run_action.triggered.connect(self._run_current)
        project_menu.addAction(self.run_action)
        self.export_action = QAction("Экспорт…", self)
        self.export_action.setShortcut(QKeySequence("Ctrl+E"))
        self.export_action.triggered.connect(self._export_current)
        project_menu.addAction(self.export_action)
        self.convert_action = QAction("Конвертировать в новый проект…", self)
        self.convert_action.setShortcut(QKeySequence("Ctrl+Shift+D"))
        self.convert_action.triggered.connect(self._convert_current)
        project_menu.addAction(self.convert_action)
        self.project_settings_action = QAction("Настройки проекта…", self)
        self.project_settings_action.setShortcut(QKeySequence("Ctrl+Shift+,"))
        self.project_settings_action.triggered.connect(self._project_settings_current)
        project_menu.addAction(self.project_settings_action)
        self.history_action = QAction("История версий…", self)
        self.history_action.setShortcut(QKeySequence("Ctrl+Shift+H"))
        self.history_action.triggered.connect(self._open_history_current)
        project_menu.addAction(self.history_action)
        project_menu.addSeparator()

        self.section_actions: list[QAction] = []
        for index, label in enumerate(("Обзор", "ИИ-агент", "Код", "Ассеты"), start=1):
            action = QAction(f"{label}  (Ctrl+{index})", self)
            action.setShortcut(QKeySequence(f"Ctrl+{index}"))
            action.triggered.connect(lambda checked=False, i=index - 1: self._show_section(i))
            project_menu.addAction(action)
            self.section_actions.append(action)
        project_menu.addSeparator()
        self.delete_action = QAction("Удалить проект…", self)
        self.delete_action.setShortcut(QKeySequence("Ctrl+Shift+Delete"))
        self.delete_action.triggered.connect(self._delete_current)
        project_menu.addAction(self.delete_action)
        project_menu.addSeparator()
        self.back_action = QAction("К списку проектов", self)
        self.back_action.setShortcut(QKeySequence("Ctrl+Shift+W"))
        self.back_action.triggered.connect(self.show_welcome)
        project_menu.addAction(self.back_action)

        help_menu = self.menuBar().addMenu("Помощь")
        about = QAction("О Reasonable Engine", self)
        about.triggered.connect(self._about)
        help_menu.addAction(about)
        docs = QAction("Открыть README", self)
        docs.triggered.connect(self._open_docs)
        help_menu.addAction(docs)

    def _update_actions(self) -> None:
        active = self.current_page is not None
        for action in (
            self.run_action,
            self.export_action,
            self.convert_action,
            self.project_settings_action,
            self.history_action,
            self.delete_action,
            self.back_action,
            *self.section_actions,
        ):
            action.setEnabled(active)

    def _fill_recent_menu(self) -> None:
        self.recent_menu.clear()
        recents = self.settings.recent_projects()
        if not recents:
            empty = self.recent_menu.addAction("Пока нет проектов")
            empty.setEnabled(False)
            return
        for entry in recents[:12]:
            action = self.recent_menu.addAction(entry.get("name", entry.get("path", "")))
            action.setToolTip(entry.get("path", ""))
            action.triggered.connect(lambda checked=False, path=entry.get("path", ""): self.open_project(path))
        self.recent_menu.addSeparator()
        clear = self.recent_menu.addAction("Очистить список")
        clear.triggered.connect(self._clear_recents)

    def _clear_recents(self) -> None:
        self.settings.data["recent_projects"] = []
        self.settings.save()
        self.welcome.refresh()

    # ------------------------------------------------------------------
    def new_project(self, _checked: bool = False, *, starter: str = "game") -> None:
        if self.current_page is not None:
            self.show_welcome()
        dialog = NewProjectDialog(self.settings, self, starter=starter)
        dialog.settings_requested.connect(lambda: self._new_project_settings(dialog))
        result = dialog.exec()
        if result == NewProjectDialog.DialogCode.Accepted and dialog.result_project() is not None:
            project = dialog.result_project()
            if starter == "blank":
                self.open_project(project.root, focus_agent=False, section=2)
            else:
                self.open_project(project.root, focus_agent=True)
        else:
            self.welcome.refresh()

    def _new_project_settings(self, dialog: NewProjectDialog) -> None:
        settings_dialog = SettingsDialog(self.settings, dialog, advanced=True)
        settings_dialog.settings_saved.connect(dialog.refresh_ai)
        settings_dialog.exec()

    def choose_project(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Открыть проект Reasonable Engine",
            str(Path.home()),
        )
        if folder:
            self.open_project(folder)

    def open_project(self, path: str | Path, *, focus_agent: bool = False, section: int | None = None) -> None:
        target = Path(path)
        if target.is_file() and target.name == "project.json":
            target = target.parent
        try:
            project = Project.load(target)
        except Exception as exc:
            QMessageBox.warning(self, "Не удалось открыть проект", str(exc))
            self.settings.remove_recent(Path(target))
            self.welcome.refresh()
            return
        if not self._leave_current():
            return
        page = ProjectPage(project, self.settings)
        page.back_requested.connect(self.show_welcome)
        page.status_message.connect(self._status)
        page.converted.connect(self._open_converted_project)
        page.delete_requested.connect(lambda root=project.root: self.delete_project(root))
        self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)
        self.current_page = page
        self.settings.touch_recent(
            project.root,
            {"name": project.name, "type": project.project_type, "goal": project.goal},
        )
        self.setWindowTitle(f"{project.name} — {branding.APP_NAME}")
        self.statusBar().showMessage(project.summary())
        self._update_actions()
        if section is not None:
            page._show_page(section)
        elif focus_agent:
            page.open_agent_page(focus=True)

    def _leave_current(self) -> bool:
        page = self.current_page
        if page is None:
            return True
        if page.process is not None and page.process.state() != QProcess.ProcessState.NotRunning:
            answer = QMessageBox.question(
                self,
                "Проект запущен",
                "Проект ещё запущен. Остановить его и переключиться?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
            page.stop_project()
        if not page.code_page.save_all():
            return False
        page.shutdown()
        self.stack.removeWidget(page)
        page.deleteLater()
        self.current_page = None
        self._update_actions()
        return True

    def show_welcome(self) -> None:
        if not self._leave_current():
            return
        self.stack.setCurrentWidget(self.welcome)
        self.welcome.refresh()
        self.setWindowTitle(f"{branding.APP_NAME} — {branding.TAGLINE_RU}")
        self.statusBar().showMessage("Выберите недавний проект или создайте новый.")
        self._update_actions()

    # ------------------------------------------------------------------
    def open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        dialog.settings_saved.connect(self._settings_saved)
        dialog.exec()

    def open_ai_settings(self) -> None:
        """Open provider/model settings directly when the user asks for AI setup."""
        dialog = SettingsDialog(self.settings, self, advanced=True)
        dialog.settings_saved.connect(self._settings_saved)
        dialog.exec()

    def _settings_saved(self) -> None:
        self.welcome.refresh()
        if self.current_page is not None:
            self.current_page.refresh_ai()
        self.statusBar().showMessage("Настройки сохранены.", 4000)

    def _run_current(self) -> None:
        if self.current_page is not None:
            self.current_page.run_project()

    def _export_current(self) -> None:
        if self.current_page is not None:
            self.current_page._open_export()

    def _convert_current(self) -> None:
        if self.current_page is not None:
            self.current_page._open_convert()

    def _open_converted_project(self, path: str) -> None:
        self.open_project(path, focus_agent=False)

    def _project_settings_current(self) -> None:
        if self.current_page is not None:
            self.current_page._open_project_settings()

    def _show_section(self, index: int) -> None:
        if self.current_page is not None:
            self.current_page._show_page(index)

    def _open_history_current(self) -> None:
        if self.current_page is not None:
            self.current_page.open_history()

    # ------------------------------------------------------------------
    def _delete_current(self) -> None:
        if self.current_page is not None:
            self.delete_project(self.current_page.project.root)

    def delete_project(self, path: str | Path) -> None:
        """Remove a project from recents, optionally deleting its folder."""
        target = Path(path).expanduser()
        try:
            target = target.resolve()
        except OSError:
            pass
        is_open = (
            self.current_page is not None
            and self.current_page.project.root.resolve() == target
        )
        has_manifest = (target / "project.json").is_file()

        box = QMessageBox(self)
        box.setWindowTitle("Удалить проект")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(f"Удалить проект «{target.name}»?")
        box.setInformativeText(
            "Можно убрать проект только из списка недавних или удалить папку проекта "
            f"с диска:\n{target}"
        )
        remove_button = box.addButton("Убрать из списка", QMessageBox.ButtonRole.ActionRole)
        delete_button = box.addButton("Удалить с диска", QMessageBox.ButtonRole.DestructiveRole)
        if not has_manifest:
            delete_button.setEnabled(False)
            delete_button.setToolTip("В этой папке нет project.json — удаление с диска недоступно.")
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked not in {remove_button, delete_button}:
            return

        if is_open:
            if not self._leave_current():
                return
            self.show_welcome()

        self.settings.remove_recent(target)

        if clicked is delete_button:
            if not has_manifest:
                self._status("Папка не похожа на проект Reasonable Engine — удаление отменено.")
            elif self._unsafe_delete_target(target):
                QMessageBox.warning(
                    self,
                    "Удаление проекта",
                    "Эта папка защищена: удалять её целиком нельзя. Проект убран из списка.",
                )
            else:
                try:
                    shutil.rmtree(target)
                    self._status(f"Проект «{target.name}» удалён с диска.")
                except OSError as exc:
                    QMessageBox.warning(
                        self,
                        "Не удалось удалить проект",
                        f"Папка проекта не удалена:\n{exc}\n\nПроект убран из списка недавних.",
                    )

        self.welcome.refresh()
        if self.stack.currentWidget() is self.welcome:
            self.setWindowTitle(f"{branding.APP_NAME} — {branding.TAGLINE_RU}")
            self.statusBar().showMessage("Список проектов обновлён.")
        self._update_actions()

    @staticmethod
    def _unsafe_delete_target(target: Path) -> bool:
        from reasonable.core.paths import install_root

        protected = {
            Path(target.anchor),
            Path.home().resolve(),
            install_root().resolve(),
            install_root().resolve() / "Projects",
        }
        try:
            return target.resolve() in protected
        except OSError:
            return True

    def _status(self, message: str) -> None:
        self.statusBar().showMessage(message, 7000)

    def _about(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("О Reasonable Engine")
        box.setIconPixmap(theme.logo_pixmap(96))
        box.setText(
            f"<h2 style='color:#F0F2F4'>Reasonable Engine {VERSION_NAME}</h2>"
            f"<p style='color:#9AA1AB'>версия {VERSION} · {branding.TAGLINE_RU}</p>"
            "<p>Редактор игр и приложений с ИИ-агентом, спрайтами, "
            "живым прогрессом и экспортом на Windows и Android.</p>"
            "<p style='color:#9AA1AB'>Python · PySide6 · pygame · Pillow</p>"
        )
        box.exec()

    def _open_docs(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        from reasonable.core.paths import ENGINE_ROOT

        readme = ENGINE_ROOT / "README.md"
        if readme.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(readme)))
        else:
            QMessageBox.information(self, "Документация", "README.md не найден.")

    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802
        if not self._leave_current():
            event.ignore()
            return
        event.accept()


def _install_excepthook() -> None:
    def handle(exc_type, exc_value, exc_traceback) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        LOGGER.error("Unhandled exception:\n%s", text)
        try:
            box = QMessageBox()
            box.setWindowTitle("Неожиданная ошибка")
            box.setIcon(QMessageBox.Icon.Critical)
            box.setText("Reasonable Engine столкнулась с ошибкой, но продолжает работу.")
            box.setDetailedText(text)
            box.exec()
        except Exception:
            pass

    sys.excepthook = handle


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ReasonableEngine.Editor")
        except Exception:
            pass
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("Reasonable Engine")
    app.setApplicationDisplayName("Reasonable Engine")
    app.setOrganizationName("Reasonable Engine")
    app.setApplicationVersion(VERSION)
    theme.apply_theme(app)
    _install_excepthook()
    window = MainWindow()
    window.show()
    return app.exec()
