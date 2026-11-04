"""Tests for the interactive, sequential first-run quick start."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication

    PYSIDE_AVAILABLE = True
except ImportError:  # pragma: no cover - editor is optional for headless CI
    PYSIDE_AVAILABLE = False

from reasonable.core.settings import Settings


class TutorialSettingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "settings.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_first_launch_is_not_seen_and_can_be_reset(self) -> None:
        settings = Settings(path=self.path)
        self.assertFalse(settings.tutorial_seen())
        settings.mark_tutorial_seen()
        self.assertTrue(Settings(path=self.path).tutorial_seen())
        settings.reset_tutorial()
        self.assertFalse(Settings(path=self.path).tutorial_seen())


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
class TutorialDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "settings.json"
        self.settings = Settings(path=self.path)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _dialog(self):
        from reasonable.editor.tutorial import TutorialDialog

        return TutorialDialog(self.settings)

    def _finish_all_steps(self, dialog) -> None:
        dialog._choose_project("ai")
        dialog.next()
        dialog._fill_task("Добавь меню и три уровня")
        dialog._submit_task()
        dialog.next()
        for index in range(5):
            dialog._visit_section(index)
        dialog.next()
        dialog._run_preview()
        dialog.next()
        dialog._undo_preview()
        dialog.next()
        dialog._choose_export("exe")
        dialog._export_preview()

    # ------------------------------------------------------------------
    def test_steps_are_sequential_and_cannot_be_skipped(self) -> None:
        dialog = self._dialog()
        self.assertEqual(len(dialog._step_buttons), 6)
        self.assertEqual(dialog.index, 0)
        self.assertFalse(dialog.back_button.isEnabled())
        self.assertFalse(dialog.next_button.isEnabled())
        # Future steps are locked, so the rail cannot be used to jump ahead.
        self.assertFalse(dialog._step_buttons[1].isEnabled())
        self.assertFalse(dialog._step_buttons[5].isEnabled())

        dialog.next()
        self.assertEqual(dialog.index, 0)
        dialog.go_to(5)
        self.assertEqual(dialog.index, 0)

        dialog._choose_project("ai")
        self.assertTrue(dialog.completed[0])
        self.assertTrue(dialog.next_button.isEnabled())
        dialog.next()
        self.assertEqual(dialog.index, 1)
        self.assertEqual(dialog.max_reached, 1)
        self.assertTrue(dialog.back_button.isEnabled())
        self.assertFalse(dialog._step_buttons[2].isEnabled())

        dialog.back()
        self.assertEqual(dialog.index, 0)

    def test_every_step_requires_its_action_then_unlocks_the_next(self) -> None:
        dialog = self._dialog()

        dialog._choose_project("blank")
        self.assertTrue(dialog.completed[0])
        dialog.next()
        self.assertEqual(dialog.index, 1)

        dialog._submit_task()  # empty input must not unlock the step
        self.assertFalse(dialog.completed[1])
        dialog._fill_task("Сделай экран статистики")
        dialog._submit_task()
        self.assertTrue(dialog.completed[1])
        dialog.next()
        self.assertEqual(dialog.index, 2)

        dialog._visit_section(1)  # out of order, ignored
        self.assertEqual(dialog.step3_visited, [])
        for index in range(5):
            dialog._visit_section(index)
        self.assertTrue(dialog.completed[2])
        dialog.next()
        self.assertEqual(dialog.index, 3)

        dialog._run_preview()
        self.assertTrue(dialog.completed[3])
        dialog.next()
        self.assertEqual(dialog.index, 4)

        dialog._undo_preview()
        self.assertTrue(dialog.completed[4])
        dialog.next()
        self.assertEqual(dialog.index, 5)
        self.assertEqual(dialog.next_button.text(), "Готово")

        dialog._choose_export("android")
        dialog._export_preview()
        self.assertTrue(dialog.completed[5])
        dialog.next()
        self.assertTrue(self.settings.tutorial_seen())

    def test_final_button_can_start_a_real_project(self) -> None:
        from reasonable.editor.tutorial import maybe_show_tutorial

        dialog = self._dialog()
        self._finish_all_steps(dialog)
        dialog._launch_new_project()
        self.assertEqual(dialog.launch_action, "new_project")
        self.assertTrue(self.settings.tutorial_seen())
        # The seen flag is honoured by the automatic first-launch path.
        self.assertEqual(maybe_show_tutorial(self.settings), "")

    def test_replay_button_exists_on_the_welcome_page(self) -> None:
        from PySide6.QtWidgets import QPushButton

        from reasonable.editor.welcome import WelcomePage

        page = WelcomePage(self.settings)
        texts = [button.text() for button in page.findChildren(QPushButton)]
        self.assertIn("Обучение", texts)


if __name__ == "__main__":
    unittest.main()
