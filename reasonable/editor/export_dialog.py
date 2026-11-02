"""Windows and Android export dialog.

Shows two live bars — the current stage and the overall build percent — plus an
.exe name field for PyInstaller builds. Default destination is the Desktop.
"""

from __future__ import annotations

import importlib.util
import re
import time
from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from reasonable.core.i18n import t
from reasonable.core.paths import slugify
from reasonable.export import desktop_dir, exe_file_name

from . import theme
from .widgets import Badge, Card, muted, title_label
from .workers import ExportWorker

EXE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 _-]{0,58}$")


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
        self._started_at = 0.0

        self.setWindowTitle(t("exportdlg.window_title"))
        self.setMinimumSize(800, 760)
        self.resize(840, 780)
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
        title = QLabel(t("exportdlg.header"))
        title.setObjectName("title")
        title.setFont(theme.display_font(15, 700))
        titles.addWidget(title)
        titles.addWidget(muted(t("exportdlg.subtitle"), wrap=False, size=9))
        header.addLayout(titles)
        header.addStretch(1)
        header.addWidget(Badge(project.name, "default"))
        layout.addLayout(header)

        options = QHBoxLayout()
        options.setSpacing(10)
        self.group = QButtonGroup(self)
        self.buttons: dict[str, QPushButton] = {}
        pyinstaller_ready = importlib.util.find_spec("PyInstaller") is not None
        for key, title_text, hint in (
            ("windows", t("exportdlg.choice_windows"), t("exportdlg.choice_windows_hint")),
            ("exe", t("exportdlg.choice_exe"), t("exportdlg.choice_exe_hint")),
            ("android", t("exportdlg.choice_android"), t("exportdlg.choice_android_hint")),
        ):
            button = QPushButton(f"{title_text}\n{hint}")
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
        self.explain_title = title_label(t("exportdlg.explain_windows"), 11)
        self.explain.layout().addWidget(self.explain_title)
        self.explain_text = muted("", size=9)
        self.explain.layout().addWidget(self.explain_text)
        layout.addWidget(self.explain)

        output_card = Card()
        output_card.layout().addWidget(title_label(t("exportdlg.output_title"), 10))
        row = QHBoxLayout()
        self.output_edit = QLineEdit()
        row.addWidget(self.output_edit, 1)
        browse = QPushButton(t("exportdlg.browse"))
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        output_card.layout().addLayout(row)
        self.output_hint = muted("", size=9)
        output_card.layout().addWidget(self.output_hint)

        self.exe_row = QHBoxLayout()
        self.exe_label = QLabel(t("exportdlg.exe_label"))
        self.exe_label.setStyleSheet("color:#9AA4B2;")
        self.exe_edit = QLineEdit()
        self.exe_edit.setPlaceholderText(t("exportdlg.exe_placeholder"))
        self.exe_edit.textChanged.connect(self._validate_inputs)
        self.exe_row.addWidget(self.exe_label)
        self.exe_row.addWidget(self.exe_edit, 1)
        output_card.layout().addLayout(self.exe_row)
        self.exe_hint = muted(t("exportdlg.exe_hint"), size=9)
        output_card.layout().addWidget(self.exe_hint)

        self.one_file = QCheckBox(t("exportdlg.one_file"))
        self.one_file.hide()
        output_card.layout().addWidget(self.one_file)
        layout.addWidget(output_card)

        self.contents = Card(soft=True)
        self.contents.layout().addWidget(title_label(t("exportdlg.contents_title"), 10))
        self.contents_text = muted("", size=9)
        self.contents.layout().addWidget(self.contents_text)
        layout.addWidget(self.contents)

        # Two live bars: overall build progress and the current stage.
        overall_row = QHBoxLayout()
        self.overall_label = QLabel(t("exportdlg.overall_progress"))
        self.overall_label.setStyleSheet("color:#9AA4B2;")
        overall_row.addWidget(self.overall_label)
        overall_row.addStretch(1)
        self.overall_percent = QLabel("0%")
        self.overall_percent.setStyleSheet("color:#FFFFFF; font-weight:700;")
        overall_row.addWidget(self.overall_percent)
        layout.addLayout(overall_row)
        self.overall_bar = QProgressBar()
        self.overall_bar.setRange(0, 100)
        self.overall_bar.setValue(0)
        self.overall_bar.hide()
        layout.addWidget(self.overall_bar)

        stage_row = QHBoxLayout()
        self.stage_label = QLabel(t("exportdlg.stage"))
        self.stage_label.setStyleSheet("color:#9AA4B2;")
        stage_row.addWidget(self.stage_label)
        stage_row.addStretch(1)
        self.stage_percent = QLabel("")
        self.stage_percent.setStyleSheet("color:#9AA4B2;")
        stage_row.addWidget(self.stage_percent)
        layout.addLayout(stage_row)
        self.stage_bar = QProgressBar()
        self.stage_bar.setRange(0, 100)
        self.stage_bar.setValue(0)
        self.stage_bar.hide()
        layout.addWidget(self.stage_bar)

        self.status = muted("", size=9)
        layout.addWidget(self.status)

        self.result_card = Card(soft=True)
        self.result_card.hide()
        self.result_title = title_label(t("exportdlg.ready"), 11)
        self.result_card.layout().addWidget(self.result_title)
        self.result_text = muted("", size=9)
        self.result_card.layout().addWidget(self.result_text)
        result_buttons = QHBoxLayout()
        self.open_result = QPushButton(t("exportdlg.open_folder"))
        self.open_result.setObjectName("teal")
        self.open_result.clicked.connect(self._open_result)
        result_buttons.addWidget(self.open_result)
        result_buttons.addStretch(1)
        self.result_card.layout().addLayout(result_buttons)
        layout.addWidget(self.result_card)

        layout.addStretch(1)
        buttons = QHBoxLayout()
        self.android_help = QPushButton(t("exportdlg.android_instructions"))
        self.android_help.setObjectName("ghost")
        self.android_help.clicked.connect(self._show_android_help)
        self.android_help.hide()
        buttons.addWidget(self.android_help)
        buttons.addStretch(1)
        close = QPushButton(t("exportdlg.close"))
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        self.export_button = QPushButton(t("exportdlg.export"))
        self.export_button.setObjectName("primary")
        self.export_button.setMinimumWidth(170)
        self.export_button.clicked.connect(self._export)
        buttons.addWidget(self.export_button)
        layout.addLayout(buttons)

        self._pyinstaller_ready = pyinstaller_ready
        self._select_target("windows")

    # ------------------------------------------------------------------
    def _default_output(self) -> Path:
        desktop = desktop_dir()
        slug = slugify(self.project.name, "project")
        if self.target == "android":
            return desktop / f"{slug}-android.zip"
        return desktop / f"{slug}-windows"

    def _default_exe_name(self) -> str:
        return exe_file_name(slugify(self.project.name, "project").replace("-", " "), self.project)

    def _select_target(self, target: str) -> None:
        if self._running:
            return
        self.target = target
        self.mode = "pyinstaller" if target == "exe" else "folder"
        self.buttons[target].setChecked(True)
        self.output_edit.setText(str(self._default_output()))
        self.result_card.hide()
        self.android_help.setVisible(target == "android")
        self.one_file.setVisible(target == "exe")
        exe_mode = target == "exe"
        self.exe_label.setVisible(exe_mode)
        self.exe_edit.setVisible(exe_mode)
        self.exe_hint.setVisible(exe_mode)
        if exe_mode and not self.exe_edit.text().strip():
            self.exe_edit.setText(self._default_exe_name())
        if target == "windows":
            self.explain_title.setText(t("exportdlg.explain_windows"))
            self.explain_text.setText(t("exportdlg.explain_windows_text"))
            self.output_hint.setText(t("exportdlg.output_hint_windows"))
            self.contents_text.setText(t("exportdlg.contents_windows"))
        elif target == "exe":
            self.explain_title.setText(t("exportdlg.explain_exe"))
            self.explain_text.setText(t("exportdlg.explain_exe_text"))
            self.output_hint.setText(
                t("exportdlg.output_hint_exe")
                if self._pyinstaller_ready
                else t("exportdlg.output_hint_exe_missing")
            )
            self.contents_text.setText(t("exportdlg.contents_exe"))
        else:
            self.explain_title.setText(t("exportdlg.explain_android"))
            self.explain_text.setText(t("exportdlg.explain_android_text"))
            self.output_hint.setText(t("exportdlg.output_hint_android"))
            self.contents_text.setText(t("exportdlg.contents_android"))
        self._validate_inputs()

    def _browse(self) -> None:
        if self.target == "android":
            path, _filter = QFileDialog.getSaveFileName(
                self,
                t("exportdlg.save_android"),
                self.output_edit.text() or str(desktop_dir() / f"{slugify(self.project.name, 'project')}-android.zip"),
                "ZIP (*.zip)",
            )
            if path:
                if not path.lower().endswith(".zip"):
                    path += ".zip"
                self.output_edit.setText(path)
        else:
            path = QFileDialog.getExistingDirectory(
                self,
                t("exportdlg.pick_folder"),
                str(desktop_dir()),
            )
            if path:
                self.output_edit.setText(str(Path(path) / f"{slugify(self.project.name, 'project')}-windows"))

    def _show_android_help(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(t("exportdlg.apk_build_title"))
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(t("exportdlg.apk_build_text"))
        box.setDetailedText(t("exportdlg.android_help"))
        box.exec()

    # ------------------------------------------------------------------
    def _validate_inputs(self) -> None:
        """Live validation of the exe name; the Export button reflects it."""
        if self.target == "exe":
            name = self.exe_edit.text().strip()
            if not EXE_NAME_RE.match(name):
                self.exe_hint.setText(t("exportdlg.exe_name_invalid"))
                self.export_button.setEnabled(not self._running and False)
                return
            self.exe_hint.setText(t("exportdlg.exe_ready_file", name=exe_file_name(name, self.project)))
        self.export_button.setEnabled(not self._running and (self.target != "exe" or self._pyinstaller_ready))

    def _export(self) -> None:
        if self._running:
            return
        output = self.output_edit.text().strip()
        if not output:
            QMessageBox.warning(self, t("exportdlg.no_path_title"), t("exportdlg.no_path_text"))
            return
        exe_name = ""
        if self.target == "exe":
            if not self._pyinstaller_ready:
                QMessageBox.warning(
                    self,
                    t("exportdlg.no_pyinstaller_title"),
                    t("exportdlg.no_pyinstaller_text"),
                )
                return
            raw = self.exe_edit.text().strip()
            if not EXE_NAME_RE.match(raw):
                QMessageBox.warning(
                    self,
                    t("exportdlg.exe_name_title"),
                    t("exportdlg.exe_name_text"),
                )
                return
            exe_name = exe_file_name(raw, self.project)
        self._running = True
        self._started_at = time.monotonic()
        self._set_inputs_enabled(False)
        self.export_button.setEnabled(False)
        self.export_button.setText(t("exportdlg.running_button"))
        self.overall_bar.show()
        self.stage_bar.show()
        self.overall_bar.setValue(0)
        self.overall_percent.setText("0%")
        self.stage_bar.setValue(0)
        self.stage_percent.setText("")
        self.status.setText(t("exportdlg.preparing"))
        self.result_card.hide()
        self.worker = ExportWorker(self.project, self.target, output, self.mode, exe_name)
        self.worker.progress.connect(self._on_progress)
        self.worker.stage.connect(self.status.setText)
        self.worker.done.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _set_inputs_enabled(self, enabled: bool) -> None:
        for button in self.buttons.values():
            button.setEnabled(enabled)
        self.output_edit.setEnabled(enabled)
        self.exe_edit.setEnabled(enabled)
        self.one_file.setEnabled(enabled)

    def _on_progress(self, stage_text: str, stage_pct: float, overall_pct: float) -> None:
        self.stage_label.setText(stage_text)
        self.stage_bar.setValue(int(round(stage_pct)))
        self.stage_percent.setText(f"{int(round(stage_pct))}%")
        self.overall_bar.setValue(int(round(overall_pct)))
        self.overall_percent.setText(f"{int(round(overall_pct))}%")

    def _done(self, result: dict) -> None:
        self._running = False
        self.result = result
        self._set_inputs_enabled(True)
        self.overall_bar.setValue(100)
        self.overall_percent.setText("100%")
        self.stage_bar.setValue(100)
        self.stage_percent.setText("100%")
        self.export_button.setEnabled(True)
        self.export_button.setText(t("exportdlg.again_button"))
        self.status.setText(result.get("message", t("exportdlg.finished_message")))
        self.result_card.show()
        elapsed = max(1, int(time.monotonic() - self._started_at))
        minutes, seconds = divmod(elapsed, 60)
        self.result_title.setText(t("exportdlg.done_prefix") + ("Android" if self.target == "android" else "Windows"))
        lines = [str(result.get("path", ""))]
        if result.get("zip"):
            lines.append("ZIP: " + str(result["zip"]))
        if result.get("exe"):
            lines.append("EXE: " + str(result["exe"]))
        lines.append(t("exportdlg.build_time", minutes=minutes, seconds=seconds))
        lines.append(t("exportdlg.splash_note"))
        if self.target == "android":
            lines.append(t("exportdlg.next_step_android"))
        self.result_text.setText("\n".join(lines))
        self.status_message = result.get("message", "")
        self.exported.emit(result)

    def _failed(self, message: str, trace: str) -> None:
        self._running = False
        self._set_inputs_enabled(True)
        self.export_button.setEnabled(True)
        self.export_button.setText(t("exportdlg.retry_button"))
        self.status.setText(t("exportdlg.error_prefix") + message)
        box = QMessageBox(self)
        box.setWindowTitle(t("exportdlg.failed_title"))
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
                t("exportdlg.close_running_title"),
                t("exportdlg.close_running_text"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        event.accept()
