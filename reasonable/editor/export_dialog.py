"""Windows and Android export dialog."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from reasonable.core.paths import slugify

from . import theme
from .widgets import Badge, Card, muted, title_label
from .workers import ExportWorker

ANDROID_HELP = """Сборка APK выполняется на Linux или в WSL2:

1. Установите WSL: wsl --install
2. В Ubuntu выполните:
   sudo apt update && sudo apt install -y git zip unzip openjdk-17-jdk \\
     autoconf libtool pkg-config zlib1g-dev libncurses5-dev libncursesw5-dev \\
     libtinfo6 cmake libffi-dev libssl-dev
   pip install --user buildozer cython
3. cd <папка-экспорта>
4. buildozer -v android debug
5. APK появится в bin/ — установите через adb install -r bin/*.apk

В экспортированном пакете есть README_ANDROID.md и готовый GitHub Actions
workflow: загрузите проект в GitHub и получите APK во вкладке Actions."""


class ExportDialog(QDialog):
    exported = Signal(object)

    def __init__(self, project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self.worker: ExportWorker | None = None
        self.result: dict | None = None
        self.target = "windows"
        self.mode = "folder"
        self._running = False

        self.setWindowTitle("Экспорт — Reasonable Engine")
        self.setMinimumSize(780, 700)
        self.resize(820, 740)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(12)

        header = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(theme.logo_pixmap(32))
        header.addWidget(logo)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        title = QLabel("Экспорт проекта")
        title.setObjectName("title")
        title.setFont(theme.display_font(15, 700))
        titles.addWidget(title)
        titles.addWidget(muted("Windows — папка или .exe. Android — готовый buildozer-пакет.", wrap=False, size=9))
        header.addLayout(titles)
        header.addStretch(1)
        header.addWidget(Badge(project.name, "default"))
        layout.addLayout(header)

        options = QHBoxLayout()
        options.setSpacing(10)
        self.group = QButtonGroup(self)
        self.buttons: dict[str, QPushButton] = {}
        pyinstaller_ready = importlib.util.find_spec("PyInstaller") is not None
        for key, title, hint in (
            ("windows", "WINDOWS · ПАПКА", "Play.bat и файлы проекта."),
            ("exe", "WINDOWS · .EXE", "Один файл через PyInstaller."),
            ("android", "ANDROID · ПАКЕТ", "buildozer.spec, ZIP и инструкция."),
        ):
            button = QPushButton(f"{title}\n{hint}")
            button.setObjectName("choice")
            button.setCheckable(True)
            button.setMinimumHeight(76)
            button.setFont(theme.ui_font(9, 700))
            self.group.addButton(button)
            self.buttons[key] = button
            options.addWidget(button)
        self.buttons["windows"].setChecked(True)
        layout.addLayout(options)
        self.buttons["windows"].toggled.connect(lambda checked: checked and self._select_target("windows"))
        self.buttons["exe"].toggled.connect(lambda checked: checked and self._select_target("exe"))
        self.buttons["android"].toggled.connect(lambda checked: checked and self._select_target("android"))

        self.explain = Card(soft=True)
        self.explain_title = title_label("Папка Windows", 11)
        self.explain.layout().addWidget(self.explain_title)
        self.explain_text = muted("", size=9)
        self.explain.layout().addWidget(self.explain_text)
        layout.addWidget(self.explain)

        output_card = Card()
        output_card.layout().addWidget(title_label("Куда сохранить", 10))
        row = QHBoxLayout()
        self.output_edit = QLineEdit()
        row.addWidget(self.output_edit, 1)
        browse = QPushButton("Выбрать…")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        output_card.layout().addLayout(row)
        self.output_hint = muted("", size=9)
        output_card.layout().addWidget(self.output_hint)
        self.one_file = QCheckBox("Собрать один .exe (медленнее, но удобнее для отправки)")
        self.one_file.hide()
        output_card.layout().addWidget(self.one_file)
        layout.addWidget(output_card)

        self.contents = Card(soft=True)
        self.contents.layout().addWidget(title_label("Что внутри", 10))
        self.contents_text = muted("", size=9)
        self.contents.layout().addWidget(self.contents_text)
        layout.addWidget(self.contents)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.status = muted("", size=9)
        layout.addWidget(self.status)

        self.result_card = Card(soft=True)
        self.result_card.hide()
        self.result_title = title_label("Готово", 11)
        self.result_card.layout().addWidget(self.result_title)
        self.result_text = muted("", size=9)
        self.result_card.layout().addWidget(self.result_text)
        result_buttons = QHBoxLayout()
        self.open_result = QPushButton("Открыть папку")
        self.open_result.setObjectName("teal")
        self.open_result.clicked.connect(self._open_result)
        result_buttons.addWidget(self.open_result)
        result_buttons.addStretch(1)
        self.result_card.layout().addLayout(result_buttons)
        layout.addWidget(self.result_card)

        layout.addStretch(1)
        buttons = QHBoxLayout()
        self.android_help = QPushButton("Инструкция Android")
        self.android_help.setObjectName("ghost")
        self.android_help.clicked.connect(self._show_android_help)
        self.android_help.hide()
        buttons.addWidget(self.android_help)
        buttons.addStretch(1)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        self.export_button = QPushButton("Экспортировать")
        self.export_button.setObjectName("primary")
        self.export_button.setMinimumWidth(170)
        self.export_button.clicked.connect(self._export)
        buttons.addWidget(self.export_button)
        layout.addLayout(buttons)

        self._pyinstaller_ready = pyinstaller_ready
        self._select_target("windows")

    # ------------------------------------------------------------------
    def _default_output(self) -> Path:
        base = self.project.root / "dist"
        slug = slugify(self.project.name, "project")
        if self.target == "android":
            return base / f"{slug}-android.zip"
        if self.target == "exe":
            return base / f"{slug}-windows"
        return base / f"{slug}-windows"

    def _select_target(self, target: str) -> None:
        self.target = target
        self.mode = "pyinstaller" if target == "exe" else "folder"
        self.buttons[target].setChecked(True)
        self.output_edit.setText(str(self._default_output()))
        self.result_card.hide()
        self.android_help.setVisible(target == "android")
        self.one_file.setVisible(target == "exe")
        if target == "windows":
            self.explain_title.setText("Папка Windows")
            self.explain_text.setText(
                "Самодостаточная папка: main.py, assets/, встроенный движок и Play.bat. "
                "Запускается на Windows с Python 3.10+. Заставка Reasonable Engine играет всегда."
            )
            self.output_hint.setText("Будет создана папка. Если она уже существует, новая получит суффикс -2.")
            self.contents_text.setText(
                "main.py · project.json · assets/ · _engine/ · progress/ · AGENT_GUIDE.md · "
                "Play.bat · README_WINDOWS.txt · app.ico"
            )
            self.export_button.setEnabled(True)
        elif target == "exe":
            self.explain_title.setText("Windows .exe через PyInstaller")
            self.explain_text.setText(
                "Соберёт автономный .exe с иконкой. Первая сборка занимает несколько минут. "
                "Если PyInstaller не установлен, установите его командой python -m pip install pyinstaller."
            )
            self.output_hint.setText(
                "Папка назначения. Внутри появится .exe и вспомогательные файлы."
                if self._pyinstaller_ready
                else "PyInstaller не найден — установите его, чтобы включить этот режим."
            )
            self.contents_text.setText(
                "Исполняемый файл проекта · иконка · ассеты · встроенный движок. "
                "Заставка и все ресурсы включены."
            )
            self.export_button.setEnabled(True)
        else:
            self.explain_title.setText("Android-пакет")
            self.explain_text.setText(
                "Готовый проект python-for-android/buildozer с buildozer.spec, README_ANDROID.md, "
                "иконкой, presplash и GitHub Actions. APK собирается на Linux/WSL — это ограничение buildozer, "
                "а не движка."
            )
            self.output_hint.setText("Будет создан ZIP-архив и папка проекта рядом с ним.")
            self.contents_text.setText(
                "main.py · buildozer.spec · assets/ · _engine/ · progress/ · README_ANDROID.md · "
                ".github/workflows/android.yml"
            )
            self.export_button.setEnabled(True)

    def _browse(self) -> None:
        if self.target == "android":
            path, _filter = QFileDialog.getSaveFileName(
                self,
                "Сохранить Android-пакет",
                self.output_edit.text() or str(self.project.root / "dist" / "android.zip"),
                "ZIP (*.zip)",
            )
            if path:
                if not path.lower().endswith(".zip"):
                    path += ".zip"
                self.output_edit.setText(path)
        else:
            path = QFileDialog.getExistingDirectory(
                self,
                "Выберите папку для экспорта",
                str(self.project.root / "dist"),
            )
            if path:
                self.output_edit.setText(str(Path(path) / self.project.root.name + "-windows"))

    def _show_android_help(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Сборка Android APK")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText("Android-пакет готов к сборке через buildozer.")
        box.setDetailedText(ANDROID_HELP)
        box.exec()

    # ------------------------------------------------------------------
    def _export(self) -> None:
        if self._running:
            return
        output = self.output_edit.text().strip()
        if not output:
            QMessageBox.warning(self, "Путь не задан", "Укажите папку или файл для экспорта.")
            return
        if self.target == "exe" and not self._pyinstaller_ready:
            QMessageBox.warning(
                self,
                "PyInstaller не установлен",
                "Установите PyInstaller командой:\n\npython -m pip install pyinstaller\n\n"
                "Или выберите экспорт в папку Windows.",
            )
            return
        self._running = True
        self.export_button.setEnabled(False)
        self.export_button.setText("Экспортирую…")
        self.progress.show()
        self.status.setText("Копирую проект и встроенный движок…")
        self.result_card.hide()
        self.worker = ExportWorker(self.project, self.target, output, self.mode)
        self.worker.stage.connect(self.status.setText)
        self.worker.done.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _done(self, result: dict) -> None:
        self._running = False
        self.result = result
        self.progress.hide()
        self.export_button.setEnabled(True)
        self.export_button.setText("Экспортировать ещё")
        self.status.setText(result.get("message", "Экспорт завершён."))
        self.result_card.show()
        self.result_title.setText("Готово: " + ("Android" if self.target == "android" else "Windows"))
        lines = [str(result.get("path", ""))]
        if result.get("zip"):
            lines.append("ZIP: " + str(result["zip"]))
        if result.get("exe"):
            lines.append("EXE: " + str(result["exe"]))
        lines.append("Заставка Reasonable Engine включена в сборку.")
        if self.target == "android":
            lines.append("Следующий шаг: buildozer android debug на Linux/WSL или GitHub Actions.")
        self.result_text.setText("\n".join(lines))
        self.status_message = result.get("message", "")
        self.exported.emit(result)

    def _failed(self, message: str, trace: str) -> None:
        self._running = False
        self.progress.hide()
        self.export_button.setEnabled(True)
        self.export_button.setText("Повторить экспорт")
        self.status.setText("Ошибка: " + message)
        box = QMessageBox(self)
        box.setWindowTitle("Экспорт не удался")
        box.setIcon(QMessageBox.Icon.Critical)
        box.setText(message)
        box.setDetailedText(trace)
        box.exec()

    def _open_result(self) -> None:
        if not self.result:
            return
        path = Path(str(self.result.get("zip") or self.result.get("path") or self.project.root))
        target = path if path.is_dir() else path.parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.worker is not None and self.worker.isRunning():
            answer = QMessageBox.question(
                self,
                "Экспорт",
                "Экспорт ещё выполняется. Закрыть окно?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        event.accept()
