import json
import tempfile
import unittest
from pathlib import Path

from reasonable.ai.tools import AgentTools, SITE_TOOL_NAMES, tool_schemas_for
from reasonable.core.progress import read_state
from reasonable.core.project import Project, default_manifest


class AgentToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "project"
        self.root.mkdir(parents=True)
        self.project = Project.create(
            self.root,
            default_manifest("Инструменты", project_type="game", mode="builtin", goal="Проверка"),
            scaffold=False,
        )
        (self.root / "assets").mkdir()
        (self.root / "progress").mkdir()
        (self.root / "main.py").write_text("print('ok')\n", encoding="utf-8")
        (self.root / "game.py").write_text("def update():\n    return 1\n", encoding="utf-8")
        self.tools = AgentTools(self.project, image_config={})

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def call(self, name: str, **arguments) -> dict:
        return json.loads(self.tools.call(name, arguments))

    def test_unknown_tool_fails_cleanly(self) -> None:
        result = self.call("does_not_exist")
        self.assertFalse(result["ok"])
        self.assertIn("Неизвестный инструмент", result["error"])

    def test_run_project_rejects_an_entry_without_launch_code(self) -> None:
        (self.root / "main.py").write_text(
            "def main():\n    pass\n", encoding="utf-8"
        )
        result = self.call("run_project", frames=2)
        self.assertFalse(result["ok"])
        self.assertIn("main.py", result["error"].lower())

    def test_write_file_cannot_remove_entry_launch_code(self) -> None:
        (self.root / "main.py").write_text(
            "def main():\n    pass\n\nif __name__ == \"__main__\":\n    main()\n",
            encoding="utf-8",
        )
        result = self.call(
            "write_file", path="main.py", content="def main():\n    pass\n"
        )
        self.assertFalse(result["ok"])
        self.assertIn("__main__", (self.root / "main.py").read_text(encoding="utf-8"))

    def test_edit_file_cannot_remove_entry_launch_code(self) -> None:
        (self.root / "main.py").write_text(
            "def main():\n    pass\n\nif __name__ == \"__main__\":\n    main()\n",
            encoding="utf-8",
        )
        result = self.call(
            "edit_file",
            path="main.py",
            old_text="\nif __name__ == \"__main__\":\n    main()\n",
            new_text="\n",
        )
        self.assertFalse(result["ok"])
        self.assertIn("__main__", (self.root / "main.py").read_text(encoding="utf-8"))

    def test_run_project_enables_autoplay_for_games(self) -> None:
        from types import SimpleNamespace
        from unittest import mock

        captured = {}

        def fake_run(command, **kwargs):
            captured["env"] = dict(kwargs.get("env") or {})
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")

        with mock.patch("reasonable.ai.tools.subprocess.run", side_effect=fake_run):
            result = self.call("run_project", frames=2)
        self.assertTrue(result["ok"])
        self.assertEqual(captured["env"].get("RE_AUTOPLAY"), "1")
        self.assertEqual(captured["env"].get("RE_FRAMES"), "2")

    def test_run_project_fails_when_autoplay_is_stuck(self) -> None:
        from types import SimpleNamespace
        from unittest import mock

        def fake_run(command, **kwargs):
            return SimpleNamespace(
                returncode=0,
                stdout=(
                    "RE_AUTOPLAY_IDLE: the game screen did not change for 120 frames\n"
                    "RE_AUTOPLAY_OK frames=121 flips=122 max_unchanged=121 idle=True\n"
                ),
                stderr="",
            )

        with mock.patch("reasonable.ai.tools.subprocess.run", side_effect=fake_run):
            result = self.call("run_project", frames=120)
        self.assertFalse(result["ok"])
        self.assertTrue(result["error"])

    def test_repeated_scratch_writes_are_blocked(self) -> None:
        for _ in range(3):
            result = self.call(
                "write_file", path="_check.py", content="print('check')\n"
            )
            self.assertTrue(result["ok"], result)
        blocked = self.call(
            "write_file", path="_check.py", content="print('check again')\n"
        )
        self.assertFalse(blocked["ok"])
        self.assertEqual(self.tools.files_changed, 0)
        ready = self.tools.readiness()
        self.assertFalse(ready["ready"])
        self.assertTrue(any("temporary" in item.lower() for item in ready["missing"]))

    def test_run_project_captures_and_checks_screenshots(self) -> None:
        from types import SimpleNamespace
        from unittest import mock
        from PIL import Image

        def fake_run(command, **kwargs):
            directory = Path(kwargs["env"]["RE_SCREENSHOTS"])
            directory.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (12, 8), (30, 40, 50)).save(directory / "frame_01.png")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with mock.patch("reasonable.ai.tools.subprocess.run", side_effect=fake_run):
            result = self.call("run_project", frames=5, screenshots=1)
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(result["screenshots"]), 1)
        self.assertFalse(result["screenshots"][0]["blank"])

    def test_read_write_edit_and_search(self) -> None:
        written = self.call("write_file", path="src/level.py", content="SCORE = 0\n")
        self.assertTrue(written["ok"])
        self.assertTrue((self.root / "src" / "level.py").is_file())

        edited = self.call("edit_file", path="src/level.py", old_text="SCORE = 0", new_text="SCORE = 10")
        self.assertTrue(edited["ok"])
        self.assertEqual((self.root / "src" / "level.py").read_text(encoding="utf-8"), "SCORE = 10\n")

        read = self.call("read_file", path="src/level.py")
        self.assertEqual(read["content"], "SCORE = 10")

        search = self.call("search_text", query="SCORE")
        self.assertEqual(search["count"], 1)
        self.assertEqual(search["matches"][0]["path"], "src/level.py")

    def test_changed_files_audit_trail(self) -> None:
        # The editor shows this list after every run, so it must record the
        # final action per file instead of only a count.
        self.call("write_file", path="src/new.py", content="X = 1\n")
        self.call("edit_file", path="src/new.py", old_text="X = 1", new_text="X = 2")
        self.call("delete_path", path="src/new.py")
        changes = {row["path"]: row["action"] for row in self.tools.changed_files}
        self.assertEqual(changes["src/new.py"], "delete")
        self.assertEqual(self.tools.readiness()["changed_files"][0]["path"], "src/new.py")

    def test_edit_requires_unique_fragment(self) -> None:
        self.call("write_file", path="dup.py", content="x = 1\nx = 1\n")
        result = self.call("edit_file", path="dup.py", old_text="x = 1", new_text="x = 2")
        self.assertFalse(result["ok"])
        self.assertIn("2 раз", result["error"])
        result = self.call("edit_file", path="dup.py", old_text="x = 1", new_text="x = 2", replace_all=True)
        self.assertTrue(result["ok"])

    def test_sandbox_rejects_traversal_engine_and_protected_delete(self) -> None:
        result = self.call("write_file", path="../outside.py", content="bad")
        self.assertFalse(result["ok"])
        result = self.call("write_file", path="_engine/reasonable/runtime/app.py", content="bad")
        self.assertFalse(result["ok"])
        result = self.call("delete_path", path="main.py")
        self.assertFalse(result["ok"])
        result = self.call("delete_path", path="assets")
        self.assertFalse(result["ok"])

    def test_invalid_json_is_rejected(self) -> None:
        result = self.call("write_file", path="broken.json", content="{oops")
        self.assertFalse(result["ok"])
        self.assertIn("JSON", result["error"])

    def test_progress_tools(self) -> None:
        plan = self.call("set_plan", tasks=["Собрать сцену", "Добавить врагов", "Проверить"])
        self.assertEqual(len(plan["tasks"]), 3)
        update = self.call("update_task", task="t2", status="in_progress")
        self.assertEqual(update["tasks"][1]["status"], "in_progress")
        progress = self.call("report_progress", percent=55, stage="Враги", message="Готово наполовину")
        self.assertEqual(progress["percent"], 55)

        # 100% is reserved until the agent has changed files, validated and run.
        capped = self.call("report_progress", percent=100, stage="Финал")
        self.assertEqual(capped["percent"], 99)
        blocked = self.call("finish", message="Готово")
        self.assertFalse(blocked["ok"])
        self.assertIn("рано", blocked["error"])

        written = self.call("write_file", path="scene.py", content="SCORE = 1\n")
        self.assertTrue(written["ok"])
        self.assertFalse(self.call("finish", message="Готово")["ok"])

        validated = self.call("validate_project")
        self.assertTrue(validated["ok"])
        self.assertFalse(validated["has_errors"])
        self.assertFalse(self.call("finish", message="Готово")["ok"])

        run = self.call("run_project", frames=1)
        self.assertTrue(run["ok"], run)
        self.assertEqual(run["returncode"], 0)

        for task in read_state(self.root).get("tasks") or []:
            self.call("update_task", task=task["id"], status="done")
        finish = self.call("finish", message="Готово")
        self.assertTrue(finish["ok"], finish)
        self.assertEqual(finish["percent"], 100.0)
        state = read_state(self.root)
        self.assertEqual(state["status"], "done")
        self.assertTrue(all(task["status"] == "done" for task in state["tasks"]))

    def test_edit_after_validation_requires_new_checks(self) -> None:
        self.call("write_file", path="level.py", content="VALUE = 1\n")
        self.call("validate_project")
        self.call("run_project", frames=1)
        self.assertTrue(self.call("finish", message="Готово")["ok"])

        self.call("edit_file", path="level.py", old_text="VALUE = 1", new_text="VALUE = 2")
        blocked = self.call("finish", message="Ещё раз")
        self.assertFalse(blocked["ok"])
        self.assertIn("validate_project", blocked["error"])

    def test_draw_sprite_and_inspection(self) -> None:
        drawn = self.call(
            "draw_sprite",
            path="assets/sprites/heart.png",
            size=96,
            shapes=[
                {"type": "ellipse", "center": [36, 40], "radius": [22, 22], "fill": "#E63946"},
                {"type": "ellipse", "center": [64, 40], "radius": [22, 22], "fill": "#E63946"},
                {"type": "polygon", "points": [[16, 44], [84, 44], [50, 88]], "fill": "#E63946"},
            ],
        )
        self.assertTrue(drawn["ok"])
        self.assertEqual(drawn["provider"], "draw")
        self.assertTrue((self.root / "assets" / "sprites" / "heart.png").is_file())
        inspected = self.call("inspect_image", path="assets/sprites/heart.png")
        self.assertTrue(inspected["ok"])
        self.assertEqual(tuple(inspected["size"]), (96, 96))
        self.assertGreater(inspected["opaque_percent"], 5)

    def test_generate_sprite_without_model_returns_an_honest_error(self) -> None:
        result = self.call("generate_sprite", prompt="звезда", path="assets/sprites/star.png", size=64)
        self.assertFalse(result["ok"])
        self.assertIn("draw_sprite", result["error"])
        self.assertFalse((self.root / "assets" / "sprites" / "star.png").exists())

    def test_sprite_must_live_in_assets(self) -> None:
        result = self.call("generate_sprite", prompt="звезда", path="star.png", size=64)
        self.assertFalse(result["ok"])
        self.assertIn("assets", result["error"])

    def test_run_command_blocks_dangerous_commands(self) -> None:
        result = self.call("run_command", command="shutdown /s")
        self.assertFalse(result["ok"])
        result = self.call("run_command", command='python -c "print(1+1)"', timeout=30)
        self.assertTrue(result["ok"])
        self.assertEqual(result["returncode"], 0)
        self.assertIn("2", result["output"])

    def test_large_file_is_readable_by_line_range(self) -> None:
        # 400 KB is the old hard rejection threshold; a slice must still work.
        big = self.root / "data" / "big.json"
        big.parent.mkdir(parents=True)
        lines = [f'"row_{index}": {index},' for index in range(20_000)]
        big.write_text("\n".join(lines), encoding="utf-8")
        result = self.call("read_file", path="data/big.json", start_line=2, end_line=4)
        self.assertTrue(result["ok"])
        self.assertEqual(result["start_line"], 2)
        self.assertEqual(result["content"].splitlines()[0], '"row_1": 1,')

    def test_project_manifest_cannot_be_rewritten_by_the_agent(self) -> None:
        before = (self.root / "project.json").read_text(encoding="utf-8")
        written = self.call("write_file", path="project.json", content="{}")
        self.assertFalse(written["ok"])
        edited = self.call(
            "edit_file",
            path="project.json",
            old_text='"format": 1',
            new_text='"format": 2',
        )
        self.assertFalse(edited["ok"])
        self.assertEqual(
            (self.root / "project.json").read_text(encoding="utf-8"), before
        )

    def test_append_file_finishes_a_partial_file(self) -> None:
        self.call("write_file", path="src/chunked.py", content="PART_ONE = 1\n# @@CHUNK@@\n")
        appended = self.call(
            "append_file", path="src/chunked.py", content="PART_TWO = 2\n"
        )
        self.assertTrue(appended["ok"])
        self.assertEqual(appended["appended"], len("PART_TWO = 2\n"))
        self.assertEqual(
            (self.root / "src" / "chunked.py").read_text(encoding="utf-8"),
            "PART_ONE = 1\n# @@CHUNK@@\nPART_TWO = 2\n",
        )

    def test_append_file_creates_a_missing_file(self) -> None:
        result = self.call("append_file", path="notes.md", content="hello\n")
        self.assertTrue(result["ok"])
        self.assertEqual((self.root / "notes.md").read_text(encoding="utf-8"), "hello\n")

    def test_append_file_rejects_invalid_json(self) -> None:
        self.call("write_file", path="data.json", content='{"a": 1}')
        result = self.call("append_file", path="data.json", content=",oops")
        self.assertFalse(result["ok"])
        self.assertEqual((self.root / "data.json").read_text(encoding="utf-8"), '{"a": 1}')

    def test_append_file_cannot_touch_the_manifest(self) -> None:
        result = self.call("append_file", path="project.json", content="x")
        self.assertFalse(result["ok"])

    def test_declined_write_is_not_applied(self) -> None:
        called: list[tuple[str, str]] = []
        tools = AgentTools(
            self.project,
            confirm_write=lambda action, path: called.append((action, path)) or False,
        )
        result = json.loads(
            tools.call("write_file", {"path": "blocked.py", "content": "X = 1\n"})
        )
        self.assertFalse(result["ok"])
        self.assertTrue(tools.write_denied)
        self.assertEqual(called, [("write", "blocked.py")])
        self.assertFalse((self.root / "blocked.py").exists())

    def test_approved_write_is_applied(self) -> None:
        tools = AgentTools(self.project, confirm_write=lambda action, path: True)
        result = json.loads(
            tools.call("write_file", {"path": "allowed.py", "content": "X = 1\n"})
        )
        self.assertTrue(result["ok"])
        self.assertFalse(tools.write_denied)
        self.assertTrue((self.root / "allowed.py").is_file())


class SiteToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "site-project"
        self.project = Project.create(
            self.root,
            default_manifest(
                "Site",
                project_type="site",
                goal="Build a landing page",
                template="site",
            ),
            scaffold=True,
        )
        self.tools = AgentTools(self.project, image_config={})

    def call(self, name: str, **arguments) -> dict:
        return json.loads(self.tools.call(name, arguments))

    def test_site_page_writes_a_complete_document(self) -> None:
        result = self.call(
            "site_page",
            path="about.html",
            title="About us",
            description="Who we are",
            body="<main><h1>About</h1></main>",
        )
        self.assertTrue(result["ok"])
        page = (self.root / "site" / "about.html").read_text(encoding="utf-8")
        self.assertIn('charset="utf-8"', page)
        self.assertIn('name="viewport"', page)
        self.assertIn("<title>About us</title>", page)
        self.assertIn('name="description"', page)
        self.assertIn("styles.css", page)
        self.assertIn("<h1>About</h1>", page)

    def test_site_theme_writes_a_design_system(self) -> None:
        result = self.call("site_theme", palette="cool", mode="dark", radius=18)
        self.assertTrue(result["ok"])
        css = (self.root / "site" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("--accent", css)
        self.assertIn("--radius: 18px", css)
        self.assertIn("color-scheme: dark", css)
        self.assertIn("@media (max-width: 820px)", css)

    def test_validate_site_finds_a_broken_reference(self) -> None:
        self.call(
            "site_page",
            path="broken.html",
            title="Broken",
            body='<a href="missing.html">Missing</a>',
        )
        result = self.call("validate_site")
        self.assertFalse(result["ok"] is False)
        self.assertTrue(result["has_errors"])
        self.assertTrue(
            any("missing.html" in str(issue.get("message")) for issue in result["issues"])
        )

    def test_run_project_uses_the_site_check_mode(self) -> None:
        result = self.call("run_project")
        self.assertTrue(result["ok"])
        self.assertEqual(result["returncode"], 0)

    def test_site_tools_are_only_advertised_where_useful(self) -> None:
        names = {schema["name"] for schema in tool_schemas_for("game")}
        self.assertFalse(names & SITE_TOOL_NAMES)
        self.assertTrue(
            {schema["name"] for schema in tool_schemas_for("site")} >= SITE_TOOL_NAMES
        )
        self.assertTrue(
            {schema["name"] for schema in tool_schemas_for("other")} >= SITE_TOOL_NAMES
        )


if __name__ == "__main__":
    unittest.main()
