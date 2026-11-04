"""The welcome intro must not clip its heading or caption on small windows."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication, QLabel

    PYSIDE_AVAILABLE = True
except ImportError:  # pragma: no cover - editor is optional for headless CI
    PYSIDE_AVAILABLE = False

from reasonable.core import i18n
from reasonable.core.settings import Settings


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
class WelcomeLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        i18n.set_override("ru")
        self.settings = Settings(path=Path(self._tmp.name) / "settings.json")

    def tearDown(self) -> None:
        i18n.set_override(None)
        self._tmp.cleanup()

    def test_intro_keeps_both_heading_lines_and_the_caption(self) -> None:
        from reasonable.editor import theme
        from reasonable.editor.welcome import WelcomePage

        theme.apply_theme(self.app)
        page = WelcomePage(self.settings)
        page.resize(1120, 750)
        page.show()
        self.app.processEvents()

        heading = next(
            label
            for label in page.findChildren(QLabel)
            if label.text().startswith("Создайте")
        )
        caption = next(
            label
            for label in page.findChildren(QLabel)
            if label.text().startswith("Три пути")
        )
        parent = heading.parentWidget()
        self.assertIsNotNone(parent)
        # The heading needs two lines; the layout used to allocate one.
        self.assertGreaterEqual(
            heading.height(), heading.minimumSizeHint().height()
        )
        self.assertIn("\n", heading.text())
        # The caption has three short lines; make sure all of them fit.
        self.assertGreaterEqual(
            caption.height(),
            caption.fontMetrics().lineSpacing() * 3,
        )
        # And the whole intro column keeps its full height.
        self.assertGreaterEqual(parent.height(), 120)
        page.close()
        page.deleteLater()

    def test_footer_shortens_the_path_in_a_narrow_window(self) -> None:
        from reasonable.editor.welcome import WelcomePage

        page = WelcomePage(self.settings)
        page.resize(1120, 750)
        page.show()
        self.app.processEvents()
        folder = page._footer_folder
        self.assertNotIn("Desktop", folder.text())
        self.assertIn("Projects", folder.text())

        page.resize(1560, 920)
        self.app.processEvents()
        self.assertIn(str(self.settings.projects_dir()), folder.text())
        page.close()
        page.deleteLater()


if __name__ == "__main__":
    unittest.main()
