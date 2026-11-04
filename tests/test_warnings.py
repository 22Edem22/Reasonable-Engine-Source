"""The engine suppresses pygame's obsolete pkg_resources deprecation warning."""

from __future__ import annotations

import subprocess
import sys
import unittest


class WarningFilterTests(unittest.TestCase):
    def test_pkg_resources_warning_is_filtered_before_pygame_import(self) -> None:
        code = "import reasonable; import pygame; print('ok')"
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        self.assertNotIn("pkg_resources is deprecated as an API", result.stderr)
        self.assertIn("ok", result.stdout)


if __name__ == "__main__":
    unittest.main()
