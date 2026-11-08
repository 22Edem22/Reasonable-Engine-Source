"""Regression tests for the agent loop: context, budgets and safe stopping.

These cover the failure modes that made a long run lose its task or keep
spending tokens without changing anything.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from reasonable.ai.agent import Agent
from reasonable.ai.client import AIClient, AIError, ChatResult, ToolCall
from reasonable.ai.tools import TOOL_SCHEMAS
from reasonable.core.project import Project, default_manifest
from reasonable.core.settings import Settings


class AgentHarnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "project"
        self.root.mkdir(parents=True)
        self.project = Project.create(
            self.root,
            default_manifest("Harness", goal="Test the loop"),
            scaffold=False,
        )
        (self.root / "main.py").write_text("print('ok')\n", encoding="utf-8")
        self.settings = Settings(path=self.root / "settings.json")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _agent(self, **kwargs) -> Agent:
        kwargs.setdefault("persist_messages", False)
        kwargs.setdefault("seed_history", False)
        kwargs.setdefault("create_snapshot", False)
        kwargs.setdefault("sync_history", False)
        return Agent(self.project, self.settings, **kwargs)

    @staticmethod
    def _not_ready(**overrides) -> dict:
        value = {
            "ready": False,
            "files_changed": 0,
            "changed_files": [],
            "validation_passed": False,
            "run_passed": False,
            "install_commands": 0,
            "missing": ["no file has been modified yet"],
        }
        value.update(overrides)
        return value

    # ------------------------------------------------------------------
    def test_history_trimming_keeps_the_original_task(self) -> None:
        agent = self._agent()
        agent.messages = [
            {"role": "system", "content": "SYSTEM"},
            {"role": "user", "content": "ORIGINAL TASK"},
        ]
        agent._task_message = agent.messages[1]
        for index in range(30):
            agent.messages.append(
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": f"call_{index}",
                            "type": "function",
                            "function": {
                                "name": "read_file",
                                "arguments": json.dumps({"path": f"file_{index}.py"}),
                            },
                        }
                    ],
                }
            )
            agent.messages.append(
                {
                    "role": "tool",
                    "tool_call_id": f"call_{index}",
                    "name": "read_file",
                    "content": "x" * 3000,
                }
            )

        agent._trim_history()

        self.assertEqual(agent.messages[0]["content"], "SYSTEM")
        self.assertEqual(agent.messages[1]["content"], "ORIGINAL TASK")
        self.assertNotEqual(agent.messages[2]["role"], "tool")
        self.assertLess(len(agent.messages), 60)

    def test_history_trimming_respects_the_character_budget(self) -> None:
        self.settings.data["agent"]["context_chars"] = 20_000
        agent = self._agent()
        agent.messages = [
            {"role": "system", "content": "SYSTEM"},
            {"role": "user", "content": "ORIGINAL TASK"},
        ]
        agent._task_message = agent.messages[1]
        for index in range(12):
            agent.messages.append(
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": f"call_{index}",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": "{}"},
                        }
                    ],
                }
            )
            agent.messages.append(
                {
                    "role": "tool",
                    "tool_call_id": f"call_{index}",
                    "name": "read_file",
                    "content": "y" * 8000,
                }
            )

        agent._trim_history()

        self.assertEqual(agent.messages[1]["content"], "ORIGINAL TASK")
        total = sum(len(str(item.get("content") or "")) for item in agent.messages[1:])
        self.assertLess(total, 25_000)

    # ------------------------------------------------------------------
    def _fill_history(self, agent: Agent, count: int = 40) -> None:
        agent.messages = [
            {"role": "system", "content": "SYSTEM"},
            {"role": "user", "content": "ORIGINAL TASK"},
        ]
        agent._task_message = agent.messages[1]
        for index in range(count):
            agent.messages.append(
                {
                    "role": "assistant",
                    "content": f"Step {index}",
                    "tool_calls": [
                        {
                            "id": f"call_{index}",
                            "type": "function",
                            "function": {
                                "name": "read_file",
                                "arguments": json.dumps({"path": f"file_{index}.py"}),
                            },
                        }
                    ],
                }
            )
            agent.messages.append(
                {
                    "role": "tool",
                    "tool_call_id": f"call_{index}",
                    "name": "read_file",
                    "content": "x" * 1200,
                }
            )

    def test_old_messages_are_compacted_into_a_summary(self) -> None:
        self.settings.data["agent"]["context_messages"] = 12
        events = []
        agent = self._agent(on_event=events.append)
        agent._compaction_enabled = True
        self._fill_history(agent)
        calls = []

        def fake_model(messages, tools, *, temperature=0.0):
            calls.append((messages, tools))
            return ChatResult(content="- Goal: keep the task\n- Files: main.py")

        agent._call_model = fake_model
        agent._trim_history()

        self.assertEqual(len(calls), 1)
        self.assertTrue(any(event.kind == "status" for event in events))
        self.assertIsNone(calls[0][1])
        self.assertTrue(agent._summary)
        self.assertEqual(agent._pending_dropped, [])
        self.assertEqual(agent.messages[1]["content"], "ORIGINAL TASK")
        self.assertTrue(
            any(
                "CONVERSATION SUMMARY" in str(item.get("content") or "")
                for item in agent.messages
            )
        )
        # The summary sits between the task and the recent window.
        self.assertIn("CONVERSATION SUMMARY", agent.messages[2]["content"])

    def test_compaction_carries_the_previous_summary_forward(self) -> None:
        self.settings.data["agent"]["context_messages"] = 12
        agent = self._agent()
        agent._compaction_enabled = True
        self._fill_history(agent)
        prompts = []

        def fake_model(messages, tools, *, temperature=0.0):
            prompts.append(messages[-1]["content"])
            return ChatResult(
                content="SUMMARY ONE" if len(prompts) == 1 else "SUMMARY TWO"
            )

        agent._call_model = fake_model
        agent._trim_history()
        self.assertIn("SUMMARY ONE", agent._summary)

        # More history arrives and is compacted together with the old summary.
        for index in range(40, 60):
            agent.messages.append(
                {
                    "role": "assistant",
                    "content": f"Step {index}",
                    "tool_calls": [
                        {
                            "id": f"call_{index}",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": "{}"},
                        }
                    ],
                }
            )
            agent.messages.append(
                {
                    "role": "tool",
                    "tool_call_id": f"call_{index}",
                    "name": "read_file",
                    "content": "y" * 1200,
                }
            )
        agent._trim_history()

        self.assertEqual(len(prompts), 2)
        self.assertIn("Previous summary:", prompts[1])
        self.assertIn("SUMMARY ONE", prompts[1])
        self.assertIn("SUMMARY TWO", agent._summary)

    def test_a_long_run_continues_after_compaction(self) -> None:
        self.settings.data["agent"]["context_messages"] = 12
        self.settings.data["agent"]["context_tokens"] = 2_000
        self.settings.data["agent"]["stall_steps"] = 0
        self.settings.data["agent"]["max_steps"] = 16
        agent = self._agent()
        calls = {"main": 0, "compact": 0, "audit": 0}

        def fake_model(messages, tools, *, temperature=0.3):
            system = str(messages[0].get("content") or "")
            if tools is None and "compress the older part" in system.lower():
                calls["compact"] += 1
                return ChatResult(content="- Goal: keep going\n- Files: none yet")
            if tools is None:
                calls["audit"] += 1
                return ChatResult(
                    content=json.dumps({"complete": True, "missing": [], "next": ""})
                )
            calls["main"] += 1
            if calls["main"] >= 11:
                return ChatResult(content="The work is done.")
            return ChatResult(
                content="",
                tool_calls=[
                    ToolCall(
                        id=f"call_{calls['main']}",
                        name="run_command",
                        arguments={"command": "echo tick"},
                    )
                ],
            )

        readiness = {
            "ready": True,
            "files_changed": 1,
            "changed_files": [{"path": "main.py", "action": "edit"}],
            "validation_passed": True,
            "run_passed": True,
            "install_commands": 0,
            "missing": [],
        }
        agent._call_model = fake_model
        agent.tools.readiness = lambda: readiness
        agent.tools.call = lambda name, arguments=None: json.dumps(
            {"ok": True, "tick": calls["main"], "data": "x" * 2_500}
        )
        agent.tools.tool_finish = lambda message: None

        answer = agent.run("Keep working until the task is done")

        self.assertTrue(agent.finished)
        self.assertTrue(answer)
        self.assertGreaterEqual(calls["compact"], 1)
        self.assertTrue(agent._summary)
        self.assertEqual(agent.messages[1]["content"].split("\n\n")[-1], "Keep working until the task is done")
        self.assertTrue(
            any(
                "CONVERSATION SUMMARY" in str(item.get("content") or "")
                for item in agent.messages
            )
        )

    def test_compaction_failure_falls_back_to_plain_trimming(self) -> None:
        self.settings.data["agent"]["context_messages"] = 12
        agent = self._agent()
        agent._compaction_enabled = True
        self._fill_history(agent)

        def fake_model(messages, tools, *, temperature=0.0):
            raise RuntimeError("provider is down")

        agent._call_model = fake_model
        agent._trim_history()

        self.assertEqual(agent._summary, "")
        self.assertEqual(agent.messages[1]["content"], "ORIGINAL TASK")
        self.assertFalse(
            any(
                "CONVERSATION SUMMARY" in str(item.get("content") or "")
                for item in agent.messages
            )
        )
        self.assertGreaterEqual(agent._compaction_failures, 1)

    def test_compaction_can_be_disabled(self) -> None:
        self.settings.data["agent"]["context_messages"] = 12
        agent = self._agent()
        agent._compaction_enabled = False
        self._fill_history(agent)

        def fake_model(messages, tools, *, temperature=0.0):
            raise AssertionError("compaction must not run when disabled")

        agent._call_model = fake_model
        agent._trim_history()
        self.assertEqual(agent._summary, "")
        self.assertEqual(agent.messages[1]["content"], "ORIGINAL TASK")

    def test_reading_different_file_ranges_counts_as_progress(self) -> None:
        agent = self._agent()
        agent._remember_evidence(
            "read_file",
            json.dumps({"path": "main.py", "start_line": 1, "end_line": 200}),
        )
        agent._remember_evidence(
            "read_file",
            json.dumps({"path": "main.py", "start_line": 201, "end_line": 400}),
        )
        self.assertEqual(len(agent._evidence_paths), 2)

    def test_token_ratio_is_calibrated_from_real_usage(self) -> None:
        agent = self._agent()
        messages = [{"role": "user", "content": "x" * 7200}]
        before = agent._chars_per_token
        agent._calibrate_tokens(messages, None, {"prompt_tokens": 1000})
        self.assertGreater(agent._chars_per_token, before)
        self.assertLessEqual(agent._chars_per_token, 9.0)
        self.assertGreater(agent._estimate_messages_tokens(messages), 0)

    # ------------------------------------------------------------------
    def test_max_steps_is_enforced(self) -> None:
        self.settings.data["agent"]["max_steps"] = 3
        self.settings.data["agent"]["stall_steps"] = 0
        events = []
        agent = self._agent(on_event=events.append)
        agent.tools.readiness = lambda: self._not_ready()
        calls = {"count": 0}

        def fake_model(messages, tools, *, temperature=0.3):
            calls["count"] += 1
            return ChatResult(
                content="",
                tool_calls=[
                    ToolCall(
                        id=f"call_{calls['count']}",
                        name="run_command",
                        arguments={"command": "echo tick"},
                    )
                ],
            )

        def fake_tool(name, arguments=None):
            return json.dumps({"ok": True, "tick": calls["count"]})

        agent._call_model = fake_model
        agent.tools.call = fake_tool
        agent.run("A task that never becomes ready")

        self.assertEqual(calls["count"], 3)
        self.assertEqual(agent._stall_limit, 0)
        self.assertFalse(agent.finished)
        self.assertIn("3", agent.incomplete_reason)
        self.assertTrue(any(event.kind == "incomplete" for event in events))

    def test_stall_guard_never_stops_a_project_that_already_passes(self) -> None:
        self.settings.data["agent"]["stall_steps"] = 2
        self.settings.data["agent"]["max_steps"] = 6
        events = []
        agent = self._agent(on_event=events.append)
        ready = {
            "ready": True,
            "files_changed": 1,
            "changed_files": [{"path": "main.py", "action": "edit"}],
            "validation_passed": True,
            "run_passed": True,
            "install_commands": 0,
            "missing": [],
        }
        agent.tools.readiness = lambda: ready
        calls = {"count": 0}

        def fake_model(messages, tools, *, temperature=0.3):
            calls["count"] += 1
            return ChatResult(
                content="",
                tool_calls=[
                    ToolCall(
                        id=f"call_{calls['count']}",
                        name="run_command",
                        arguments={"command": "echo tick"},
                    )
                ],
            )

        agent._call_model = fake_model
        agent.tools.call = lambda name, arguments=None: json.dumps(
            {"ok": True, "tick": calls["count"]}
        )
        agent.run("Keep polishing")

        self.assertFalse(agent.finished)
        self.assertNotIn("without progress", agent.incomplete_reason.lower())
        self.assertNotIn("без прогресса", agent.incomplete_reason.lower())
        self.assertTrue(
            any(
                event.kind == "status" and "already pass" in event.text.lower()
                for event in events
            )
            or any(
                event.kind == "status" and "уже проход" in event.text.lower()
                for event in events
            )
        )

    def test_stall_guard_stops_a_run_without_progress(self) -> None:
        self.settings.data["agent"]["stall_steps"] = 3
        events = []
        agent = self._agent(on_event=events.append)
        agent.tools.readiness = lambda: self._not_ready()
        calls = {"count": 0}

        def fake_model(messages, tools, *, temperature=0.3):
            calls["count"] += 1
            return ChatResult(
                content="",
                tool_calls=[
                    ToolCall(
                        id=f"call_{calls['count']}",
                        name="run_command",
                        arguments={"command": "echo tick"},
                    )
                ],
            )

        def fake_tool(name, arguments=None):
            # Output changes every time, so the old identical-output detector
            # would not notice that nothing in the project changed.
            return json.dumps({"ok": True, "tick": calls["count"]})

        agent._call_model = fake_model
        agent.tools.call = fake_tool
        agent.run("A task that never makes progress")

        self.assertFalse(agent.finished)
        self.assertTrue(agent.incomplete_reason)
        self.assertLessEqual(calls["count"], 8)
        self.assertTrue(any(event.kind == "incomplete" for event in events))
        self.assertTrue(any(event.kind == "status" and "progress" in event.text.lower() for event in events)
                        or any(event.kind == "status" and "прогресс" in event.text.lower() for event in events))

    # ------------------------------------------------------------------
    def test_an_informational_answer_can_finish_without_file_changes(self) -> None:
        agent = self._agent()
        agent.tools.readiness = lambda: self._not_ready()
        calls = {"main": 0, "audit": 0}

        def fake_model(messages, tools, *, temperature=0.3):
            if tools is None:
                calls["audit"] += 1
                return ChatResult(
                    content=json.dumps({"complete": True, "missing": [], "next": ""})
                )
            calls["main"] += 1
            return ChatResult(content="main.py opens the application window.")

        agent._call_model = fake_model
        answer = agent.run("Explain what main.py does. Do not modify files.")

        self.assertTrue(agent.finished)
        self.assertEqual(answer, "main.py opens the application window.")
        self.assertEqual(calls, {"main": 1, "audit": 1})
        self.assertEqual(agent.tools.files_changed, 0)

    def test_truncated_replies_are_not_executed_and_stop_after_two(self) -> None:
        self.settings.data["agent"]["stall_steps"] = 0
        events = []
        agent = self._agent(on_event=events.append)
        calls = {"count": 0}

        def fake_model(messages, tools, *, temperature=0.3):
            calls["count"] += 1
            return ChatResult(content="partial answer", finish_reason="length")

        agent._call_model = fake_model
        agent.tools.call = lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("truncated calls must not execute")
        )
        agent.run("Write a huge file")

        self.assertFalse(agent.finished)
        self.assertEqual(calls["count"], 2)
        self.assertTrue(agent.incomplete_reason)
        self.assertFalse(
            any(event.kind == "assistant" and "partial" in event.text for event in events)
        )

    def test_tools_outside_the_role_schema_are_not_executed(self) -> None:
        self.settings.data["agent"]["max_steps"] = 1
        self.settings.data["agent"]["stall_steps"] = 0
        read_only = [
            schema for schema in TOOL_SCHEMAS if schema.get("name") == "read_file"
        ]
        agent = self._agent(tool_schemas_override=read_only)
        executed = []

        def fake_model(messages, tools, *, temperature=0.3):
            return ChatResult(
                content="",
                tool_calls=[
                    ToolCall(
                        id="forbidden",
                        name="write_file",
                        arguments={"path": "main.py", "content": "x"},
                    )
                ],
            )

        def fake_tool(name, arguments=None):
            executed.append(name)
            return json.dumps({"ok": True})

        agent._call_model = fake_model
        agent.tools.call = fake_tool
        agent.run("Try to use a tool that is not in this role")

        self.assertEqual(executed, [])
        self.assertTrue(
            any(
                "not available in this role" in str(item.get("content") or "")
                for item in agent.messages
            )
        )

    def test_malformed_tool_arguments_are_reported_not_executed(self) -> None:
        self.settings.data["agent"]["max_steps"] = 1
        self.settings.data["agent"]["stall_steps"] = 0
        agent = self._agent()
        executed = []

        def fake_model(messages, tools, *, temperature=0.3):
            return ChatResult(
                content="",
                tool_calls=[
                    ToolCall(
                        id="broken",
                        name="write_file",
                        arguments={
                            "_raw_arguments": '{"path": "main.py", "content": "',
                            "_parse_error": True,
                        },
                        raw_arguments='{"path": "main.py", "content": "',
                    )
                ],
            )

        def fake_tool(name, arguments=None):
            executed.append(name)
            return json.dumps({"ok": True})

        agent._call_model = fake_model
        agent.tools.call = fake_tool
        agent.run("Write main.py")

        self.assertEqual(executed, [])
        self.assertTrue(
            any(
                "not valid JSON" in str(item.get("content") or "")
                for item in agent.messages
            )
        )


class ClientFallbackTests(unittest.TestCase):
    def _client(self) -> AIClient:
        return AIClient(
            {
                "id": "test",
                "kind": "openai",
                "base_url": "https://example.test/v1",
                "model": "test-model",
                "api_key": "test",
                "headers": {},
            },
            timeout=5,
            retries=0,
        )

    def test_400_about_max_tokens_keeps_tool_calling(self) -> None:
        client = self._client()
        seen: list[dict] = []

        class FakeHTTP:
            def request(self, url, method="GET", headers=None, payload=None):
                seen.append(payload)
                if len(seen) == 1:
                    raise AIError(
                        "bad request",
                        status=400,
                        detail='{"error":{"message":"max_tokens is too large"}}',
                    )
                return {
                    "choices": [
                        {
                            "message": {"content": "ok"},
                            "finish_reason": "stop",
                        }
                    ]
                }

        client.http = FakeHTTP()
        result = client.chat(
            [{"role": "user", "content": "hi"}],
            [{"name": "echo", "description": "", "parameters": {"type": "object", "properties": {}}}],
            temperature=0.2,
            max_tokens=99999,
        )

        self.assertEqual(result.finish_reason, "stop")
        self.assertIn("tools", seen[1])
        self.assertNotIn("max_tokens", seen[1])

    def test_anthropic_system_prompt_uses_a_cache_breakpoint(self) -> None:
        client = AIClient(
            {
                "kind": "anthropic",
                "base_url": "https://api.anthropic.com/v1",
                "model": "claude-test",
                "api_key": "test",
            },
            timeout=5,
            retries=0,
        )
        seen: list[dict] = []

        class FakeHTTP:
            def request(self, url, method="GET", headers=None, payload=None):
                seen.append(payload)
                return {
                    "content": [{"type": "text", "text": "ok"}],
                    "usage": {
                        "input_tokens": 10,
                        "cache_read_input_tokens": 5,
                        "cache_creation_input_tokens": 2,
                        "output_tokens": 3,
                    },
                    "stop_reason": "end_turn",
                }

        client.http = FakeHTTP()
        result = client.chat(
            [
                {"role": "system", "content": "SYSTEM PROMPT"},
                {"role": "user", "content": "hi"},
            ],
            [
                {
                    "name": "echo",
                    "description": "",
                    "parameters": {"type": "object", "properties": {}},
                }
            ],
        )

        self.assertEqual(result.content, "ok")
        system = seen[0]["system"]
        self.assertIsInstance(system, list)
        self.assertEqual(system[0]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(result.usage["cache_read_input_tokens"], 5)

    def test_finish_reason_is_exposed_to_the_agent(self) -> None:
        client = self._client()

        class FakeHTTP:
            def request(self, url, method="GET", headers=None, payload=None):
                return {
                    "choices": [
                        {
                            "message": {"content": "cut"},
                            "finish_reason": "length",
                        }
                    ]
                }

        client.http = FakeHTTP()
        result = client.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(result.finish_reason, "length")


class UsagePayloadTests(unittest.TestCase):
    def test_openai_cached_tokens_are_detected(self) -> None:
        payload = Agent._usage_payload(
            {
                "prompt_tokens": 1_000,
                "completion_tokens": 10,
                "prompt_tokens_details": {"cached_tokens": 800},
            },
            1.0,
        )
        self.assertEqual(payload["prompt_tokens"], 1_000)
        self.assertEqual(payload["cached_tokens"], 800)

    def test_anthropic_cache_fields_are_added_to_the_prompt(self) -> None:
        payload = Agent._usage_payload(
            {
                "input_tokens": 200,
                "cache_read_input_tokens": 800,
                "cache_creation_input_tokens": 100,
                "output_tokens": 10,
            },
            1.0,
        )
        self.assertEqual(payload["prompt_tokens"], 1_100)
        self.assertEqual(payload["cached_tokens"], 800)
        self.assertEqual(payload["cache_write_tokens"], 100)
        self.assertEqual(payload["total_tokens"], 1_110)

    def test_deepseek_and_opencode_cache_fields_are_detected(self) -> None:
        deepseek = Agent._usage_payload(
            {
                "prompt_tokens": 1_000,
                "completion_tokens": 10,
                "prompt_cache_hit_tokens": 700,
            },
            1.0,
        )
        self.assertEqual(deepseek["cached_tokens"], 700)

        opencode = Agent._usage_payload(
            {
                "prompt_tokens": 1_000,
                "completion_tokens": 10,
                "opencode": {
                    "tokens": {"cache_read": 600, "cache_write_5m": 50}
                },
            },
            1.0,
        )
        self.assertEqual(opencode["cached_tokens"], 600)
        self.assertEqual(opencode["cache_write_tokens"], 50)


class ProviderContextWindowTests(unittest.TestCase):
    def test_provider_presets_expose_a_context_window(self) -> None:
        from reasonable.ai.providers import get_provider

        self.assertEqual(get_provider("ollama").context_window, 32_768)
        self.assertEqual(get_provider("anthropic").context_window, 200_000)
        self.assertEqual(get_provider("gemini").context_window, 1_000_000)
        self.assertGreaterEqual(get_provider("openai").context_window, 128_000)


class SettingsMigrationTests(unittest.TestCase):
    def test_old_stall_default_is_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(
                json.dumps({"agent": {"stall_steps": 8}}), encoding="utf-8"
            )
            settings = Settings(path)
            self.assertEqual(settings.data["agent"]["stall_steps"], 0)

    def test_old_default_temperature_and_new_guards_are_migrated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(
                json.dumps({"agent": {"temperature": 0.65}}), encoding="utf-8"
            )
            settings = Settings(path)
            self.assertAlmostEqual(settings.data["agent"]["temperature"], 0.3)
            self.assertEqual(settings.data["agent"]["stall_steps"], 0)
            self.assertEqual(settings.data["agent"]["context_chars"], 120_000)
            self.assertEqual(settings.data["agent"]["context_tokens"], 0)
            self.assertTrue(settings.data["agent"]["compaction"])
            self.assertEqual(settings.data["agent"]["max_output_tokens"], 16384)


if __name__ == "__main__":
    unittest.main()
