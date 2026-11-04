"""Independent completion audit of the built-in agent."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from reasonable.ai.agent import Agent
from reasonable.ai.client import ChatResult
from reasonable.core.project import Project, default_manifest
from reasonable.core.settings import Settings


class StarterContextTests(unittest.TestCase):
    def test_system_prompt_explains_the_starter_and_scenes(self) -> None:
        from reasonable.ai.prompts import build_agent_system_prompt
        from reasonable.core.scene import create_scene

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir(parents=True)
            project = Project.create(
                root,
                default_manifest("Starter", goal="Star collector"),
                scaffold=False,
            )
            create_scene(root, "Main", template="level", identifier="main")
            prompt = build_agent_system_prompt(project)
            self.assertIn("STARTER PROJECT", prompt)
            self.assertIn("not the user's specification", prompt)
            self.assertIn("SCENES", prompt)
            self.assertIn("scenes/main.json", prompt)
            self.assertIn("spawn markers", prompt)


class AgentLanguageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "project"
        self.root.mkdir(parents=True)
        self.project = Project.create(
            self.root,
            default_manifest("Language", goal="Language"),
            scaffold=False,
        )
        (self.root / "main.py").write_text("print('ok')\n", encoding="utf-8")
        self.settings = Settings(path=self.root / "settings.json")
        self.settings.set_supervisor(False)

    def tearDown(self) -> None:
        from reasonable.core import i18n

        i18n.set_override(None)
        self._tmp.cleanup()

    def _prompt_for(self, ui_language: str, task: str) -> str:
        from reasonable.core import i18n

        i18n.set_override(ui_language)
        agent = Agent(self.project, self.settings)
        captured: dict = {}

        def fake_model(messages, tools, *, temperature=0.65):
            captured["messages"] = [dict(item) for item in messages]
            return ChatResult(content="OK")

        agent._call_model = fake_model
        agent.tools.readiness = lambda: {
            "ready": True,
            "files_changed": 1,
            "changed_files": [],
            "validation_passed": True,
            "run_passed": True,
            "install_commands": 0,
            "missing": [],
        }
        agent.tools.tool_finish = lambda message: None
        agent.run(task)
        return "\n".join(
            str(item.get("content") or "") for item in captured.get("messages", [])
        )

    def test_agent_uses_the_ui_language_not_the_task_language(self) -> None:
        prompt = self._prompt_for("ru", "Make an English game")
        self.assertIn("editor UI language is Russian", prompt)
        self.assertIn("Make an English game", prompt)

        prompt = self._prompt_for("en", "Сделай игру")
        self.assertIn("editor UI language is English", prompt)
        self.assertIn("Сделай игру", prompt)


class SupervisorSettingsTests(unittest.TestCase):
    def test_supervisor_is_on_by_default_and_can_be_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            settings = Settings(path=path)
            self.assertTrue(settings.supervisor_enabled())
            settings.set_supervisor(False)
            self.assertFalse(Settings(path=path).supervisor_enabled())


class SupervisorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "project"
        self.root.mkdir(parents=True)
        self.project = Project.create(
            self.root,
            default_manifest("Supervisor", goal="Add a menu and three levels"),
            scaffold=False,
        )
        (self.root / "main.py").write_text("print('ok')\n", encoding="utf-8")
        self.settings = Settings(path=self.root / "settings.json")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _agent(self, **kwargs) -> Agent:
        return Agent(self.project, self.settings, **kwargs)

    @staticmethod
    def _reply(payload: dict) -> ChatResult:
        return ChatResult(content=json.dumps(payload))

    def test_incomplete_verdict_returns_concrete_feedback(self) -> None:
        agent = self._agent()
        agent._call_model = lambda *args, **kwargs: self._reply(
            {
                "complete": False,
                "missing": ["The menu has no working Play button"],
                "next": "Add the Play button and wire it to the first level.",
            }
        )
        complete, feedback, stalled = agent._supervise_completion(
            "Add a menu and three levels", "Done, everything works."
        )
        self.assertFalse(complete)
        self.assertFalse(stalled)
        self.assertIn("Play button", feedback)
        self.assertIn("Add the Play button", feedback)
        self.assertIn("Original user task", feedback)

    def test_same_verdict_without_progress_is_reported_as_stalled_but_continues(self) -> None:
        agent = self._agent()
        agent._call_model = lambda *args, **kwargs: self._reply(
            {"complete": False, "missing": ["No levels"], "next": "Build three levels."}
        )
        results = [agent._supervise_completion("Build three levels", "Done.") for _ in range(3)]
        self.assertFalse(results[0][2])
        self.assertFalse(results[1][2])
        self.assertTrue(results[2][2])
        # No terminal "incomplete" state: the caller injects a stronger
        # recovery prompt and keeps the agent working.
        self.assertEqual(agent.incomplete_reason, "")

    def test_complete_verdict_passes(self) -> None:
        agent = self._agent()
        agent._call_model = lambda *args, **kwargs: self._reply(
            {"complete": True, "missing": [], "next": ""}
        )
        self.assertEqual(
            agent._supervise_completion("Build three levels", "Done."),
            (True, "", False),
        )

    def test_unparseable_verdict_does_not_block_completion(self) -> None:
        agent = self._agent()
        agent._call_model = lambda *args, **kwargs: ChatResult(content="not json")
        self.assertEqual(
            agent._supervise_completion("Build three levels", "Done."),
            (True, "", False),
        )

    def test_disabled_supervisor_skips_the_extra_request(self) -> None:
        self.settings.set_supervisor(False)
        agent = self._agent()
        agent._call_model = lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("supervisor request must not run")
        )
        self.assertEqual(
            agent._supervise_completion("Build three levels", "Done."),
            (True, "", False),
        )

    def test_analysis_mode_is_not_audited(self) -> None:
        agent = self._agent(analysis=True)
        agent._call_model = lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("analysis must not be audited")
        )
        self.assertEqual(
            agent._supervise_completion("Review the project", "Suggestions."),
            (True, "", False),
        )

    def test_run_continues_after_an_incomplete_audit(self) -> None:
        agent = self._agent()
        main_calls = {"count": 0}
        audits = {"count": 0}

        def fake_model(messages, tools, *, temperature=0.65):
            if tools is None:
                audits["count"] += 1
                if audits["count"] == 1:
                    return self._reply(
                        {
                            "complete": False,
                            "missing": ["No visible menu"],
                            "next": "Add the menu screen.",
                        }
                    )
                return self._reply({"complete": True, "missing": [], "next": ""})
            main_calls["count"] += 1
            return ChatResult(content="Menu implemented.")

        agent._call_model = fake_model
        agent.tools.readiness = lambda: {
            "ready": True,
            "files_changed": 1,
            "changed_files": [],
            "validation_passed": True,
            "run_passed": True,
            "install_commands": 0,
            "missing": [],
        }
        agent.tools.tool_finish = lambda message: None
        text = agent.run("Make a visible menu")
        self.assertTrue(agent.finished)
        self.assertEqual(main_calls["count"], 2)
        self.assertEqual(audits["count"], 2)
        self.assertIn("Menu implemented.", text)

    def test_finish_is_not_executed_before_the_audit_passes(self) -> None:
        from reasonable.ai.agent import ToolCall

        agent = self._agent()
        main_calls = {"count": 0}
        audits = {"count": 0}
        finished = {"count": 0}

        def fake_model(messages, tools, *, temperature=0.65):
            if tools is None:
                audits["count"] += 1
                if audits["count"] == 1:
                    return self._reply(
                        {"complete": False, "missing": ["No menu"], "next": "Add the menu."}
                    )
                return self._reply({"complete": True, "missing": [], "next": ""})
            main_calls["count"] += 1
            return ChatResult(
                content="",
                tool_calls=[
                    ToolCall(
                        id=f"finish_{main_calls['count']}",
                        name="finish",
                        arguments={"message": "Done."},
                    )
                ],
            )

        def fake_tool(name, arguments=None):
            if name == "finish":
                finished["count"] += 1
                return json.dumps({"ok": True})
            return json.dumps({"ok": True})

        agent._call_model = fake_model
        agent.tools.readiness = lambda: {
            "ready": True,
            "files_changed": 1,
            "changed_files": [],
            "validation_passed": True,
            "run_passed": True,
            "install_commands": 0,
            "missing": [],
        }
        agent.tools.call = fake_tool
        text = agent.run("Make a visible menu")
        self.assertTrue(agent.finished)
        self.assertEqual(finished["count"], 1)
        self.assertEqual(main_calls["count"], 2)
        self.assertEqual(audits["count"], 2)
        self.assertIn("Done.", text)

    def test_passive_model_is_kept_working_until_the_task_finishes(self) -> None:
        agent = self._agent()
        main_calls = {"count": 0}
        events: list[str] = []

        def readiness():
            ready = main_calls["count"] >= 4
            return {
                "ready": ready,
                "files_changed": 4,
                "changed_files": [],
                "validation_passed": ready,
                "run_passed": ready,
                "install_commands": 0,
                "missing": [] if ready else ["no file has been modified yet"],
            }

        def fake_model(messages, tools, *, temperature=0.65):
            if tools is None:
                return self._reply({"complete": True, "missing": [], "next": ""})
            main_calls["count"] += 1
            return ChatResult(content="I think this is done.")

        def fake_tool(name, arguments=None):
            if name == "validate_project":
                return json.dumps({"ok": True, "has_errors": True, "issues": []})
            return json.dumps({"ok": True})

        agent._call_model = fake_model
        agent.on_event = lambda event: events.append(event.kind)
        agent.tools.readiness = readiness
        agent.tools.call = fake_tool
        agent.tools.tool_finish = lambda message: None
        text = agent.run("Implement a real feature")

        self.assertTrue(agent.finished)
        self.assertFalse(agent.incomplete_reason)
        self.assertNotIn("incomplete", events)
        self.assertGreaterEqual(main_calls["count"], 4)
        self.assertIn("done", events)
        self.assertTrue(text)

    def test_payload_contains_task_changes_and_scene_summary(self) -> None:
        agent = self._agent()
        agent.tools.files_changed = 1
        agent.tools._changes["main.py"] = {
            "path": "main.py",
            "action": "edit",
            "size": 11,
        }
        payload = agent._supervisor_payload("Add a menu", "Done.")
        self.assertEqual(payload["user_task"], "Add a menu")
        self.assertEqual(payload["changed_files"][0]["path"], "main.py")
        self.assertIn("print('ok')", payload["changed_files"][0]["content"])
        self.assertIn("scenes", payload)


if __name__ == "__main__":
    unittest.main()
