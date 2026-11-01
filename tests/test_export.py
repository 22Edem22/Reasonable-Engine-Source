import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from reasonable.core.project import Project, default_manifest
from reasonable.export import export_android, export_windows


class ExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls._tmp.name)
        cls.project = Project.create(
            cls.base / "project",
            default_manifest(
                "Экспортный кот",
                project_type="game",
                mode="builtin",
                goal="Проверка экспорта",
            ),
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_windows_folder_export_runs(self) -> None:
        result = export_windows(self.project, self.base / "win")
        target = Path(result["path"])
        self.assertTrue(result["ok"])
        self.assertTrue(target.is_dir())
        self.assertTrue((target / "Play.bat").is_file())
        self.assertTrue((target / "README_WINDOWS.txt").is_file())
        self.assertTrue((target / "assets" / "icon.png").is_file())
        self.assertTrue((target / "_engine" / "reasonable" / "runtime" / "app.py").is_file())
        self.assertTrue((target / "config.json").is_file())
        self.assertFalse((target / "progress" / "state.json").read_text(encoding="utf-8") == "")

        env = dict(os.environ)
        env["PYTHONPATH"] = str(target / "_engine") + os.pathsep + str(target)
        env.update(
            {
                "SDL_VIDEODRIVER": "dummy",
                "SDL_AUDIODRIVER": "dummy",
                "RE_SKIP_SPLASH": "1",
                "RE_FRAMES": "4",
            }
        )
        run = subprocess.run(
            [sys.executable, "main.py"],
            cwd=str(target),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
        )
        self.assertEqual(run.returncode, 0, run.stderr[-2000:])

    def test_windows_export_does_not_overwrite_foreign_folder(self) -> None:
        foreign = self.base / "foreign"
        foreign.mkdir()
        (foreign / "keep.txt").write_text("не трогать", encoding="utf-8")
        result = export_windows(self.project, foreign)
        self.assertNotEqual(Path(result["path"]), foreign)
        self.assertTrue((foreign / "keep.txt").is_file())

    def test_android_package_and_instructions(self) -> None:
        result = export_android(self.project, self.base / "android.zip")
        self.assertTrue(result["ok"])
        archive = Path(result["zip"])
        self.assertTrue(archive.is_file())
        self.assertGreater(archive.stat().st_size, 1000)
        with zipfile.ZipFile(archive) as zf:
            names = set(zf.namelist())
            root = archive.stem
            self.assertIn(f"{root}/buildozer.spec", names)
            self.assertIn(f"{root}/main.py", names)
            self.assertIn(f"{root}/README_ANDROID.md", names)
            self.assertIn(f"{root}/assets/icon.png", names)
            self.assertIn(f"{root}/_engine/reasonable/runtime/app.py", names)
            spec = zf.read(f"{root}/buildozer.spec").decode("utf-8")
        self.assertIn("requirements = python3,pygame", spec)
        self.assertIn("android.api = 34", spec)
        self.assertIn("orientation = landscape", spec)
        self.assertIn("android.archs = arm64-v8a, armeabi-v7a", spec)

    def test_android_export_has_github_workflow(self) -> None:
        result = export_android(self.project, self.base / "android-actions.zip", zip_result=False)
        target = Path(result["path"])
        workflow = target / ".github" / "workflows" / "android.yml"
        self.assertTrue(workflow.is_file())
        self.assertIn("buildozer -v android debug", workflow.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
