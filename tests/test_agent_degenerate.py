"""Guards against models that get stuck repeating the same fragment."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from reasonable.ai.agent import Agent, _looks_degenerate
from reasonable.ai.client import ChatResult
from reasonable.core.project import Project, default_manifest
from reasonable.core.settings import Settings

LOOP = "\n".join(
    [
        "Ok.",
        "Go.",
        "Done.",
        "Write.",
        "Emit.",
        "Now.",
        "Final.",
        "Ok.",
        "Go.",
        "Done.",
        "Write.",
        "Emit.",
        "Now.",
        "Output.",
    ]
)


class DegenerateReplyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "project"
        self.root.mkdir(parents=True)
        self.project = Project.create(
            self.root,
            default_manifest("Loop", goal="Review the project"),
            scaffold=False,
        )
        (self.root / "main.py").write_text("print('ok')\n", encoding="utf-8")
        self.settings = Settings(path=self.root / "settings.json")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_detector_flags_a_thought_loop_but_not_real_text(self) -> None:
        self.assertTrue(_looks_degenerate(LOOP))
        self.assertFalse(
            _looks_degenerate(
                "1. Add a main menu.\n2. Add three levels.\n3. Save the best score."
            )
        )
        self.assertFalse(
            _looks_degenerate(
                "```python\nfor x in range(3):\n    print(x)\n    print(x)\n"
                "    print(x)\n    print(x)\n```"
            )
        )

    def test_loop_is_discarded_and_the_next_reply_is_used(self) -> None:
        events = []
        agent = Agent(
            self.project,
            self.settings,
            on_event=events.append,
            analysis=True,
            reply_language="ru",
        )
        replies = iter([ChatResult(content=LOOP), ChatResult(content="1. Добавить меню.")])
        calls = []

        def fake_call(messages, tools, *, temperature=0.65):
            calls.append(temperature)
            return next(replies)

        agent._call_model = fake_call
        answer = agent.run("private prompt")

        self.assertEqual(answer, "1. Добавить меню.")
        self.assertTrue(agent.finished)
        self.assertEqual(len(calls), 2)
        self.assertLess(calls[1], calls[0])
        shown = "\n".join(
            event.text for event in events if event.kind == "assistant"
        )
        self.assertNotIn("Emit.", shown)
        self.assertNotIn("Ok.", shown)

    def test_two_loops_stop_with_an_honest_message(self) -> None:
        events = []
        agent = Agent(
            self.project,
            self.settings,
            on_event=events.append,
            analysis=True,
            reply_language="ru",
        )
        calls = []

        def fake_call(messages, tools, *, temperature=0.65):
            calls.append(temperature)
            return ChatResult(content=LOOP)

        agent._call_model = fake_call
        agent.run("private prompt")

        self.assertFalse(agent.finished)
        self.assertEqual(len(calls), 2)
        self.assertTrue(agent.incomplete_reason)
        self.assertTrue(any(event.kind == "incomplete" for event in events))


if __name__ == "__main__":
    unittest.main()
