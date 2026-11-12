"""Tests for the master/specialist parallel orchestrator."""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from reasonable.ai.client import ChatResult
from reasonable.ai.orchestrator import Orchestrator
from reasonable.ai.tools import AgentTools
from reasonable.core.project import Project, default_manifest
from reasonable.core.settings import Settings


class OrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "project"
        self.root.mkdir(parents=True)
        self.project = Project.create(
            self.root,
            default_manifest("Parallel", goal="Build a game menu and assets"),
            scaffold=False,
        )
        (self.root / "main.py").write_text("print('ok')\n", encoding="utf-8")
        self.settings = Settings(path=self.root / "settings.json")
        self.events: list = []

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _orchestrator(self) -> Orchestrator:
        return Orchestrator(
            self.project,
            self.settings,
            message=None,
            on_event=self.events.append,
            persist_messages=False,
        )

    def test_planner_parses_and_merges_conflicting_code_scopes(self) -> None:
        orchestrator = self._orchestrator()
        orchestrator._call_model = lambda *args, **kwargs: ChatResult(
            content=json.dumps(
                {
                    "summary": "Menu and art",
                    "tasks": [
                        {
                            "id": "code-1",
                            "role": "code",
                            "title": "Menu state",
                            "files": ["main.py"],
                            "instructions": "Add the menu.",
                        },
                        {
                            "id": "code-2",
                            "role": "code",
                            "title": "Menu input",
                            "files": ["main.py"],
                            "instructions": "Add keyboard input.",
                        },
                        {
                            "id": "assets-1",
                            "role": "assets",
                            "title": "Logo",
                            "files": ["assets/sprites/logo.png"],
                            "instructions": "Draw a logo.",
                        },
                    ],
                }
            )
        )
        plan = orchestrator._plan("Build a menu with a logo")
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(len(plan["tasks"]), 2)
        code_tasks = [item for item in plan["tasks"] if item["role"] == "code"]
        self.assertEqual(len(code_tasks), 1)
        self.assertIn("Add the menu.", code_tasks[0]["instructions"])
        self.assertIn("Add keyboard input.", code_tasks[0]["instructions"])

    def test_dependent_test_task_is_merged_with_the_module_it_imports(self) -> None:
        orchestrator = self._orchestrator()
        tasks = orchestrator._normalise_tasks(
            [
                {
                    "id": "code-1",
                    "role": "code",
                    "title": "Create math_utils",
                    "files": ["math_utils.py"],
                    "instructions": "Create math_utils.py with add and sub.",
                },
                {
                    "id": "code-2",
                    "role": "code",
                    "title": "Create tests",
                    "files": ["test_math_utils.py"],
                    "instructions": "Import add and sub from math_utils.py and test them.",
                },
            ]
        )
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["id"], "code-1")
        self.assertIn("test_math_utils.py", tasks[0]["files"])
        self.assertIn("Import add and sub", tasks[0]["instructions"])

    def test_verification_only_plan_items_are_dropped(self) -> None:
        orchestrator = self._orchestrator()
        tasks = orchestrator._normalise_tasks(
            [
                {
                    "id": "verify",
                    "role": "code",
                    "title": "validate_project",
                    "files": ["main.py"],
                    "instructions": "Run validate_project and report the result.",
                },
                {
                    "id": "create",
                    "role": "code",
                    "title": "Create the menu",
                    "files": ["main.py"],
                    "instructions": "Create the main menu screen.",
                },
            ]
        )
        self.assertEqual([item["id"] for item in tasks], ["create"])

    def test_specialist_write_scope_is_enforced(self) -> None:
        tools = AgentTools(self.project, write_scope=("main.py",))
        allowed = json.loads(tools.call("write_file", {"path": "main.py", "content": "print(1)\n"}))
        self.assertTrue(allowed["ok"])
        denied = json.loads(tools.call("write_file", {"path": "other.py", "content": "print(2)\n"}))
        self.assertFalse(denied["ok"])
        self.assertIn("main.py", denied["error"])

    def test_specialist_usage_and_progress_reach_the_chat(self) -> None:
        from unittest import mock

        from reasonable.ai.agent import AgentEvent

        orchestrator = self._orchestrator()
        events: list[AgentEvent] = []
        orchestrator.on_event = events.append

        class FakeAgent:
            def __init__(self, *args, **kwargs):
                self.tools = type(
                    "Tools",
                    (),
                    {"changed_files": [], "files_changed": 0},
                )()
                self.last_error = ""
                self._emit = kwargs.get("on_event")

            def run(self, message, **kwargs):
                self._emit(
                    AgentEvent(
                        "usage",
                        data={
                            "usage": {
                                "prompt_tokens": 10,
                                "completion_tokens": 5,
                                "total_tokens": 15,
                                "seconds": 1.0,
                            }
                        },
                    )
                )
                self._emit(AgentEvent("assistant", "Working on the task"))
                self._emit(
                    AgentEvent(
                        "tool_start",
                        data={
                            "tool": "write_file",
                            "arguments": {"path": "main.py"},
                            "call_id": "call-42",
                        },
                    )
                )
                return "done"

        with mock.patch("reasonable.ai.orchestrator.Agent", FakeAgent), mock.patch(
            "reasonable.ai.orchestrator.update_task"
        ):
            orchestrator._run_specialist(
                {
                    "id": "code-1",
                    "role": "code",
                    "title": "Implement",
                    "files": ["main.py"],
                    "instructions": "Do it.",
                },
                "Task",
            )

        usage = [event for event in events if event.kind == "usage"]
        self.assertEqual(len(usage), 1)
        self.assertEqual(usage[0].data["usage"]["total_tokens"], 15)
        self.assertTrue(
            any(
                event.kind == "assistant" and "Working on the task" in event.text
                for event in events
            )
        )
        self.assertTrue(
            any(
                event.kind == "tool_start"
                and event.data.get("agent") == "code-1"
                and event.data.get("call_id") == "call-42"
                and event.data.get("arguments") == {"path": "main.py"}
                for event in events
            )
        )

    def test_independent_specialists_run_in_parallel(self) -> None:
        orchestrator = self._orchestrator()
        orchestrator.workers = 3

        def fake_specialist(task, original):
            time.sleep(0.25)
            return {
                "id": task["id"],
                "role": task["role"],
                "title": task["title"],
                "report": "ok",
                "error": "",
                "files_changed": [{"path": task["files"][0], "action": "edit"}],
                "changed_count": 1,
            }

        orchestrator._run_specialist = fake_specialist
        plan = {
            "summary": "",
            "tasks": [
                {"id": "a", "role": "code", "title": "A", "files": ["a.py"], "instructions": "a"},
                {"id": "b", "role": "code", "title": "B", "files": ["b.py"], "instructions": "b"},
                {"id": "c", "role": "assets", "title": "C", "files": ["assets/c.png"], "instructions": "c"},
            ],
        }
        started = time.perf_counter()
        results = orchestrator._execute(plan, "task")
        elapsed = time.perf_counter() - started
        self.assertEqual(len(results), 3)
        self.assertLess(elapsed, 0.6)

    def test_run_reports_completion_after_audit(self) -> None:
        orchestrator = self._orchestrator()
        orchestrator._plan = lambda task: {
            "summary": "one item",
            "tasks": [
                {
                    "id": "code-1",
                    "role": "code",
                    "title": "Implement",
                    "files": ["main.py"],
                    "instructions": "Do it.",
                }
            ],
        }
        orchestrator._start_snapshot = lambda task: None
        orchestrator._apply_plan = lambda plan: None
        orchestrator._execute = lambda plan, task: [
            {
                "id": "code-1",
                "role": "code",
                "title": "Implement",
                "report": "Implemented.",
                "error": "",
                "files_changed": [{"path": "main.py", "action": "edit"}],
                "changed_count": 1,
            }
        ]
        orchestrator._verify = lambda: {"ok": True, "missing": [], "validation": {}, "run": {}}
        orchestrator._review = lambda *args: {"complete": True, "missing": [], "next": ""}
        orchestrator._final_text = lambda *args: "Ready."
        orchestrator._finish_snapshot = lambda *args: None
        text = orchestrator.run("Implement the task")
        self.assertEqual(text, "Ready.")
        self.assertTrue(orchestrator.finished)
        self.assertEqual(orchestrator.changes[0]["path"], "main.py")
        self.assertTrue(any(event.kind == "assistant" for event in self.events))

    def test_invalid_plan_falls_back_to_single_agent(self) -> None:
        orchestrator = self._orchestrator()
        orchestrator._plan = lambda task: None
        orchestrator._fallback = lambda task: "fallback"
        self.assertEqual(orchestrator.run("Task"), "fallback")


if __name__ == "__main__":
    unittest.main()
