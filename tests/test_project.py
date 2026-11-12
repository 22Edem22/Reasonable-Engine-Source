import json
import os
import tempfile
import unittest
from pathlib import Path

from reasonable.core.project import Project, default_manifest


class ProjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "Мой проект"
        self.root.mkdir(parents=True)
        self.project = Project.create(
            self.root,
            default_manifest(
                "Мой проект",
                project_type="game",
                mode="external",
                goal="Кот собирает звёзды",
                notes="Три уровня и сохранение",
                width=720,
                height=1280,
                window_mode="fullscreen",
                resizable=False,
                orientation="portrait",
            ),
            scaffold=False,
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_game_entry_without_launch_code_is_an_error(self) -> None:
        (self.root / "main.py").write_text(
            "def main():\n    print('never called')\n", encoding="utf-8"
        )
        self.assertFalse(self.project.has_launch_block())
        issues = self.project.validate()
        self.assertTrue(
            any(
                issue.level == "error" and issue.path.endswith("main.py")
                for issue in issues
            )
        )

    def test_game_entry_with_main_guard_has_launch_code(self) -> None:
        (self.root / "main.py").write_text(
            "def main():\n    print('ok')\n\n"
            "if __name__ == \"__main__\":\n    main()\n",
            encoding="utf-8",
        )
        self.assertTrue(self.project.has_launch_block())
        self.assertFalse(
            any(
                issue.level == "error" and issue.path.endswith("main.py")
                for issue in self.project.validate()
            )
        )

    def test_missing_requirement_is_reported(self) -> None:
        (self.root / "requirements.txt").write_text(
            "definitely-not-installed-package-xyz>=1\n", encoding="utf-8"
        )
        issues = self.project.validate()
        self.assertTrue(
            any(
                issue.level == "warning"
                and issue.path == "requirements.txt"
                for issue in issues
            )
        )

    def test_site_and_other_types_are_kept(self) -> None:
        for kind in ("site", "other"):
            root = self.root.parent / kind
            root.mkdir()
            project = Project.create(
                root,
                default_manifest(kind, project_type=kind),
                scaffold=False,
            )
            self.assertEqual(project.project_type, kind)
            self.assertIn("Python", project.summary())


        manifest = self.project.manifest
        self.assertEqual(manifest["format"], 1)
        self.assertEqual(manifest["name"], "Мой проект")
        self.assertEqual(self.project.project_type, "game")
        self.assertEqual(self.project.mode, "external")
        self.assertEqual(self.project.goal, "Кот собирает звёзды")
        self.assertEqual(self.project.notes, "Три уровня и сохранение")
        self.assertEqual(self.project.window["width"], 720)
        self.assertEqual(self.project.window_mode, "fullscreen")
        self.assertTrue(self.project.fullscreen)
        self.assertFalse(self.project.resizable)
        self.assertEqual(manifest["orientation"], "portrait")
        self.assertEqual(manifest["android"]["orientation"], "portrait")
        self.assertTrue(manifest["splash"])
        self.assertTrue(manifest["android"]["package"].startswith("org.reasonable."))

    def test_legacy_prompts_are_read_as_notes(self) -> None:
        data = default_manifest("Старый проект")
        data.pop("notes", None)
        data["prompts"] = "Формат прошлых версий"
        legacy_root = Path(self._tmp.name) / "legacy"
        legacy_root.mkdir()
        (legacy_root / "project.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        loaded = Project.load(legacy_root)
        self.assertEqual(loaded.notes, "Формат прошлых версий")

    def test_load_and_save(self) -> None:
        self.project.save()
        loaded = Project.load(self.root)
        self.assertEqual(loaded.name, self.project.name)
        self.assertEqual(loaded.mode, "external")
        self.assertTrue(Project.is_project(self.root))

    def test_safe_writes_stay_inside_project(self) -> None:
        self.project.write_text("src/game.py", "print('ok')\n")
        self.assertEqual((self.root / "src" / "game.py").read_text(encoding="utf-8"), "print('ok')\n")
        with self.assertRaises(ValueError):
            self.project.write_text("../outside.py", "bad")
        with self.assertRaises(ValueError):
            self.project.read_text("../../secret.txt")

    def test_list_tree_skips_engine_and_cache(self) -> None:
        (self.root / "_engine" / "reasonable").mkdir(parents=True)
        (self.root / "_engine" / "reasonable" / "x.py").write_text("x = 1", encoding="utf-8")
        (self.root / "__pycache__").mkdir()
        (self.root / "__pycache__" / "x.pyc").write_bytes(b"x")
        (self.root / "main.py").write_text("print('x')", encoding="utf-8")
        paths = [row["path"] for row in self.project.list_tree()]
        self.assertIn("main.py", paths)
        self.assertNotIn("_engine/reasonable/x.py", paths)
        self.assertNotIn("__pycache__/x.pyc", paths)

    def test_validate_detects_broken_syntax_and_missing_entry(self) -> None:
        (self.root / "main.py").write_text("def broken(:\n", encoding="utf-8")
        (self.root / "assets").mkdir()
        (self.root / "progress").mkdir()
        problems = self.project.validate()
        errors = [issue for issue in problems if issue.level == "error"]
        self.assertTrue(any("синтаксис" in issue.message.lower() for issue in errors), errors)
        (self.root / "main.py").unlink()
        problems = self.project.validate()
        self.assertTrue(any("точки входа" in issue.message.lower() for issue in problems))

    def test_run_env_includes_project_and_engine(self) -> None:
        env = self.project.run_env()
        paths = env["PYTHONPATH"].split(os.pathsep)
        self.assertEqual(paths[0], str(self.root / "_engine"))
        self.assertEqual(paths[1], str(self.root))
        self.assertEqual(self.project.run_command()[-1], str(self.root / "main.py"))

    def test_splash_wrapper_runs_through_the_engine_launcher(self) -> None:
        (self.root / "_engine" / "reasonable").mkdir(parents=True, exist_ok=True)
        command = self.project.run_command(splash_wrapper=True)
        self.assertIn("-m", command)
        self.assertIn("reasonable.runtime.launch", command)
        self.assertEqual(command[-1], str(self.root / "main.py"))


if __name__ == "__main__":
    unittest.main()
