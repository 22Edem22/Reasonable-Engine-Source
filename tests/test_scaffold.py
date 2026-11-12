import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from reasonable.core.project import Project, default_manifest


def _run_project(project: Project, frames: int = 4) -> subprocess.CompletedProcess:
    env = project.run_env()
    env.update(
        {
            "SDL_VIDEODRIVER": "dummy",
            "SDL_AUDIODRIVER": "dummy",
            "RE_FRAMES": str(frames),
        }
    )
    return subprocess.run(
        [sys.executable, str(project.entry)],
        cwd=str(project.root),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
    )


class ScaffoldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls._tmp.name)
        cls.game = Project.create(
            cls.base / "game",
            default_manifest(
                "Звёздный кот",
                project_type="game",
                mode="builtin",
                goal="Кот собирает звёзды и убегает от слизней",
                notes="Три уровня, меню, пауза, сохранение рекорда.",
            ),
        )
        cls.app = Project.create(
            cls.base / "app",
            default_manifest(
                "Планировщик",
                project_type="app",
                mode="external",
                goal="Планировщик задач с ИИ-помощником",
                notes="Задачи, дедлайны, статистика и чат.",
                width=720,
                height=1280,
                orientation="portrait",
            ),
        )
        cls.site = Project.create(
            cls.base / "site",
            default_manifest(
                "Лендинг",
                project_type="site",
                mode="builtin",
                goal="Лендинг студии",
                template="site",
            ),
        )
        cls.other = Project.create(
            cls.base / "other",
            default_manifest(
                "Утилита",
                project_type="other",
                mode="builtin",
                goal="Полезная утилита",
                template="other",
            ),
        )
        cls.blank = Project.create(
            cls.base / "blank",
            default_manifest("Пустой проект", template="blank"),
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_project_is_self_contained(self) -> None:
        for project in (self.game, self.app):
            self.assertTrue((project.root / "main.py").is_file())
            self.assertTrue((project.root / "project.json").is_file())
            self.assertTrue((project.root / "_engine" / "reasonable" / "runtime" / "app.py").is_file())
            self.assertTrue((project.root / "assets" / "icon.png").is_file())
            self.assertTrue((project.root / "assets" / "background.png").is_file())
            self.assertTrue((project.root / "assets" / "sprites" / "player.png").is_file())
            self.assertTrue((project.root / "run.bat").is_file())
            self.assertTrue((project.root / "run.sh").is_file())
            self.assertTrue((project.root / "re.bat").is_file())
            self.assertTrue((project.root / "README.md").is_file())
            self.assertTrue(project.has_vendored_engine())

    def test_game_project_ships_an_editable_starter_scene(self) -> None:
        from reasonable.core.scene import list_scenes, load_scene

        scenes = list_scenes(self.game.root)
        self.assertEqual(scenes[0]["id"], "main")
        scene = load_scene(self.game.root, "main")
        self.assertEqual(scene["size"], [1280, 720])
        self.assertGreaterEqual(len(scene["objects"]), 10)
        roles = {str(item.get("role")) for item in scene["objects"] if item.get("marker")}
        self.assertIn("player", roles)
        self.assertIn("star", roles)
        self.assertIn("slime", roles)

    def test_app_project_ships_an_editable_ui_scene(self) -> None:
        from reasonable.core.scene import load_scene

        scene = load_scene(self.app.root, "main")
        self.assertEqual(scene.get("template"), "app")
        self.assertGreaterEqual(len(scene["objects"]), 15)
        kinds = {str(item.get("kind")) for item in scene["objects"]}
        self.assertIn("panel", kinds)
        self.assertIn("text", kinds)

    def test_agent_pack_is_complete(self) -> None:
        for project, type_skill in (
            (self.game, "game-development.md"),
            (self.app, "app-development.md"),
        ):
            self.assertTrue((project.root / "AGENT_GUIDE.md").is_file())
            self.assertTrue((project.root / "AGENTS.md").is_file())
            self.assertTrue((project.root / "CLAUDE.md").is_file())
            # Base skills plus the type-specific skill; skills for other
            # interface levels must not leak in (no garbage in the pack).
            self.assertTrue((project.root / "skills" / type_skill).is_file())
            self.assertTrue((project.root / "skills" / "engine-basics.md").is_file())
            self.assertTrue((project.root / "skills" / "ui-standard-widgets.md").is_file())
            self.assertTrue((project.root / "skills" / "progress-and-handoff.md").is_file())
            self.assertFalse((project.root / "skills" / "ui-simple-tkinter.md").is_file())
            self.assertTrue((project.root / ".cursor" / "rules" / "reasonable-engine.mdc").is_file())
            guide = (project.root / "AGENT_GUIDE.md").read_text(encoding="utf-8")
            self.assertIn("re.bat progress", guide)
            self.assertIn("_engine", guide)

    def test_external_project_has_live_progress_state(self) -> None:
        from reasonable.core.progress import read_state

        state = read_state(self.app.root)
        self.assertEqual(state["mode"], "external")
        self.assertEqual(len(state["tasks"]), 5)
        self.assertTrue((self.app.root / "progress" / "events.jsonl").is_file())

    def test_launchers_use_vendored_engine(self) -> None:
        for name in ("run.bat", "re.bat"):
            text = (self.game.root / name).read_text(encoding="utf-8")
            self.assertIn("_engine", text)
            self.assertIn("chcp 65001", text)
            self.assertIn("REASONABLE_PYTHON", text)
            self.assertIn("python.exe", text)
            # The installed layout keeps Python in runtime\python.
            self.assertIn("..\\..\\runtime\\python\\python.exe", text)
            # %~dp0 ends with a backslash; quoting it directly would escape the
            # closing quote and swallow the following CLI arguments.
            self.assertIn('set "ROOT=%HERE:~0,-1%"', text)
            self.assertNotIn('--project "%HERE%"', text)
            self.assertNotIn('cd /d "%HERE%"', text)
        re_text = (self.game.root / "re.bat").read_text(encoding="utf-8")
        self.assertIn('--project "%ROOT%"', re_text)
        run_text = (self.game.root / "run.bat").read_text(encoding="utf-8")
        self.assertIn('cd /d "%ROOT%"', run_text)
        readme = (self.game.root / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("RE_SKIP_SPLASH", readme)
        self.assertIn("Android", readme)
        self.assertIn("ИИ-агент", readme)
        self.assertIn("F11", readme)
        self.assertIn("Три уровня", readme)
        self.assertNotIn("Основные промпты", readme)
        gitignore = (self.game.root / ".gitignore").read_text(encoding="utf-8")
        self.assertNotIn("*.spec", gitignore, "buildozer.spec must not be ignored")

    def test_templates_read_window_settings_from_manifest(self) -> None:
        manifest_path = self.game.root / "project.json"
        original = manifest_path.read_text(encoding="utf-8")
        try:
            data = json.loads(original)
            data["window"].update(
                {"width": 900, "height": 600, "mode": "fullscreen", "resizable": False}
            )
            manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            env = self.game.run_env()
            env.update({"SDL_VIDEODRIVER": "dummy", "SDL_AUDIODRIVER": "dummy"})
            command = (
                "import main; "
                "print(main.WINDOW_SIZE, main.WINDOW_RESIZABLE, main.WINDOW_FULLSCREEN)"
            )
            result = subprocess.run(
                [sys.executable, "-c", command],
                cwd=str(self.game.root),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])
            self.assertIn("(900, 600) False True", result.stdout)
        finally:
            manifest_path.write_text(original, encoding="utf-8")

    def test_validation_has_no_errors(self) -> None:
        for project in (self.game, self.app):
            errors = [issue for issue in project.validate() if issue.level == "error"]
            self.assertEqual(errors, [])

    def test_both_templates_run_headless(self) -> None:
        for project in (self.game, self.app):
            result = _run_project(project)
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])

    def test_platformer_goal_uses_the_platformer_starter(self) -> None:
        root = self.base / "platformer"
        project = Project.create(
            root,
            default_manifest(
                "Прыгун",
                project_type="game",
                mode="builtin",
                goal="Сделай платформер с уровнями, прыжками и монетами",
            ),
        )
        source = project.entry.read_text(encoding="utf-8")
        self.assertIn("Platformer starter", source)
        self.assertIn("class Player", source)
        self.assertIn("if __name__ == \"__main__\":", source)
        result = _run_project(project, frames=8)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])

    def test_blank_template_is_minimal_and_runs(self) -> None:
        self.assertEqual(self.blank.manifest.get("template"), "blank")
        source = (self.blank.root / "main.py").read_text(encoding="utf-8")
        self.assertIn("class Project(Game)", source)
        self.assertIn("Пустой проект", source)
        self.assertNotIn("class Player", source)
        self.assertTrue((self.blank.root / "_engine" / "reasonable" / "runtime" / "app.py").is_file())
        self.assertEqual(
            [issue for issue in self.blank.validate() if issue.level == "error"],
            [],
        )
        result = _run_project(self.blank)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])

    def test_sync_engine_refreshes_vendored_copy(self) -> None:
        marker = self.game.root / "_engine" / "reasonable" / "runtime" / "app.py"
        marker.write_text("# broken\n", encoding="utf-8")
        self.game.sync_engine()
        self.assertIn("class Game", marker.read_text(encoding="utf-8"))

    def test_simple_ui_level_uses_tkinter_template_without_pygame_art(self) -> None:
        simple = Project.create(
            self.base / "simple-app",
            default_manifest(
                "Утилита",
                project_type="app",
                mode="builtin",
                goal="Простая программа с окнами и списками",
                ui_levels=["simple"],
            ),
        )
        source = (simple.root / "main.py").read_text(encoding="utf-8")
        self.assertIn("tkinter", source)
        self.assertIn("play_engine_splash", source)
        self.assertFalse((simple.root / "assets" / "background.png").exists())
        self.assertFalse(any((simple.root / "assets" / "sprites").glob("*.png")))
        # The simple-level agent pack carries the tkinter skill only.
        self.assertTrue((simple.root / "skills" / "ui-simple-tkinter.md").is_file())
        self.assertFalse((simple.root / "skills" / "ui-advanced-scenes.md").is_file())
        result = _run_project(simple)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])

    def test_example_app_migrates_old_data_and_keeps_planner_fields(self) -> None:
        env = self.app.run_env()
        env.update({"SDL_VIDEODRIVER": "dummy", "SDL_AUDIODRIVER": "dummy"})
        code = (
            "import json, main;"
            "data = main.normalise_data({'tasks': [{'id': 7, 'title': 'Old', 'done': True}]});"
            "print(json.dumps({'version': data['version'], 'history': data['history'],"
            " 'task': data['tasks'][0]}, ensure_ascii=False))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(self.app.root),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        data = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(data["version"], 2)
        self.assertEqual(data["history"], {})
        self.assertEqual(data["task"]["priority"], 1)
        self.assertEqual(data["task"]["tag"], "Личное")

    def test_game_scene_markers_spawn_entities_and_effects_stay_centred(self) -> None:
        env = self.game.run_env()
        env.update({"SDL_VIDEODRIVER": "dummy", "SDL_AUDIODRIVER": "dummy"})
        code = (
            "import pygame, main;"
            "pygame.init(); pygame.display.set_mode((1280, 720));"
            "g = main.SparkGame(); s = main.WorldScene(g); g.scene = s;"
            "print(len(s.stars), len(s.enemies));"
            "s.on_resize((1920, 1080));"
            "p = s.camera.world_to_screen((s.player.x, s.player.y));"
            "print(round(p.x), round(p.y), round(s.player.x), round(s.player.y))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(self.game.root),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        lines = result.stdout.strip().splitlines()
        self.assertEqual(lines[-2].split()[:2], ["7", "2"])
        screen_x, screen_y, player_x, player_y = lines[-1].split()
        self.assertEqual((screen_x, screen_y), (player_x, player_y))

    def test_example_game_ships_a_real_menu_and_powerups(self) -> None:
        env = self.game.run_env()
        env.update({"SDL_VIDEODRIVER": "dummy", "SDL_AUDIODRIVER": "dummy"})
        code = (
            "import main;"
            "print(main.SparkGame.__name__, hasattr(main, 'Sfx'),"
            " hasattr(main, 'PowerUp'), hasattr(main, 'WorldScene'))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(self.game.root),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        self.assertIn("SparkGame True True True", result.stdout)

    def test_protected_vendoring_ships_bytecode_only(self) -> None:
        from reasonable.core.scaffold import vendor_engine

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "engine_src" / "reasonable"
            (source / "runtime").mkdir(parents=True)
            (source / "core").mkdir(parents=True)
            (source / "__init__.pyc").write_bytes(b"pyc")
            (source / "runtime" / "__init__.pyc").write_bytes(b"pyc")
            (source / "runtime" / "app.pyc").write_bytes(b"pyc")
            (source / "core" / "secret.py").write_text("TOKEN = 1\n", encoding="utf-8")
            (source / "assets").mkdir()
            (source / "assets" / "logo.txt").write_text("asset", encoding="utf-8")

            project = root / "project"
            project.mkdir()
            with mock.patch.dict(os.environ, {"REASONABLE_ENGINE_SOURCE": str(root / "engine_src")}):
                target = vendor_engine(project, protected=True)
            vendored = target / "reasonable"

            self.assertTrue((vendored / "runtime" / "app.pyc").is_file())
            self.assertFalse((vendored / "runtime" / "app.py").exists())
            self.assertFalse((vendored / "core" / "secret.py").exists())
            self.assertFalse(any(vendored.rglob("*.py")))
            self.assertTrue((vendored / "assets" / "logo.txt").is_file())

    def test_site_is_a_plain_python_server(self) -> None:
        self.assertTrue((self.site.root / "site" / "index.html").is_file())
        self.assertTrue((self.site.root / "site" / "styles.css").is_file())
        main = self.site.entry.read_text(encoding="utf-8")
        self.assertIn("http.server", main)
        self.assertNotIn("reasonable.runtime", main)
        result = subprocess.run(
            [sys.executable, str(self.site.entry), "--check"],
            cwd=str(self.site.root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_other_is_a_plain_python_project(self) -> None:
        main = self.other.entry.read_text(encoding="utf-8")
        self.assertIn("--check", main)
        self.assertNotIn("reasonable.runtime", main)
        result = subprocess.run(
            [sys.executable, str(self.other.entry), "--check"],
            cwd=str(self.other.root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
