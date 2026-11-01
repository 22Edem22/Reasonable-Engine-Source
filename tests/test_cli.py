import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from reasonable.core.progress import read_state
from reasonable.core.project import Project, default_manifest

ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls._tmp.name)
        cls.project = Project.create(
            cls.base / "cli-project",
            default_manifest("CLI проект", project_type="app", mode="external", goal="Проверка команд"),
            scaffold=False,
        )
        (cls.project.root / "assets").mkdir()
        (cls.project.root / "progress").mkdir()
        (cls.project.root / "main.py").write_text("print('cli')\n", encoding="utf-8")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def cli(self, *args: str) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONPATH"] = str(ROOT)
        return subprocess.run(
            [sys.executable, "-m", "reasonable.cli", "--project", str(self.project.root), *args],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )

    def test_status(self) -> None:
        result = self.cli("status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CLI проект", result.stdout)
        self.assertIn("external", result.stdout)

    def test_progress_and_plan(self) -> None:
        result = self.cli("plan", "Сделать меню", "Добавить экран", "Проверить")
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.cli("progress", "35", "Меню готово", "--stage", "Меню")
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.cli("task", "t2", "done")
        self.assertEqual(result.returncode, 0, result.stderr)
        state = read_state(self.project.root)
        self.assertEqual(state["percent"], 35.0)
        self.assertEqual(state["stage"], "Меню")
        self.assertEqual(state["tasks"][1]["status"], "done")

    def test_validate_and_version(self) -> None:
        result = self.cli("validate")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = self.cli("version")
        self.assertEqual(result.returncode, 0)
        self.assertIn("Reasonable Engine", result.stdout)

    def test_help_and_version_flag(self) -> None:
        # Regression: a literal % in a subparser help crashed print_help().
        result = self.cli("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage:", result.stdout)
        self.assertIn("100%", result.stdout)
        result = self.cli("--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Reasonable Engine", result.stdout)

    def test_convert_creates_new_project(self) -> None:
        import json

        target = self.base / "converted"
        target.mkdir()
        result = self.cli(
            "convert",
            "--to",
            "android",
            "--name",
            "CLI Android",
            "--dir",
            str(target),
            "--orientation",
            "portrait",
            "--json",
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["platform"], "android")
        converted = Project.load(payload["path"])
        self.assertEqual(converted.name, "CLI Android")
        self.assertEqual(converted.platform, "android")
        self.assertEqual(converted.orientation, "portrait")
        self.assertTrue((converted.root / "CONVERSION.md").is_file())
        self.assertEqual(Project.load(self.project.root).platform, "windows")

    def test_json_output_is_valid(self) -> None:
        import json

        result = self.cli("status", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["project"]["name"], "CLI проект")
        self.assertIn("progress", payload)

    def test_init_accepts_notes_and_window_flags(self) -> None:
        from reasonable.core.paths import slugify

        target = self.base / "cli-init"
        target.mkdir()
        result = self.cli(
            "init",
            "--name",
            "CLI новая игра",
            "--goal",
            "Кот в космосе",
            "--notes",
            "Меню и два уровня",
            "--mode",
            "external",
            "--window-mode",
            "fullscreen",
            "--fixed-size",
            "--width",
            "1024",
            "--height",
            "600",
            "--dir",
            str(target),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        root = target / slugify("CLI новая игра", "project")
        project = Project.load(root)
        self.assertEqual(project.notes, "Меню и два уровня")
        self.assertEqual(project.window_mode, "fullscreen")
        self.assertTrue(project.fullscreen)
        self.assertFalse(project.resizable)
        self.assertEqual(project.window["width"], 1024)
        self.assertEqual(project.window["height"], 600)
        self.assertTrue((root / "AGENT_GUIDE.md").is_file())


if __name__ == "__main__":
    unittest.main()
