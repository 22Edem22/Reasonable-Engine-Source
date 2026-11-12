"""Captain / durable member / dependency DAG behaviour."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from reasonable.ai.orchestrator import Orchestrator
from reasonable.core.project import Project, default_manifest
from reasonable.core.settings import Settings


class FakeTools:
    def __init__(self) -> None:
        self.changed_files: list[dict] = []
        self.files_changed = 0
        self.write_scope = None

    def reset_evidence(self) -> None:
        self.changed_files = []
        self.files_changed = 0


class FakeAgent:
    created: list["FakeAgent"] = []

    def __init__(self, *args, **kwargs) -> None:
        self.kwargs = dict(kwargs)
        self.tools = FakeTools()
        self.last_error = ""
        self.messages: list[str] = []
        self.chat_id = kwargs.get("chat_id")
        self.extra_system_prompt = kwargs.get("extra_system_prompt")
        self.on_event = kwargs.get("on_event")
        self.reports: list[str] = []
        FakeAgent.created.append(self)

    def run(self, message: str, **kwargs) -> str:
        self.messages.append(str(message))
        self.reports.append("report")
        return f"report {len(self.messages)}"


class OrchestratorTeamTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "project"
        self.root.mkdir(parents=True)
        self.project = Project.create(
            self.root,
            default_manifest("Team", goal="Build a menu"),
            scaffold=False,
        )
        (self.root / "main.py").write_text("print('ok')\n", encoding="utf-8")
        self.settings = Settings(path=self.root / "settings.json")
        FakeAgent.created = []

    def _orchestrator(self) -> Orchestrator:
        return Orchestrator(
            self.project,
            self.settings,
            persist_messages=False,
        )

    def test_depends_on_is_kept_and_invalid_edges_are_dropped(self) -> None:
        orchestrator = self._orchestrator()
        tasks = orchestrator._normalise_tasks(
            [
                {
                    "id": "a",
                    "role": "code",
                    "title": "A",
                    "files": ["a.py"],
                    "instructions": "create module a",
                },
                {
                    "id": "b",
                    "role": "assets",
                    "title": "B",
                    "files": ["assets/b.png"],
                    "instructions": "draw b",
                    "depends_on": ["a", "missing", "b"],
                },
            ]
        )
        by_id = {task["id"]: task for task in tasks}
        self.assertEqual(by_id["b"]["depends_on"], ["a"])
        self.assertEqual(by_id["a"]["depends_on"], [])

    def test_a_cycle_is_broken_instead_of_stalling(self) -> None:
        orchestrator = self._orchestrator()
        tasks = orchestrator._normalise_tasks(
            [
                {
                    "id": "a",
                    "role": "code",
                    "title": "A",
                    "files": ["a.py"],
                    "instructions": "create module a",
                    "depends_on": ["b"],
                },
                {
                    "id": "b",
                    "role": "code",
                    "title": "B",
                    "files": ["b.py"],
                    "instructions": "create module b",
                    "depends_on": ["a"],
                },
            ]
        )
        self.assertEqual(len(tasks), 2)
        self.assertEqual(sum(len(task["depends_on"]) for task in tasks), 1)
        self.assertTrue(all(task["id"] not in task["depends_on"] for task in tasks))

    def test_execute_runs_dependency_waves_and_delivers_reports(self) -> None:
        orchestrator = self._orchestrator()
        calls: list[tuple[str, list[dict]]] = []

        def fake_specialist(task, original):
            calls.append((task["id"], list(task.get("_inbox") or [])))
            return {
                "id": task["id"],
                "role": task["role"],
                "title": task["title"],
                "report": f"done {task['id']}",
                "error": "",
                "files_changed": [],
                "changed_count": 0,
            }

        orchestrator._run_specialist = fake_specialist
        plan = {
            "tasks": [
                {
                    "id": "a",
                    "role": "code",
                    "title": "A",
                    "files": ["a.py"],
                    "instructions": "a",
                    "depends_on": [],
                },
                {
                    "id": "b",
                    "role": "assets",
                    "title": "B",
                    "files": ["assets/b.png"],
                    "instructions": "b",
                    "depends_on": ["a"],
                },
            ]
        }
        results = orchestrator._execute(plan, "task")
        self.assertEqual(len(results), 2)
        self.assertEqual([item[0] for item in calls], ["a", "b"])
        inbox = calls[1][1]
        self.assertEqual(inbox[0]["from"], "a")
        self.assertIn("done a", inbox[0]["report"])

    def test_a_member_is_reused_and_remembers_its_previous_work(self) -> None:
        orchestrator = self._orchestrator()
        with mock.patch("reasonable.ai.orchestrator.update_task"), mock.patch(
            "reasonable.ai.orchestrator.Agent", FakeAgent
        ):
            first = orchestrator._run_specialist(
                {
                    "id": "a",
                    "role": "code",
                    "title": "First",
                    "files": ["main.py"],
                    "instructions": "write first",
                },
                "Task",
            )
            second = orchestrator._run_specialist(
                {
                    "id": "b",
                    "role": "code",
                    "title": "Second",
                    "files": ["main.py"],
                    "instructions": "write second",
                    "_reuse": True,
                },
                "Task",
            )

        self.assertEqual(first["member"], second["member"])
        self.assertEqual(len(orchestrator._members), 1)
        self.assertEqual(len(FakeAgent.created), 1)
        agent = FakeAgent.created[0]
        self.assertEqual(len(agent.messages), 2)
        self.assertIn("DURABLE MEMBER MEMORY", agent.messages[1])
        self.assertIn("report 1", agent.messages[1])

    def test_stalled_specialist_is_not_marked_done(self) -> None:
        class StalledAgent(FakeAgent):
            def __init__(self, *args, **kwargs) -> None:
                super().__init__(*args, **kwargs)
                self.last_error = ""
                self.incomplete_reason = "stopped without editing"

            def run(self, message: str, **kwargs) -> str:
                return ""

        orchestrator = self._orchestrator()
        with mock.patch("reasonable.ai.orchestrator.update_task") as update, mock.patch(
            "reasonable.ai.orchestrator.Agent", StalledAgent
        ):
            result = orchestrator._run_specialist(
                {
                    "id": "a",
                    "role": "code",
                    "title": "First",
                    "files": ["main.py"],
                    "instructions": "write",
                },
                "Task",
            )
        self.assertIn("without editing", result["error"])
        self.assertEqual(update.call_args_list[-1].args[2], "skipped")

    def test_specialists_receive_time_step_and_write_expectation_limits(self) -> None:
        orchestrator = self._orchestrator()
        with mock.patch("reasonable.ai.orchestrator.update_task"), mock.patch(
            "reasonable.ai.orchestrator.Agent", FakeAgent
        ):
            orchestrator._run_specialist(
                {
                    "id": "a",
                    "role": "code",
                    "title": "First",
                    "files": ["main.py"],
                    "instructions": "write",
                },
                "Task",
            )
        kwargs = FakeAgent.created[0].kwargs
        self.assertEqual(kwargs["max_seconds"], 15 * 60)
        self.assertEqual(kwargs["max_steps_override"], 60)
        self.assertTrue(kwargs["expect_writes"])

    def test_review_payload_uses_diffs_instead_of_full_files(self) -> None:
        from reasonable.core.history import create_snapshot

        snapshot = create_snapshot(self.project, label="before", reason="agent")
        (self.root / "main.py").write_text("print('changed')\n", encoding="utf-8")
        orchestrator = self._orchestrator()
        orchestrator.snapshot = {"id": str(snapshot["id"])}
        payload = orchestrator._changed_payload(
            [
                {
                    "files_changed": [
                        {"path": "main.py", "action": "edit"}
                    ]
                }
            ]
        )
        self.assertIn("+print('changed')", payload[0]["diff"])
        self.assertNotIn("content", payload[0])

    def test_plan_exposes_roles_and_dependencies(self) -> None:
        from reasonable.core.progress import read_state

        orchestrator = self._orchestrator()
        orchestrator._apply_plan(
            {
                "tasks": [
                    {
                        "id": "a",
                        "role": "code",
                        "title": "A",
                        "files": ["a.py"],
                        "instructions": "a",
                        "depends_on": [],
                    },
                    {
                        "id": "b",
                        "role": "assets",
                        "title": "B",
                        "files": ["assets/b.png"],
                        "instructions": "b",
                        "depends_on": ["a"],
                    },
                ]
            }
        )
        tasks = read_state(self.project.root)["tasks"]
        by_id = {task["id"]: task for task in tasks}
        self.assertEqual(by_id["b"]["depends_on"], ["a"])
        self.assertEqual(by_id["b"]["role"], "assets")

    def test_fix_round_is_sent_to_an_existing_member(self) -> None:
        orchestrator = self._orchestrator()
        with mock.patch("reasonable.ai.orchestrator.update_task"), mock.patch(
            "reasonable.ai.orchestrator.Agent", FakeAgent
        ):
            orchestrator._run_specialist(
                {
                    "id": "a",
                    "role": "code",
                    "title": "First",
                    "files": ["main.py"],
                    "instructions": "write",
                },
                "Task",
            )
            fix = {
                "id": "fix-1",
                "role": "code",
                "title": "Repair round",
                "files": ["main.py"],
                "instructions": "fix it",
                "_reuse": True,
            }
            orchestrator._run_specialist(fix, "Task")

        self.assertEqual(len(orchestrator._members), 1)
        self.assertEqual(orchestrator._members[0].tasks, ["a", "fix-1"])

    def test_verify_calls_run_project_with_arguments_dict(self) -> None:
        calls: list[tuple[str, dict | None]] = []

        class FakeTools:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def call(self, name, arguments=None):
                calls.append((name, arguments))
                if name == "validate_project":
                    return '{"ok": true, "has_errors": false, "issues": []}'
                if name == "run_project":
                    return '{"ok": true, "returncode": 0}'
                return "{}"

        orchestrator = self._orchestrator()
        with mock.patch("reasonable.ai.orchestrator.AgentTools", FakeTools):
            result = orchestrator._verify()
        self.assertTrue(result["ok"])
        self.assertIn(("run_project", {"frames": 8}), calls)

    def test_run_journal_round_trip(self) -> None:
        orchestrator = self._orchestrator()
        plan = {
            "tasks": [
                {"id": "a", "role": "code", "title": "A", "files": ["main.py"], "depends_on": []}
            ]
        }
        results = [{"id": "a", "role": "code", "title": "A", "report": "done"}]
        orchestrator.snapshot = {"id": "snap-1"}
        orchestrator._journal_save("Build a menu", plan, results)
        loaded = orchestrator._load_journal("Build a menu")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["plan"]["tasks"][0]["id"], "a")
        self.assertEqual(loaded["results"][0]["report"], "done")
        self.assertEqual(loaded["snapshot"]["id"], "snap-1")
        self.assertIsNone(orchestrator._load_journal("Another task"))

        orchestrator._clear_journal()
        self.assertIsNone(orchestrator._load_journal("Build a menu"))

    def test_execute_skips_items_already_done_in_the_journal(self) -> None:
        orchestrator = self._orchestrator()
        plan = {
            "tasks": [
                {"id": "a", "role": "code", "title": "A", "files": ["main.py"], "depends_on": []},
                {"id": "b", "role": "code", "title": "B", "files": ["main.py"], "depends_on": ["a"]},
            ]
        }
        done = {
            "a": {"id": "a", "role": "code", "title": "A", "report": "first"},
            "b": {"id": "b", "role": "code", "title": "B", "report": "second"},
        }
        results = orchestrator._execute(plan, "Task", done=done)
        self.assertEqual([item["id"] for item in results], ["a", "b"])
        self.assertEqual(FakeAgent.created, [])


if __name__ == "__main__":
    unittest.main()
