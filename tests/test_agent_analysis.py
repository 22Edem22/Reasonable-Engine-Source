"""Tests for the read-only "Improve project" analysis run."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from reasonable.ai.agent import Agent
from reasonable.ai.client import ChatResult
from reasonable.core import chatlog
from reasonable.core.project import Project, default_manifest
from reasonable.core.settings import Settings


class AgentAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "project"
        self.root.mkdir(parents=True)
        self.project = Project.create(
            self.root,
            default_manifest("Анализ", project_type="game", mode="builtin", goal="Проверка"),
            scaffold=False,
        )
        (self.root / "main.py").write_text("print('ok')\n", encoding="utf-8")
        self.chat = chatlog.create_chat(self.root, "Улучшения")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_analysis_is_read_only_and_hides_the_prompt(self) -> None:
        events = []
        agent = Agent(
            self.project,
            Settings(path=self.root / "settings.json"),
            on_event=events.append,
            analysis=True,
            hidden_message=True,
            chat_id=self.chat["id"],
            reply_language="ru",
        )
        schemas = {schema["name"] for schema in agent.tool_schemas}
        self.assertIn("read_file", schemas)
        self.assertIn("search_text", schemas)
        self.assertIn("validate_project", schemas)
        self.assertNotIn("write_file", schemas)
        self.assertNotIn("delete_path", schemas)
        self.assertNotIn("finish", schemas)

        def fake_call(messages, tools, temperature=0.65):
            return ChatResult(content="1. Добавить меню.\n2. Улучшить звук.")

        agent._call_model = fake_call
        answer = agent.run("private prompt")
        self.assertEqual(answer, "1. Добавить меню.\n2. Улучшить звук.")
        self.assertTrue(agent.finished)
        self.assertIsNone(agent.snapshot)
        self.assertEqual(agent.tools.files_changed, 0)

        history = chatlog.load_chat(self.root, self.chat["id"])
        self.assertEqual([item["role"] for item in history], ["user", "assistant"])
        self.assertTrue(history[0]["hidden"])
        self.assertFalse(history[1]["hidden"])
        self.assertTrue(any(event.kind == "done" for event in events))

    def test_hidden_review_prompt_is_not_seeded_into_user_follow_ups(self) -> None:
        chatlog.append_message(
            self.root, "user", "private review prompt", chat_id=self.chat["id"], hidden=True
        )
        chatlog.append_message(
            self.root, "assistant", "1. Добавить меню.", chat_id=self.chat["id"]
        )
        agent = Agent(
            self.project,
            Settings(path=self.root / "settings.json"),
            chat_id=self.chat["id"],
        )
        agent.messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "Сделай пункт 1"},
        ]
        agent._seed_chat_history()
        note = agent.messages[1]["content"]
        self.assertIn("1. Добавить меню.", note)
        self.assertNotIn("private review prompt", note)


if __name__ == "__main__":
    unittest.main()
