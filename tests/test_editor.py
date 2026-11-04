import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication

    PYSIDE_AVAILABLE = True
except ImportError:  # pragma: no cover - editor is optional for headless CI
    PYSIDE_AVAILABLE = False

from reasonable.core.project import Project
from reasonable.core.settings import Settings


def wait_for_worker(worker, timeout_seconds: int = 90) -> dict:
    loop = QEventLoop()
    outcome = {"done": False, "failed": False, "result": None, "error": ""}
    worker.done.connect(lambda result: (outcome.update(done=True, result=result), loop.quit()))
    worker.failed.connect(lambda message, _trace: (outcome.update(failed=True, error=message), loop.quit()))
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(timeout_seconds * 1000)
    loop.exec()
    if worker.isRunning():
        worker.terminate()
        worker.wait(3000)
    return outcome


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
class EditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls._tmp.name)
        os.environ["REASONABLE_HOME"] = str(cls.base / "home")
        from reasonable.editor import theme

        cls.app = QApplication.instance() or QApplication(sys.argv)
        theme.apply_theme(cls.app)
        cls.settings = Settings(path=cls.base / "home" / "settings.json")

        from reasonable.editor.new_project import NewProjectDialog

        cls.wizard = NewProjectDialog(cls.settings)
        cls.wizard.goal_edit.setText("Космический кот собирает звёзды")
        # Two content steps: idea -> name/location. Window mode, notes and the
        # first agent task are intentionally not part of the wizard.
        cls.wizard._next()
        cls.wizard.name_edit.setText("Test Game")
        cls.wizard.folder_edit.setText(str(cls.base / "projects"))
        cls.wizard._next()
        cls.outcome = wait_for_worker(cls.wizard.worker)
        cls.project = cls.outcome["result"]

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.wizard.reject()
        finally:
            cls._tmp.cleanup()
            # Flush deferred deletes before the interpreter tears Qt down.
            cls.app.processEvents()

    def test_wizard_creates_project(self) -> None:
        self.assertTrue(self.outcome["done"], self.outcome["error"])
        self.assertIsNotNone(self.project)
        self.assertTrue((self.project.root / "main.py").is_file())
        self.assertTrue((self.project.root / "_engine" / "reasonable" / "runtime" / "app.py").is_file())
        self.assertEqual(self.project.project_type, "game")
        self.assertEqual(self.project.mode, "builtin")
        self.assertEqual(self.project.window["width"], 1280)
        self.assertEqual(self.project.window["height"], 720)
        self.assertEqual(self.project.window_mode, "windowed")
        self.assertTrue(self.project.resizable)
        self.assertEqual(self.project.notes, "")
        self.assertIs(self.wizard.result_project(), self.project)

    def test_wizard_has_no_window_or_prompt_fields(self) -> None:
        # Regression: the wizard used to ask for prompts, style, orientation
        # and window size before the project even existed.
        self.assertEqual(len(self.wizard.step_pills), 2)
        for attribute in ("prompts_edit", "width_spin", "height_spin", "orientation_combo", "style_combo"):
            self.assertFalse(hasattr(self.wizard, attribute), attribute)
        self.assertIn("Интерфейс:", self.wizard.summary_label.text())

    def test_wizard_mode_toggle_refreshes_summary(self) -> None:
        # Regression: toggling mode used to call a missing method.
        self.wizard.mode_buttons["external"].setChecked(True)
        self.assertEqual(self.wizard.mode(), "external")
        self.assertIn("Внешний агент", self.wizard.mode_hint.text())
        self.assertIn("внешний агент", self.wizard.summary_label.text())
        self.wizard.mode_buttons["builtin"].setChecked(True)
        self.assertIn("Встроенный", self.wizard.mode_hint.text())
        self.assertIn("встроенный ИИ", self.wizard.summary_label.text())

    def test_welcome_offers_three_first_run_actions(self) -> None:
        from reasonable.editor.welcome import WelcomePage

        page = WelcomePage(self.settings)
        try:
            self.assertIn("ИИ", page.create_button.text())
            self.assertIn("Открыть", page.open_button.text())
            self.assertIn("Пустой", page.blank_button.text())
        finally:
            page.deleteLater()

    def test_blank_wizard_skips_idea_and_ai_questions(self) -> None:
        from reasonable.editor.new_project import NewProjectDialog

        dialog = NewProjectDialog(self.settings, starter="blank")
        try:
            self.assertEqual(dialog.starter, "blank")
            self.assertTrue(dialog.goal_edit.isHidden())
            self.assertTrue(dialog.mode_buttons["builtin"].isHidden())
            self.assertIn("Пустой проект", dialog.summary_label.text())
            dialog._next()
            dialog.name_edit.setText("Blank Test")
            dialog.folder_edit.setText(str(self.base / "blank-wizard"))
            dialog._next()
            outcome = wait_for_worker(dialog.worker)
            self.assertTrue(outcome["done"], outcome["error"])
            project = outcome["result"]
            self.assertEqual(project.manifest.get("template"), "blank")
            self.assertIn("class Project(Game)", (project.root / "main.py").read_text(encoding="utf-8"))
        finally:
            dialog.reject()

    def test_settings_advanced_mode_is_opt_in(self) -> None:
        from reasonable.editor.settings_dialog import SettingsDialog

        dialog = SettingsDialog(self.settings)
        try:
            self.assertFalse(dialog._advanced)
            self.assertTrue(dialog.sidebar.isHidden())
            dialog.advanced_toggle.setChecked(True)
            self.assertFalse(dialog.sidebar.isHidden())
            self.assertEqual(dialog.mode_stack.currentIndex(), 1)
            dialog.advanced_toggle.setChecked(False)
            self.assertTrue(dialog.sidebar.isHidden())
            self.assertEqual(dialog.mode_stack.currentIndex(), 0)
            self.assertFalse((self.settings.data.get("ui") or {}).get("advanced_settings", False))
        finally:
            dialog.reject()

    def test_settings_can_open_advanced_page_explicitly(self) -> None:
        from reasonable.editor.settings_dialog import SettingsDialog

        dialog = SettingsDialog(self.settings, advanced=True)
        try:
            self.assertTrue(dialog._advanced)
            self.assertFalse(dialog.sidebar.isHidden())
            self.assertEqual(dialog.mode_stack.currentIndex(), 1)
        finally:
            dialog.reject()

    def test_external_agent_panel_shows_task_and_prompt(self) -> None:
        from reasonable.editor.external import ExternalAgentPanel

        panel = ExternalAgentPanel(self.project)
        try:
            self.assertTrue(panel.prompt_preview.isReadOnly())
            self.assertIn("Пока задача не написана", panel.prompt_hint.text())
            self.assertNotIn(self.project.name, panel.first_task_edit.placeholderText())
            self.assertIn("re.bat done", panel.prompt_preview.toPlainText())

            panel.first_task_edit.setPlainText("Собери меню и первый уровень")
            preview = panel.prompt_preview.toPlainText()
            self.assertIn("Собери меню и первый уровень", preview)
            self.assertIn(str(self.project.root), preview)
            self.assertIn("ПЕРВАЯ ЗАДАЧА", preview)
            self.assertIn("AGENT_GUIDE.md", preview)
            self.assertIn("Задача добавлена в промпт", panel.prompt_hint.text())
        finally:
            panel.timer.stop()
            panel.deleteLater()

    def test_external_live_progress_replaces_old_tasks_without_ghosts(self) -> None:
        from PySide6.QtWidgets import QLabel

        from reasonable.editor.external import ExternalAgentPanel

        panel = ExternalAgentPanel(self.project)
        try:
            panel._render_tasks(
                {"tasks": [{"id": "t1", "title": "Old task", "status": "done"}]},
                force=True,
            )
            panel._render_tasks(
                {"tasks": [{"id": "t2", "title": "New task", "status": "in_progress"}]},
                force=True,
            )
            self.assertEqual(panel.task_host.count(), 1)
            row = panel.task_host.itemAt(0).widget()
            self.assertIsNotNone(row)
            texts = [label.text() for label in row.findChildren(QLabel)]
            self.assertIn("New task", texts)
            # The old row must be gone, not painted underneath the new one.
            all_texts = [label.text() for label in panel.findChildren(QLabel)]
            self.assertNotIn("Old task", all_texts)
        finally:
            panel.timer.stop()
            panel.deleteLater()
            self.app.processEvents()

    def test_agent_worker_reports_provider_error_as_failure(self) -> None:
        from reasonable.editor.workers import AgentWorker

        worker = AgentWorker(self.project, self.settings, "task")
        worker.agent.run = lambda _message=None: ""
        worker.agent.last_error = "401 Unauthorized"
        events = {"done": [], "failed": []}
        worker.done.connect(lambda text: events["done"].append(text))
        worker.failed.connect(lambda message: events["failed"].append(message))
        worker.run()
        self.assertEqual(events["done"], [])
        self.assertEqual(events["failed"], ["401 Unauthorized"])

    def test_history_dialog_lists_and_previews_snapshot(self) -> None:
        from reasonable.core.history import create_snapshot, delete_snapshot
        from reasonable.editor.history_dialog import HistoryDialog

        snapshot = create_snapshot(self.project, label="До правок агента", reason="manual", record=False)
        dialog = HistoryDialog(self.project)
        try:
            self.assertEqual(dialog.list.count(), 1)
            self.assertIsNotNone(dialog._current)
            self.assertEqual(dialog._current["id"], snapshot["id"])
            self.assertIn("До правок агента", dialog._current["label"])
        finally:
            dialog.deleteLater()
            delete_snapshot(self.project, str(snapshot["id"]))

    def test_settings_save_persists_provider(self) -> None:
        from reasonable.editor.settings_dialog import SettingsDialog

        dialog = SettingsDialog(self.settings)
        dialog._select_provider("groq")
        dialog.model_combo.setEditText("llama-3.3-70b-versatile")
        dialog.key_edit.setText("gsk-test")
        dialog._save()
        reloaded = Settings(path=self.settings.path)
        self.assertEqual(reloaded.active_provider, "groq")
        config = reloaded.get_provider_config("groq")
        self.assertEqual(config["api_key"], "gsk-test")
        self.assertEqual(config["model"], "llama-3.3-70b-versatile")

    def test_code_editor_opens_and_saves(self) -> None:
        from reasonable.editor.code import CodePage

        page = CodePage(self.project)
        page.open_file("main.py")
        self.assertIn("pygame", page.editor.toPlainText())
        page.editor.setPlainText(page.editor.toPlainText().rstrip() + "\n# auto-test-marker\n")
        self.assertTrue(page.save_file())
        self.assertIn("auto-test-marker", (self.project.root / "main.py").read_text(encoding="utf-8"))
        page.deleteLater()

    def test_chat_enter_sends_and_ctrl_enter_adds_a_line(self) -> None:
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent

        from reasonable.editor.chat import ChatPanel

        panel = ChatPanel(self.project, self.settings)
        sent: list[str] = []
        panel.send = lambda text=None: sent.append(text if text is not None else panel.input.toPlainText())
        try:
            panel.input.setPlainText("первая строка")
            enter = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
            self.assertTrue(panel.eventFilter(panel.input, enter))
            self.assertEqual(sent, ["первая строка"])

            panel.input.setPlainText("первая")
            panel.input.moveCursor(panel.input.textCursor().MoveOperation.End)
            ctrl_enter = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
            self.assertTrue(panel.eventFilter(panel.input, ctrl_enter))
            self.assertEqual(sent, ["первая строка"])
            self.assertEqual(panel.input.toPlainText(), "первая\n")
        finally:
            panel.deleteLater()
            self.app.processEvents()

    def test_chat_usage_label_reads_lifetime_totals(self) -> None:
        from reasonable.core.usage import add_usage
        from reasonable.editor.chat import ChatPanel

        add_usage(self.project.root, prompt_tokens=100, completion_tokens=50, seconds=125)
        panel = ChatPanel(self.project, self.settings)
        try:
            self.assertFalse(panel.usage_label.isHidden())
            self.assertIn("150", panel.usage_label.text())
            self.assertIn("2 мин", panel.usage_label.text())
        finally:
            panel.deleteLater()

    def test_tool_calls_are_compact_and_collapsible(self) -> None:
        from reasonable.editor.chat import ToolCallCard, ToolCallGroup

        card = ToolCallCard("edit_file", {"path": "main.py", "old_text": "a", "new_text": "b"})
        group = ToolCallGroup()
        group.add_call(card)
        try:
            self.assertIn("Правка файла", card.header.text())
            self.assertIn("main.py", card.header.text())
            self.assertTrue(card.details.isHidden())
            self.assertLessEqual(card.sizeHint().height(), 34)

            card.header.click()
            self.assertFalse(card.details.isHidden())
            card.finish('{"ok": true, "message": "Файл изменён."}', True)
            self.assertIn("✓", card.header.text())
            self.assertEqual(card.details.text(), "Файл изменён.")

            # Tool-call groups are collapsed by default.
            self.assertTrue(group.body.isHidden())
            self.assertIn("Вызовы инструментов · 1", group.header.text())
            group.header.click()
            self.assertFalse(group.body.isHidden())
            group.header.click()
            self.assertTrue(group.body.isHidden())
        finally:
            group.deleteLater()
            card.deleteLater()
            self.app.processEvents()

    def test_server_error_offers_continue_and_can_auto_continue(self) -> None:
        from reasonable.ai.agent import AgentEvent
        from reasonable.core.settings import Settings
        from reasonable.editor.chat import AgentErrorBubble, ChatPanel

        settings = Settings(path=self.base / "auto_continue_settings.json")
        settings.set_auto_continue("server", True)
        panel = ChatPanel(self.project, settings)
        sent: list[str] = []
        panel.send = lambda text=None: sent.append(text)
        try:
            panel._on_event(
                AgentEvent(
                    "error",
                    "Ошибка на стороне AI-провайдера (500).",
                    {"error_kind": "server"},
                )
            )
            bubble = panel.stream.itemAt(panel.stream.count() - 2).widget()
            self.assertIsInstance(bubble, AgentErrorBubble)
            self.assertIsNotNone(bubble.auto_check)
            self.assertTrue(bubble.auto_check.isChecked())
            self.assertEqual(bubble.continue_button.text(), "Продолжай")

            bubble.auto_check.setChecked(False)
            self.assertFalse(settings.is_auto_continue_enabled("server"))
            bubble.auto_check.setChecked(True)
            self.assertTrue(settings.is_auto_continue_enabled("server"))

            bubble.continue_button.click()
            self.assertEqual(sent, ["Продолжай"])

            sent.clear()
            panel._on_event(
                AgentEvent(
                    "error",
                    "Ошибка на стороне AI-провайдера (500).",
                    {"error_kind": "server"},
                )
            )
            panel._on_failed("Ошибка на стороне AI-провайдера (500).")
            loop = QEventLoop()
            QTimer.singleShot(200, loop.quit)
            loop.exec()
            self.assertEqual(sent, ["Продолжай"])
        finally:
            settings.data.setdefault("agent", {})["auto_continue_errors"] = []
            panel.deleteLater()
            self.app.processEvents()

    def test_auto_continue_has_no_attempt_limit(self) -> None:
        from unittest import mock

        from reasonable.core.settings import Settings
        from reasonable.editor.chat import ChatPanel

        settings = Settings(path=self.base / "auto_continue_unlimited.json")
        settings.set_auto_continue("server", True)
        panel = ChatPanel(self.project, settings)
        try:
            with mock.patch("reasonable.editor.chat.QTimer.singleShot") as timer:
                for _ in range(15):
                    panel._auto_continue_kind = "server"
                    panel._schedule_auto_continue()
            self.assertEqual(panel._auto_continue_attempts, 15)
            self.assertEqual(timer.call_count, 15)
        finally:
            settings.data.setdefault("agent", {})["auto_continue_errors"] = []
            panel.deleteLater()
            self.app.processEvents()

    def test_chat_panel_switches_between_saved_chats(self) -> None:
        from reasonable.core import chatlog
        from reasonable.core.project import Project, default_manifest
        from reasonable.core.settings import Settings
        from reasonable.editor.chat import ChatPanel

        root = self.base / "multi-chat-project"
        project = Project.create(
            root,
            default_manifest("Chat Test", project_type="game", mode="external"),
            scaffold=False,
        )
        settings = Settings(path=self.base / "multi_chat_settings.json")
        panel = ChatPanel(project, settings)
        try:
            first = chatlog.active_chat_id(root)
            panel.new_chat()
            chats = chatlog.list_chats(root)
            self.assertEqual(len(chats), 2)
            self.assertEqual(panel.chat_combo.count(), 2)
            second = chatlog.active_chat_id(root)
            self.assertNotEqual(first, second)

            index = panel.chat_combo.findData(first)
            panel.chat_combo.setCurrentIndex(index)
            self.app.processEvents()
            self.assertEqual(chatlog.active_chat_id(root), first)
            self.assertTrue(panel.chat_combo.isEnabled())
        finally:
            panel.set_enabled(True)
            panel.deleteLater()
            self.app.processEvents()

    def test_improve_creates_hidden_analysis_chat(self) -> None:
        from reasonable.core import chatlog
        from reasonable.core.project import Project, default_manifest
        from reasonable.core.settings import Settings
        from reasonable.editor.chat import ChatPanel, MessageBubble

        root = self.base / "improve-chat-project"
        project = Project.create(
            root,
            default_manifest("Chat Test", project_type="game", mode="external"),
            scaffold=False,
        )
        settings = Settings(path=self.base / "improve_chat_settings.json")
        panel = ChatPanel(project, settings)
        captured: dict = {}
        panel._ready_to_run = lambda: True
        panel.prepare_run = lambda: True
        panel._start = lambda message, **kwargs: captured.update(message=message, **kwargs)
        try:
            before = len(chatlog.list_chats(root))
            panel.improve_project()
            self.assertEqual(len(chatlog.list_chats(root)), before + 1)
            self.assertTrue(captured.get("hidden"))
            self.assertTrue(captured.get("analysis"))
            self.assertEqual(captured.get("reply_language"), "ru")
            self.assertIn("improvement", captured.get("message", "").lower())
            active = chatlog.active_chat_id(root)
            self.assertEqual(captured.get("chat_id"), active)
            self.assertEqual(
                next(chat["title"] for chat in chatlog.list_chats(root) if chat["id"] == active),
                "Улучшения",
            )

            bubbles = [
                panel.stream.itemAt(index).widget()
                for index in range(panel.stream.count())
            ]
            self.assertFalse(
                any(
                    isinstance(widget, MessageBubble) and widget.role == "user"
                    for widget in bubbles
                )
            )
        finally:
            panel.deleteLater()
            self.app.processEvents()

    def test_sprite_dialog_uses_only_the_external_model(self) -> None:
        from reasonable.editor.assets import GenerateImageDialog

        dialog = GenerateImageDialog(self.project, self.settings)
        self.assertEqual(dialog.provider_combo.count(), 1)
        self.assertEqual(dialog.provider_combo.itemData(0), "openai")
        self.assertEqual(dialog.provider_combo.findData("procedural"), -1)
        dialog.deleteLater()

    def test_convert_dialog_creates_new_project(self) -> None:
        from reasonable.editor.convert_dialog import ConvertDialog

        dialog = ConvertDialog(self.project)
        try:
            self.assertEqual(dialog.target, "android")
            self.assertIn("Платформа", dialog.preview_text.text())
            dialog.name_edit.setText("Тестовая игра Android")
            dialog.folder_edit.setText(str(self.base / "converted"))
            dialog.orientation_combo.setCurrentIndex(2)  # portrait
            dialog._refresh_preview()
            self.assertIn("Android", dialog.preview_text.text())
            dialog._start()
            outcome = wait_for_worker(dialog.worker)
            self.assertTrue(outcome["done"], outcome["error"])
            result = outcome["result"]
            converted = Project.load(result["path"])
            self.assertEqual(converted.platform, "android")
            self.assertEqual(converted.orientation, "portrait")
            self.assertLess(converted.window["width"], converted.window["height"])
            self.assertTrue(dialog.result_card.isVisibleTo(dialog))
            self.assertIsNotNone(dialog.result)
        finally:
            dialog.reject()
            dialog.deleteLater()

    def test_main_window_opens_project(self) -> None:
        from reasonable.editor.main_window import MainWindow

        window = MainWindow()
        window.open_project(self.project.root, focus_agent=True)
        try:
            self.assertIsNotNone(window.current_page)
            page = window.current_page
            self.assertEqual(page.project.name, self.project.name)
            self.assertTrue(page.name_label.text())
            self.assertEqual(len(page.nav_buttons), 4)
            self.assertEqual([button.text() for button in page.nav_buttons], ["Обзор", "ИИ-агент", "Код", "Ассеты"])
            self.assertEqual(page.stack.currentIndex(), 1)
            self.assertIsNotNone(page.chat)
            self.assertIsNone(page.external)
            self.assertTrue(callable(page.chat.prepare_run))
            self.assertIn("·", page.header_model.text())
            self.assertIn("Интерфейс:", page.side_meta.text())
            self.assertNotIn("×", page.side_meta.text())
            self.assertEqual(page.platform_badge.text(), "WINDOWS")
            self.assertEqual(page.convert_button.text(), "Конвертировать…")
            for index in range(4):
                window._show_section(index)
                self.assertEqual(page.stack.currentIndex(), index)
                self.assertTrue(page.nav_buttons[index].isChecked())
        finally:
            window.current_page.shutdown()
            window.close()
            window.deleteLater()

    def test_project_settings_edits_notes_and_keeps_window_to_agent(self) -> None:
        from reasonable.editor.project_settings import ProjectSettingsDialog

        dialog = ProjectSettingsDialog(self.project)
        try:
            self.assertFalse(hasattr(dialog, "prompts_edit"))
            # Window settings are not user-visible: the agent chooses them.
            self.assertFalse(hasattr(dialog, "width_spin"))
            self.assertFalse(hasattr(dialog, "window_mode_combo"))
            dialog.notes_edit.setPlainText("Меню, три уровня и сохранение рекорда.")
            dialog._save()
            project = Project.load(self.project.root)
            self.assertEqual(project.notes, "Меню, три уровня и сохранение рекорда.")
            # The window block survives the save untouched (agent's domain).
            self.assertEqual(project.window["width"], 1280)
            self.assertEqual(project.window["height"], 720)
            self.assertEqual(project.window_mode, "windowed")
            self.assertTrue(project.resizable)
            self.assertNotIn("prompts", project.manifest)
        finally:
            dialog.deleteLater()
            # Restore the shared fixture for the other tests.
            self.project.manifest["notes"] = ""
            self.project.save()


    def test_main_window_deletes_project_from_disk(self) -> None:
        from unittest import mock

        from PySide6.QtWidgets import QMessageBox

        from reasonable.core.project import default_manifest
        from reasonable.editor.main_window import MainWindow

        target = self.base / "deletable-project"
        Project.create(target, default_manifest("Удаляемый проект"), scaffold=False)
        self.settings.touch_recent(target, {"name": "Удаляемый проект", "type": "game"})

        window = MainWindow()
        chosen: dict = {}
        original_add = QMessageBox.addButton

        def add_button(box, *args, **kwargs):
            button = original_add(box, *args, **kwargs)
            if len(args) >= 2 and args[1] == QMessageBox.ButtonRole.DestructiveRole:
                chosen["delete"] = button
            return button

        try:
            with mock.patch.object(QMessageBox, "addButton", add_button), mock.patch.object(
                QMessageBox, "exec", lambda box: 0
            ), mock.patch.object(
                QMessageBox, "clickedButton", lambda box: chosen.get("delete")
            ):
                window.delete_project(target)
            self.assertFalse(target.exists())
            reloaded = Settings(path=self.settings.path)
            self.assertNotIn(
                str(target.resolve()).lower(),
                {str(Path(item["path"]).resolve()).lower() for item in reloaded.data["recent_projects"]},
            )
        finally:
            window.close()
            window.deleteLater()

    def test_delete_is_blocked_for_install_root(self) -> None:
        from reasonable.core.paths import install_root
        from reasonable.editor.main_window import MainWindow

        self.assertTrue(MainWindow._unsafe_delete_target(install_root()))
        self.assertTrue(MainWindow._unsafe_delete_target(Path.home()))
        self.assertFalse(MainWindow._unsafe_delete_target(self.base / "some-project"))


if __name__ == "__main__":
    unittest.main()
