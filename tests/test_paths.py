import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from reasonable.core.paths import (
    atomic_write_json,
    atomic_write_text,
    read_json,
    rel_to,
    slugify,
    unique_directory,
)


class PathsTests(unittest.TestCase):
    def test_slugify_transliterates_cyrillic(self) -> None:
        self.assertEqual(slugify("Космический кот"), "kosmicheskii-kot")
        self.assertEqual(slugify("Умный планировщик"), "umnyi-planirovschik")
        self.assertEqual(slugify("  ...  "), "project")

    def test_slugify_is_filesystem_friendly(self) -> None:
        value = slugify("Игра: 100% круто!")
        self.assertEqual(value, "igra-100-kruto")
        self.assertNotIn(" ", value)
        self.assertNotIn(":", value)

    def test_unique_directory_increments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            (parent / "game").mkdir()
            (parent / "game-2").mkdir()
            self.assertEqual(unique_directory(parent, "game"), parent / "game-3")

    def test_atomic_json_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "data.json"
            payload = {"имя": "Кот", "items": [1, 2, 3]}
            atomic_write_json(path, payload)
            self.assertEqual(read_json(path), payload)
            atomic_write_text(path.with_suffix(".txt"), "привет")
            self.assertEqual(path.with_suffix(".txt").read_text(encoding="utf-8"), "привет")

    def test_read_json_returns_default_for_broken_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.json"
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(read_json(path, {"fallback": True}), {"fallback": True})

    def test_rel_to_uses_forward_slashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / "assets" / "sprite.png"
            nested.parent.mkdir()
            nested.write_bytes(b"x")
            self.assertEqual(rel_to(nested, root), "assets/sprite.png")

    def test_bundled_python_honors_reasonable_python(self) -> None:
        from reasonable.core.paths import bundled_python

        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "python.exe"
            exe.write_bytes(b"x")
            with mock.patch.dict(os.environ, {"REASONABLE_PYTHON": str(exe)}):
                self.assertEqual(bundled_python(), exe)

    def test_project_launch_command_prefers_player_when_frozen(self) -> None:
        from reasonable.core import paths

        with tempfile.TemporaryDirectory() as tmp:
            player = Path(tmp) / "ReasonablePlayer.exe"
            player.write_bytes(b"x")
            with mock.patch.object(paths, "is_frozen", return_value=True), mock.patch.object(
                paths, "player_executable", return_value=player
            ):
                command = paths.project_launch_command(Path(tmp) / "main.py")
                self.assertEqual(command[0], str(player))
                self.assertTrue(command[1].endswith("main.py"))

    def test_project_launch_command_uses_python_in_source_checkout(self) -> None:
        from reasonable.core import paths

        with mock.patch.object(paths, "is_frozen", return_value=False):
            command = paths.project_launch_command("main.py")
            self.assertTrue(command[0])
            self.assertEqual(command[-1], "main.py")
            self.assertNotIn("ReasonablePlayer.exe", command[0])

    def test_default_projects_dir_inside_install_root(self) -> None:
        from reasonable.core import paths

        with tempfile.TemporaryDirectory() as tmp:
            install = Path(tmp) / "engine"
            with mock.patch.object(paths, "install_root", return_value=install):
                with mock.patch.dict(os.environ, {}, clear=True):
                    self.assertEqual(paths.default_projects_dir(), install / "Projects")


if __name__ == "__main__":
    unittest.main()
