import json
import tempfile
import unittest
from pathlib import Path

from reasonable.ai.tools import AgentTools
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
        self.tools = AgentTools(self.project, image_config={"provider": "procedural"})

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def call(self, name: str, **arguments) -> dict:
        return json.loads(self.tools.call(name, arguments))

    def test_unknown_tool_fails_cleanly(self) -> None:
        result = self.call("does_not_exist")
        self.assertFalse(result["ok"])
        self.assertIn("Неизвестный инструмент", result["error"])

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

    def test_sprite_generation_and_inspection(self) -> None:
        generated = self.call(
            "generate_sprite",
            prompt="золотая звезда",
            path="assets/sprites/star.png",
            size=96,
        )
        self.assertTrue(generated["ok"])
        self.assertEqual(generated["provider"], "procedural")
        self.assertTrue((self.root / "assets" / "sprites" / "star.png").is_file())
        inspected = self.call("inspect_image", path="assets/sprites/star.png")
        self.assertTrue(inspected["ok"])
        self.assertEqual(tuple(inspected["size"]), (96, 96))
        self.assertGreater(inspected["opaque_percent"], 5)

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


if __name__ == "__main__":
    unittest.main()
