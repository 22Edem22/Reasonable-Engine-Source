import tempfile
import unittest
from pathlib import Path

from reasonable.core.convert import convert_project
from reasonable.core.progress import read_events, read_state, set_plan, set_progress
from reasonable.core.project import Project, default_manifest


class ConvertTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls._tmp.name)
        cls.source = Project.create(
            cls.base / "source",
            default_manifest(
                "Звёздный кот",
                project_type="game",
                mode="builtin",
                goal="Кот собирает звёзды",
                notes="Меню, три уровня и сохранение рекорда.",
                width=1280,
                height=720,
                orientation="landscape",
            ),
        )
        set_plan(cls.source.root, ["Меню", "Игровой цикл", "Проверить сборку"])
        set_progress(cls.source.root, 42, stage="Игровой цикл", message="Меню готово")
        (cls.source.root / "dist" / "old-export").mkdir(parents=True)
        (cls.source.root / "dist" / "old-export" / "Play.bat").write_text("old", encoding="utf-8")
        (cls.source.root / "__pycache__").mkdir()
        (cls.source.root / "__pycache__" / "junk.pyc").write_bytes(b"junk")
        (cls.source.root / "_engine" / "reasonable" / "old-marker.txt").write_text(
            "old engine", encoding="utf-8"
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_windows_to_android_creates_new_project(self) -> None:
        result = convert_project(
            self.source,
            "android",
            name="Космический кот Android",
            output=self.base / "out",
            orientation="portrait",
        )
        self.assertTrue(result["ok"])
        target = Project.load(result["path"])
        self.assertNotEqual(target.root, self.source.root)
        self.assertEqual(target.platform, "android")
        self.assertEqual(target.name, "Космический кот Android")
        self.assertEqual(target.orientation, "portrait")
        self.assertLess(target.window["width"], target.window["height"])
        self.assertEqual(target.android["package"], "org.reasonable.kosmicheskiikotandroid")
        self.assertTrue(target.has_vendored_engine())
        self.assertTrue((target.root / "CONVERSION.md").is_file())
        self.assertTrue((target.root / "AGENT_GUIDE.md").is_file())
        guide = (target.root / "AGENT_GUIDE.md").read_text(encoding="utf-8")
        # The external agent guide is English-only by design.
        self.assertIn("**Platform:** Android", guide)
        self.assertIn("Converted from", guide)
        main = (target.root / "main.py").read_text(encoding="utf-8")
        self.assertIn(repr(target.name), main)
        readme = (target.root / "README.md").read_text(encoding="utf-8")
        self.assertTrue(readme.startswith(f"# {target.name}"))
        self.assertEqual(target.manifest["converted_from"]["platform"], "windows")
        self.assertEqual(target.manifest["conversions"][-1]["to"]["platform"], "android")

        state = read_state(target.root)
        self.assertEqual(state["percent"], 42.0)
        events = read_events(target.root)
        self.assertTrue(any(event.get("type") == "conversion" for event in events))
        self.assertFalse((target.root / "dist").exists())
        self.assertFalse((target.root / "__pycache__").exists())
        self.assertFalse((target.root / "_engine" / "reasonable" / "old-marker.txt").exists())

        # The source project is never mutated.
        self.assertEqual(self.source.name, "Звёздный кот")
        self.assertEqual(self.source.platform, "windows")
        self.assertEqual(read_state(self.source.root)["percent"], 42.0)
        self.assertTrue((self.source.root / "dist" / "old-export" / "Play.bat").is_file())
        self.assertTrue((self.source.root / "_engine" / "reasonable" / "old-marker.txt").is_file())

    def test_android_to_windows_and_external_agent(self) -> None:
        android = convert_project(
            self.source,
            "android",
            name="Кот в телефоне",
            output=self.base / "android",
            orientation="portrait",
        )
        source = Project.load(android["path"])
        result = convert_project(
            source,
            "windows",
            name="Кот на Windows",
            output=self.base / "windows",
            orientation="landscape",
            mode="external",
            window_mode="fullscreen",
            resizable=False,
            width=1920,
            height=1080,
        )
        target = Project.load(result["path"])
        self.assertEqual(target.platform, "windows")
        self.assertEqual(target.orientation, "landscape")
        self.assertEqual(target.mode, "external")
        self.assertTrue(target.fullscreen)
        self.assertFalse(target.resizable)
        self.assertEqual((target.window["width"], target.window["height"]), (1920, 1080))
        self.assertEqual(target.android["package"], "org.reasonable.kotnawindows")
        self.assertEqual(read_state(target.root)["mode"], "external")
        self.assertEqual(read_state(target.root)["percent"], 42.0)
        guide = (target.root / "AGENT_GUIDE.md").read_text(encoding="utf-8")
        self.assertIn("режим: внешний агент", guide)
        self.assertIn("Платформа:** Windows", guide)
        changes = "\n".join(result["changes"])
        self.assertIn("Windows", changes)
        self.assertIn("внешний агент", changes)
        self.assertIn("полный экран", changes)

    def test_same_project_without_changes_is_rejected(self) -> None:
        before = set((self.base / "out").iterdir()) if (self.base / "out").exists() else set()
        with self.assertRaises(ValueError):
            convert_project(self.source, "windows")
        after = set((self.base / "out").iterdir()) if (self.base / "out").exists() else set()
        self.assertEqual(before, after)

    def test_reset_progress_creates_clean_plan(self) -> None:
        result = convert_project(
            self.source,
            "windows",
            name="Кот чистовой",
            output=self.base / "fresh",
            reset_progress=True,
        )
        target = Project.load(result["path"])
        state = read_state(target.root)
        self.assertEqual(state["percent"], 0)
        self.assertEqual(state["status"], "idle")
        self.assertEqual(len(state["tasks"]), 4)
        events = read_events(target.root)
        self.assertTrue(any(event.get("type") == "conversion" for event in events))
        self.assertFalse(any(event.get("message") == "Меню готово" for event in events))

    def test_output_inside_source_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            convert_project(self.source, "android", output=self.source.root)
        self.assertFalse(any(child.is_dir() and child.name == "zvyozdnyy-kot" for child in self.source.root.iterdir()))

    def test_conversion_plan_reports_changes(self) -> None:
        from reasonable.core.convert import conversion_plan

        plan = conversion_plan(
            self.source,
            "android",
            name="Новый кот",
            output=self.base / "plans",
            orientation="portrait",
        )
        self.assertTrue(plan["has_changes"])
        self.assertEqual(plan["target"], "android")
        self.assertEqual(plan["target_name"], "Новый кот")
        self.assertLess(plan["width"], plan["height"])
        self.assertTrue(any(change.startswith("Платформа:") for change in plan["changes"]))
        self.assertFalse(plan["target_root"].exists())


if __name__ == "__main__":
    unittest.main()
